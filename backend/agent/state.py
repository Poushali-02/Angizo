"""
neurocode-backend/agent/state.py

Shared agent state schema for the LangGraph loop.
"""

from typing import TypedDict, Optional, Literal


class AgentState(TypedDict):
    """
    State flowing through the 7-node LangGraph loop.
    """
    # [Listen]
    transcript: str

    # [Understand]
    intent: Optional[str]
    plan_data: Optional[dict]

    # [Context]
    context: dict  # Holds data gathered from tools, e.g., git status

    # [Reason]
    reasoning: Optional[str]
    confirmation_required: bool

    # [Confirm]
    confirmed: bool
    confirmation_message: Optional[str]

    # [Execute]
    action_result: Optional[dict]

    # [Verify]
    verification_status: Literal["success", "failure", "pending"]

    # [Narrate]
    narration: Optional[str]
    earcon: Optional[Literal["safe", "caution", "high-risk"]]
