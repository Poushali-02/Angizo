# Changelog

All notable changes to Angizo, newest first. Everything below is on the `v1` branch and not yet in `main`.

## 2026-11-28: Speaking sooner

### Added
- **Instant acknowledgement.** Every typed command, voice command and Alt+Y now gets a short reply the moment it arrives ("Reading your changes.", "Preparing a commit.", "Working on it."), before any LLM call. The phrases are synthesised once at startup and served from the cache after that. Before this, the backend had no filler, despite the docs; only typed commands got the browser's "Processing your request...".
- **First sentence first.** Replies are spoken in two parts: the first sentence plays while the rest is still being synthesised (`audio_narration` with channel `agent_continuation`).
- **Speech prefetch.** The opening sentence of a review or commit prompt ("On main, 1 changed file: auth.py.") is synthesised while the LLM is still writing the rest.
- **Planner fast path.** Clear commands ("commit my changes", "review my diff", "push", "pull", "status") and questions about the code ("what does charge do") are planned without the LLM. Anything else, including questions about git actions, still goes to the LLM.
- Live latency test (`tests_live/test_live_latency.py`).

### Changed
- Speech moved out of the graph's narrate node into `api/ws.py` (`send_spoken`), so it can be streamed.
- The panel no longer says "Processing your request..." in the system voice; it plays the backend's acknowledgement instead.

### Fixed
- **The event loop was blocked by git and code search.** They now run in worker threads, so the server can send messages (such as the acknowledgement) while they work.
- **Sarvam "no credits" (402) stopped all speech.** The key now rotates and rests for an hour. When every key is out, the request is skipped at once and the panel's system voice reads the text.
- **A rejected ElevenLabs key was retried on every sentence.** It now pauses for 10 minutes. Its HTTP client is also tied to the event loop, like Groq's.
- The same sentence requested twice at once (prefetch and reply) is synthesised only once.

### Measured (live, sandbox repo)
| Command | Before | After |
|---|---|---|
| Acknowledgement | none (silence) | 0.0 s |
| "review my diff", first sentence | about 11 s (whole reply) | 5.7 s |
| "commit my changes", first sentence | about 9 s | 5.5 s |

## 2026-11-27: Late errors

### Added
- **Errors away from the cursor are announced.** An error on another line (reported late by the language server, or caused by an edit elsewhere) is announced after 1.5 s without edits. Several new errors become one summary: "3 syntax errors in app.ts, first on line 12." Each error is spoken once, and again only if it comes back after a fix. The line being typed on still waits until the cursor leaves it.

## 2026-11-27: Testing sandbox and live tests

### Added
- `scripts/make_sandbox.py` builds a testing sandbox: a playground repo whose `origin` is a local bare repo (push and pull are safe), plus scratch space. `ANGIZO_SANDBOX` points every test suite at it.
- `backend/tests_live`: real-API tests (opt-in, `ANGIZO_LIVE=1`). They cover a 16-command planner eval, the full agent in the sandbox, narration with prompt injection, speech, transcription round trips and an opt-in microphone test. They write a report with every answer and its latency.

### Fixed
- **Plan guard.** Commit, push and pull stay in a plan only if the user's words asked for them, and never for questions or negations. The LLM had added a commit to "pull the latest changes", and the keyword fallback committed for "don't commit".
- **Groq calls could fail with "Event loop is closed"** and silently fall back to keyword rules.
- Spoken reviews and answers are capped at two short sentences, with markdown stripped.
- gpt-oss runs with low reasoning effort (about half the tokens).

## 2026-11-27: Tested and fixed for v1

### Added
- 67 offline backend tests (LLM and voices faked, git in throwaway repos) and a VS Code end-to-end test against a fake backend. Plus CI for both on GitHub Actions.

### Fixed
- **Commits contain exactly the files and message read out at confirmation.** They used `git add -A`, and redrafted the message after the user said yes.
- **Terminal crashes were never caught in normal VS Code** (they relied on a proposed API). They now use stable terminal shell integration, and Node errors are no longer reported as Python.
- **Copilot summaries describe the inserted code** instead of counting lines, and they send real error counts.
- A new file is announced once, and credited to Copilot only when AI code lands in it.
- **Debug pop-ups that screen readers read aloud are removed.**
- Spoken yes/no match whole words: "look" no longer means "ok".
- `.env` files are never indexed for code search, so secrets never reach the LLM.
- Groq's retired `llama-3.3-70b-versatile` was replaced by `openai/gpt-oss-120b`; a rejected Gemini key is dropped for the session.
- "Diff then commit" is labelled a commit, not a status check.
- The Sarvam API key is no longer printed to the console.

## Known issues
- Sarvam's free credits are used up: speech falls back to the system voice until the account is topped up.
- ElevenLabs key lacks the `text_to_speech` permission; Gemini key or model is rejected.
- A pasted block looks the same as a Copilot insertion.
