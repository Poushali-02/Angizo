# Angizo Architecture Diagrams & System Topology

This document illustrates the complete system topology, agent workflow, component breakdown, and audio latency management for the **Angizo AI Accessibility Agent**, updated to match the verified implementation across the VS Code extension host and Python FastAPI backend.

---

## 1. End-to-End System Topology & OS Voice Data Flow

This diagram shows how native OS voice capture, WebSocket streaming, Sarvam AI STT, LangGraph state machine, Groq/Gemini LLM intelligence, local RAG/Git tools, and multi-tier TTS narration interact seamlessly across the stack.

```mermaid
graph TD
    subgraph "VS Code Webview UI (Chromium Sandbox)"
        UI["Side Panel UI (main.js)"] -- "1. Click 🎙️ Mic / Send Text" --> VEM["postMessage: toggle_backend_mic / text_command"]
        UI -- "Plays Spoken Audio Payload" --> AudioPlayer["HTML5 Audio Player (Base64 MP3)"]
        UI -- "Renders Confirmation Banner" --> ConfUI["Interactive [Yes] / [No] Buttons"]
    end

    subgraph "VS Code Extension Host (Node.js Environment)"
        VEM --> WBridge["webview-bridge.ts"]
        WBridge --> WSClient["ws-client.ts (AngizoWsClient)"]
        WSClient -- "Bi-directional WebSocket (ws://localhost:7001/ws/session)" --> WSAPI["api/ws.py (FastAPI Endpoint)"]
    end

    subgraph "FastAPI Backend Engine (Python 3.11+)"
        WSAPI -- "toggle_backend_mic" --> RecTask["record_backend_audio Task"]
        OSMic["Host OS Microphone"] -->|"16kHz 16-bit Mono PCM"| RecTask
        RecTask -- "PCM Audio Bytes" --> SarvamSTT["Sarvam AI STT (saarika:v2.5)"]
        SarvamSTT -- "Transcribed Text" --> Graph["LangGraph StateGraph Engine"]
        WSAPI -- "text_command" --> Graph

        subgraph "Local Workspace Intelligence"
            RAG["rag_engine.py (Codebase RAG)"]
            GitTools["git_tool.py (GitPython Wrapper)"]
        end

        Graph <--> RAG
        Graph <--> GitTools
    end

    subgraph "External AI Model Cloud APIs"
        Graph -- "Diff Risk & Intent Analysis" --> Groq["Groq LLM (llama-3.3-70b-versatile) / Gemini"]
        Graph -- "Primary Voice Narration" --> ElevenLabs["ElevenLabs TTS API (eleven_monolingual_v1)"]
        Graph -- "Instant Filler & Fallback Voice" --> SarvamTTS["Sarvam AI TTS API (bulbul:v2)"]
    end

    WSAPI -- "Instant Filler Audio (<200ms)" --> WSClient
    Graph -- "Final Audio Payload + Result" --> WSAPI
    WSClient -- "postMessage: action_result" --> WBridge
    WBridge --> AudioPlayer
```

---

## 2. Agent Core Loop (LangGraph 7-Node StateGraph Flow)

Angizo orchestrates complex operations through a deterministic 7-node LangGraph `StateGraph`. Safe actions proceed automatically; mutating actions pause at the `confirm` node for human-in-the-loop verification.

