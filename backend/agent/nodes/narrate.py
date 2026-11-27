"""
neurocode-backend/agent/nodes/narrate.py
"""
import logging
from agent.state import AgentState

logger = logging.getLogger("neurocode.agent.narrate")

async def narrate_response(state: AgentState) -> AgentState:
    """
    [Narrate] node.
    Generates the final spoken audio summary for dynamic tool executions.
    """
    v_status = state.get("verification_status")
    result = state.get("action_result", {})
    reasoning = state.get("reasoning", "")
    ctx = state.get("context", {})
    risk_band = ctx.get("risk_band", "safe")

    executed_steps = result.get("executed_steps", []) if isinstance(result, dict) else []
    executed_tools = [s.get("tool") for s in executed_steps]

    if v_status == "failure" or (isinstance(result, dict) and result.get("status") == "failure"):
        narration = f"Action failed: {result.get('detail', 'unknown error')}."
        risk_band = "high-risk"
    elif "commit_changes" in executed_tools and "push_to_remote" in executed_tools:
        narration = f"Committed {_commit_summary(executed_steps)} and pushed to origin."
    elif "commit_changes" in executed_tools:
        narration = f"Committed {_commit_summary(executed_steps)}."
    elif "push_to_remote" in executed_tools:
        narration = "Push completed successfully."
    elif "pull_from_remote" in executed_tools:
        narration = "Pulled latest changes from remote origin successfully."
    else:
        narration = reasoning if reasoning else "Action completed successfully."

    # Speech is produced by api/ws.py (send_spoken), which streams the first sentence first.
    logger.info(f"[Narrate] {narration} (risk_band={risk_band})")
    return {"narration": narration, "earcon": risk_band}


def _commit_summary(executed_steps: list) -> str:
    """'2 files with message: fix login retry' from the commit step's result."""
    for step in executed_steps:
        if step.get("tool") == "commit_changes" and isinstance(step.get("result"), dict):
            res = step["result"]
            n = len(res.get("files", []))
            noun = "file" if n == 1 else "files"
            if res.get("message"):
                return f"{n} {noun} with message: {res['message']}"
    return "your changes"
