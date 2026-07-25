"""
neurocode-backend/agent/graph.py
"""
import logging
from langgraph.graph import StateGraph, END
from agent.state import AgentState
from agent.nodes import (
    understand_intent,
    gather_context,
    reason_plan,
    confirm_action,
    execute_action,
    verify_action,
    narrate_response,
)

logger = logging.getLogger("neurocode.agent.graph")

def should_confirm(state: AgentState) -> str:
    """
    Conditional edge logic from Confirm node.
    Returns the name of the next node or an interrupt.
    """
    if state.get("confirmation_required") and not state.get("confirmed"):
        logger.info("[Graph] Pausing for user confirmation.")
        # If we need confirmation but haven't got it, we end this graph run.
        # The caller will send a confirmation request and resume later.
        # LangGraph v0.0.65 supports interrupt before/after, but we can also
        # just exit and resume by passing state in again. 
        # For simplicity in this spike, we route to a special node or end.
        return "wait_for_user"
    return "execute"

def build_graph() -> StateGraph:
    """Builds the LangGraph state graph."""
    builder = StateGraph(AgentState)

    # Add nodes
    builder.add_node("understand", understand_intent)
    builder.add_node("context", gather_context)
    builder.add_node("reason", reason_plan)
    builder.add_node("confirm", confirm_action)
    builder.add_node("execute", execute_action)
    builder.add_node("verify", verify_action)
    builder.add_node("narrate", narrate_response)

    # Edges
    builder.set_entry_point("context")
    builder.add_edge("context", "understand")
    builder.add_edge("understand", "reason")
    builder.add_edge("reason", "confirm")

    # Conditional edge after confirm
    builder.add_conditional_edges(
        "confirm",
        should_confirm,
        {
            "wait_for_user": END, # Ends the run, caller asks user and resumes
            "execute": "execute"
        }
    )

    builder.add_edge("execute", "verify")
    builder.add_edge("verify", "narrate")
    builder.add_edge("narrate", END)

    # In LangGraph 0.0.65, state graphs can be compiled without a checkpointer
    # if we manage the state externally in our websocket handler.
    return builder.compile()

# Singleton graph instance
agent_graph = build_graph()
