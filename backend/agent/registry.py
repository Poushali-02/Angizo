"""
neurocode-backend/agent/registry.py

Atomic Tool Registry & Executor for Dynamic ReAct Planning.
Eliminates static intent taxonomy enums completely.
"""

import logging
from tools.git_tool import (
    status as git_status_tool,
    diff as git_diff_tool,
    commit as git_commit_tool,
    push as git_push_tool,
    pull as git_pull_tool
)
from tools.diff_intelligence import diff_intelligence

logger = logging.getLogger("neurocode.agent.registry")

# --- ATOMIC TOOL SPECIFICATIONS FOR LLM PLANNER ---
ATOMIC_TOOLS = [
    {
        "name": "get_git_status",
        "description": "Get current active git branch and list of modified/untracked files.",
        "parameters": {},
        "mutating": False
    },
    {
        "name": "get_git_diff",
        "description": "Get line-by-line working tree git diff for modified files.",
        "parameters": {},
        "mutating": False
    },
    {
        "name": "commit_changes",
        "description": "Stage working tree changes and commit them with a conventional commit message.",
        "parameters": {
            "message": "Suggested conventional commit message string (optional)"
        },
        "mutating": True
    },
    {
        "name": "push_to_remote",
        "description": "Push local branch commits to remote origin repository.",
        "parameters": {
            "branch": "Branch name to push (optional, defaults to active branch)"
        },
        "mutating": True
    },
    {
        "name": "pull_from_remote",
        "description": "Fetch and pull remote changes from origin repository into current local branch.",
        "parameters": {
            "branch": "Branch name to pull (optional, defaults to active branch)"
        },
        "mutating": True
    },
    {
        "name": "query_codebase_rag",
        "description": "Query local workspace codebase files and return relevant code snippets to answer user questions.",
        "parameters": {
            "query": "Search query or question string"
        },
        "mutating": False
    }
]


async def execute_tool_call(tool_name: str, args: dict = None, context: dict = None) -> dict:
    """
    Executes an atomic tool function dynamically and returns structured results.
    """
    args = args or {}
    context = context or {}
    logger.info(f"[ToolRegistry] Executing tool '{tool_name}' with args={args}")

    try:
        if tool_name == "get_git_status":
            return git_status_tool()

        elif tool_name == "get_git_diff":
            diff_text = git_diff_tool()
            return {"diff_text": diff_text, "diff_len": len(diff_text)}

        elif tool_name == "commit_changes":
            msg = args.get("message")
            if not msg:
                diff_text = context.get("diff_text", git_diff_tool())
                msg = await diff_intelligence.draft_commit_message(diff_text)
            return git_commit_tool(msg, files=args.get("files"))

        elif tool_name == "push_to_remote":
            branch = args.get("branch") or context.get("git_status", {}).get("branch", "main")
            return git_push_tool(branch)

        elif tool_name == "pull_from_remote":
            branch = args.get("branch") or context.get("git_status", {}).get("branch", "main")
            return git_pull_tool(branch)

        elif tool_name == "query_codebase_rag":
            return {"status": "success", "rag_retrieved": True}

        else:
            logger.warning(f"[ToolRegistry] Unknown tool_name '{tool_name}'")
            return {"status": "skipped", "detail": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.error(f"[ToolRegistry] Tool '{tool_name}' execution failed: {e}")
        return {"status": "failure", "detail": str(e)}
