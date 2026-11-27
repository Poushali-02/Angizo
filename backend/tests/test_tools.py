"""Code search, the LLM fallbacks and the speech clients."""

import asyncio
import json

import httpx
import pytest

import tools.elevenlabs_tts as elevenlabs_module
import tools.gemini_llm as gemini_module
import tools.sarvam_tts as sarvam_module
from conftest import mock_httpx
from tools.diff_intelligence import _short_name, diff_intelligence
from tools.gemini_llm import GeminiLLM
from tools.rag_engine import rag_engine
from tools.sarvam_key_manager import sarvam_key_manager
from tools.sarvam_tts import SarvamFillerTTS, pick_speaker, truncate_for_tts


# ── Code search (RAG) ────────────────────────────────────────────────────────

def test_secrets_files_are_never_indexed(tmp_path):
    (tmp_path / ".env").write_text("STRIPE_SECRET_KEY=sk_live_123\n")
    (tmp_path / ".env.local").write_text("STRIPE_SECRET_KEY=sk_live_456\n")
    (tmp_path / "billing.py").write_text("STRIPE_SECRET_KEY = os.environ['STRIPE_SECRET_KEY']\n")

    # Keyword search matches whole identifiers, so ask with the name exactly as the files use it
    context = asyncio.run(rag_engine.retrieve_context("what is STRIPE_SECRET_KEY", workspace_path=str(tmp_path)))

    assert "billing.py" in context
    assert "sk_live" not in context
    assert "--- File: .env" not in context


