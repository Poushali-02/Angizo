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

def _changed_paths(repo: git.Repo) -> list:
    """Every path with uncommitted work: unstaged edits, staged edits and untracked files."""
    paths = set()
    for item in repo.index.diff(None):  # working tree vs index
        paths.add(item.b_path or item.a_path)
    try:
        for item in repo.index.diff("HEAD"):  # index vs last commit (staged changes)
            paths.add(item.b_path or item.a_path)
    except (git.BadName, ValueError, git.GitCommandError):
        # A repo with no commits yet has no HEAD: everything in the index is new
        paths.update(path for path, _stage in repo.index.entries.keys())
    paths.update(repo.untracked_files)  # .gitignore'd files never appear here
    return sorted(paths)


def status() -> dict:
    """Returns the current branch and every changed, staged or untracked file."""
    repo = _get_repo()
    if not repo:
        return {"error": "Not a git repository"}

    branch = "HEAD"
    if not repo.head.is_detached:
        branch = repo.active_branch.name

    return {
        "branch": branch,
        "changed_files": _changed_paths(repo),
        "repo_path": repo.working_dir,
    }

MAX_UNTRACKED_PREVIEW = 4000  # characters of new files shown to the LLM, in total


def diff() -> str:
    """Working tree + staged diff, plus a preview of new untracked files (git diff skips them)."""
    repo = _get_repo()
    if not repo:
        return ""
    try:
        parts = [repo.git.diff(), repo.git.diff("--cached")]
        budget = MAX_UNTRACKED_PREVIEW
        for path in repo.untracked_files:
            if budget <= 0:
                parts.append(f"new file: {path} (not shown)")
                continue
            try:
                with open(os.path.join(repo.working_dir, path), "r", encoding="utf-8") as f:
                    text = f.read(budget)
            except (OSError, UnicodeDecodeError):
                parts.append(f"new file: {path} (binary or unreadable)")
                continue
            budget -= len(text)
            body = "\n".join("+" + line for line in text.splitlines())
            parts.append(f"diff --git a/{path} b/{path}\nnew file\n--- /dev/null\n+++ b/{path}\n{body}")
        return "\n".join(p for p in parts if p).strip()
    except Exception as e:
        logger.error(f"[git_tool] Failed to fetch git diff: {e}")
        return ""

def commit(message: str, files: list = None) -> dict:
    """
    Commits exactly `files` (the list the user heard and approved) with `message`.
    Without a list it commits every changed file, as `git status` reports them.
    Never uses `git add -A`, so files that appear after the confirmation are left alone.
    """
    repo = _get_repo()
    if not repo:
        return {"status": "failure", "detail": "Not a git repository"}

    try:
        current = set(_changed_paths(repo))
        wanted = list(files) if files else sorted(current)
        to_stage = [f for f in wanted if f in current]
        if not to_stage:
            return {"status": "failure", "detail": "No changes to commit."}
        repo.git.add("--", *to_stage)  # also stages deletions of tracked files
        repo.git.commit("-m", message, "--", *to_stage)
        return {
            "status": "success",
            "commit_hash": repo.head.commit.hexsha,
            "files": to_stage,
            "message": message,
        }
    except Exception as e:
        return {"status": "failure", "detail": str(e)}

def _safe_branch(branch: str) -> bool:
    """A plain branch name: no refspec tricks ("+main" force-pushes, "a:b" pushes elsewhere)."""
    return (
        bool(branch)
        and not branch.startswith(("-", "+", "."))
        and ":" not in branch
        and ".." not in branch
        and all(c.isalnum() or c in "._/-" for c in branch)
    )


def push(branch: str) -> dict:
    """git push origin <branch>. Never forces; a rejection comes back as a failure with git's reason."""
    repo = _get_repo()
    if not repo:
        return {"status": "failure", "detail": "Not a git repository"}
    if not _safe_branch(branch):
        return {"status": "failure", "detail": f"Refused to push unsafe branch name {branch!r}"}
    try:
        repo.git.push("origin", branch)
        return {"status": "success", "branch": branch}
    except git.GitCommandError as e:
        return {"status": "failure", "detail": (e.stderr or str(e)).strip()}
    except Exception as e:
        return {"status": "failure", "detail": str(e)}


def pull(branch: str = None) -> dict:
    """
    git pull --no-rebase origin <branch>: merges the remote's commits, never rewrites history.
    On a merge conflict the merge is aborted, so the working tree is left exactly as it was,
    and the failure names the conflicting files.
    """
    repo = _get_repo()
    if not repo:
        return {"status": "failure", "detail": "Not a git repository"}

    current_branch = branch or (repo.active_branch.name if not repo.head.is_detached else "main")
    if not _safe_branch(current_branch):
        return {"status": "failure", "detail": f"Refused to pull unsafe branch name {current_branch!r}"}
    try:
        before = repo.head.commit.hexsha
    except ValueError:
        before = None
    try:
        repo.git.pull("--no-rebase", "--no-edit", "origin", current_branch)
    except git.GitCommandError as e:
        message = "\n".join(part for part in (e.stdout, e.stderr) if part).strip() or str(e)
        conflicted = [f for f in repo.git.diff("--name-only", "--diff-filter=U").split() if f]
        if conflicted or "CONFLICT" in message:
            try:
                repo.git.merge("--abort")
            except git.GitCommandError:
                pass
            files = ", ".join(conflicted) or "some files"
            return {"status": "failure", "detail": f"Merge conflict in {files}; the merge was aborted."}
        logger.error(f"[git_tool] Failed to pull: {message}")
        return {"status": "failure", "detail": message}
    except Exception as e:
        logger.error(f"[git_tool] Failed to pull: {e}")
        return {"status": "failure", "detail": str(e)}

    incoming = []
    if before:
        incoming = [c.message.strip() for c in repo.iter_commits(f"{before}..HEAD")][:5]
    return {
        "status": "success",
        "branch": current_branch,
        "incoming_commits": incoming,
        "detail": f"Pulled {len(incoming)} new commit(s) from origin/{current_branch}.",
    }