```mermaid
graph TD
    Start(("Incoming Command (Voice / Text)")) --> Node1["1. Context Node (context.py)<br/>• Fetches Git Status & Working Tree Diffs<br/>• Queries Codebase RAG Engine"]
    
    Node1 --> Node2["2. Understand Node (understand.py)<br/>• AI Planner dynamically selects atomic tool calls<br/>• Gemini LLM / Rule-Based Keyword Fallback"]
    
    Node2 --> Node3["3. Reason Node (reason.py)<br/>• Runs Diff Intelligence (diff_intelligence.py)<br/>• Evaluates Risk Band (safe / caution / high-risk)<br/>• Computes Blast Radius & Drafts Commit Message"]
    
    Node3 --> Node4["4. Confirm Node (confirm.py)<br/>• Checks if action mutates repository"]
    
    Node4 -- "Conditional Edge: should_confirm" --> Branch{"Confirmation Required?"}
    
    Branch -- "YES (Mutating: commit, push, pull, branch)" --> Pause["wait_for_user (State Interrupted)<br/>• Sends confirmation_request over WS<br/>• Webview renders [Yes]/[No] + Voice Prompt"]
    
    Pause -. "User Confirms: [Yes]" .-> Node5
    Pause -. "User Cancels: [No]" .-> Cancel(("Action Cancelled"))
    
    Branch -- "NO (Safe / Read-Only: status, review, rag query)" --> Node5["5. Execute Node (execute.py)<br/>• Iterates dynamic tool_calls plan<br/>• Executes atomic tools via registry.py"]
    
    Node5 --> Node6["6. Verify Node (verify.py)<br/>• Checks execution success/failure"]
    
    Node6 --> Node7["7. Narrate Node (narrate.py)<br/>• Converts result into Spoken Prose<br/>• Primary: Sarvam TTS (bulbul:v2)<br/>• Fallback: ElevenLabs (eleven_monolingual_v1)"]
    
    Node7 --> End(("Response Sent over WS + Audio Played"))
```

---

## 3. Full-Stack Class & Modular Component Breakdown

This diagram shows class relationships across the extension host TypeScript code and FastAPI Python backend.

```mermaid
classDiagram
    namespace VS_Code_Extension {
        class Extension {
            +activate(context)
            +deactivate()
        }
        class AngizoWsClient {
            -ws: WebSocket
            +connect()
            +send(message)
            +onMessage(callback)
        }
        class WebviewBridge {
            +handlePostMessage(msg)
            +sendToWebview(msg)
        }
        class WebviewPanel {
            +main.js
            +pcm-processor.js
            +HTML5 Audio Engine
        }
    }

    namespace FastAPI_Backend {
        class MainApp {
            +FastAPI App
            +/ws/session Endpoint
            +/health Endpoint
        }
        class WebSocketHandler {
            +session_states: dict
            +session_audio_buffers: dict
            +record_backend_audio()
            +run_agent_graph()
        }
        class AgentGraph {
            +StateGraph(AgentState)
            +build_graph()
            +ainvoke(state)
        }
        class AgentState {
            +transcript: str
            +intent: str
            +context: dict
            +reasoning: str
            +confirmation_required: bool
            +confirmed: bool
            +action_result: dict
            +verification_status: str
            +narration: str
            +earcon: str
        }
        class DiffIntelligence {
            +classify_intent()
            +classify_diff()
            +draft_commit_message()
            +generate_prose_review()
        }
        class RAGEngine {
            +index_workspace()
            +query_codebase()
        }
        class GitTool {
            +get_status()
            +get_diff()
            +commit()
            +push()
            +pull()
            +switch_branch()
        }
        class SarvamSTTClient {
            +transcribe_pcm_bytes()
        }
        class SarvamTTSClient {
            +generate_filler_audio_base64()
        }
        class ElevenLabsTTSClient {
            +generate_narration_audio_base64()
        }
    }

    Extension --> AngizoWsClient
    Extension --> WebviewBridge
    WebviewBridge --> WebviewPanel
    AngizoWsClient <..> WebSocketHandler : WebSocket Protocol

    MainApp --> WebSocketHandler
    WebSocketHandler --> SarvamSTTClient
    WebSocketHandler --> AgentGraph
    AgentGraph --> AgentState
    AgentGraph --> DiffIntelligence
    AgentGraph --> RAGEngine
    AgentGraph --> GitTool
    AgentGraph --> ElevenLabsTTSClient
    AgentGraph --> SarvamTTSClient
```

---

## 4. Zero-Silence Audio Handoff Sequence Diagram

To eliminate silent "dead air" for blind developers, Angizo streams instant filler audio while RAG and LLM processing execute in parallel.

