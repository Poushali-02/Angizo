"""
neurocode-backend/agent/nodes/verify.py

[Verify] node: reads what [execute] reported and, for a failure, works out WHY from the
git error text. The cause decides what happens next (agent/graph.py, route_after_verify):
"remote_ahead" can be fixed by pulling first, so the graph loops back through [recover]
and [confirm]; every other cause goes to [narrate] and is explained in plain words.
"""

import logging

from agent.state import AgentState

logger = logging.getLogger("neurocode.agent.verify")

# (cause, phrases git uses for it), checked in order. The phrases are specific on purpose:
# git messages include repository paths, and a folder named "conflict-test" must not make
# a plain rejected push look like a merge conflict.
_FAILURE_PATTERNS = [
    ("conflict", ("merge conflict", "automatic merge failed", "conflict (content)", "unmerged files")),
    ("local_changes", ("would be overwritten", "please commit your changes or stash them")),
    ("remote_ahead", ("rejected", "fetch first", "non-fast-forward", "failed to push some refs",
                      "tip of your current branch is behind")),
    ("auth", ("authentication failed", "could not read username", "permission denied",
              "could not read from remote repository")),
    ("nothing_to_commit", ("no changes to commit", "nothing to commit")),
]


def classify_failure(detail: str) -> str:
    text = (detail or "").lower()
    for cause, phrases in _FAILURE_PATTERNS:
        if any(p in text for p in phrases):
            return cause
    return "unknown"


def verify_action(state: AgentState) -> dict:
    result = state.get("action_result") or {}
    status = result.get("status", "success")
    if status != "failure":
        logger.info(f"[Verify] Action status: {status}")
        return {"verification_status": status, "failure_cause": None}

    cause = classify_failure(result.get("detail", ""))
    logger.info(f"[Verify] Action failed ({cause}): {result.get('detail', '')[:200]}")
    return {"verification_status": "failure", "failure_cause": cause}
