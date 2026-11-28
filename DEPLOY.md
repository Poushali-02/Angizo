# Angizo — Deployment & Operations Guide (`DEPLOY.md`)

This document provides comprehensive, step-by-step instructions for deploying, packaging, and operating the **Angizo** AI Accessibility Agent system.

---

## 🏗️ Architecture Overview

Angizo consists of two main decoupled components that communicate over a local or remote WebSocket connection:

```
┌─────────────────────────────────────────────────────────────┐
│                    VS Code Extension                        │
│  ┌───────────────────────┐       ┌───────────────────────┐  │
│  │   Webview UI          │ ────> │   Extension Host      │  │
│  │   (Dark-Mode Panel)   │ <──── │   (Node.js / TS)      │  │
│  └───────────────────────┘       └──────────┬────────────┘  │
└─────────────────────────────────────────────┼───────────────┘
                                              │ WebSocket
                                              │ (ws://localhost:7001/ws/session)
┌─────────────────────────────────────────────▼───────────────┐
│                    FastAPI Backend                          │
│  ┌───────────────────────┐       ┌───────────────────────┐  │
│  │   Voice Engine        │       │   LangGraph Agent     │  │
│  │   (Sarvam / 11Labs)   │       │   (Groq LLaMA 3.3)    │  │
│  └───────────────────────┘       └───────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

1. **FastAPI Backend Engine (`backend/`)**: Modular Python monolith that handles microphone recording (`sounddevice`), speech-to-text (`Sarvam AI`), LLM diff reasoning (`Groq LLaMA 3.3`), multi-tier TTS narration (`ElevenLabs` + `Sarvam AI` fallback), and Git operations (`GitPython`).
2. **VS Code Extension (`angizo-extension/`)**: TypeScript extension host managing the WebSocket client connection and bridging messages to an accessible webview UI.

---

## 📋 Prerequisites & System Requirements

### Backend Requirements
- **Python**: Version `3.9` or higher (`3.10` / `3.11` recommended)
- **Package Manager**: `pip` or `uv`
- **System Audio Drivers & PortAudio**:
  - **Linux (Ubuntu/Debian)**: `sudo apt-get update && sudo apt-get install -y portaudio19-dev python3-pyaudio ffmpeg`
  - **macOS**: `brew install portaudio ffmpeg`
  - **Windows**: Native WASAPI / DirectSound drivers (installed automatically with Windows)

### Extension Requirements
- **Node.js**: Version `18.0.0` or higher
- **npm**: Version `9.0.0` or higher
- **VS Code**: Version `^1.85.0`
- **VS Code Extension Manager**: `@vscode/vsce` (for building `.vsix` packages)

---

## 🔑 Environment Configuration

Create a `.env` file in the `backend/` directory based on the following template:

```ini
# --- Server Configuration ---
ANGIZO_HOST=0.0.0.0
ANGIZO_PORT=7001
ANGIZO_REPO_PATH=

# --- AI & LLM Service Keys ---
# Groq API Key (Primary LLM: llama-3.3-70b-versatile)
GROQ_API_KEY=gsk_xxxxxxxx──────────────────────
GROQ_MODEL=llama-3.3-70b-versatile

# Sarvam AI Key (Primary STT: saarika:v2.5, Fallback TTS: bulbul:v2)
SARVAM_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SARVAM_STT_ENDPOINT=https://api.sarvam.ai/speech-to-text
SARVAM_FILLER_SPEAKER=anushka

# ElevenLabs API Key (Primary Risk-Toned TTS)
ELEVENLABS_API_KEY=sk_xxxxxxxx──────────────────
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM

# Google Gemini API Key (Optional fallback/alternative)
GEMINI_API_KEY=AIzaSyxxxxxxxx──────────────────
GEMINI_MODEL=gemini-1.5-flash

# GitHub Integration Token (For PR creation & remote git sync)
GITHUB_PAT=ghp_xxxxxxxx─────────────────────────

# Database / Telemetry (Optional)
MONGODB_URI=mongodb://localhost:27017/angizo
```

---

## 🚀 Local Deployment & Development

### 1. Launching the Backend Server

```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python -m venv .venv

# On Windows (PowerShell):
.venv\Scripts\activate

# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Or using uv (faster):
# uv pip install -r requirements.txt

# Start FastAPI server
python main.py
```

*The server will start listening at `http://0.0.0.0:7001`. The WebSocket endpoint will be live at `ws://localhost:7001/ws/session`.*

### 2. Building & Launching the VS Code Extension

```bash
# Navigate to extension directory
cd angizo-extension

# Install node dependencies
npm install

# Compile TypeScript source files
npm run compile
```

