"""
neurocode-backend/agent/nodes/understand.py
"""
import asyncio
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
        git_status = ctx.get("git_status") or await asyncio.to_thread(git_status_tool)
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
    # Name the command after its most significant tool, not its first one:
    # "get diff, then commit" is a commit, not a status check.
    intent_by_priority = [
        ("commit_changes", "git_commit"),
        ("push_to_remote", "git_push"),
        ("pull_from_remote", "git_pull"),
        ("get_git_diff", "git_status"),
        ("get_git_status", "git_status"),
    ]
    intent_name = next(
        (intent for tool, intent in intent_by_priority if tool in tool_names),
        tool_names[0] if tool_names else "dynamic_plan",
    )
    logger.info(f"[Understand] transcript: '{transcript}' -> planned tools: {tool_names} (intent: {intent_name})")

    return {
        "intent": intent_name,
        "plan_data": plan_data
    }

