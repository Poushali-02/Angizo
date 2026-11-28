"""
backend/agent/nodes/narrate.py

[Narrate] node: chooses the sentence the user hears. Speech itself is produced by
api/ws.py (send_spoken), which plays the first sentence while the rest is synthesised.
Failures are explained in plain words from [verify]'s cause, never as raw git output.
"""

import logging
import re

from agent.state import AgentState

logger = logging.getLogger("angizo.agent.narrate")

_FAILURE_WORDS = {
    "remote_ahead": "The push was rejected because the remote has commits you don't have. Pull them first, then push.",
    "local_changes": "Git stopped the pull because it would overwrite your uncommitted changes. Commit or stash them first.",
    "auth": "Git could not sign in to the remote. Check your credentials or network.",
    "nothing_to_commit": "There was nothing to commit.",
}


async def narrate_response(state: AgentState) -> dict:
    v_status = state.get("verification_status")
    result = state.get("action_result") or {}
    reasoning = state.get("reasoning", "")
    risk_band = state.get("context", {}).get("risk_band", "safe")

    executed_steps = result.get("executed_steps", [])
    executed_tools = [s.get("tool") for s in executed_steps]
    recovered = state.get("attempts", 0) > 0

    if state.get("cancelled") or v_status == "cancelled":
        narration = "Action cancelled."
    elif v_status == "failure":
        narration = _explain_failure(state.get("failure_cause"), result.get("detail", ""))
        risk_band = "high-risk"
    elif "commit_changes" in executed_tools and "push_to_remote" in executed_tools:
        narration = f"Committed {_commit_summary(executed_steps)} and pushed to origin."
    elif "commit_changes" in executed_tools:
        narration = f"Committed {_commit_summary(executed_steps)}."
    elif recovered and "pull_from_remote" in executed_tools and "push_to_remote" in executed_tools:
        narration = "Pulled the new commits from origin, merged them, and pushed successfully."
    elif "push_to_remote" in executed_tools:
        narration = "Push completed successfully."
    elif "pull_from_remote" in executed_tools:
        narration = "Pulled latest changes from remote origin successfully."
    else:
        narration = reasoning if reasoning else "Action completed successfully."

    logger.info(f"[Narrate] {narration} (risk_band={risk_band})")
    return {"narration": narration, "earcon": risk_band}


def _explain_failure(cause: str, detail: str) -> str:
    if cause == "conflict":
        files = re.findall(r"conflict in ([^\s,.;]+(?:\.[\w]+)?)", detail, flags=re.IGNORECASE)
        where = f" in {', '.join(dict.fromkeys(files))}" if files else ""
        return (f"Pulling caused a merge conflict{where}. I undid the merge, so nothing changed. "
                "Resolve it by hand, then try again.")
    if cause in _FAILURE_WORDS:
        return _FAILURE_WORDS[cause]
    short = " ".join((detail or "unknown error").split())[:160]
    return f"Action failed: {short}."


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
