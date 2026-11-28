# Angizo — Design Specification

## Architecture decision: Modular Monolith

One FastAPI service, internally organized into independent modules, deployed as a single unit.

**Rationale:** microservices would introduce network hops between components, directly hurting the responsiveness Zero-Silence Handoff depends on, plus more independent failure points during a live demo. A monolith gets separation-of-concerns via clean module boundaries without the operational cost. If this becomes a production platform later, modules can be extracted individually.

## System Diagram

```
┌───────────────────────────────────────────────────────────┐
│              Webview (sandboxed, Chromium)                   │
│  - Mic capture via AudioWorklet → raw PCM frames             │
│  - Earcon player (Web Audio API, 3-sound fixed set)          │
│  - Simulated Braille panel (on-screen mock)                  │
│  - Narration audio playback + barge-in stop logic            │
└───────────────────────┬───────────────────────────────────┘
                         │  postMessage() — in-process, NOT network
                         │  (no CSP/remote-connection restrictions apply
                         │   here since this never leaves the process)
                         ▼
┌───────────────────────────────────────────────────────────┐
│         Extension Host (Node.js process, local)              │
│  - Command palette + status bar commands                    │
│  - SecretStorage (PAT, API keys — never passed to webview)  │
│  - Owns the WebSocket connection to the backend               │
│  - Screen reader accessibility API hooks                     │
└───────────────────────┬───────────────────────────────────┘
                         │  WebSocket (wss://) — the real host-to-host
                         │  network connection
                         │  (audio frames up; transcripts,
                         │   earcon events, narration audio,
                         │   confirmation prompts down)
                         ▼
┌───────────────────────────────────────────────────────────┐
│           Angizo Accessibility Agent (FastAPI)               │
│                                                               │
│         Listen → Understand → Context → Reason →             │
│              Confirm → Execute → Verify → Narrate             │
│                    (LangGraph state graph)                    │
│                                                               │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐│
│  │  Git Tool   │ │GitHub Tool │ │   Diff      │ │Accessibility││
│  │ (GitPython) │ │ (PyGithub) │ │Intelligence │ │  Engine    ││
│  │             │ │            │ │  (Gemini)   │ │(Sarvam +   ││
│  │             │ │            │ │             │ │ ElevenLabs)││
│  └────────────┘ └────────────┘ └────────────┘ └───────────┘│
│                         │                                    │
│                         ▼                                    │
│              Memory + RAG Engine                              │
│         (MongoDB Atlas + Vector Search)                       │
└───────────────────────┬───────────────────────────────────┘
                         │
                         ▼
              DigitalOcean App Platform
       (Cloud Mode primary; Local Mode fallback switch
        for unreliable venue wifi)
```

## Backend module breakdown

```
backend/
├── agent/
│   ├── graph.py          # LangGraph state graph definition (the 7-step loop)
│   ├── state.py          # Shared agent state schema
│   └── nodes/            # One module per graph node (understand, context, reason, confirm, execute, verify, narrate)
├── tools/
│   ├── git_tool.py       # GitPython wrapper: status, commit, push, pull, branch, merge, checkout, revert, stash
│   ├── github_tool.py    # PyGithub wrapper: PR create/review, comments, reviewers, metadata
│   ├── diff_intelligence.py  # Gemini calls: classify, summarize, risk-score, commit-message-draft
│   └── accessibility_engine.py  # Earcon selection, Sarvam/ElevenLabs dispatch, Braille fragment routing
├── memory/
│   ├── session_store.py  # MongoDB: session state, preferences, risk history
│   └── rag_engine.py     # Embedding generation + MongoDB Atlas Vector Search retrieval
├── voice/
│   ├── sarvam_stt.py     # WebSocket proxy to Sarvam streaming STT, VAD event handling
│   ├── sarvam_tts.py     # WebSocket proxy to Sarvam streaming TTS (filler narration)
│   └── elevenlabs_tts.py # ElevenLabs streaming client (primary narration)
├── api/
│   ├── ws.py              # Main WebSocket endpoint — client <-> agent bridge
│   └── rest.py             # Health check, config, auth token exchange
├── config.py              # Env vars, API keys (loaded server-side only)
└── main.py                # FastAPI app entrypoint
```

## Client (extension) module breakdown

```
angizo-extension/
├── src/
│   ├── extension.ts          # Activation, command registration
│   ├── commands/               # One handler per VS Code command surface
│   ├── ws-client.ts            # WebSocket connection to backend (lives in extension
│   │                            # host, NOT webview — see note below), Cloud/Local mode switch
│   ├── webview-bridge.ts       # postMessage relay between webview and ws-client.ts
│   ├── webview/
│   │   ├── mic-capture.ts      # AudioWorkletNode → raw PCM frames → postMessage to extension host
│   │   ├── playback.ts         # Narration audio playback + barge-in stop logic
│   │   └── earcon-player.ts    # Web Audio API earcon triggers
│   └── accessibility/
│       ├── braille-sim.ts      # Simulated Braille panel rendering (webview)
│       └── screen-reader.ts    # VS Code accessibility API integration (extension host)
```

