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
    # (a command the fast path does not handle, so the LLM is asked)
    asyncio.run(GeminiLLM().plan_actions("commit with the message fix login", {"branch": "main", "changed_files": ["a.py"]}))
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
    plan = asyncio.run(_Planner().plan_actions("pull the latest changes from upstream", {}))
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



# ── Speech helpers and the planner fast path ─────────────────────────────────

from tools.speech import ACK_PHRASES, ack_phrase, prewarm_acks, split_for_speech  # noqa: E402
from tools.gemini_llm import fast_plan  # noqa: E402


@pytest.mark.parametrize("text, first, rest", [
    ("On main, 1 changed file: auth.py. The login function now retries.",
     "On main, 1 changed file: auth.py.", "The login function now retries."),
    ("Committed 2 files with message: fix: v1.2 login.", "Committed 2 files with message: fix: v1.2 login.", ""),
    ("Done. The push reached origin. Nothing else changed.", "Done. The push reached origin.", "Nothing else changed."),
    ("Is it safe? Yes, nothing is staged.", "Is it safe? Yes, nothing is staged.", ""),
    ("", "", ""),
])
def test_split_for_speech(text, first, rest):
    assert split_for_speech(text) == (first, rest)


@pytest.mark.parametrize("command, phrase", [
    ("commit and push my changes", "Preparing a commit."),
    ("push my branch", "Getting ready to push."),
    ("pull the latest changes", "Checking the remote."),
    ("review my diff", "Reading your changes."),
    ("what is my git status", "Checking your status."),
    ("what does charge do", "Looking into it."),
])
def test_ack_phrase(command, phrase):
    assert ack_phrase(command) == phrase


def test_prewarm_caches_every_ack_phrase(monkeypatch, sarvam_keys):
    calls = mock_httpx(monkeypatch, sarvam_module, lambda req: httpx.Response(200, json={"audios": ["A"]}))
    tts = SarvamFillerTTS()
    assert asyncio.run(prewarm_acks(tts)) == len(ACK_PHRASES)
    assert all(tts.cached(p) == "A" for p in ACK_PHRASES.values())
    asyncio.run(tts.generate_filler_audio_base64("Reading your changes."))
    assert len(calls) == len(ACK_PHRASES)  # the repeat came from the cache


@pytest.mark.parametrize("command, tools", [
    ("commit my changes", ["get_git_diff", "commit_changes"]),
    ("Please commit my changes.", ["get_git_diff", "commit_changes"]),
    ("commit and push my changes", ["get_git_diff", "commit_changes", "push_to_remote"]),
    ("save my work", ["get_git_diff", "commit_changes"]),
    ("what is my git status", ["get_git_status", "get_git_diff"]),
    ("which files did I change", ["get_git_status", "get_git_diff"]),
    ("hey angizo, review my diff", ["get_git_diff"]),
    ("push to origin", ["push_to_remote"]),
    ("pull the latest changes", ["pull_from_remote"]),
])
def test_fast_path_plans_clear_commands(command, tools):
    assert [c["tool"] for c in fast_plan(command)["tool_calls"]] == tools


@pytest.mark.parametrize("command", [
    "commit with the message fix login",  # the message has to be extracted
    "push to staging",  # unusual target
    "don't commit, show me the diff",  # negation
    "is it safe to push?",  # question about an action
    "what would happen if I committed now?",
    "why is my push failing",  # a code-style question, but about git
    "commit my changes and then tell me a joke",
    "delete all my files",
])
def test_anything_else_goes_to_the_llm(command):
    assert fast_plan(command) is None


@pytest.mark.parametrize("command", [
    "what does the charge function do",
    "which language is this project written in",
    "how does login work",
    "explain the payment module",
])
def test_code_questions_go_straight_to_code_search(command):
    plan = fast_plan(command)
    assert [c["tool"] for c in plan["tool_calls"]] == ["query_codebase_rag"]
    assert plan["tool_calls"][0]["args"]["query"] == command


def test_the_same_sentence_is_synthesised_once_even_when_asked_twice_at_once(monkeypatch, sarvam_keys):
    """prefetch_speech and the reply can ask for the same sentence; only one request is sent."""
    calls = mock_httpx(monkeypatch, sarvam_module, lambda req: httpx.Response(200, json={"audios": ["A"]}))
    tts = SarvamFillerTTS()

    async def both():
        return await asyncio.gather(tts.generate_filler_audio_base64("On main, 1 changed file: auth.py."),
                                    tts.generate_filler_audio_base64("On main, 1 changed file: auth.py."))

    assert asyncio.run(both()) == ["A", "A"]
    assert len(calls) == 1


def test_out_of_credits_key_rotates_and_rests_for_an_hour(monkeypatch, sarvam_keys):
    def handler(req):
        if req.headers["api-subscription-key"] == "key-a":
            return httpx.Response(402, json={"error": {"message": "No credits available."}})
        return httpx.Response(200, json={"audios": ["FROM_B"]})

    mock_httpx(monkeypatch, sarvam_module, handler)

    assert asyncio.run(SarvamFillerTTS().generate_filler_audio_base64("hello")) == "FROM_B"
    import time
    assert sarvam_key_manager.key_status["key-a"]["cooldown_until"] > time.time() + 3000


