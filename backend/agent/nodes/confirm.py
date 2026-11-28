"""
backend/agent/nodes/confirm.py

[Confirm] node: the human-in-the-loop step.

When the plan needs a spoken "yes" (commit, push, pull, reading a .env file), this node
calls LangGraph's interrupt(). The graph stops here and the checkpointer saves the whole
state. api/ws.py speaks the question; when the user answers (Alt+Y / Alt+N or by voice) it
resumes the graph with Command(resume=True/False), and interrupt() returns that answer.

Note: on resume LangGraph runs this node again from the top, so everything before
interrupt() must be free of side effects (it is: it only reads the state).
"""

import logging

from langgraph.types import interrupt

from agent.state import AgentState

logger = logging.getLogger("angizo.agent.confirm")


def confirm_action(state: AgentState) -> dict:
    if not state.get("confirmation_required"):
        return {}

    risk_band = state.get("context", {}).get("risk_band", "safe")
    logger.info("[Confirm] Pausing for the user's answer.")
    answer = interrupt({
        "prompt": state.get("confirmation_message") or "Continue?",
        "risk_band": risk_band,
        "gate": state.get("pending_gate") or "action",
    })
    yes = answer is True or str(answer).strip().lower() in ("yes", "true", "y", "confirm")
    logger.info(f"[Confirm] User answered {'yes' if yes else 'no'}.")

    if not yes:
        return {"confirmed": False, "cancelled": True, "confirmation_required": False,
                "verification_status": "cancelled"}
    if state.get("pending_gate") == "env":
        # Permission to read the .env file: go back to [reason] to answer the real question
        return {"confirmed": True, "confirmation_required": False, "pending_gate": "env_granted",
                "env_confirmations_received": state.get("env_confirmations_received", 0) + 1}
    return {"confirmed": True, "confirmation_required": False}
