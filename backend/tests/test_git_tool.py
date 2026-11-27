"""Git tool: what counts as a change, and committing exactly the approved files."""

import tools.git_tool as git_tool
from conftest import run_git


def test_status_lists_modified_staged_and_untracked_but_not_ignored(git_repo):
    (git_repo / "auth.py").write_text("def login(): pass\n")  # modified
    (git_repo / "staged.py").write_text("x = 1\n")
    run_git(git_repo, "add", "staged.py")  # staged only
    (git_repo / "new.py").write_text("y = 2\n")  # untracked
    (git_repo / ".env").write_text("SECRET=1\n")  # ignored

    status = git_tool.status()

    assert status["branch"] == "main"
    assert status["changed_files"] == ["auth.py", "new.py", "staged.py"]


def test_status_on_clean_repo_has_no_changes(git_repo):
    assert git_tool.status()["changed_files"] == []


def test_status_works_before_the_first_commit(tmp_path, monkeypatch):
    repo = tmp_path / "empty"
    repo.mkdir()
    run_git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("a = 1\n")
    run_git(repo, "add", "a.py")
    (repo / "b.py").write_text("b = 1\n")
    monkeypatch.setattr(git_tool, "_session_repo_path", str(repo))

    assert git_tool.status()["changed_files"] == ["a.py", "b.py"]


def test_status_outside_a_repo_reports_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(git_tool, "_session_repo_path", str(tmp_path))
    assert "error" in git_tool.status()


def test_diff_includes_new_untracked_files(git_repo):
    (git_repo / "auth.py").write_text("def login(user, password, retries=3):\n    pass\n")
    (git_repo / "payment.py").write_text("def charge(amount):\n    return amount\n")

    diff = git_tool.diff()

    assert "retries=3" in diff
    assert "+++ b/payment.py" in diff
    assert "+def charge(amount):" in diff


def test_commit_only_commits_the_approved_files(git_repo):
    (git_repo / "auth.py").write_text("def login(): return True\n")
    (git_repo / "later.py").write_text("print('appeared after the user said yes')\n")

    result = git_tool.commit("fix: simplify login", files=["auth.py"])

    assert result["status"] == "success"
    assert result["files"] == ["auth.py"]
    assert run_git(git_repo, "log", "-1", "--format=%s") == "fix: simplify login"
    assert run_git(git_repo, "show", "--name-only", "--format=", "HEAD") == "auth.py"
    assert "?? later.py" in run_git(git_repo, "status", "--porcelain")


def test_commit_leaves_other_staged_files_staged(git_repo):
    (git_repo / "auth.py").write_text("changed\n")
    (git_repo / "other.py").write_text("other\n")
    run_git(git_repo, "add", "other.py")

    git_tool.commit("chore: auth only", files=["auth.py"])

    assert run_git(git_repo, "show", "--name-only", "--format=", "HEAD") == "auth.py"
    assert "A  other.py" in run_git(git_repo, "status", "--porcelain")


def test_commit_records_a_deleted_file(git_repo):
    (git_repo / "auth.py").unlink()

    result = git_tool.commit("chore: remove auth", files=["auth.py"])

    assert result["status"] == "success"
    assert run_git(git_repo, "ls-files", "auth.py") == ""


def test_commit_without_a_list_commits_every_change_but_not_ignored_files(git_repo):
    (git_repo / "auth.py").write_text("changed\n")
    (git_repo / "new.py").write_text("new\n")
    (git_repo / ".env").write_text("SECRET=1\n")

    result = git_tool.commit("feat: everything")

    assert result["files"] == ["auth.py", "new.py"]
    assert run_git(git_repo, "ls-files", ".env") == ""


def test_commit_with_nothing_to_commit_fails_cleanly(git_repo):
    result = git_tool.commit("empty", files=["auth.py"])
    assert result == {"status": "failure", "detail": "No changes to commit."}


def test_commit_skips_approved_files_that_no_longer_changed(git_repo):
    (git_repo / "auth.py").write_text("changed\n")

    result = git_tool.commit("fix", files=["auth.py", "gone.py"])

    assert result["files"] == ["auth.py"]


def test_push_without_a_remote_fails_without_raising(git_repo):
    result = git_tool.push("main")
    assert result["status"] == "failure"
