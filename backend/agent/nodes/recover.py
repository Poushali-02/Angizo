"""
neurocode-backend/agent/nodes/recover.py

[Recover] node: the agentic loop. Reached only when [verify] found a failure that has a
known fix and no recovery has been tried yet. It replaces the plan with the fix and asks
for a new "yes", so the graph goes recover -> confirm -> execute -> verify again.

Today the one fixable case is a push rejected because the remote has commits this branch
does not have: pull them (merge, never rebase or force), then push again. Anything that
needs a human decision, such as a merge conflict, is explained instead (see narrate).
"""

import logging

from agent.state import AgentState

logger = logging.getLogger("neurocode.agent.recover")

MAX_RECOVERY_ATTEMPTS = 1


def can_recover(state: AgentState) -> bool:
    return (
        state.get("verification_status") == "failure"
        and state.get("failure_cause") == "remote_ahead"
        and state.get("attempts", 0) < MAX_RECOVERY_ATTEMPTS
    )


def recover_plan(state: AgentState) -> dict:
    attempts = state.get("attempts", 0) + 1
    branch = state.get("context", {}).get("git_status", {}).get("branch", "main")
    logger.info(f"[Recover] Push rejected; proposing pull then push (attempt {attempts})")
    message = (
        f"The push was rejected because origin/{branch} has commits you don't have yet. "
        "Should I pull them and push again?"
    )
    return {
        "plan_data": {
            "reasoning": "recover from a rejected push",
            "tool_calls": [
                {"tool": "pull_from_remote", "args": {}},
                {"tool": "push_to_remote", "args": {}},
            ],
            "source": "recovery",
        },
        "attempts": attempts,
        "reasoning": message,
        "confirmation_required": True,
        "confirmation_message": message,
        "pending_gate": "action",
        "confirmed": False,
        "action_result": None,
        "verification_status": "pending",
        "failure_cause": None,
        "context": {**state.get("context", {}), "risk_band": "caution"},
    }
