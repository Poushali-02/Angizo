"""The WebSocket API the VS Code extension talks to, end to end through FastAPI."""

import asyncio

import pytest
from fastapi.testclient import TestClient

import api.ws as ws_module
from conftest import FAKE_AUDIO, new_state, run_git
from main import app

RESULT_TYPES = {"action_result", "confirmation_request", "audio_narration"}


@pytest.fixture
def ws(git_repo, fake_llm, fake_voice):
    with TestClient(app) as client:
        with client.websocket_connect("/ws/session") as socket:
            socket.send_json({"type": "set_workspace", "workspace_path": str(git_repo)})
            ack = socket.receive_json()
            assert ack["type"] == "workspace_ack" and ack["status"] == "success"
            yield socket


def next_result(socket) -> dict:
    while True:
        msg = socket.receive_json()
        if msg["type"] in RESULT_TYPES:
            return msg


def test_health_endpoint():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_status_command_returns_a_spoken_result(ws, git_repo):
    (git_repo / "auth.py").write_text("changed\n")
    ws.send_json({"type": "text_command", "text": "what is my git status"})

    msg = next_result(ws)

    assert msg["type"] == "action_result"
    assert "1 changed file" in msg["detail"]
    assert msg["audio_base64"] == FAKE_AUDIO


def test_commit_then_alt_n_cancels_and_commits_nothing(ws, git_repo):
    (git_repo / "auth.py").write_text("changed\n")
    ws.send_json({"type": "text_command", "text": "commit my changes"})
    prompt = next_result(ws)
    assert prompt["type"] == "confirmation_request"
    assert "auth.py" in prompt["prompt"]

    ws.send_json({"type": "confirm_response", "confirmed": False})
    msg = next_result(ws)

    assert msg["status"] == "cancelled"
    assert run_git(git_repo, "rev-list", "--count", "HEAD") == "1"


def test_commit_then_alt_y_commits_with_the_spoken_message(ws, git_repo):
    (git_repo / "auth.py").write_text("changed\n")
    ws.send_json({"type": "text_command", "text": "commit my changes"})
    assert next_result(ws)["type"] == "confirmation_request"

    ws.send_json({"type": "confirm_response", "confirmed": True})
    msg = next_result(ws)

    assert msg["status"] == "success"
    assert "feat(auth): add login retries" in msg["detail"]
    assert run_git(git_repo, "log", "-1", "--format=%s") == "feat(auth): add login retries"


def test_a_new_command_while_waiting_drops_the_pending_commit(ws, git_repo):
    (git_repo / "auth.py").write_text("changed\n")
    ws.send_json({"type": "text_command", "text": "commit my changes"})
    assert next_result(ws)["type"] == "confirmation_request"

    ws.send_json({"type": "text_command", "text": "what is my git status"})
    assert next_result(ws)["type"] == "action_result"
    ws.send_json({"type": "confirm_response", "confirmed": True})  # a stray yes afterwards
    next_result(ws)

    assert run_git(git_repo, "rev-list", "--count", "HEAD") == "1"


@pytest.mark.parametrize("bad", ["asdfghjkl qwrtzxcvb", "\x00commit", ""])
def test_gibberish_and_null_bytes_are_rejected(ws, bad):
    ws.send_json({"type": "text_command", "text": bad})
    msg = next_result(ws)
    assert msg["status"] == "failure"
    assert msg["detail"].startswith("Rejected")


def test_invalid_json_and_unknown_types_get_an_error(ws):
    ws.send_text("{not json")
    assert next_result(ws)["detail"] == "Invalid JSON"
    ws.send_json({"type": "teleport"})
    assert "Unknown message type" in next_result(ws)["detail"]


def test_syntax_error_event_is_narrated_without_a_double_period(ws, fake_voice):
    ws.send_json({
        "type": "manual_observer_event", "event_type": "syntax_error",
        "file": "src/sample.ts", "line": 2, "error_message": "Expression expected.", "is_resolved": False,
    })
    msg = next_result(ws)

    assert msg["type"] == "audio_narration" and msg["channel"] == "manual_observer"
    assert msg["narration"] == "Syntax error detected in sample.ts on line 2: Expression expected."