#### Debugging in VS Code (Extension Development Host):
1. Open the workspace root (`angizo`) in VS Code.
2. Press `F5` (or go to **Run and Debug** -> **Extension**).
3. In the new VS Code window that opens, open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`).
4. Type `Angizo: Start Voice Input` and press `Enter`.
5. The accessible Angizo panel will open in the side column and automatically connect to `ws://localhost:7001/ws/session`.

---

## 📦 Packaging & Distributing the VS Code Extension

To package the extension into a standalone `.vsix` file for installation across machines without requiring source compilation:

### 1. Install VSCE Tool
```bash
npm install -g @vscode/vsce
```

### 2. Package into VSIX
```bash
cd angizo-extension

# Package extension
vsce package
```
*This produces `angizo-0.1.0.vsix` in the `angizo-extension/` directory.*

### 3. Installing the VSIX Package

#### Via VS Code CLI:
```bash
code --install-extension angizo-0.1.0.vsix
```

#### Via Cursor IDE CLI:
```bash
cursor --install-extension angizo-0.1.0.vsix
```

#### Via VS Code UI:
1. Open VS Code.
2. Go to the **Extensions** view (`Ctrl+Shift+X` / `Cmd+Shift+X`).
3. Click the three dots `...` menu in the top-right corner of the Extensions view.
4. Select **Install from VSIX...**.
5. Select `angizo-0.1.0.vsix`.

---

## 🐳 Containerized Production Backend (Docker Deployment)

For deploying the backend service on cloud servers (AWS, GCP, Azure, Railway, Render, DigitalOcean):

### 1. Production Dockerfile (`backend/Dockerfile`)

```dockerfile
FROM python:3.11-slim

# Install system audio dependencies for sounddevice & portaudio
RUN apt-get update && apt-get install -y --no-install-recommends \
    portaudio19-dev \
    libasound2-dev \
    ffmpeg \
    git \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specifications
COPY pyproject.toml requirements.txt ./

# Install python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend codebase
COPY . .

# Expose FastAPI / WebSocket port
EXPOSE 7001

# Run Uvicorn server
CMD ["python", "main.py"]
```

### 2. Building & Running Docker Container

```bash
cd backend

# Build Docker image
docker build -t angizo-backend:latest .

# Run Docker container with environment variables
docker run -d \
  --name angizo-server \
  -p 7001:7001 \
  --env-file .env \
  angizo-backend:latest
```

### 3. Deploying to Cloud PaaS (Railway / Render / AWS ECS)
- **Port**: Set application port to `7001`.
- **Environment Variables**: Add all key-value pairs from `.env` into the Cloud Provider's Secret Settings.
- **WebSocket Support**: Ensure WebSocket connections (`/ws/session`) are enabled in your Cloud Load Balancer / Reverse Proxy.
- **HTTPS / WSS**: When deploying to remote servers, replace `ws://` with secure WebSocket `wss://` in `angizo-extension/src/extension.ts`.

---

## 🔍 Verification & Health Checks

| Check Item | Target Endpoint / Command | Expected Result |
| :--- | :--- | :--- |
| **Backend REST API** | `GET http://localhost:7001/` | Returns JSON status `{ "status": "ok", "app": "Angizo" }`    |
| **WebSocket Connection** | `ws://localhost:7001/ws/session` | Upgraded to WebSocket (HTTP 101 Switching Protocols) |
| **Voice STT Audio Test** | Voice toggle in Webview | Status updates `listening` → `transcribing` → `idle` |
| **LLM Reasoning & Git** | Voice/Text: "check git status" | Speaks summary via TTS and logs diff analysis |
| **Extension Health** | VS Code Developer Tools (`Help -> Toggle Developer Tools`) | Logs `[ws-client] Connected` with 0 console errors |

---

## 🛠️ Troubleshooting Guide

### 1. `sounddevice.PortAudioError` / Microphone Initialization Failed
- **Cause**: PortAudio library missing on Linux/macOS or no physical input device found.
- **Solution**: Install system library (`apt-get install portaudio19-dev` / `brew install portaudio`). In headless server environments, the system falls back to text-mode input via the Command Palette or WebSocket messages.

### 2. Extension Displays "Backend Disconnected"
- **Cause**: FastAPI server is not running, or listening on a different port.
- **Solution**: Check if backend is running on `http://localhost:7001`. If custom port is used, update `wsPort` in `angizo-extension/src/extension.ts` line 62.

### 3. ElevenLabs Audio Payload Silent / Fails
- **Cause**: ElevenLabs quota exceeded or `ELEVENLABS_API_KEY` invalid/missing.
- **Solution**: Angizo includes an automatic fallback mechanism. If ElevenLabs returns an error (or 401/429), it instantly falls back to **Sarvam AI TTS (`bulbul:v2`)**, ensuring voice output is never interrupted.

---

*Angizo — AI Accessibility Agent Deployment Guide.*
