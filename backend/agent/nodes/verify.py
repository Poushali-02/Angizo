"""
neurocode-backend/agent/nodes/verify.py
"""
import logging
from agent.state import AgentState

logger = logging.getLogger("neurocode.agent.verify")

def verify_action(state: AgentState) -> AgentState:
    """
    [Verify] node.
    Checks the outcome of the execute step.
    """
    result = state.get("action_result", {})
    status = result.get("status", "success") # default success if no action or skipped
    
    logger.info(f"[Verify] Action status: {status}")
    return {"verification_status": status}