def test_ignored_folders_are_skipped(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("function paymentGateway() {}\n")

    assert asyncio.run(rag_engine.retrieve_context("paymentGateway", workspace_path=str(tmp_path))) == ""


def test_index_picks_up_new_files_after_it_expires(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("def alpha(): pass\n")
    asyncio.run(rag_engine.retrieve_context("alpha", workspace_path=str(tmp_path)))
    (tmp_path / "b.py").write_text("def bravo_unique_name(): pass\n")

    assert asyncio.run(rag_engine.retrieve_context("bravo_unique_name", workspace_path=str(tmp_path))) == ""
    monkeypatch.setattr(rag_engine, "max_index_age_s", -1)  # force the index to be stale
    assert "b.py" in asyncio.run(rag_engine.retrieve_context("bravo_unique_name", workspace_path=str(tmp_path)))


# ── LLM: Gemini first, then Groq ─────────────────────────────────────────────

def test_rejected_gemini_key_is_dropped_and_groq_answers(monkeypatch, fake_llm):
    calls = mock_httpx(monkeypatch, gemini_module, lambda req: httpx.Response(
        401, json={"error": {"message": "API key not valid. Please pass a valid API key."}}))
    llm = GeminiLLM()
    llm.api_key = "bad-key"

    first = asyncio.run(llm.generate("hello"))
    second = asyncio.run(llm.generate("hello again"))

    assert first == second == fake_llm.answer  # both answered by the (fake) Groq fallback
    assert len(calls) == 1  # Gemini was not tried again after rejecting the key
    assert llm.api_key == ""


def test_gemini_answer_is_used_when_it_works(monkeypatch, fake_llm):
    mock_httpx(monkeypatch, gemini_module, lambda req: httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": "from gemini"}]}}]}))
    llm = GeminiLLM()
    llm.api_key = "good-key"

    assert asyncio.run(llm.generate("hi")) == "from gemini"
    assert fake_llm.prompts == []


def test_planner_prompt_requires_a_commit_tool_and_no_empty_plans(fake_llm):
    asyncio.run(GeminiLLM().plan_actions("commit my changes", {"branch": "main", "changed_files": ["a.py"]}))
    prompt = fake_llm.prompts[-1]
    assert "include commit_changes even when they gave no message" in prompt
    assert "Never return an empty tool_calls list" in prompt


def test_groq_without_a_key_returns_nothing_instead_of_raising(monkeypatch):
    monkeypatch.setattr(diff_intelligence, "api_key", "")
    assert asyncio.run(diff_intelligence._call_groq("hi")) == ""


# ── Narration text ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path, short", [
    ("src/services/payment.py", "payment.py"),
    ("C:\\repo\\src\\app.ts", "app.ts"),
    ("main.py", "main.py"),
])
def test_short_file_names(path, short):
    assert _short_name(path) == short


def test_syntax_error_without_a_message():
    assert diff_intelligence.format_syntax_error_narration("a.ts", 3, "", False) == \
        "Syntax error detected in a.ts on line 3."


def test_copilot_summary_strips_markdown_from_the_llm(fake_llm):
    fake_llm.copilot_sentence = "`charge()` **validates** the amount"
    text = asyncio.run(diff_intelligence.generate_copilot_spoken_summary(
        {"file": "p.py", "code_snippet": "def charge(): pass", "error_count": 0}))
    assert text == "charge() validates the amount. No errors in p.py."


# ── Sarvam speech: cache, key rotation, model fallback, ElevenLabs ──────────

@pytest.fixture
def sarvam_keys(monkeypatch):
    monkeypatch.setattr(sarvam_key_manager, "keys", ["key-a", "key-b"])
    monkeypatch.setattr(sarvam_key_manager, "current_index", 0)
    monkeypatch.setattr(sarvam_key_manager, "key_status", {
        k: {"cooldown_until": 0, "consecutive_errors": 0, "total_requests": 0} for k in ("key-a", "key-b")})


def test_truncate_for_tts_respects_the_limit():
    long_text = "word " * 200
    out = truncate_for_tts(long_text)
    assert len(out) <= 450 and out.endswith("...")
    assert truncate_for_tts("  short  ") == "short"


def test_only_male_voices_are_used():
    assert pick_speaker("bulbul:v3", "anushka") == "shubh"
    assert pick_speaker("bulbul:v3", "Rahul") == "rahul"
    assert pick_speaker("bulbul:v2", "shubh") == "karun"


def test_repeated_phrase_is_served_from_the_cache(monkeypatch, sarvam_keys):
    calls = mock_httpx(monkeypatch, sarvam_module, lambda req: httpx.Response(200, json={"audios": ["AUDIO1"]}))
    tts = SarvamFillerTTS()

    assert asyncio.run(tts.generate_filler_audio_base64("Syntax error resolved.")) == "AUDIO1"
    assert asyncio.run(tts.generate_filler_audio_base64("Syntax error resolved.")) == "AUDIO1"
    assert len(calls) == 1


def test_rate_limited_key_rotates_to_the_next_key(monkeypatch, sarvam_keys):
    def handler(req):
        if req.headers["api-subscription-key"] == "key-a":
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"audios": ["FROM_B"]})

    calls = mock_httpx(monkeypatch, sarvam_module, handler)

    assert asyncio.run(SarvamFillerTTS().generate_filler_audio_base64("hello")) == "FROM_B"
    assert [c.headers["api-subscription-key"] for c in calls] == ["key-a", "key-b"]


def test_v3_rejection_retries_with_v2(monkeypatch, sarvam_keys):
    def handler(req):
        model = json.loads(req.content)["model"]
        return httpx.Response(422, json={}) if model == "bulbul:v3" else httpx.Response(200, json={"audios": ["V2"]})

    calls = mock_httpx(monkeypatch, sarvam_module, handler)

    assert asyncio.run(SarvamFillerTTS().generate_filler_audio_base64("hello")) == "V2"
    sent = json.loads(calls[-1].content)
    assert sent["model"] == "bulbul:v2" and sent["speaker"] == "karun"


def test_everything_failing_falls_back_to_elevenlabs(monkeypatch, sarvam_keys):
    mock_httpx(monkeypatch, sarvam_module, lambda req: httpx.Response(500, json={}))
    used = []

    async def fake_eleven(text, risk_band="safe"):
        used.append(text)
        return "ELEVEN"

    monkeypatch.setattr(elevenlabs_module.elevenlabs_tts_client, "generate_narration_audio_base64", fake_eleven)

    assert asyncio.run(SarvamFillerTTS().generate_filler_audio_base64("hello")) == "ELEVEN"
    assert used == ["hello"]


