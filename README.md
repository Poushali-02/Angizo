# NeuroCode — Deployment Guide

Complete step-by-step instructions to get NeuroCode running locally for development, demo, or hackathon judging.

> [!IMPORTANT]
> NeuroCode has **two components** that must both be running simultaneously:
> 1. **Python FastAPI Backend** — the AI brain (LangGraph, STT, TTS, Git, RAG)
> 2. **VS Code Extension** — the IDE interface (voice toggle, webview panel, WebSocket bridge)

---

## 📋 Prerequisites

Before starting, ensure you have the following installed:

| Requirement | Version | Check Command |
|---|---|---|
| **Python** | `>= 3.9` | `python --version` |
| **Node.js** | `>= 18.x` | `node --version` |
| **npm** | `>= 9.x` | `npm --version` |
| **Git** | Any modern version | `git --version` |
| **VS Code** | `>= 1.85.0` | Help → About |
| **uv** *(Python package manager, recommended)* | Latest | `uv --version` |

> [!TIP]
> `uv` is significantly faster than `pip` for installing Python dependencies. Install it with:
> ```bash
> pip install uv
> ```
> If you prefer plain `pip`, all `uv` commands below have a plain `pip` equivalent shown.

---

## 🔑 Step 1: Obtain API Keys

NeuroCode integrates with the following external AI services. Collect your API keys before proceeding.

