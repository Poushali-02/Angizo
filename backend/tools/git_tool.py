"""
neurocode-backend/tools/git_tool.py

GitPython wrapper per AGENT_SPEC.md interfaces.
"""
import git
import os
import logging
import config

logger = logging.getLogger("neurocode.tools.git")

# Per-session repo path override (set by WebSocket client)
_session_repo_path = None

def _set_repo_path(path: str):
    """Set the repository path for the current session."""
    global _session_repo_path
    _session_repo_path = path
    logger.info(f"[git_tool] Repo path set to: {path}")

def _get_repo() -> git.Repo:
    # Use session-specific path if set, otherwise fall back to config
    repo_path = _session_repo_path if _session_repo_path else config.REPO_PATH
    logger.info(f"[git_tool] Getting repo at: {repo_path} (session override: {_session_repo_path})")
    try:
        return git.Repo(repo_path, search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        logger.warning(f"No git repository found at {repo_path}")
        return None

def status() -> dict:
    """Returns changed/added/deleted files, current branch, ahead/behind counts."""
    repo = _get_repo()
    if not repo:
        return {"error": "Not a git repository"}

    branch = "HEAD"
    if not repo.head.is_detached:
        branch = repo.active_branch.name

    # Changed files (untracked + modified)
    changed = [item.a_path for item in repo.index.diff(None)]
    untracked = repo.untracked_files
    all_changed = list(set(changed + untracked))

    repo_path = repo.working_dir if repo else (_session_repo_path or config.REPO_PATH)

    return {
        "branch": branch,
        "changed_files": all_changed,
        "repo_path": repo_path
    }

def diff() -> str:
    """Returns working tree git diff string."""
    repo = _get_repo()
    if not repo:
        return ""
    try:
        # Get working tree diff
        unstaged = repo.git.diff()
        staged = repo.git.diff("--cached")
        combined = (unstaged + "\n" + staged).strip()
        return combined
    except Exception as e:
        logger.error(f"[git_tool] Failed to fetch git diff: {e}")
        return ""

def commit(message: str) -> dict:
    """Runs git add . && git commit -m <message>."""
    repo = _get_repo()
    if not repo:
        return {"status": "failure", "detail": "Not a git repository"}

    try:
        repo.git.add(A=True)
        commit_obj = repo.index.commit(message)
        return {"status": "success", "commit_hash": commit_obj.hexsha}
    except Exception as e:
        return {"status": "failure", "detail": str(e)}

def push(branch: str) -> dict:
    """Runs git push origin <branch>. Raises on conflict/rejection."""
    repo = _get_repo()
    if not repo:
        return {"status": "failure", "detail": "Not a git repository"}

    try:
        remote = repo.remote(name='origin')
        push_info = remote.push(branch)
        
        # Check if push failed
        for info in push_info:
            if info.flags & git.remote.PushInfo.ERROR:
                return {"status": "failure", "detail": info.summary}
                
        return {"status": "success"}
    except Exception as e:
        return {"status": "failure", "detail": str(e)}

def pull(branch: str = None) -> dict:
    """
    Executes git fetch + git pull origin <branch>.
    Extracts incoming commit messages and diff summaries for accessibility narration.
    """
    repo = _get_repo()
    if not repo:
        return {"status": "failure", "detail": "Not a git repository"}

    try:
        current_branch = branch or (repo.active_branch.name if not repo.head.is_detached else "main")
        
        # 1. Fetch remote changes and compute incoming diff/commit log before pull
        try:
            repo.git.fetch()
        except Exception:
            pass

        incoming_diff = ""
        try:
            incoming_diff = repo.git.diff(f"HEAD..origin/{current_branch}")
        except Exception:
            pass

        # 2. Execute git pull
        remote = repo.remote(name='origin')
        pull_info = remote.pull(current_branch)
        
        # 3. Extract incoming commit messages
        incoming_commits = []
        try:
            incoming_commits = [c.message.strip() for c in repo.iter_commits("ORIG_HEAD..HEAD")]
        except Exception:
            pass

        return {
            "status": "success",
            "branch": current_branch,
            "incoming_diff": incoming_diff[:2500],
            "incoming_commits": incoming_commits[:5],
            "detail": f"Successfully pulled latest changes from origin/{current_branch}."
        }
    except Exception as e:
        logger.error(f"[git_tool] Failed to pull: {e}")
        return {"status": "failure", "detail": str(e)}
