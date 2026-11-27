"""
Shared fixtures for the Angizo backend tests.

Every test runs offline: no API keys are loaded, the LLM and the voices are fakes,
and git commands run only inside throwaway repositories under pytest's tmp_path.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Must happen before any backend module is imported: config.py and main.py read these at import time.
os.environ["ANGIZO_SKIP_DOTENV"] = "1"
for _key in list(os.environ):
    if _key.startswith(("SARVAM_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "ELEVENLABS_API_KEY", "GITHUB_PAT")):
        del os.environ[_key]

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
import pytest  # noqa: E402

import tools.git_tool as git_tool  # noqa: E402
from tools.diff_intelligence import diff_intelligence  # noqa: E402
from tools.elevenlabs_tts import elevenlabs_tts_client  # noqa: E402
from tools.gemini_llm import gemini_llm  # noqa: E402
from tools.rag_engine import rag_engine  # noqa: E402
from tools.sarvam_tts import sarvam_tts_client  # noqa: E402

FAKE_AUDIO = "RkFLRV9BVURJTw=="  # base64 of "FAKE_AUDIO"


def pytest_configure(config):
    """With ANGIZO_SANDBOX set (see scripts/make_sandbox.py), every temp repo goes in <sandbox>/runs/pytest."""
    sandbox = os.environ.get("ANGIZO_SANDBOX")
    if sandbox and not config.option.basetemp:
        config.option.basetemp = str(Path(sandbox) / "runs" / "pytest")


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """A fresh repo with one commit; the backend's git tool points at it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    hooks = tmp_path / "no-hooks"
    hooks.mkdir()
    run_git(repo, "init", "-q", "-b", "main")
    run_git(repo, "config", "user.name", "Angizo Test")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "core.hooksPath", str(hooks))  # ignore any global commit hooks
    run_git(repo, "config", "core.autocrlf", "false")
    (repo / "auth.py").write_text("def login(user, password):\n    return check(user, password)\n")
    (repo / ".gitignore").write_text(".env\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-q", "-m", "init")
    monkeypatch.setattr(git_tool, "_session_repo_path", str(repo))
    return repo


class FakeLLM:
    """
    Stands in for Groq (and Gemini, which falls back to Groq when it has no key).
    Answers by prompt type; tests can override with `plan`, `commit_message` or `answer`,
    and read every prompt it was sent in `prompts`.
    """

    def __init__(self):
        self.prompts: list[str] = []
        self.plan = None  # dict or raw string returned for planner prompts; None = keyword plan
        self.commit_message = "feat(auth): add login retries"
        self.review = "The login function now retries three times before failing."
        self.answer = "This project uses FastAPI and a VS Code extension."
        self.copilot_sentence = "Adds a charge function that validates the amount and calls the payment gateway"

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "AI Planner" in prompt:
            if self.plan is not None:
                return self.plan if isinstance(self.plan, str) else json.dumps(self.plan)
            command = re.search(r'User Command: "(.*)"', prompt).group(1).lower()
            return json.dumps(_keyword_plan(command))
        if "conventional commit message" in prompt:
            return self.commit_message
        if "code review engine" in prompt:
            return self.review
        if "Copilot just inserted this code" in prompt:
            return self.copilot_sentence
        if "runtime / compilation error" in prompt:
            return "TypeError on line 1 of app.js. The code reads a property of null."
        return self.answer


def _keyword_plan(command: str) -> dict:
    if "commit" in command and "push" in command:
        calls = ["get_git_diff", "commit_changes", "push_to_remote"]
    elif "commit" in command:
        calls = ["get_git_diff", "commit_changes"]
    elif "push" in command:
        calls = ["push_to_remote"]
    elif "pull" in command:
        calls = ["pull_from_remote"]
    elif "status" in command:
        calls = ["get_git_status"]
    elif "diff" in command or "review" in command:
        calls = ["get_git_diff"]
    else:
        calls = ["query_codebase_rag"]
    return {
        "reasoning": "test plan",
        "tool_calls": [{"tool": c, "args": {}} for c in calls],
        "requires_confirm": False,
        "risk_band": "safe",
    }


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(diff_intelligence, "_call_groq", llm)
    monkeypatch.setattr(gemini_llm, "api_key", "")  # plan through the (fake) Groq path
    return llm


class FakeVoice:
    def __init__(self):
        self.spoken: list[str] = []

    async def sarvam(self, text: str) -> str:
        self.spoken.append(text)
        return FAKE_AUDIO

    async def elevenlabs(self, text: str, risk_band: str = "safe") -> str:
        self.spoken.append(text)
        return FAKE_AUDIO


@pytest.fixture
def fake_voice(monkeypatch):
    voice = FakeVoice()
    monkeypatch.setattr(sarvam_tts_client, "generate_filler_audio_base64", voice.sarvam)
    monkeypatch.setattr(elevenlabs_tts_client, "generate_narration_audio_base64", voice.elevenlabs)
    return voice


@pytest.fixture(autouse=True)
def fresh_rag_index():
    rag_engine._index_cache.clear()
    rag_engine._indexed_at.clear()
    yield


def mock_httpx(monkeypatch, module, handler):
    """
    Make `module.httpx.AsyncClient(...)` use an in-memory transport that calls handler(request).
    Returns the list of requests it saw.
    """
    seen = []

    def recording_handler(request):
        seen.append(request)
        return handler(request)

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(recording_handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)
    return seen


def new_state(transcript: str) -> dict:
    return {
        "transcript": transcript,
        "intent": None,
        "plan_data": None,
        "context": {},
        "reasoning": None,
        "confirmation_required": False,
        "confirmed": False,
        "confirmation_message": None,
        "action_result": None,
        "verification_status": "pending",
        "narration": None,
        "earcon": None,
    }