| Service | Purpose | Where to Get |
|---|---|---|
| **Sarvam AI** | Speech-to-Text (STT) + Fallback TTS | [dashboard.sarvam.ai](https://dashboard.sarvam.ai) |
| **Groq** | LLM Diff Intelligence & Intent Classification | [console.groq.com](https://console.groq.com) |
| **ElevenLabs** | Primary Risk-Modulated Voice Narration | [elevenlabs.io](https://elevenlabs.io) |
| **Google Gemini** | Optional LLM fallback | [aistudio.google.com](https://aistudio.google.com) |
| **GitHub PAT** | PR creation & GitHub operations | GitHub → Settings → Developer Settings → Personal Access Tokens |

> [!NOTE]
> Only **Sarvam AI** and **Groq** keys are strictly required for the core voice pipeline and Git diff intelligence. ElevenLabs is recommended for the best narration quality. Gemini and GitHub PAT are optional.

---

## 🗂️ Step 2: Clone the Repository

```bash
git clone https://github.com/<your-org>/neurocode.git
cd neurocode
```

Your project structure should look like this:

```
neurocode/
├── backend/                  # Python FastAPI Backend Engine
│   ├── agent/                # LangGraph State Machine
│   │   ├── graph.py          # 7-Node StateGraph definition
│   │   ├── state.py          # AgentState TypedDict schema
│   │   └── nodes/            # understand, context, reason, confirm, execute, verify, narrate
│   ├── api/
│   │   ├── ws.py             # WebSocket endpoint & OS mic recording
│   │   └── rest.py           # REST health endpoint
│   ├── tools/
│   │   ├── diff_intelligence.py   # Groq/Gemini LLM integration
│   │   ├── git_tool.py            # GitPython wrapper
│   │   ├── rag_engine.py          # Local codebase RAG
│   │   ├── sarvam_stt.py          # Sarvam STT client
│   │   ├── sarvam_tts.py          # Sarvam TTS filler client
│   │   ├── elevenlabs_tts.py      # ElevenLabs TTS client
│   │   └── gemini_llm.py          # Gemini LLM client
│   ├── main.py               # FastAPI app entrypoint
│   ├── config.py             # Environment variable config
│   ├── .env                  # Your API keys (never commit this)
│   ├── pyproject.toml
│   └── requirements.txt
│
└── neurocode-extension/      # VS Code Extension
    ├── src/
    │   ├── extension.ts      # Extension host entry point
    │   ├── ws-client.ts      # WebSocket client to backend
    │   ├── webview-bridge.ts # Webview ↔ Extension Host bridge
    │   └── webview/
    │       ├── main.js       # Accessible webview UI
    │       └── pcm-processor.js
    ├── package.json
    └── tsconfig.json
```

---

## ⚙️ Step 3: Configure Environment Variables

Navigate to the backend folder and create your `.env` file:

```bash
cd backend
```

Copy the template below into a new file called `.env` inside `backend/`:

```env
# ==============================================================================
# NeuroCode Backend — Environment Configuration (.env)
# ==============================================================================

# Server Network Settings
NEUROCODE_HOST=0.0.0.0
NEUROCODE_PORT=7001

# Target Repository Path (optional — defaults to current working directory)
# NEUROCODE_REPO_PATH=C:\path\to\your\project

# ------------------------------------------------------------------------------
# API Keys — Fill in your own keys below
# ------------------------------------------------------------------------------

# Sarvam AI API Key (STT + Fallback TTS) — REQUIRED
SARVAM_API_KEY=your_sarvam_api_key_here

# Groq API Key (LLM Diff Intelligence) — REQUIRED
GROQ_API_KEY=your_groq_api_key_here

# ElevenLabs API Key (Primary Voice Narration) — RECOMMENDED
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here

# Google Gemini API Key (Optional LLM fallback)
GEMINI_API_KEY=

# GitHub Personal Access Token (Optional — for PR creation)
GITHUB_PAT=

# ------------------------------------------------------------------------------
# Voice & Audio Model Customization (defaults shown)
# ------------------------------------------------------------------------------
SARVAM_STT_ENDPOINT=https://api.sarvam.ai/speech-to-text
SARVAM_FILLER_SPEAKER=ratan
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
GROQ_MODEL=llama-3.3-70b-versatile
GEMINI_MODEL=gemini-1.5-flash
```

> [!CAUTION]
> **Never commit `.env` to version control.** It is already in `.gitignore`. Keep your API keys private.

---

## 🐍 Step 4: Install Python Backend Dependencies

From the `backend/` directory:

### Using `uv` (Recommended — Fastest)

```bash
cd backend

# Create virtual environment
uv venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Install all dependencies from pyproject.toml
uv pip install -e .

# Install audio capture dependencies (required for OS microphone)
uv pip install sounddevice numpy scipy httpx python-dotenv
```

### Using plain `pip` (Alternative)

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Install from requirements.txt
pip install -r requirements.txt

# Install additional dependencies
pip install sounddevice numpy scipy httpx python-dotenv nest-asyncio
```

> [!NOTE]
> On **Windows**, `sounddevice` requires **PortAudio** to be available. It is typically bundled automatically with the `sounddevice` wheel. If you encounter an error, install it via:
> ```bash
> pip install sounddevice --find-links https://github.com/spatialaudio/python-sounddevice/releases
> ```
> On **Linux**, install PortAudio first: `sudo apt-get install portaudio19-dev`
> On **macOS**: `brew install portaudio`

---

## 🚀 Step 5: Launch the Python FastAPI Backend

From the `backend/` directory (with virtual environment activated):

```bash
cd backend
python main.py
```

**Expected startup output:**
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     NeuroCode backend starting on 0.0.0.0:7001
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:7001 (Press CTRL+C to quit)
```

> [!IMPORTANT]
> The backend **must be running on `ws://localhost:7001`** before launching the VS Code extension. The WebSocket endpoint is `ws://localhost:7001/ws/session`.

**Verify the backend is healthy:**
```bash
curl http://localhost:7001/health
```
Expected response: `{"status": "ok"}`

---

## 🧩 Step 6: Install VS Code Extension Dependencies

In a **separate terminal**, navigate to the extension folder:

```bash
cd neurocode-extension

# Install Node.js dependencies
npm install
```

---

## 🔨 Step 7: Compile the TypeScript Extension

```bash
cd neurocode-extension

# One-time compile
npm run compile
```

Or for live development (auto-recompiles on file save):

```bash
npm run watch
```

> [!TIP]
> Keep `npm run watch` running in a terminal during development so TypeScript changes are picked up immediately without manual recompilation.

---

## 🖥️ Step 8: Launch the Extension in VS Code

### Option A: Developer Mode (Recommended for Hackathon Demo)

1. Open the **`neurocode-extension`** folder in VS Code:
   ```bash
   code neurocode-extension
   ```
2. Press **`F5`** (or go to **Run → Start Debugging**).
3. A new **[Extension Development Host]** VS Code window opens.
4. In the new window, open the command palette (`Ctrl+Shift+P`) and run:
   ```
   NeuroCode: Start Voice Input
   ```
5. The **NeuroCode Side Panel** will appear on the left sidebar.

### Option B: Install as `.vsix` Package

First, build the packaged extension:
```bash
cd neurocode-extension

# Install vsce packaging tool
npm install -g @vscode/vsce

# Package the extension
vsce package
```

This generates a `neurocode-0.1.0.vsix` file. Install it into VS Code:
```bash
code --install-extension neurocode-0.1.0.vsix
```

Or via VS Code UI: **Extensions panel → `...` menu → Install from VSIX...**

---

## ✅ Step 9: Verify Full System is Working

Once both the backend and extension are running, verify the entire pipeline:

### 1. Check WebSocket Connection
In the NeuroCode side panel, the status indicator should show:
```
● Backend Connected
```
If it shows "Disconnected" or "Connecting...", verify the backend is running on port `7001`.

### 2. Test Text Command (No Microphone Needed)
Type `git status` in the command input field and press Enter. You should hear/see a spoken narration of your repository status within 3–5 seconds.

### 3. Test Voice Input
Click the **🎙️ microphone button** and say: *"What is the git status?"*

Expected flow:
- UI switches to **Listening...** state
- UI switches to **Transcribing...**
- Filler audio plays: *"Processing your request..."*
- Final spoken narration plays with git status summary

---

## 🔁 Running Order Summary (Quick Reference)

Every time you want to use NeuroCode, always start in this order:

```
Terminal 1                         VS Code
─────────────────────────────────  ─────────────────────────────────
cd backend                         Open neurocode-extension folder
.venv\Scripts\activate             Press F5 to launch Extension Dev Host
python main.py                     Open NeuroCode side panel
  ↓                                  ↓
Backend live on :7001  ←──WS──→  Extension connected
```

---

## 🛠️ Troubleshooting

### ❌ `WebSocket connection refused` in VS Code panel
- **Cause:** Backend is not running or crashed.
- **Fix:** Start the backend first (`python main.py`) and verify it shows `Uvicorn running on http://0.0.0.0:7001`.

### ❌ `sounddevice: No module named '_sounddevice'`
- **Cause:** PortAudio library missing on the system.
- **Fix (Windows):** `pip install sounddevice` usually bundles it. Try reinstalling: `pip uninstall sounddevice && pip install sounddevice`.
- **Fix (Linux):** `sudo apt-get install portaudio19-dev && pip install sounddevice`
- **Fix (macOS):** `brew install portaudio && pip install sounddevice`

### ❌ `No speech detected in audio`
- **Cause:** Microphone not capturing or Sarvam STT returned empty transcript.
- **Fix:** Check that your system microphone is enabled and set as the default recording device. Test with `python -c "import sounddevice; print(sounddevice.query_devices())"` to list available devices.

### ❌ `Groq API error 401`
- **Cause:** Invalid or missing `GROQ_API_KEY` in `.env`.
- **Fix:** Verify the key at [console.groq.com](https://console.groq.com). The system will fall back to rule-based keyword intent classification automatically.

### ❌ `ElevenLabs API 401 / no audio`
- **Cause:** Invalid or missing `ELEVENLABS_API_KEY`.
- **Fix:** NeuroCode **automatically falls back** to Sarvam AI TTS. Voice narration will still work. Add a valid ElevenLabs key when available.

### ❌ TypeScript compile error in extension
- **Cause:** Node modules not installed or TypeScript version mismatch.
- **Fix:**
  ```bash
  cd neurocode-extension
  rm -rf node_modules
  npm install
  npm run compile
  ```

---

## 📦 Required Environment at a Glance

```
neurocode/
└── backend/
    └── .env          ← Must be filled with API keys (see Step 3)
```

```
Ports in Use:
  7001  ← NeuroCode FastAPI Backend (WebSocket + REST)
```

```
Python Virtual Environment:
  backend/.venv/      ← Must be activated before running python main.py
```