def test_empty_text_makes_no_request(monkeypatch, sarvam_keys):
    calls = mock_httpx(monkeypatch, sarvam_module, lambda req: httpx.Response(200, json={"audios": ["X"]}))
    assert asyncio.run(SarvamFillerTTS().generate_filler_audio_base64("   ")) == ""
    assert calls == []


# ── Plan guard: actions the user did not ask for are removed ─────────────────

from tools.gemini_llm import GeminiLLM as _Planner, guard_plan  # noqa: E402


def _plan(*tools):
    return {"reasoning": "x", "tool_calls": [{"tool": t, "args": {}} for t in tools]}


def _tools(plan):
    return [c["tool"] for c in plan["tool_calls"]]


@pytest.mark.parametrize("command, proposed, allowed", [
    ("pull the latest changes", ["commit_changes", "pull_from_remote"], ["pull_from_remote"]),
    ("commit my changes", ["get_git_diff", "commit_changes"], ["get_git_diff", "commit_changes"]),
    ("save my work", ["commit_changes"], ["commit_changes"]),
    ("commit and push", ["commit_changes", "push_to_remote"], ["commit_changes", "push_to_remote"]),
    ("push my branch", ["commit_changes", "push_to_remote"], ["push_to_remote"]),
    ("review my diff", ["get_git_diff", "commit_changes"], ["get_git_diff"]),
    ("don't commit anything, just show me the diff", ["get_git_diff", "commit_changes"], ["get_git_diff"]),
    ("what would happen if I committed now?", ["commit_changes"], ["get_git_status", "get_git_diff"]),
    ("is it safe to push right now?", ["push_to_remote"], ["get_git_status", "get_git_diff"]),
    ("what does charge do", ["query_codebase_rag"], ["query_codebase_rag"]),
])
def test_guard_keeps_only_requested_actions(command, proposed, allowed):
    assert _tools(guard_plan(command, _plan(*proposed))) == allowed


@pytest.mark.parametrize("command, expected", [
    ("commit my changes", ["get_git_diff", "commit_changes"]),
    ("commit and push", ["get_git_diff", "commit_changes", "push_to_remote"]),
    ("push to origin", ["push_to_remote"]),  # never commits on its own
    ("pull the latest changes", ["pull_from_remote"]),
    ("don't commit anything, just show me the diff", ["get_git_status", "get_git_diff"]),
    ("what would happen if I committed now?", ["get_git_status", "get_git_diff"]),
    ("what is my status", ["get_git_status", "get_git_diff"]),
    ("what does the charge function do", ["query_codebase_rag"]),
])
def test_rule_fallback_planner(command, expected):
    assert _tools(guard_plan(command, _Planner._rule_plan(command))) == expected


def test_llm_plan_with_an_unrequested_commit_is_cut_back(fake_llm):
    fake_llm.plan = _plan("commit_changes", "pull_from_remote")
    plan = asyncio.run(_Planner().plan_actions("pull the latest changes", {}))
    assert _tools(plan) == ["pull_from_remote"]
    assert plan["dropped_actions"] == ["commit_changes"]


def test_groq_client_survives_a_new_event_loop(monkeypatch):
    """Each asyncio.run() is a new loop; the pooled client must not be reused across loops."""
    seen = mock_httpx(monkeypatch, __import__("tools.diff_intelligence", fromlist=["x"]),
                      lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]}))
    monkeypatch.setattr(diff_intelligence, "api_key", "test-key")
    monkeypatch.setattr(diff_intelligence, "_client", None)
    assert asyncio.run(diff_intelligence._call_groq("a")) == "hi"
    assert asyncio.run(diff_intelligence._call_groq("b")) == "hi"
    assert len(seen) == 2
    assert json.loads(seen[0].content).get("reasoning_effort") in (None, "low")
