"""The 7-node LangGraph agent: planning, the confirmation stop, and what actually gets committed."""

import asyncio

from agent.graph import agent_graph
from agent.nodes import execute_action, narrate_response, verify_action
from conftest import new_state, run_git


def run_graph(transcript: str) -> dict:
    return asyncio.run(agent_graph.ainvoke(new_state(transcript)))


def resume_after_yes(state: dict) -> dict:
    """What api/ws.py does when the user confirms: run execute -> verify -> narrate on the saved state."""
    state = dict(state, confirmed=True)

    async def resume():
        state.update(await execute_action(state))
        state.update(verify_action(state))
        state.update(await narrate_response(state))
        return state

    return asyncio.run(resume())


def test_status_question_never_asks_for_confirmation(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("def login(user, password, retries=3):\n    pass\n")

    final = run_graph("what is my git status")

    assert final["intent"] == "git_status"
    assert final["confirmation_required"] is False
    assert final["verification_status"] == "skipped"  # read-only tools change nothing
    assert "1 changed file" in final["narration"]  # speech is added by api/ws.py, not the graph


def test_diff_review_reads_the_real_diff(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("def login(user, password, retries=3):\n    pass\n")

    final = run_graph("review my git diff")

    review_prompt = next(p for p in fake_llm.prompts if "code review engine" in p)
    assert "retries=3" in review_prompt
    assert fake_llm.review in final["narration"]


def test_commit_stops_for_confirmation_and_changes_nothing_yet(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")

    final = run_graph("commit my changes")

    assert final["confirmation_required"] is True
    assert final["confirmed"] is False
    assert final.get("action_result") is None  # execute never ran
    assert "1 changed file: auth.py" in final["confirmation_message"]
    assert fake_llm.commit_message in final["confirmation_message"]
    assert run_git(git_repo, "rev-list", "--count", "HEAD") == "1"


def test_yes_commits_exactly_what_was_approved(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")
    paused = run_graph("commit my changes")

    # After the prompt: a new file appears and the LLM would now draft a different message
    (git_repo / "late.py").write_text("appeared after the prompt\n")
    fake_llm.commit_message = "something else entirely"

    final = resume_after_yes(paused)

    assert final["verification_status"] == "success"
    assert run_git(git_repo, "log", "-1", "--format=%s") == "feat(auth): add login retries"
    assert run_git(git_repo, "show", "--name-only", "--format=", "HEAD") == "auth.py"
    assert final["narration"] == "Committed 1 file with message: feat(auth): add login retries."


def test_empty_llm_plan_falls_back_to_the_rules(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")
    fake_llm.plan = {"reasoning": "need a message first", "tool_calls": [], "requires_confirm": True}

    final = run_graph("commit my changes")

    assert final["intent"] == "git_commit"
    assert final["confirmation_required"] is True


def test_broken_llm_json_falls_back_to_the_rules(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")
    fake_llm.plan = "Sure! I'd commit that for you."

    final = run_graph("commit my changes")

    assert final["intent"] == "git_commit"
    assert final["confirmation_required"] is True


def test_plan_wrapped_in_a_code_fence_is_still_read(git_repo, fake_llm, fake_voice):
    fake_llm.plan = '```json\n{"reasoning": "x", "tool_calls": [{"tool": "get_git_status", "args": {}}]}\n```'

    final = run_graph("anything at all")

    assert final["intent"] == "git_status"


def test_unknown_tool_from_the_llm_is_skipped_not_run(git_repo, fake_llm, fake_voice):
    fake_llm.plan = {"reasoning": "x", "tool_calls": [{"tool": "rm_rf_everything", "args": {}}]}

    final = run_graph("do something odd")

    step = final["action_result"]["executed_steps"][0]
    assert step["result"]["status"] == "skipped"
    assert run_git(git_repo, "status", "--porcelain") == ""


def test_push_always_asks_first(git_repo, fake_llm, fake_voice):
    final = run_graph("push my branch")

    assert final["confirmation_required"] is True
    assert "push branch 'main'" in final["confirmation_message"]


def test_dotenv_request_asks_first_and_is_high_risk(git_repo, fake_llm, fake_voice):
    final = run_graph("read my .env file")

    assert final["confirmation_required"] is True
    assert final["context"]["risk_band"] == "high-risk"


def test_failed_commit_is_narrated_as_a_failure(git_repo, fake_llm, fake_voice):
    paused = run_graph("commit my changes")  # nothing changed, but the plan still asks
    final = resume_after_yes(paused)

    assert final["verification_status"] == "failure"
    assert final["narration"].startswith("Action failed")
    assert final["earcon"] == "high-risk"


def test_spoken_review_has_no_markdown(git_repo, fake_llm, fake_voice):
    (git_repo / "auth.py").write_text("changed\n")
    fake_llm.review = "The `login` function is **now** simpler."

    final = run_graph("review my diff")

    assert final["narration"] == "On main, 1 changed file: auth.py. The login function is now simpler."
