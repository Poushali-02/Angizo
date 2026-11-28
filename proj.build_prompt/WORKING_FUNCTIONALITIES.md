# Angizo — Working Functionalities & Feature Audit

This document summarizes all verified, working functionalities built into the Angizo AI Accessibility Agent across the backend engine, voice pipeline, AI models, and VS Code extension.

---

## 🎙️ 1. Voice Input & Audio Capture Pipeline

* **Native Backend OS Microphone Recording:**
  * Captures raw 16kHz 16-bit mono PCM audio directly from the host operating system's microphone using Python `sounddevice` and `numpy`.
  * Fully bypasses VS Code webview iframe permission restrictions.
  * Real-time WebSocket state streaming (`recording` → `transcribing` → `idle`).
* **Sarvam AI Speech-to-Text (STT):**
  * Integrated with Sarvam AI STT API (`saarika:v2.5` model, `en-IN` language code).
  * Automatically converts captured PCM audio bytes to high-accuracy text transcripts.

---

## 🧠 2. LLM Diff Intelligence & Intent Classification

* **Groq LLM Integration:**
  * Powered by Groq's high-speed `llama-3.3-70b-versatile` model over an OpenAI-compatible REST API.
* **Intent Classification Taxonomy:**
  * Classifies freeform voice transcripts into 10 structured Git/GitHub intents:
    * `git_status`, `git_commit`, `git_push`, `git_pull`, `git_branch_create`, `git_branch_switch`, `git_explain_conflict`, `git_review`, `git_undo`, `github_open_pr`.
  * **Rule-Based Fallback:** Robust keyword matching fallback if LLM queries time out or fail.
* **Diff Risk Analysis:**
  * Classifies working directory diffs into risk bands (`safe`, `caution`, `high-risk`).
  * Computes blast radius (file count) and lists affected area summaries.
* **Conventional Commit Drafting:**
  * Automatically generates single-line conventional commit messages from git diffs.
* **Accessibility Code Review:**
  * Generates screen-reader and voice-friendly prose code reviews summarizing uncommitted changes.

---

## 🔊 3. Multi-Tier Text-to-Speech (TTS) Narration Engine

* **ElevenLabs Primary TTS:**
  * Generates risk-toned voice narration audio payloads using ElevenLabs API (`eleven_monolingual_v1`).
  * Dynamic parameter tuning (stability, similarity boost, style) based on risk bands (`safe`, `caution`, `high-risk`).
* **Sarvam AI TTS Fallback:**
  * Seamless fallback to Sarvam AI TTS (`bulbul:v2` model, neutral speaker `ratan`, `en-IN`).
  * Triggers automatically if ElevenLabs API key is unconfigured, unauthorized (401), or fails, guaranteeing voice audio responses always play.
* **Webview Audio Playback:**
  * Base64 MP3 audio payloads sent via WebSocket and played automatically inside the VS Code webview panel.

---

## ⚡ 4. LangGraph Agent Graph & Safety Confirmation

* **State-Machine Architecture:**
  * Orchestrated via LangGraph: `understand` → `context` → `reason` → `confirm` → `execute` → `verify` → `narrate`.
* **Human-in-the-Loop Confirmation:**
  * Intercepts high-risk or destructive commands (e.g. switching branches with uncommitted changes, force pushes).
  * Sends confirmation prompt (`confirmation_request`) to the webview UI with interactive `[Yes]` and `[No]` buttons and voice prompt.

---

## 🛠️ 5. Git Tools & Workspace Operations

* **Git Integration (`GitPython`):**
  * Dynamic repository tracking (`_set_repo_path`).
  * Automatically syncs active VS Code workspace folder path (`set_workspace`).
  * Checks working tree status, branch state, uncommitted changed files, and git diffs.

---

## 🔌 6. VS Code Extension & Bridge Architecture

* **Extension Host Architecture:**
  * Webview never communicates with the network directly.
  * Extension host maintains a persistent WebSocket connection (`ws://localhost:7001/ws/session`) via `AngizoWsClient`.
* **Webview Bridge (`WebviewBridge`):**
  * Relays postMessages between the webview UI and extension host WebSocket.
* **Accessible Dark-Mode Webview UI:**
  * Live status indicator ("Backend Connected", "Listening…", "Transcribing…").
  * 🎙️ / 🛑 Microphone toggle button with visual recording ring.
  * Command palette text input field for manual text commands.
  * Real-time activity log window with auto-scrolling timestamped events.
  * Interactive confirmation UI banner.
