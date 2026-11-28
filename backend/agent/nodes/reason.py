"""
backend/agent/nodes/reason.py
"""
import logging
from agent.state import AgentState
from tools.diff_intelligence import diff_intelligence
from tools.gemini_llm import gemini_llm
from tools.speech import prefetch_speech

logger = logging.getLogger("angizo.agent.reason")

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
                "pending_gate": "env",
                "context": {**ctx, "risk_band": "high-risk"},
                "plan_data": plan_data
            }

    if "commit_changes" in tool_names:
        changed_files = list(git_status.get("changed_files", []))
        files_spoken = _speak_files(changed_files)
        prefetch_speech(f"Found {files_spoken}.")  # synthesised while the LLM drafts the message
        draft_msg = await diff_intelligence.draft_commit_message(diff_text)
        # Pin what the user approves: the commit later uses exactly this message and file list
        plan_data = _pin_commit_args(plan_data, draft_msg, changed_files)
        if "push_to_remote" in tool_names:
            branch = git_status.get("branch", "main")
            reasoning = f"Found {files_spoken}. Suggested commit: '{draft_msg}'. Should I commit and push to origin/{branch}?"
            risk_band = "caution"
        else:
            reasoning = f"Found {files_spoken}. Suggested commit message: '{draft_msg}'. Should I commit?"
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
            preamble = f"On {branch}, {_speak_files(git_status.get('changed_files', []))}."
            prefetch_speech(preamble)  # synthesised while the LLM writes the review
            prose_review = await diff_intelligence.review_before_commit(diff_text)
            reasoning = f"{preamble} {prose_review}"
        else:
            reasoning = f"On {branch}, no uncommitted changes."
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
        "pending_gate": "action" if confirmation_required else None,
        "context": {**ctx, "risk_band": risk_band},
        "plan_data": plan_data
    }


def _speak_files(files: list) -> str:
    """'2 changed files: auth.py and payment.py' (names only up to 5 files, so it stays short)."""
    n = len(files)
    if n == 0:
        return "no changed files"
    label = "changed file" if n == 1 else "changed files"
    names = [f.replace("\\", "/").split("/")[-1] for f in files]
    if n > 5:
        return f"{n} {label}"
    listed = names[0] if n == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{n} {label}: {listed}"


def _pin_commit_args(plan_data: dict, message: str, files: list) -> dict:
    """Return a copy of the plan whose commit_changes call carries the approved message and files."""
    calls = []
    for tc in plan_data.get("tool_calls", []):
        if tc.get("tool") == "commit_changes":
            tc = {**tc, "args": {**tc.get("args", {}), "message": message, "files": files}}
        calls.append(tc)
    return {**plan_data, "tool_calls": calls}
