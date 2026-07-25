"""
neurocode-backend/agent/nodes/understand.py
"""
import logging
from agent.state import AgentState
from tools.gemini_llm import gemini_llm
from tools.git_tool import status as git_status_tool

logger = logging.getLogger("neurocode.agent.understand")

async def understand_intent(state: AgentState) -> AgentState:
    """
    [Understand / Plan] node.
    Uses AI Planner to dynamically plan tool executions (ReAct loop).
    Completely eliminates static intent enums.
    """
    transcript = state.get("transcript", "")

    ctx = state.get("context", {})
    try:
        git_status = ctx.get("git_status") or git_status_tool()
        plan_data = await gemini_llm.plan_actions(transcript, status_info=git_status)
    except Exception as e:
        logger.error(f"[Understand] Planning failed: {e}")
        plan_data = {
            "reasoning": f"Processed command: {transcript}",
            "tool_calls": [{"tool": "query_codebase_rag", "args": {"query": transcript}}],
            "requires_confirm": False,
            "risk_band": "safe"
        }

    tool_names = [tc.get("tool") for tc in plan_data.get("tool_calls", [])]
    logger.info(f"[Understand] transcript: '{transcript}' -> planned tools: {tool_names}")

    return {
        "intent": tool_names[0] if tool_names else "dynamic_plan",
        "plan_data": plan_data
    }
