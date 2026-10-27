# 🧠 Angizo — AI Accessibility Agent for Developers

> **Empowering Blind and Low-Vision Software Developers through Voice-Driven Git Workflows, Real-Time Copilot Observer Streams, and Intellisense Error Interceptors.**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![VS Code Extension](https://img.shields.io/badge/VS_Code-v1.85+-007ACC.svg?style=flat&logo=visual-studio-code)](https://code.visualstudio.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-FF6F00.svg?style=flat)](https://langchain-ai.github.io/langgraph/)
[![Groq LLM](https://img.shields.io/badge/Groq-Llama_3.3_70B-F05032.svg?style=flat)](https://groq.com)
[![Sarvam AI](https://img.shields.io/badge/Sarvam_AI-STT_%26_TTS-6B46C1.svg?style=flat)](https://sarvam.ai)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-Risk--Modulated_Voice-000000.svg?style=flat)](https://elevenlabs.io)

---

## 📌 Executive Overview

Standard IDE screen readers (NVDA, JAWS, VoiceOver) suffer from severe limitations when interacting with modern AI developer tools. When **GitHub Copilot** generates code, or when complex Git diffs and runtime errors occur, screen readers either stay completely silent ("dead air") or read raw diff punctuation character-by-character (`+`, `-`, `{`, `}`), creating cognitive overload.

**NeuroCode** bridges this accessibility gap by introducing an audio-first, AI-driven IDE companion. Built with a 7-Node **LangGraph State Machine**, **Sarvam AI STT/TTS**, **Groq LLM Diff Intelligence**, and a custom **VS Code Extension**, NeuroCode translates complex background IDE events into non-intrusive Web Audio earcon streams, high-contrast HUD status overlays, and natural voice narration.

---

## ⚡ The 3 Core Features

NeuroCode provides three distinct, seamlessly integrated core features tailored for accessible software development:

```
                                  ┌───────────────────────────────────────────────┐
                                  │               NeuroCode Agent                 │
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
  * Hooks into `vscode.window.onDidWriteTerminalData` and debug stderr events to capture compilation failures and runtime crash stack traces (Python `Traceback`, Node `TypeError`, Rust/Go panics).
  * Sends stack traces over WebSocket to the Groq LLM backend to narrate the root cause and line number in 2 plain spoken sentences.
* **Toggle Command**: `NeuroCode: Toggle Manual Coding Stream` (Hotkey: `Alt+M`).

---

### 2. 🤖 Copilot Assistance Streaming (`CopilotWatcher` & Observer Mode)

Eliminates "dead air" when GitHub Copilot, inline completions, or automated agents generate code, create files, or install dependencies:

* **Insertion Velocity Classifier**:
  * Differentiates human keystrokes (`len == 1`) from AI code generation (`len >= 5` in `<50ms` intervals).
* **The 4-Layer Observer Interface**:
  1. **Ambient Audio Earcon Stream**: Ascending chime on generation start (🎵), soft background ticker pulse during streaming (⏱️), completion chime (✅), and error alert tone (⚠️).
  2. **Floating Editor HUD Banner**: High-contrast, WCAG 2.1 AAA compliant top banner embedded directly at the top of the active editor.
  3. **Accessible Status Bar**: Live update status item readable on-demand by standard screen readers.
  4. **Backend Voice Summarization**: Sends exact inserted code snippets to Groq LLM (`llama-3.3-70b-versatile`) to generate a 2-sentence architectural summary explaining **what the code does and why it is necessary** for the application architecture.
* **`AuthorTracker` Coordination**:
  * Dynamically attributes active files to `"copilot"` or `"user"`, suppressing false syntax error alerts while Copilot is mid-stream and resuming manual checks after cooldown.
* **Toggle Command**: `NeuroCode: Toggle Copilot Observer (Mute/Unmute)`.

---

### 3. 🌿 Version Control Assistance (LangGraph Voice Agent & Git Intelligence)

Voice-first repository management and intelligent Git diff analysis:

* **Voice & Text Command Execution**:
  * Execute natural language commands (e.g., *"Commit my changes with message update auth"*, *"What files did I modify?"*, *"Review my git diff"*, *"Push to origin main"*).
* **7-Node LangGraph StateMachine Architecture**:
  * `understand` → `context` → `reason` → `confirm` → `execute` → `verify` → `narrate`.
  * Evaluates repository status, working tree diffs, and RAG context before taking action.
* **Guarded `.env` File Access Security**:
  * When a screen-reader or blind-mode developer attempts to open a sensitive `.env` file, NeuroCode intercepts access and prompts an auditory confirmation: *"Warning: You are trying to access a dot env file containing sensitive credentials. Press Alt+Y to confirm or Alt+N to reject."*
* **Spoken Confirmation Flow**:
  * High-risk operations (destructive commits, `.env` file modifications, git pushes) pause the agent execution loop and request explicit verbal or hotkey confirmation (`Alt+Y` / `Alt+N`).
* **Multi-Tier Risk-Modulated Voice TTS**:
  * Features instant zero-silence filler audio via **Sarvam AI TTS** (`"Processing your request..."`) and high-fidelity narration via **ElevenLabs** / **Sarvam AI**.

---

## ⌨️ Command & Keybinding Reference

NeuroCode exposes native VS Code commands and accessible keyboard shortcuts:

| Command Title | Command ID | Default Keybinding | Description |
|---|---|---|---|
| **Toggle Voice Input (Backend Mic)** | `neurocode.toggleMic` | `Alt+M` (`Cmd+Alt+M`) | Toggles OS microphone capture via Python `sounddevice`. |
| **Toggle Manual Coding Stream** | `neurocode.toggleManualStream` | `Alt+M` (`Cmd+Alt+M`) | Enables/disables Intellisense syntax & terminal error interception. |
| **Confirm Action (Yes)** | `neurocode.confirm` | `Alt+Y` (`Cmd+Alt+Y`) | Confirms a pending agent action or sensitive file access. |
| **Cancel Action (No)** | `neurocode.cancel` | `Alt+N` (`Cmd+Alt+N`) | Cancels a pending agent action or sensitive file access. |
| **Toggle Copilot Observer** | `neurocode.toggleObserver` | *Palette* | Mutes or unmutes Copilot ambient audio earcons and HUD. |
| **Start Voice Input** | `neurocode.startVoiceInput` | *Palette* | Opens the NeuroCode webview panel & starts voice loop. |
| **Stop Voice Input** | `neurocode.stopVoiceInput` | *Palette* | Stops active microphone audio capture. |

---

## 📂 Repository Structure

```
angizo/
├── backend/                          # Python FastAPI Backend Engine
│   ├── agent/                        # LangGraph Agent State Machine
│   │   ├── graph.py                  # 7-Node StateGraph definition
│   │   ├── state.py                  # AgentState TypedDict schema
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
│   ├── pyproject.toml
│   └── requirements.txt
│
├── neurocode-extension/              # VS Code Extension
│   ├── src/
│   │   ├── extension.ts              # Extension host entrypoint & command registry
│   │   ├── ws-client.ts              # WebSocket client connecting host to backend
│   │   ├── webview-bridge.ts         # postMessage bridge between webview and extension host
│   │   └── observer/
│   │       ├── copilot-watcher.ts    # Copilot AI generation detector & event emitter
│   │       ├── manual-watcher.ts     # Intellisense LSP syntax error interceptor
│   │       ├── terminal-watcher.ts   # Terminal stdout/stderr runtime crash interceptor
│   │       ├── author-tracker.ts     # Coordinated state tracker (Copilot vs Human)
│   │       ├── observer-earcon.ts    # Web Audio synth chime generator
│   │       ├── observer-hud.ts       # Top editor high-contrast overlay banner
│   │       └── observer-status-bar.ts# Accessible status bar item
│   │   └── webview/
│   │       ├── main.js               # Accessible webview UI logic & audio player
│   │       └── pcm-processor.js      # AudioWorklet PCM processor
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
| **VS Code** | `>= 1.85.0` | Help → About |
| **uv** *(Recommended)* | Latest | `uv --version` |

---

## 🔑 Environment Configuration (`.env`)

Create a `.env` file inside `backend/`:

```env
# Server Configuration
NEUROCODE_HOST=0.0.0.0
NEUROCODE_PORT=7001

# API Keys
SARVAM_API_KEY=your_sarvam_api_key_here        # Required (STT & Fallback TTS)
GROQ_API_KEY=your_groq_api_key_here            # Required (LLM Diff Intelligence & Copilot Summaries)
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here# Recommended (High Quality Voice Narration)
GEMINI_API_KEY=your_gemini_api_key_here        # Optional Fallback
GITHUB_PAT=your_github_token_here              # Optional (PR creation)

# Engine Defaults
SARVAM_STT_ENDPOINT=https://api.sarvam.ai/speech-to-text
SARVAM_FILLER_SPEAKER=ratan
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
GROQ_MODEL=llama-3.3-70b-versatile
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
uv pip install -e .
uv pip install sounddevice numpy scipy httpx python-dotenv

# Run the FastAPI server
python main.py
```
> Server runs at `http://localhost:7001`. Health check: `curl http://localhost:7001/health`.

### Step 2: Build & Launch the VS Code Extension

In a separate terminal:

```bash
cd neurocode-extension

# Install dependencies & compile TypeScript
npm install
npm run compile
```

1. Open `neurocode-extension` in VS Code (`code neurocode-extension`).
2. Press **`F5`** to launch the **Extension Development Host**.
3. In the new window, open the Command Palette (`Ctrl+Shift+P`) and run **`NeuroCode: Start Voice Input`**.

---

## 🛠️ Verification & Testing

1. **Test Voice Command**: Click 🎙️ or press `Alt+M` and speak: *"What is my git status?"*.
2. **Test Copilot Streaming**: Trigger Copilot inline completion or Copilot Chat edit. Observe the Web Audio earcon chime, floating HUD banner, and Groq architectural narration.
3. **Test Manual Assistance**: Type code with a syntax error and move off the line (`Alt+M` enabled). Observe the instant error chime and line-exit narration.
4. **Test Sensitive File Guard**: Open a `.env` file in the editor to trigger the screen reader security warning.

---

## 📄 License & Acknowledgments

Built for accessibility innovation during hackathon development. Powered by **FastAPI**, **LangGraph**, **Groq**, **Sarvam AI**, **ElevenLabs**, and **VS Code Extension API**.
## Built by 
Team *Nano Pineapple*
