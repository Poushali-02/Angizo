# Angizo: the pipeline, the demo, and how to test everything

## 1. The pipeline in one picture

Angizo is two programs that talk over one WebSocket (`ws://localhost:7001/ws/session`):

```
 VS Code extension (TypeScript)                         Backend (Python, FastAPI)
 ─────────────────────────────                          ──────────────────────────
 ManualWatcher   syntax errors ──── manual_observer ──▶ fixed sentence ─────────────┐
 TerminalWatcher terminal crashes ─ runtime_error ────▶ Groq explains the crash ────┤
 CopilotWatcher  AI-sized edits ─── copilot_complete ─▶ Groq: one-sentence summary ─┤
 Panel / Ctrl+Alt+Space / "Run a Command…" ─ text_command ▶ LangGraph agent (below) ┤
 Alt+Y / Alt+N / spoken yes-no ──── confirm_response ─▶ resumes the paused agent ───┤
                                                                                    ▼
 Panel plays the audio ◀──── ack / confirmation_request / action_result ◀── Sarvam speech
                                                         (first sentence first)
```

**The four streams:**

| Stream | Trigger | What you hear |
|---|---|---|
| Manual | a red squiggle on a line you just left (or one that appears on another line) | "Syntax error detected in app.ts on line 5: Expression expected." … "Syntax error resolved in app.ts." |
| Terminal | a command crashes (`node crash.js`) | "TypeError in crash.js at line two. The code read the id property of null." |
| Copilot | code arriving in big chunks | "Adds an applyCoupon function that validates the percent and rounds the total. No errors in app.ts." |
| Voice Git agent | "review my diff", "commit my changes", "push my branch"… | an instant acknowledgement, then the answer; risky actions wait for a yes |

**The agent (LangGraph, `backend/agent/graph.py`):**

```
context → understand → reason → confirm ⇄ interrupt(): pause for a spoken yes
                                   │
                                   ▼
                         ┌──▶ execute → verify ── fixable failure (first time) ──┐
                         │                 └── otherwise ──▶ narrate → END       │
                         └──────────── confirm ◀──── recover ◀───────────────────┘
```

- **context**: git status, diff, code-search snippets.
- **understand**: the plan. Clear commands use a fast path with no LLM. Others go to Groq, whose JSON must pass a Pydantic schema (one retry, then safe rules). The plan guard then removes any commit, push or pull you didn't ask for.
- **reason**: what to say, and whether it needs a yes. Commit messages and file lists are pinned here.
- **confirm**: `interrupt()`. The checkpointer saves the state, and Alt+Y resumes it with `Command(resume=True)`.
- **execute → verify**: run the tools, classify any failure.
- **recover**: a push rejected because the remote is ahead → "Should I pull them and push again?" (at most once).
- **narrate**: the sentence you hear. Failures are explained in plain words.

## 2. Live demo, step by step (about 5 minutes)

### One-time setup
1. `backend/.env` has `GROQ_API_KEY` and a `SARVAM_API_KEY` with credits (check the Sarvam dashboard).
2. Install the dependencies:

   ```powershell
   cd backend; uv pip install -r requirements-dev.txt; cd ..\angizo-extension; npm install; npm run compile
   ```

3. A fresh sandbox to demo in (this resets it):

   ```powershell
   python scripts\make_sandbox.py C:\Users\poush\OneDrive\Projects\angizo-sandbox
   ```

### Start it
1. Start the backend and leave the terminal open:

   ```powershell
   cd backend; .venv\Scripts\python.exe main.py
   ```

2. Open VS Code with Angizo on the playground:

   ```powershell
   code --extensionDevelopmentPath=C:\Users\poush\OneDrive\Desktop\angizo\angizo-extension C:\Users\poush\OneDrive\Projects\angizo-sandbox\playground
   ```

3. Angizo is in the right sidebar, with the cat asleep at the top. If the sidebar is closed, press `Ctrl+Alt+B` (or run **Angizo: Show Panel**). It never opens an editor tab or takes focus from your code.

### The scenes

