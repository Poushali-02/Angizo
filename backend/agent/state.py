"""
neurocode-backend/agent/state.py

Shared agent state for the LangGraph graph (see agent/graph.py). Every node reads this
dict and returns only the keys it changes. LangGraph keeps only the keys declared here,
so any value a node needs later must be listed.
"""

from typing import TypedDict, Optional, Literal


class AgentState(TypedDict, total=False):
    # Input
    transcript: str

    # [context] git status, diff and code-search snippets; [reason] adds risk_band
    context: dict

    # [understand] the validated plan: {"tool_calls": [...], "source": "fast_path" | "llm" | ...}
    intent: Optional[str]
    plan_data: Optional[dict]

    # [reason] what to say, and whether it needs a spoken "yes" first
    reasoning: Optional[str]
    confirmation_required: bool
    confirmation_message: Optional[str]
    # Which question the pending "yes" answers: "action" (run the plan) or "env" (read a .env file)
    pending_gate: Optional[Literal["action", "env", "env_granted"]]
    env_confirmations_received: int

    # [confirm] the user's answer (filled in when the graph resumes after interrupt())
    confirmed: bool
    cancelled: bool

    # [execute]
    action_result: Optional[dict]

    # [verify] outcome, and why it failed (drives the recovery loop)
    verification_status: Literal["pending", "success", "skipped", "failure", "cancelled"]
    failure_cause: Optional[Literal["remote_ahead", "conflict", "local_changes", "auth", "nothing_to_commit", "unknown"]]

    # [recover] how many recovery rounds have run (at most MAX_RECOVERY_ATTEMPTS)
    attempts: int

    # [narrate]
    narration: Optional[str]
    earcon: Optional[Literal["safe", "caution", "high-risk"]]
