<p align="center"><img src="angizo-extension/media/logo.svg" width="120" alt="Angizo logo: a grey cat wearing headphones"></p>

# Angizo — AI Accessibility Agent for Developers

> **Empowering Blind and Low-Vision Software Developers through Voice-Driven Git Workflows, Real-Time Copilot Observer Streams, and Intellisense Error Interceptors.**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![VS Code Extension](https://img.shields.io/badge/VS_Code-v1.93+-007ACC.svg?style=flat&logo=visual-studio-code)](https://code.visualstudio.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-FF6F00.svg?style=flat)](https://langchain-ai.github.io/langgraph/)
[![Groq LLM](https://img.shields.io/badge/Groq-gpt--oss--120b-F05032.svg?style=flat)](https://groq.com)
[![Sarvam AI](https://img.shields.io/badge/Sarvam_AI-STT_%26_TTS-6B46C1.svg?style=flat)](https://sarvam.ai)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-Risk--Modulated_Voice-000000.svg?style=flat)](https://elevenlabs.io)

---

## 📌 Executive Overview

Standard IDE screen readers (NVDA, JAWS, VoiceOver) suffer from severe limitations when interacting with modern AI developer tools. When **GitHub Copilot** generates code, or when complex Git diffs and runtime errors occur, screen readers either stay completely silent ("dead air") or read raw diff punctuation character-by-character (`+`, `-`, `{`, `}`), creating cognitive overload.

**Angizo** bridges this accessibility gap by introducing an audio-first, AI-driven IDE companion. Built with a 7-Node **LangGraph State Machine**, **Sarvam AI STT/TTS**, **Groq LLM Diff Intelligence**, and a custom **VS Code Extension**, Angizo translates complex background IDE events into non-intrusive Web Audio earcon streams, high-contrast HUD status overlays, and natural voice narration.

---

## ⚡ The 3 Core Features

Angizo provides three distinct, seamlessly integrated core features tailored for accessible software development:

```
                                  ┌───────────────────────────────────────────────┐
                                  │               Angizo Agent                    │
                                  └───────────────────────┬───────────────────────┘
                                                          │
          ┌───────────────────────────────────────────────┼───────────────────────────────────────────────┐
          │                                               │                                               │
┌─────────▼─────────────────────────┐   ┌─────────────────▼─────────────────────────┐   ┌─────────────────▼─────────────────────────┐
│ 1. Manual Assistance Streaming    │   │ 2. Copilot Assistance Streaming           │   │ 3. Version Control Assistance             │
├───────────────────────────────────┤   ├───────────────────────────────────────────┤   ├───────────────────────────────────────────┤
│ • Real-time Intellisense Squiggles│   │ • AI Generation Velocity Classifier       │   │ • Voice-Driven Git Operations             │
│ • Line-Shift Error Exit Voice     │   │ • Ambient Audio Ticker & Earcon Stream    │   │ • 7-Node LangGraph StateMachine           │
│ • Terminal & Debugger Exception   │   │ • Groq LLM Architectural Summaries        │   │ • Sensitive .env Access Security Guard    │
│   Interceptor (Python/Node/Go)    │   │ • AuthorTracker Coordinated Handoff       │   │ • Risk-Modulated Multi-Tier Audio TTS     │
└───────────────────────────────────┘   └───────────────────────────────────────────┘   └───────────────────────────────────────────┘
```

---

### 1. 🛠️ Manual Assistance Streaming (`ManualWatcher` & Error Interceptors)

Designed for developer typing and real-time coding feedback, this feature acts as an immediate auditory error interceptor:

* **Intellisense LSP Syntax Squiggle Interception (`ManualWatcher`)**:
  * Tracks syntax errors across all active document lines in real time using VS Code Language Server Protocol (LSP) diagnostics.
  * **Instant Earcon (<10ms)**: Plays a distinct Web Audio sound chime immediately when a red squiggle appears.
  * **Strict Line-Shift Voice Narration**: Voice narration fires ONLY when the developer exits a line containing errors, eliminating speech stutter while actively typing on the line.
  * **Resolved State Tracking**: Automatically debounces and announces when all syntax errors in a file are resolved (`"All syntax errors resolved"`).
* **Terminal & Debugger Runtime Interceptor (`TerminalWatcher`)**:
  * Reads each terminal command's output through VS Code's terminal shell integration (and debugger stderr); when a command exits with an error it looks for a stack trace to capture compilation failures and runtime crash stack traces (Python `Traceback`, Node `TypeError`, Rust/Go panics).
  * Sends stack traces over WebSocket to the Groq LLM backend to narrate the root cause and line number in 2 plain spoken sentences.
* **Toggle Command**: `Angizo: Toggle Manual Coding Stream` (Hotkey: `Alt+M`).

---

### 2. 🤖 Copilot Assistance Streaming (`CopilotWatcher` & Observer Mode)

Eliminates "dead air" when GitHub Copilot, inline completions, or automated agents generate code, create files, or install dependencies:

* **Insertion Velocity Classifier**:
  * Differentiates human keystrokes (`len == 1`) from AI code generation (a single edit inserting 10 or more characters; the session ends after 1.5 s without new chunks).
* **The 4-Layer Observer Interface**:
  1. **Ambient Audio Earcon Stream**: Ascending chime on generation start (🎵), soft background ticker pulse during streaming (⏱️), completion chime (✅), and error alert tone (⚠️).
  2. **Floating Editor HUD Banner**: High-contrast, WCAG 2.1 AAA compliant top banner embedded directly at the top of the active editor.
  3. **Accessible Status Bar**: Live update status item readable on-demand by standard screen readers.
  4. **Backend Voice Summarization**: Sends exact inserted code snippets to Groq LLM (`openai/gpt-oss-120b`) to generate a 2-sentence architectural summary explaining **what the code does and why it is necessary** for the application architecture.
* **`AuthorTracker` Coordination**:
  * Dynamically attributes active files to `"copilot"` or `"user"`, suppressing false syntax error alerts while Copilot is mid-stream and resuming manual checks after cooldown.
* **Toggle Command**: `Angizo: Toggle Copilot Observer (Mute/Unmute)`.

---

### 3. 🌿 Version Control Assistance (LangGraph Voice Agent & Git Intelligence)

Voice-first repository management and intelligent Git diff analysis:

* **Voice & Text Command Execution**:
  * Execute natural language commands (e.g., *"Commit my changes with message update auth"*, *"What files did I modify?"*, *"Review my git diff"*, *"Push to origin main"*).
* **LangGraph agent with a human-in-the-loop pause and a recovery loop** (`backend/agent/graph.py`):
  * `context` → `understand` → `reason` → `confirm` → `execute` → `verify` → `narrate`, plus `recover`.
  * **Structured output**: the planner's JSON must match a Pydantic schema (`agent/plan_schema.py`): only the six real tools, typed arguments, safe branch names (no `+main` force push, no `main:prod` refspecs). An invalid plan gets one retry with the error, then safe keyword rules.
  * **`interrupt()`**: commit, push and pull pause in `confirm`; a checkpointer keeps the state until the spoken "yes" resumes it with `Command(resume=...)`.
  * **Agentic loop**: `verify` classifies a failure; a push rejected because the remote is ahead goes `verify → recover → confirm` ("Should I pull them and push again?"), at most once. Conflicts are undone and explained, never left half-merged.
* **Guarded `.env` File Access Security**:
  * When a screen-reader or blind-mode developer attempts to open a sensitive `.env` file, Angizo intercepts access and prompts an auditory confirmation: *"Warning: You are trying to access a dot env file containing sensitive credentials. Press Alt+Y to confirm or Alt+N to reject."*
* **Spoken Confirmation Flow**:
  * High-risk operations (destructive commits, `.env` file modifications, git pushes) pause the agent execution loop and request explicit verbal or hotkey confirmation (`Alt+Y` / `Alt+N`).
* **Multi-Tier Risk-Modulated Voice TTS**:
  * Features instant zero-silence filler audio via **Sarvam AI TTS** (`"Processing your request..."`) and high-fidelity narration via **ElevenLabs** / **Sarvam AI**.

---

## ⌨️ Command & Keybinding Reference

Angizo exposes native VS Code commands and accessible keyboard shortcuts:

| Command Title | Command ID | Default Keybinding | Description |
|---|---|---|---|
| **Start/Stop Listening (Mic)** | `angizo.toggleMic` | `Ctrl+Alt+Space` (`Cmd+Alt+Space`) | Push to talk. Recording stops by itself about 1.2 s after you stop talking; press again to stop sooner. Also cuts Angizo off if it is talking. The backend must be running: it records the mic. To use another mic, set `ANGIZO_MIC_DEVICE` in `backend/.env` to part of its name (e.g. `ZEB-DUKE`). |
| **Toggle Manual Coding Stream** | `angizo.toggleManualStream` | `Alt+M` (`Cmd+Alt+M`) | Enables/disables Intellisense syntax & terminal error interception.    |
| **Confirm Action (Yes)** | `angizo.confirm` | `Alt+Y` (`Cmd+Alt+Y`) | Confirms a pending agent action or sensitive file access.    |
| **Cancel Action (No)** | `angizo.cancel` | `Alt+N` (`Cmd+Alt+N`) | Cancels a pending agent action or sensitive file access.    |
| **Toggle Copilot Observer** | `angizo.toggleObserver` | *Palette* | Mutes or unmutes Copilot ambient audio earcons and HUD.    |
| **Show Panel** | `angizo.showPanel` | *Palette* | Shows the Angizo panel (with the cat) in the right sidebar. |
| **Start Voice Input** | `angizo.startVoiceInput` | *Palette* | Shows the panel without taking focus and starts listening. |
| **Stop Voice Input** | `angizo.stopVoiceInput` | *Palette* | Stops the microphone. |

The panel lives in the right (secondary) sidebar, not in an editor tab. It never opens or takes focus by itself. A cat in headphones at the top shows what Angizo is doing: asleep (idle), ears twitching with sound waves (listening), looking up with a thought bubble and swishing tail (thinking), happy eyes and moving mouth (talking), waving its paw with a question mark (waiting for your yes), and wide-eyed with an exclamation mark (something failed). The cat is hidden from screen readers; every state is also spoken or played as a sound.

---

## 📂 Repository Structure

```
angizo/
├── backend/                          # Python FastAPI Backend Engine
│   ├── agent/                        # LangGraph Agent State Machine
│   │   ├── graph.py                  # StateGraph: nodes, interrupt, recovery loop
│   │   ├── state.py                  # AgentState TypedDict schema
│   │   ├── plan_schema.py            # Pydantic schema for the planner's JSON
│   │   ├── registry.py               # Tool registry
│   │   └── nodes/                    # understand, context, reason, confirm, execute, verify, narrate
│   ├── api/
│   │   ├── ws.py                     # Main WebSocket server & OS sounddevice mic recorder
│   │   └── rest.py                   # REST health endpoint
│   ├── tools/
│   │   ├── diff_intelligence.py       # Groq/Gemini LLM diff analysis & observer summaries
│   │   ├── git_tool.py                # GitPython wrapper
│   │   ├── rag_engine.py              # Codebase vector/text search
│   │   ├── sarvam_stt.py              # Sarvam AI STT integration
│   │   ├── sarvam_tts.py              # Sarvam AI TTS filler audio
│   │   ├── elevenlabs_tts.py          # ElevenLabs TTS primary voice
│   │   └── gemini_llm.py              # Google Gemini LLM fallback
│   ├── config.py                     # Environment variable config
│   ├── main.py                       # FastAPI application entry point
│   ├── .env                          # API keys & server configuration
│   ├── tests/                        # pytest suite (LLM, voices and git all faked or sandboxed)
│   ├── pyproject.toml
│   ├── requirements.txt
│   └── requirements-dev.txt          # adds pytest
│
├── angizo-extension/              # VS Code Extension
│   ├── src/
│   │   ├── extension.ts              # Extension host entrypoint & command registry
│   │   ├── ws-client.ts              # WebSocket client connecting host to backend
│   │   ├── webview-bridge.ts         # postMessage bridge between webview and extension host
│   │   └── observer/
│   │       ├── copilot-watcher.ts    # Copilot AI generation detector & event emitter
│   │       ├── manual-watcher.ts     # Intellisense LSP syntax error interceptor
│   │       ├── terminal-watcher.ts   # Terminal crash interceptor (shell integration + debugger)
│   │       ├── observer-earcon.ts    # Web Audio synth chime generator
│   │       ├── observer-hud.ts       # Top editor high-contrast overlay banner
│   │       └── observer-status-bar.ts# Accessible status bar item
│   │   └── webview/
│   │       ├── main.js               # Accessible webview UI logic & audio player
│   │       └── pcm-processor.js      # AudioWorklet PCM processor
│   ├── test/e2e/                     # end-to-end test: real VS Code + fake backend
│   ├── package.json
│   └── tsconfig.json
│
├── DEPLOY.md                         # Detailed step-by-step deployment guide
├── STREAM.md                         # Copilot real-time streaming specification
├── TECH_DES.md                       # Technical design architecture document
├── MARKETING.md                      # Product positioning & competitive matrix
├── USECASE.md                        # Developer persona use cases
└── PITCH_DIFFERENTIATION.md          # Key differentiators & pitch summary
```

---

## 📋 Prerequisites

| Component | Minimum Version | Verification Command |
|---|---|---|
| **Python** | `>= 3.9` | `python --version` |
| **Node.js** | `>= 18.x` | `node --version` |
| **npm** | `>= 9.x` | `npm --version` |
| **VS Code** | `>= 1.93.0` (terminal shell integration) | Help → About |
| **uv** *(Recommended)* | Latest | `uv --version` |

---

## 🔑 Environment Configuration (`.env`)

Create a `.env` file inside `backend/`:

```env
# Server Configuration
ANGIZO_HOST=0.0.0.0
ANGIZO_PORT=7001

# API Keys
SARVAM_API_KEY=your_sarvam_api_key_here        # Required (STT & Fallback TTS)
GROQ_API_KEY=your_groq_api_key_here            # Required (LLM Diff Intelligence & Copilot Summaries)
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here# Recommended (High Quality Voice Narration)
GEMINI_API_KEY=your_gemini_api_key_here        # Optional Fallback
GITHUB_PAT=your_github_token_here              # Optional (PR creation)

# Engine Defaults
SARVAM_STT_ENDPOINT=https://api.sarvam.ai/speech-to-text
SARVAM_FILLER_SPEAKER=shubh
ELEVENLABS_VOICE_ID=EXAVITQu4vr4xnSDxMaL
GROQ_MODEL=openai/gpt-oss-120b
```

---

## 🚀 Quick Start Guide

### Step 1: Start the Python Backend

```bash
cd backend

# Create & activate virtual environment
uv venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt

# Run the FastAPI server
python main.py
```
> Server runs at `http://localhost:7001`. Health check: `curl http://localhost:7001/health`.

### Step 2: Build & Launch the VS Code Extension

In a separate terminal:

```bash
cd angizo-extension

# Install dependencies & compile TypeScript
npm install
npm run compile
```

1. Open `angizo-extension` in VS Code (`code angizo-extension`).
2. Press **`F5`** to launch the **Extension Development Host**.
3. Angizo appears in the right sidebar (press `Ctrl+Alt+B` if the sidebar is closed). Press **`Ctrl+Alt+Space`** and speak.

---

## 🎬 Demo, measurements and changelog

- **[docs/DEMO.md](docs/DEMO.md)**: the pipeline in one picture, a step-by-step live demo, how to record the demo video (`scripts/record_demo.py`), and how to test every layer.
- **[reports/measurements.md](reports/measurements.md)**: planner accuracy (97% over 3 runs, 0 unsafe actions), time per graph node, code-search hit rate, LLM usage and speech latency. Reproduce with `backend/evals/measure.py`.
- **[CHANGELOG.md](CHANGELOG.md)**: every change, newest first.

## 🧪 Automated Tests

Two suites, both offline: no API keys, no network, no real repository touched.

### Backend: 67 pytest tests

```bash
cd backend
uv pip install -r requirements-dev.txt   # or: pip install -r requirements-dev.txt
python -m pytest
```

The LLM (Groq/Gemini) and the voices (Sarvam/ElevenLabs) are replaced by fakes, and every git command runs in a throwaway repository. `ANGIZO_SKIP_DOTENV=1` is set by the tests so `backend/.env` is never read.

| File | What it proves |
|---|---|
| `tests/test_git_tool.py` | Status finds modified, staged and untracked files but never `.gitignore`d ones; a commit contains exactly the approved files, never files that appeared later; deletions, empty commits and repos without commits are handled |
| `tests/test_agent_graph.py` | Read-only commands never ask; commit and push stop for confirmation and change nothing; "yes" commits the exact message and files that were read out; empty or broken LLM plans fall back to rules; unknown tools are skipped |
| `tests/test_ws_api.py` | The WebSocket API end to end: Alt+Y commits, Alt+N cancels, a new command drops a pending commit, gibberish and null bytes are rejected, syntax/runtime/Copilot/new-file events are narrated, spoken yes/no match whole words ("look" is not "ok") |
| `tests/test_tools.py` | `.env` files never reach the LLM; the code index refreshes; a rejected Gemini key is dropped; Sarvam caching, key rotation on 429, bulbul v3 → v2 fallback and the ElevenLabs fallback |

### VS Code extension: end-to-end

```bash
cd angizo-extension
npm install
npm run test:e2e
```

Starts a fake backend, opens the VS Code installed on your machine with the extension loaded (a window shows for about a minute), and checks what the extension sends while it makes real edits:

1. Connects and sends the workspace path.
2. A syntax error on the line you are typing is reported only when the cursor leaves it, then "resolved" after the fix. An error on another line (reported late, or caused elsewhere) is announced after 1.5 s of quiet; several at once become one summary ("3 syntax errors in many.ts, first on line 3"); each is said once, and again only if it comes back after a fix.
3. Fast multi-line inserts (like Copilot) send the inserted code and the real error count.
4. A file you create is announced once, and not credited to Copilot.
5. A command that crashes in the terminal (`node -e "null.x"`) is caught through terminal shell integration; a successful command is not.
6. Alt+Y / Alt+N send the confirmation answer; muting the observer silences it.

Set `VSCODE_PATH` if VS Code is not in its default install location.

### Testing sandbox

All test activity can live in one folder outside this repo:

```bash
python scripts/make_sandbox.py ~/Projects/angizo-sandbox
```

It holds `playground/` (a small git project with crashing scripts and a fake `.env`), `remote.git/` (a bare repo used as playground's `origin`, so push and pull are safe) and `runs/` (scratch space). With `ANGIZO_SANDBOX` set, the backend suite and the end-to-end test write there instead of the system temp folder. The sandbox's `run-tests.ps1` runs everything.

### Live tests (real API keys)

```bash
cd backend
ANGIZO_LIVE=1 ANGIZO_SANDBOX=~/Projects/angizo-sandbox python -m pytest tests_live -s
# add ANGIZO_LIVE_MIC=1 to test the microphone: it plays a phrase on the speakers and records it
```

Skipped unless `ANGIZO_LIVE=1`; uses the keys in `backend/.env`. Every git action runs in a fresh clone of the sandbox playground. It covers:

- **Planner eval**: 16 commands, including traps ("don't commit, just show me the diff", "is it safe to push?"). Must plan the requested tools and never an unrequested commit, push or pull.
- **Full agent in the sandbox**: diff review, commit (conventional message, exact files, `.env` never offered), commit and push to the sandbox origin, pull a teammate's commit, code questions, and a secret that must not be revealed.
- **Narration**: the Copilot summary names the function, ignores instructions hidden in code, and explains runtime errors.
- **Voices**: Sarvam speech (WAV, cache), ElevenLabs, and Sarvam speech-to-text round trips.
- **Microphone** (opt-in): input level, speaker → mic → transcript, and the panel's mic button through to the agent's spoken answer.

Every answer and its latency is written to `<sandbox>/runs/live/report.md`.

### Manual checks (need real API keys)

1. **Voice command**: press `Ctrl+Alt+Space`, say *"review my git diff"*, and stop talking (or type it in the panel and press Run).
2. **Commit**: type *"commit my changes"*, listen to the files and message, then press `Alt+Y` (or `Alt+N`).
3. **Copilot**: accept a Copilot completion and listen for the one-sentence summary.
4. **Sensitive file guard**: with a screen reader on (or `angizo.simulateBlindMode`), open a `.env` file.

---

## 📄 License & Acknowledgments

Built for accessibility innovation during hackathon development. Powered by **FastAPI**, **LangGraph**, **Groq**, **Sarvam AI**, **ElevenLabs**, and **VS Code Extension API**.
## Built by 
Team *Nano Pineapple*