| # | Do this | You'll hear | Say this in the interview |
|---|---|---|---|
| 1 | Open `app.ts`, add a line `const discount = ;`, press ↑ | "Syntax error detected in app.ts on line 5: Expression expected." | "It waits until you leave the line, so it never talks over your typing." |
| 2 | Change it to `= 10;`, press ↑ | "Syntax error resolved in app.ts." | |
| 3 | Accept a Copilot suggestion, or paste a small function | one sentence on what the code does | "The code itself goes to the LLM, with instructions inside it treated as data." |
| 4 | In the terminal: `node crash.js` | what crashed, where, and why | "Caught through VS Code's stable shell-integration API." |
| 5 | Panel box (or **Angizo: Run a Command…**): `review my diff` | "Reading your changes." at once, then the review | "Instant acknowledgement from a cache, then first sentence first." |
| 6 | `commit my changes` | the files, the suggested message, "Should I commit?" | "LangGraph `interrupt()`: the graph is paused and saved." |
| 7 | `Alt+Y` | "Committed 1 file with message: …" | "It commits exactly the files and message it read out." |
| 8 | Make a teammate push first (commands below), then `push my branch`, `Alt+Y` | "The push was rejected… Should I pull them and push again?" | "The agentic loop: verify → recover → confirm." |
| 9 | `Alt+Y` | "Pulled the new commits from origin, merged them, and pushed successfully." | "Merges, never rebases or force-pushes; a conflict is undone and explained." |
| 10 | (optional) press `Ctrl+Alt+Space`, say "what is my git status", then just stop talking | a blip when it starts and stops listening, then the status | "Push to talk; it stops by itself after 1.2 s of silence, and pressing it while Angizo talks cuts it off." |

**Make a teammate push first (for scene 8),** in a separate terminal:

```powershell
cd C:\Users\poush\OneDrive\Projects\angizo-sandbox; git clone -q remote.git teammate; cd teammate; "notes" > TEAM.md; git add .; git -c user.name=Teammate -c user.email=t@example.com commit -qm "docs: team notes"; git push -q
```

When you're done, reset the sandbox with the `make_sandbox.py` command above.

## 3. Record the demo as a video

```powershell
python scripts\record_demo.py --sandbox C:\Users\poush\OneDrive\Projects\angizo-sandbox
```

This runs every scene above automatically, against the real backend, in a throwaway copy of the playground:
- It records only the VS Code window, with `ffmpeg`.
- It builds the soundtrack from the exact clips Angizo spoke.
- The output is `angizo-sandbox\demo\angizo-demo.mp4`.

It takes about 3 minutes. It records the screen area where the VS Code window sits (VS Code draws with the GPU, so window capture comes out black), and stops the moment the last scene ends. **Don't use the computer while it records**: a window moved on top would be recorded too. It costs about 25 short Sarvam requests and 6 Groq calls.

## 4. Test the full pipeline

| Layer | Command | What it proves | Cost |
|---|---|---|---|
| Backend logic | `cd backend; .venv\Scripts\python.exe -m pytest` | ~186 tests: git safety, the graph with `interrupt()` and the recovery loop, schema validation, the plan guard, the WebSocket API, speech fallbacks | free, offline |
| Extension in real VS Code | `cd angizo-extension; npm run test:e2e` | 14 checks: the sidebar panel (no editor tab), the mic shortcut, syntax errors (late ones too), Copilot detection, the terminal crash, Alt+Y/N, mute | free, offline    |
| Real APIs | `$env:ANGIZO_LIVE="1"; $env:ANGIZO_SANDBOX="C:\Users\poush\OneDrive\Projects\angizo-sandbox"; cd backend; .venv\Scripts\python.exe -m pytest tests_live` | Groq planning and answers, speech, transcription, latency; add `$env:ANGIZO_LIVE_MIC="1"` for the microphone | Groq free; about 30 Sarvam requests |
| Measurements | `cd backend; .venv\Scripts\python.exe evals\measure.py --runs 3 --speech` | planner accuracy, unsafe-action count, time per node, code search, token use, writes `reports/measurements.md` | Groq free; 4 Sarvam requests |
| Everything, as a user sees it | the demo recording (section 3) | the whole loop: VS Code → backend → LLM → git → speech → panel | about 25 Sarvam requests |

All the offline suites at once: `C:\Users\poush\OneDrive\Projects\angizo-sandbox\run-tests.ps1`. Add `-Live` for the real APIs, and `-Live -Mic` for the microphone too.
