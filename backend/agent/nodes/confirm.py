"""
neurocode-backend/agent/nodes/confirm.py
"""
import logging
from agent.state import AgentState

logger = logging.getLogger("neurocode.agent.confirm")



def confirm_action(state: AgentState) -> AgentState:
    """
    [Confirm] node.
    This is a pass-through node in LangGraph. The conditional edge logic
    will check `state["confirmation_required"]` and `state["confirmed"]`
    to decide whether to pause the graph or proceed.
    """
    logger.info("[Confirm] Evaluated confirm node.")
    # No state mutations needed here; edges handle the routing based on state fields.
    return {}
