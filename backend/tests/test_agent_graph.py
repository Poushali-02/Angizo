"""
The LangGraph agent: planning, the interrupt() pause for a spoken "yes", what actually gets
committed, and the verify -> recover -> confirm loop for a rejected push.
"""

import asyncio
import itertools

import pytest
from langgraph.types import Command

from agent.graph import agent_graph
from conftest import new_state, run_git

_threads = itertools.count()


class Run:
    """One command through the graph, like api/ws.py does it: start, then resume with answers."""

    def __init__(self):
        self.config = {"configurable": {"thread_id": f"test-{next(_threads)}"}}

    def start(self, transcript: str) -> dict:
        state = dict(new_state(transcript), cancelled=False, attempts=0, env_confirmations_received=0)
        return asyncio.run(agent_graph.ainvoke(state, self.config))

    def answer(self, yes: bool) -> dict:
        return asyncio.run(agent_graph.ainvoke(Command(resume=yes), self.config))


def question(result: dict):
    """The prompt confirm() paused on, or None when the run finished."""
    pending = result.get("__interrupt__") or []
    return pending[0].value["prompt"] if pending else None


# ── Read-only commands never pause ───────────────────────────────────────────

def test_status_question_never_asks_for_confirmation(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("def login(user, password, retries=3):\n    pass\n")

    final = Run().start("what is my git status")

    assert question(final) is None
    assert final["intent"] == "git_status"
    assert final["verification_status"] == "skipped"  # read-only tools change nothing
    assert "1 changed file" in final["narration"]  # speech is added by api/ws.py, not the graph


def test_diff_review_reads_the_real_diff(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("def login(user, password, retries=3):\n    pass\n")

    final = Run().start("review my git diff")

    review_prompt = next(p for p in fake_llm.prompts if "code review engine" in p)
    assert "retries=3" in review_prompt
    assert fake_llm.review in final["narration"]


def test_spoken_review_has_no_markdown(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")
    fake_llm.review = "The `login` function is **now** simpler."

    final = Run().start("review my diff")

    assert final["narration"] == "On main, 1 changed file: auth.py. The login function is now simpler."


# ── interrupt(): the pause for a spoken "yes" ────────────────────────────────

def test_commit_pauses_at_confirm_and_changes_nothing_yet(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")

    paused = Run().start("commit my changes")

    prompt = question(paused)
    assert "1 changed file: auth.py" in prompt and fake_llm.commit_message in prompt
    assert paused["__interrupt__"][0].value["gate"] == "action"
    assert paused.get("action_result") is None  # execute never ran
    assert run_git(git_repo, "rev-list", "--count", "HEAD") == "1"


def test_yes_resumes_and_commits_exactly_what_was_approved(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")
    run = Run()
    run.start("commit my changes")

    # After the prompt: a new file appears and the LLM would now draft a different message
    (git_repo / "late.py").write_text("appeared after the prompt\n")
    fake_llm.commit_message = "something else entirely"

    final = run.answer(True)

    assert question(final) is None
    assert final["verification_status"] == "success"
    assert run_git(git_repo, "log", "-1", "--format=%s") == "feat(auth): add login retries"
    assert run_git(git_repo, "show", "--name-only", "--format=", "HEAD") == "auth.py"
    assert final["narration"] == "Committed 1 file with message: feat(auth): add login retries."


def test_no_cancels_and_commits_nothing(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")
    run = Run()
    run.start("commit my changes")

    final = run.answer(False)

    assert final["verification_status"] == "cancelled"
    assert final["narration"] == "Action cancelled."
    assert run_git(git_repo, "rev-list", "--count", "HEAD") == "1"


def test_push_always_asks_first(git_repo, fake_llm, fake_voice):
    assert "push branch 'main'" in question(Run().start("push my branch"))


def test_dotenv_request_asks_then_answers_the_question(git_repo, fake_llm, fake_voice):
    run = Run()
    paused = run.start("read my .env file")
    assert "sensitive credentials" in question(paused)
    assert paused["__interrupt__"][0].value["gate"] == "env"
    assert paused["context"]["risk_band"] == "high-risk"

    final = run.answer(True)  # allowed: the graph goes back to reason and answers

    assert question(final) is None
    assert final["narration"] == fake_llm.answer


def test_dotenv_request_refused(git_repo, fake_llm, fake_voice):
    run = Run()
    run.start("read my .env file")
    assert run.answer(False)["narration"] == "Action cancelled."


def test_nothing_to_commit_is_said_plainly(git_repo, fake_llm, fake_voice):
    run = Run()
    run.start("commit my changes")  # nothing changed, but the plan still asks

    final = run.answer(True)

    assert final["verification_status"] == "failure"
    assert final["narration"] == "There was nothing to commit."
    assert final["earcon"] == "high-risk"


# ── Structured output: the planner's JSON must match the schema ─────────────

def test_empty_llm_plan_falls_back_to_the_rules(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")
    fake_llm.plan = {"reasoning": "need a message first", "tool_calls": [], "requires_confirm": True}

    paused = Run().start("commit everything I changed today")  # not a fast-path phrase

    assert paused["plan_data"]["source"] == "rules"
    assert paused["intent"] == "git_commit"
    assert question(paused) is not None
    assert sum("AI Planner" in p for p in fake_llm.prompts) == 2  # first try + one retry


def test_broken_llm_json_falls_back_to_the_rules(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")
    fake_llm.plan = "Sure! I'd commit that for you."

    paused = Run().start("commit everything I changed today")

    assert paused["plan_data"]["source"] == "rules"
    assert question(paused) is not None


def test_invalid_plan_is_fixed_by_the_retry(git_repo, fake_llm, fake_voice):
    fake_llm.plan = [
        '{"tool_calls": [{"tool": "show_status"}]}',  # a tool that does not exist
        '{"tool_calls": [{"tool": "get_git_status", "args": {}}]}',
    ]

    final = Run().start("summarise where things stand")

    assert final["plan_data"]["source"] == "llm_retry"
    assert "rejected" in fake_llm.prompts[-1] and "show_status" in fake_llm.prompts[-1]
    assert final["intent"] == "git_status"


def test_plan_wrapped_in_a_code_fence_is_still_read(git_repo, fake_llm, fake_voice):
    fake_llm.plan = '```json\n{"reasoning": "x", "tool_calls": [{"tool": "get_git_status", "args": {}}]}\n```'

    final = Run().start("anything at all")

    assert final["intent"] == "git_status"
    assert final["plan_data"]["source"] == "llm"


def test_unknown_tool_from_the_llm_never_runs(git_repo, fake_llm, fake_voice):
    fake_llm.plan = {"reasoning": "x", "tool_calls": [{"tool": "rm_rf_everything", "args": {}}]}

    final = Run().start("do something odd")

    assert final["plan_data"]["source"] == "rules"
    tools_run = [s["tool"] for s in final["action_result"]["executed_steps"]]
    assert "rm_rf_everything" not in tools_run
    assert run_git(git_repo, "status", "--porcelain") == ""


def test_force_push_branch_from_the_llm_is_rejected(git_repo, fake_llm, fake_voice):
    fake_llm.plan = {"tool_calls": [{"tool": "push_to_remote", "args": {"branch": "+main"}}]}

    paused = Run().start("push it to the server")

    pushes = [c for c in paused["plan_data"]["tool_calls"] if c["tool"] == "push_to_remote"]
    assert all(c["args"].get("branch") != "+main" for c in pushes)
    assert paused["plan_data"]["source"] == "rules"


# ── The agentic loop: verify -> recover -> confirm ──────────────────────────

def test_graph_has_the_recovery_loop():
    edges = {(e.source, e.target) for e in agent_graph.get_graph().edges}
    assert ("verify", "recover") in edges
    assert ("recover", "confirm") in edges
    assert ("confirm", "execute") in edges


def test_rejected_push_is_recovered_by_pull_then_push(team_repos, fake_llm, fake_voice):
    me, teammate, remote = team_repos
    run = Run()
    assert "push branch 'main'" in question(run.start("push my branch"))

    retry = run.answer(True)  # push is rejected: origin has the teammate's commit

    assert "rejected" in question(retry) and "pull them and push again" in question(retry)
    assert retry["attempts"] == 1

    final = run.answer(True)  # pull (merge), then push

    assert question(final) is None
    assert final["verification_status"] == "success"
    assert final["narration"] == "Pulled the new commits from origin, merged them, and pushed successfully."
    remote_log = run_git(me, "log", "origin/main", "--format=%s")
    assert "my work" in remote_log and "teammate work" in remote_log


def test_declining_the_recovery_pushes_nothing(team_repos, fake_llm, fake_voice):
    me, teammate, remote = team_repos
    run = Run()
    run.start("push my branch")
    run.answer(True)  # rejected -> recovery question

    final = run.answer(False)

    assert final["narration"] == "Action cancelled."
    assert "my work" not in run_git(me, "log", "origin/main", "--format=%s")


def test_recovery_runs_only_once(team_repos, fake_llm, fake_voice, monkeypatch):
    import tools.git_tool as git_tool
    monkeypatch.setattr(git_tool, "push", lambda branch: {
        "status": "failure", "detail": "! [rejected] main -> main (fetch first)"})
    import agent.registry as registry
    monkeypatch.setattr(registry, "git_push_tool", git_tool.push)
    run = Run()
    run.start("push my branch")
    run.answer(True)  # rejected -> one recovery

    final = run.answer(True)  # still rejected: no third question

    assert question(final) is None
    assert final["attempts"] == 1
    assert final["narration"].startswith("The push was rejected because the remote has commits")


def test_conflict_is_explained_and_the_merge_undone(team_repos_conflict, fake_llm, fake_voice):
    me, teammate, remote = team_repos_conflict
    run = Run()
    run.start("push my branch")
    run.answer(True)  # rejected -> recovery question

    final = run.answer(True)  # the pull conflicts

    assert final["verification_status"] == "failure"
    assert final["narration"].startswith("Pulling caused a merge conflict in auth.py")
    assert run_git(me, "status", "--porcelain") == ""  # merge aborted: nothing half-merged
    assert not (me / ".git" / "MERGE_HEAD").exists()
