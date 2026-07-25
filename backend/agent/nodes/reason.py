"""
neurocode-backend/agent/nodes/reason.py
"""
import logging
from agent.state import AgentState
from tools.diff_intelligence import diff_intelligence
from tools.gemini_llm import gemini_llm

logger = logging.getLogger("neurocode.agent.reason")

async def reason_plan(state: AgentState) -> AgentState:
    """
    [Reason/Plan] node.
    Synthesizes spoken audio reasoning for dynamic tool plans.
    """
    transcript = state.get("transcript", "")
    plan_data = state.get("plan_data", {})
    ctx = state.get("context", {})
    git_status = ctx.get("git_status", {})
    diff_text = ctx.get("diff_text", "")
    rag_context = ctx.get("rag_context", "")

    tool_calls = plan_data.get("tool_calls", [])
    confirmation_required = plan_data.get("requires_confirm", False)
    risk_band = plan_data.get("risk_band", "safe")

    # Check tool names in plan
    tool_names = [tc.get("tool") for tc in tool_calls]

    # Overriding security check for .env file access
    if ".env" in transcript.lower() or "dotenv" in transcript.lower():
        confirmations = state.get("env_confirmations_received", 0)
        if confirmations < 1:
            reasoning = "Warning: The command accesses a .env file containing sensitive credentials. Do you permit reading and analyzing the .env file? Press Alt+Y to confirm or Alt+N to reject."
            logger.info(f"[Reason] Overrode logic for .env file access confirmation, confirmations={confirmations}")
            return {
                "reasoning": reasoning,
                "confirmation_required": True,
                "confirmation_message": reasoning,
                "context": {**ctx, "risk_band": "high-risk"},
                "plan_data": plan_data
            }

    if "commit_changes" in tool_names and "push_to_remote" in tool_names:
        changed = len(git_status.get("changed_files", []))
        draft_msg = await diff_intelligence.draft_commit_message(diff_text)
        branch = git_status.get("branch", "main")
        reasoning = f"Found {changed} changed file(s). Suggested commit: '{draft_msg}'. Should I commit and push to origin/{branch}?"
        confirmation_required = True
        risk_band = "caution"

    elif "commit_changes" in tool_names:
        changed = len(git_status.get("changed_files", []))
        draft_msg = await diff_intelligence.draft_commit_message(diff_text)
        reasoning = f"Found {changed} changed file(s). Suggested commit message: '{draft_msg}'."
        confirmation_required = True

    elif "push_to_remote" in tool_names:
        branch = git_status.get("branch", "main")
        reasoning = f"You are about to push branch '{branch}' to origin."
        confirmation_required = True
        risk_band = "caution"

    elif "pull_from_remote" in tool_names:
        branch = git_status.get("branch", "main")
        reasoning = f"You are about to pull latest incoming changes from origin/{branch}."
        confirmation_required = True

    elif "get_git_diff" in tool_names or "get_git_status" in tool_names:
        branch = git_status.get("branch", "unknown")
        changed = len(git_status.get("changed_files", []))
        if diff_text.strip():
            prose_review = await diff_intelligence.review_before_commit(diff_text)
            reasoning = f"You are on branch '{branch}' with {changed} changed file(s). {prose_review}"
        else:
            reasoning = f"You are on branch '{branch}' with no uncommitted file changes."
        confirmation_required = False

    else:
        git_combined_info = f"Git Status: {git_status}\n\nWorking Tree Git Diff:\n{diff_text[:3000]}"
        reasoning = await gemini_llm.generate_reasoning(transcript, rag_context=rag_context, git_info=git_combined_info)
        confirmation_required = False

    logger.info(f"[Reason] Planned tools: {tool_names}, confirmation_required: {confirmation_required}, risk_band: {risk_band}")
    return {
        "reasoning": reasoning,
        "confirmation_required": confirmation_required,
        "confirmation_message": f"{reasoning}" if confirmation_required else None,
        "context": {**ctx, "risk_band": risk_band},
        "plan_data": plan_data
    }
