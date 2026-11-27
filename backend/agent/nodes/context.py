"""
neurocode-backend/agent/nodes/context.py
"""
import asyncio
import logging
from agent.state import AgentState
from tools.git_tool import status as git_status_tool, diff as git_diff_tool
from tools.rag_engine import rag_engine

logger = logging.getLogger("neurocode.agent.context")

async def gather_context(state: AgentState) -> AgentState:
    """
    [Gather Context] node.
    Fetches required Git information, working tree diffs, and codebase RAG context.
    """
    intent = state.get("intent")
    transcript = state.get("transcript", "")
    context_data = {}

    try:
        status = await asyncio.to_thread(git_status_tool)  # git is slow: keep the event loop free
        diff_text = await asyncio.to_thread(git_diff_tool)
        context_data["git_status"] = status
        context_data["diff_text"] = diff_text
        logger.info(f"[Context] Gathered git status: branch={status.get('branch')}, changed_files={len(status.get('changed_files', []))}, diff_len={len(diff_text)}")

        # Retrieve RAG codebase context
        repo_path = status.get("repo_path", "")
        rag_context = await rag_engine.retrieve_context(transcript, workspace_path=repo_path)
        context_data["rag_context"] = rag_context

    except Exception as e:
        logger.error(f"[Context] Failed to gather context: {e}")
        context_data["error"] = str(e)

    return {"context": context_data}
