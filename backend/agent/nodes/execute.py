"""
neurocode-backend/agent/nodes/execute.py
"""
import logging
from agent.state import AgentState
from agent.registry import execute_tool_call

logger = logging.getLogger("neurocode.agent.execute")

async def execute_action(state: AgentState) -> AgentState:
    """
    [Execute] node.
    Iterates dynamically over plan_data['tool_calls'] tool chain, executing each atomic tool.
    """
    plan_data = state.get("plan_data", {})
    tool_calls = plan_data.get("tool_calls", [])
    ctx = state.get("context", {})

    if not tool_calls:
        logger.info("[Execute] No tool calls planned. Skipping execution.")
        return {"action_result": {"status": "skipped"}}

    executed_results = []
    overall_status = "success"
    failure_detail = ""

    for tc in tool_calls:
        tool_name = tc.get("tool")
        args = tc.get("args", {})

        logger.info(f"[Execute] Running planned tool step '{tool_name}' with args={args}")
        res = await execute_tool_call(tool_name, args=args, context=ctx)
        executed_results.append({"tool": tool_name, "result": res})

        if isinstance(res, dict) and res.get("status") == "failure":
            overall_status = "failure"
            failure_detail = res.get("detail", "Tool step failed")
            logger.error(f"[Execute] Tool step '{tool_name}' failed: {failure_detail}. Aborting remaining tools.")
            break

    # Read-only status/diff tools do not mutate state and are treated as skipped execution
    is_read_only = all(tc.get("tool") in ["get_git_status", "get_git_diff", "query_codebase_rag"] for tc in tool_calls)
    if is_read_only and overall_status == "success":
        overall_status = "skipped"

    return {
        "action_result": {
            "status": overall_status,
            "executed_steps": executed_results,
            "detail": failure_detail if overall_status == "failure" else f"Successfully executed {len(executed_results)} planned tool step(s)."
        }
    }

