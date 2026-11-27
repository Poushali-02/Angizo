"""
neurocode-backend/agent/graph.py

The agent as a LangGraph state graph (8 nodes; the 8th, recover, makes it a loop):

    context -> understand -> reason -> confirm --(no)--------------------------> narrate -> END
                               ^          |  ^                                       ^
                 .env allowed  |          |  |                                       |
                 --------------+       (yes) |                                       |
                                          v  |                                       |
                                       execute -> verify --(ok / unfixable)----------+
                                                     |
                                                     +--(fixable failure, first time)--> recover
                                                                                           |
                                         confirm <-----------------------------------------+

- confirm calls interrupt() when a "yes" is needed: the graph pauses there and the
  checkpointer keeps the state until api/ws.py resumes it with Command(resume=answer).
- verify -> recover -> confirm is the agentic loop: a push rejected because the remote is
  ahead is retried once as "pull, then push", after a new spoken "yes".
"""

import logging

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from agent.nodes import (
    confirm_action,
    execute_action,
    gather_context,
    narrate_response,
    reason_plan,
    understand_intent,
    verify_action,
)
from agent.nodes.recover import can_recover, recover_plan
from agent.state import AgentState

logger = logging.getLogger("neurocode.agent.graph")


def route_after_confirm(state: AgentState) -> str:
    """After the user's answer (or straight through when no answer was needed)."""
    if state.get("cancelled"):
        return "narrate"
    if state.get("pending_gate") == "env_granted":
        return "reason"  # allowed to read the .env file: now answer the actual question
    return "execute"


def route_after_verify(state: AgentState) -> str:
    return "recover" if can_recover(state) else "narrate"


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("context", gather_context)
    builder.add_node("understand", understand_intent)
    builder.add_node("reason", reason_plan)
    builder.add_node("confirm", confirm_action)
    builder.add_node("execute", execute_action)
    builder.add_node("verify", verify_action)
    builder.add_node("recover", recover_plan)
    builder.add_node("narrate", narrate_response)

    builder.set_entry_point("context")
    builder.add_edge("context", "understand")
    builder.add_edge("understand", "reason")
    builder.add_edge("reason", "confirm")
    builder.add_conditional_edges(
        "confirm", route_after_confirm, {"narrate": "narrate", "reason": "reason", "execute": "execute"}
    )
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges("verify", route_after_verify, {"recover": "recover", "narrate": "narrate"})
    builder.add_edge("recover", "confirm")  # the loop
    builder.add_edge("narrate", END)

    # The checkpointer saves the state at every step, so a run paused by interrupt() can be
    # resumed later under the same thread_id. In memory: a server restart forgets pauses.
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


agent_graph = build_graph()