**Why the WebSocket lives in the extension host, not the webview:** VS Code webviews are sandboxed with a restrictive Content-Security-Policy (`connect-src` blocks arbitrary remote hosts by default), and real-world reports show even correctly-configured remote WebSocket connections from a webview can be unreliable (blocked by CSP or local proxy settings) in ways that don't reproduce in a normal browser tab. The extension host is a plain Node.js process with no such sandbox. It also already owns `SecretStorage`, so keeping the authenticated connection there means API keys and the GitHub PAT never have to be exposed to the (inspectable) webview context at all. Audio frames and playback data cross the webview/extension-host boundary via `postMessage`, which is in-process and unaffected by CSP.

## The Agent Loop (LangGraph state graph)

```
[Listen] → [Understand Intent] → [Gather Context] → [Reason/Plan]
    → [Confirm?] --yes--> wait for user response --> [Execute]
              --no (low-risk/read-only)--> [Execute]
    → [Verify] → [Narrate] → back to [Listen]
```

**Confirmation policy:**
- Read-only actions (status, diff review, "why can't I push") → no confirmation needed, execute and narrate directly
- Mutating actions (commit, push, branch create/switch, undo/revert, PR creation) → always confirm before executing
- High-risk mutating actions (undo/revert, force operations) → confirm and explicitly state the consequence before executing

## Data Flow — example: "Push changes"

1. `mic-capture.ts` (webview) captures PCM frames → `postMessage` → `webview-bridge.ts` → `ws-client.ts` (extension host) → WebSocket → backend
2. `sarvam_stt.py` proxies to Sarvam STT WebSocket, VAD detects end of speech, transcript returned
3. Agent `[Understand Intent]` node classifies: `git_push`
4. `[Gather Context]` node calls `git_tool.status()`, `git_tool.current_branch()`, `git_tool.remote_ahead_behind()`
5. `[Reason]` node: any uncommitted changes? any conflicts? branch pushable?
6. `[Confirm]` node: agent sends narration "You're on feature/auth, two commits ready to push. Continue?" via `elevenlabs_tts.py`, waits for next transcript
7. On "yes" → `[Execute]` calls `git_tool.push()`
8. `[Verify]` checks push succeeded (exit code / remote ref check)
9. `[Narrate]` → "Push completed successfully." + success earcon via `accessibility_engine.py`
10. Session logged to `session_store.py` (command, risk band, outcome, timestamp)

## Zero-Silence Handoff implementation note
Any node expected to take >500ms (Gemini call, git fetch over network, PR creation) should emit incremental filler events to `sarvam_tts.py` on a separate lightweight channel *while* the main reasoning step is still in flight — not blocking on it. Filler phrases should be short, varied, and voice-matched to the primary ElevenLabs narration so the handoff between the two is inaudible.

## Barge-in implementation note
VAD `START_SPEECH` events from Sarvam STT, received while `playback.ts` is actively playing narration audio, must trigger an immediate **client-side** stop (fade-out over ~200–300ms, not a hard cut) with zero backend round-trip. Only after playback has stopped does the new transcript get sent to the agent as the next turn. Sarvam's TTS WebSocket has no server-side cancel message — the client must independently stop local playback and close/reopen the TTS socket for the next utterance.

## Data Model — MongoDB Atlas

**Collection: `sessions`**
```json
{
  "_id": "ObjectId",
  "user_id": "string",
  "started_at": "datetime",
  "preferences": {
    "speech_rate": "number",
    "verbosity": "low|medium|high"
  },
  "current_repo": "string",
  "current_branch": "string"
}
```

**Collection: `command_history`**
```json
{
  "_id": "ObjectId",
  "session_id": "ObjectId",
  "timestamp": "datetime",
  "raw_transcript": "string",
  "intent": "string",
  "risk_band": "safe|caution|high-risk",
  "confirmed": "boolean",
  "action_taken": "string",
  "outcome": "success|failure|cancelled"
}
```

**Collection: `repo_embeddings`** (Vector Search index on `embedding`)
```json
{
  "_id": "ObjectId",
  "repo": "string",
  "file_path": "string",
  "symbol": "string",
  "chunk_text": "string",
  "embedding": "[float, ...]"
}
```

## API Contract

### WebSocket — `/ws/session`

**Client → Server messages**
```json
{"type": "audio_frame", "data": "<base64 PCM chunk>"}
{"type": "text_command", "text": "commit my changes"}
{"type": "confirm_response", "confirmed": true}
{"type": "interrupt"}
```

**Server → Client messages**
```json
{"type": "transcript", "text": "..."}
{"type": "earcon", "risk_band": "caution"}
{"type": "narration_audio", "data": "<base64 audio chunk>", "source": "filler|primary"}
{"type": "confirmation_request", "prompt": "..."}
{"type": "action_result", "status": "success|failure", "detail": "..."}
{"type": "braille_fragment", "text": "});"}
```

### REST
```
GET  /health
GET  /config          # non-secret client config (feature flags, mode)
POST /auth/token       # exchange for session-scoped token (PAT stored server-side)
```

## Auth
Phase 1: GitHub PAT stored via VS Code `SecretStorage`, passed to backend over an authenticated channel, never exposed in webview JS. Phase 2 (only if GitHub track rules require it or time allows): swap for GitHub OAuth/App without changing any other module — `github_tool.py`'s interface stays identical.

## Deployment
- Docker image for the FastAPI backend, deployed to DigitalOcean App Platform (Cloud Mode)
- Extension supports a Local Mode toggle pointing `ws-client.ts` at `localhost` instead, as a live fallback if venue wifi fails mid-demo — decide which mode to use *before* going on stage, not during