def test_resolved_event_is_narrated(ws):
    ws.send_json({"type": "manual_observer_event", "event_type": "syntax_error",
                  "file": "sample.ts", "line": 0, "is_resolved": True})
    assert next_result(ws)["narration"] == "Syntax error resolved in sample.ts."


def test_runtime_error_event_is_explained(ws):
    ws.send_json({"type": "manual_observer_event", "event_type": "runtime_error", "file": "app.js",
                  "line": 1, "error_name": "TypeError", "error_message": "Cannot read properties of null",
                  "stack_trace": "TypeError: Cannot read properties of null\n    at app.js:1:5"})
    assert "TypeError" in next_result(ws)["narration"]


def test_copilot_summary_describes_the_inserted_code(ws, fake_llm):
    ws.send_json({"type": "copilot_observer_event", "event_type": "copilot_complete", "file": "payment.py",
                  "lines_added": 8, "error_count": 0,
                  "code_snippet": "def charge(amount, card):\n    return gateway.charge(card, amount)\n"})
    msg = next_result(ws)

    sent = next(p for p in fake_llm.prompts if "Copilot just inserted this code" in p)
    assert "def charge(amount, card)" in sent
    assert msg["narration"] == (
        "Adds a charge function that validates the amount and calls the payment gateway. No errors in payment.py."
    )


def test_copilot_summary_without_code_reports_lines_and_errors(ws):
    ws.send_json({"type": "copilot_observer_event", "event_type": "copilot_complete",
                  "file": "a/b/payment.py", "lines_added": 1, "error_count": 2})
    assert next_result(ws)["narration"] == "Copilot added 1 line to payment.py, 2 errors."


@pytest.mark.parametrize("by_ai, expected", [
    (True, "Copilot created new file payment.py."),
    (False, "New file payment.py created."),
])
def test_new_file_wording_depends_on_who_made_it(ws, by_ai, expected):
    ws.send_json({"type": "copilot_observer_event", "event_type": "file_created",
                  "file": "src/payment.py", "by_ai": by_ai})
    assert next_result(ws)["narration"] == expected


# ── Spoken yes / no while a commit is waiting ────────────────────────────────

class _FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


@pytest.mark.parametrize("heard, outcome", [
    ("yes", "confirm"),
    ("okay go ahead", "confirm"),
    ("please proceed", "confirm"),
    ("no", "cancel"),
    ("no, don't confirm", "cancel"),
    ("cancel that", "cancel"),
    ("look at the diff", "new command"),  # "ok" inside "look" must not confirm
    ("I know", "new command"),  # "no" inside "know" must not cancel
    ("tokens", "new command"),
])
def test_spoken_confirmation_matches_whole_words(monkeypatch, heard, outcome):
    ran = []

    async def fake_run(socket, session_id):
        ran.append(ws_module.session_states[session_id].get("confirmed"))

    monkeypatch.setattr(ws_module, "run_agent_graph", fake_run)
    sid = "voice-test"
    ws_module.session_states[sid] = dict(new_state("commit my changes"), confirmation_required=True)
    socket = _FakeSocket()

    async def scenario():
        await ws_module.handle_voice_transcript(socket, sid, heard)
        await asyncio.sleep(0.01)  # let the scheduled task run

    asyncio.run(scenario())
    try:
        if outcome == "cancel":
            assert socket.sent[-1]["status"] == "cancelled"
            assert ran == []
        elif outcome == "confirm":
            assert ran == [True]
        else:
            # Treated as a new command: the pending commit is dropped, never confirmed
            assert True not in ran
            assert not any(m.get("status") == "cancelled" for m in socket.sent)
    finally:
        ws_module.session_states.pop(sid, None)