def test_when_every_key_is_out_of_credits_no_request_is_made(monkeypatch, sarvam_keys):
    import time
    for status in sarvam_key_manager.key_status.values():
        status["cooldown_until"] = time.time() + 3600
    calls = mock_httpx(monkeypatch, sarvam_module, lambda req: httpx.Response(200, json={"audios": ["X"]}))
    monkeypatch.setattr(elevenlabs_module.elevenlabs_tts_client, "api_key", "")

    assert asyncio.run(SarvamFillerTTS().generate_filler_audio_base64("hello")) == ""
    assert calls == []  # the panel's system voice reads the text instead


def test_rejected_elevenlabs_key_is_not_retried(monkeypatch):
    calls = mock_httpx(monkeypatch, elevenlabs_module, lambda req: httpx.Response(
        401, json={"detail": {"message": "missing the permission text_to_speech"}}))
    client = elevenlabs_module.ElevenLabsTTS(api_key="bad")

    assert asyncio.run(client.generate_narration_audio_base64("one")) == ""
    assert asyncio.run(client.generate_narration_audio_base64("two")) == ""
    assert len(calls) == 1


# ── Groq free-tier rate limit ────────────────────────────────────────────────

import tools.diff_intelligence as diff_module  # noqa: E402


def test_rate_limited_groq_call_waits_and_retries_once(monkeypatch):
    replies = iter([
        httpx.Response(429, headers={"retry-after": "0.01"}, json={"error": {"message": "rate limit"}}),
        httpx.Response(200, json={"choices": [{"message": {"content": "second try"}}]}),
    ])
    calls = mock_httpx(monkeypatch, diff_module, lambda req: next(replies))
    monkeypatch.setattr(diff_intelligence, "api_key", "test-key")
    monkeypatch.setattr(diff_intelligence, "_client", None)

    assert asyncio.run(diff_intelligence._call_groq("hi")) == "second try"
    assert len(calls) == 2


def test_still_rate_limited_after_the_retry_returns_nothing(monkeypatch):
    calls = mock_httpx(monkeypatch, diff_module, lambda req: httpx.Response(429, headers={"retry-after": "0.01"}, json={}))
    monkeypatch.setattr(diff_intelligence, "api_key", "test-key")
    monkeypatch.setattr(diff_intelligence, "_client", None)

    assert asyncio.run(diff_intelligence._call_groq("hi")) == ""
    assert len(calls) == 2  # one retry, not a loop


@pytest.mark.parametrize("headers, seconds", [
    ({"retry-after": "3"}, 3.0),
    ({"x-ratelimit-reset-tokens": "2.19s"}, 2.19),
    ({"x-ratelimit-reset-tokens": "1m3.5s"}, 8.0),  # capped: a voice reply never stalls long
    ({"x-ratelimit-reset-tokens": "250ms"}, 0.25),
    ({}, 2.0),
])
def test_retry_wait_is_read_from_groq_headers(headers, seconds):
    assert diff_module._retry_after_seconds(httpx.Headers(headers)) == pytest.approx(seconds)


def test_no_llm_answer_is_said_honestly(fake_llm):
    fake_llm.answer = ""
    answer = asyncio.run(_Planner().generate_reasoning("what is the PAYMENT_API_KEY", rag_context="some code"))
    assert answer == "I couldn't get an answer just now. Please try again in a moment."


@pytest.mark.parametrize("diff, message", [
    ("diff --git a/src/auth.py b/src/auth.py\n+x\ndiff --git a/notes.md b/notes.md\n+y", "chore: update auth.py and notes.md"),
    ("diff --git a/a.py b/a.py\ndiff --git a/b.py b/b.py\ndiff --git a/c.py b/c.py\ndiff --git a/d.py b/d.py", "chore: update 4 files"),
    ("something without headers", "chore: update workspace files"),
])
def test_commit_message_without_the_llm_is_still_conventional(fake_llm, diff, message):
    fake_llm.commit_message = ""
    assert asyncio.run(diff_intelligence.draft_commit_message(diff)) == message


def test_rate_limited_main_model_switches_to_the_fallback_model_at_once(monkeypatch):
    replies = iter([
        httpx.Response(429, headers={"retry-after": "5"}, json={}),
        httpx.Response(200, json={"choices": [{"message": {"content": "from 20b"}}]}),
    ])
    calls = mock_httpx(monkeypatch, diff_module, lambda req: next(replies))
    monkeypatch.setattr(diff_intelligence, "api_key", "test-key")
    monkeypatch.setattr(diff_intelligence, "_client", None)
    monkeypatch.setattr(diff_intelligence, "model", "openai/gpt-oss-120b")
    monkeypatch.setattr(diff_intelligence, "fallback_model", "openai/gpt-oss-20b")

    import time
    start = time.perf_counter()
    assert asyncio.run(diff_intelligence._call_groq("hi")) == "from 20b"
    assert time.perf_counter() - start < 1  # no 5-second wait
    assert [json.loads(c.content)["model"] for c in calls] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_without_a_fallback_model_it_waits_and_retries_the_same_model(monkeypatch):
    replies = iter([
        httpx.Response(429, headers={"retry-after": "0.01"}, json={}),
        httpx.Response(200, json={"choices": [{"message": {"content": "same model"}}]}),
    ])
    calls = mock_httpx(monkeypatch, diff_module, lambda req: next(replies))
    monkeypatch.setattr(diff_intelligence, "api_key", "test-key")
    monkeypatch.setattr(diff_intelligence, "_client", None)
    monkeypatch.setattr(diff_intelligence, "fallback_model", "")

    assert asyncio.run(diff_intelligence._call_groq("hi")) == "same model"
    assert json.loads(calls[0].content)["model"] == json.loads(calls[1].content)["model"]