```mermaid
sequenceDiagram
    autonumber
    participant UI as VS Code Webview (main.js)
    participant Ext as Extension Host (ws-client.ts)
    participant WS as FastAPI WS (ws.py)
    participant Mic as Native OS Mic (sounddevice)
    participant STT as Sarvam STT API
    participant TTS_Filler as Sarvam TTS API
    participant Graph as LangGraph Agent Loop
    participant LLM as Groq / Gemini LLM
    participant TTS_Main as ElevenLabs TTS API

    UI->>Ext: User speaks command / clicks Mic
    Ext->>WS: postMessage("toggle_backend_mic")
    WS->>Mic: Record 16kHz PCM audio bytes
    Mic-->>WS: PCM Audio Buffer
    WS->>STT: Send PCM Bytes (saarika:v2.5)
    STT-->>WS: Transcribed Text Transcript

    par Zero-Silence Filler Audio Generation (<200ms)
        WS->>TTS_Filler: Request filler audio ("Processing your request...")
        TTS_Filler-->>WS: Return base64 MP3 Audio
        WS->>Ext: Send audio_narration (channel: filler)
        Ext->>UI: Play Filler Audio in HTML5 Player
    and Agent Graph Execution (Parallel)
        WS->>Graph: Invoke agent_graph.ainvoke(state)
        Graph->>LLM: Classify Intent, Analyze Diff Risk & Blast Radius
        LLM-->>Graph: Return Intelligence Payload
        Graph->>TTS_Main: Generate Spoken Narration (eleven_monolingual_v1)
        TTS_Main-->>Graph: Return Primary Audio Payload (base64 MP3)
    end

    Graph-->>WS: Return Final Agent State
    WS->>Ext: Send action_result + primary audio_base64
    Ext->>UI: Replace Filler Audio with Primary Spoken Narration
```

---

## 5. Technology Stack Summary

| Layer / Subsystem | Primary Technology | Model / Library | Key Responsibility in Angizo    |
|---|---|---|---|
| **IDE Extension Host** | TypeScript / Node.js | `vscode` API v1.85+ | Extension lifecycle, window management, webview messaging bridge. |
| **Webview UI** | Vanilla HTML5 / JS | ARIA Live Regions, Web Audio | Accessible dark-mode UI, base64 audio player, recording indicator ring. |
| **Network Bridge** | WebSockets | `ws` (Node.js) / `WebSockets` | Bi-directional streaming connection (`ws://localhost:7001/ws/session`). |
| **Backend Engine** | Python 3.11+ | `FastAPI` + `uvicorn` | Async server, session state management, native OS mic background tasks. |
| **Host Audio Capture** | Native OS Mic API | `sounddevice` + `numpy` | Direct 16kHz Int16 PCM capture bypassing VS Code webview iframe permissions. |
| **Speech-to-Text (STT)** | Sarvam AI STT | `saarika:v2.5` (`en-IN`) | Transcribes technical developer voice commands into text. |
| **Agent Orchestration** | LangGraph | `langgraph` StateGraph | 7-node state machine (`Context` → `Understand` → `Reason` → `Confirm` → `Execute` → `Verify` → `Narrate`). |
| **Diff & Risk LLM** | Groq API / Gemini API | `llama-3.3-70b-versatile` | Diff risk classification (`safe`/`caution`/`high-risk`), conventional commit message drafting, prose review. |
| **Codebase Retrieval** | Custom Local RAG | Token-based TF-IDF | Zero-dependency local file indexing and semantic query retrieval. |
| **Git Operations** | GitPython | `git` binary wrapper | Local repository tracking, diff extraction, branch management, commit/push. |
| **Primary Narration TTS** | Sarvam AI TTS | `bulbul:v2` (`anushka`/`ratan`) | Primary spoken narration in narrate node; instant <200ms filler audio for Zero-Silence handoffs. |
| **Fallback Narration TTS** | ElevenLabs TTS | `eleven_monolingual_v1` | Risk-modulated fallback narration (stability & style parameters tuned by risk band). |
