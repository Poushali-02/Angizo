/**
 * angizo-extension/src/ws-client.ts
 *
 * WebSocket connection to the Angizo backend.
 *
 * CRITICAL CONSTRAINT (DESIGN.md + 01-architecture.md):
 *   This WebSocket lives in the extension host (Node.js process),
 *   NEVER in the webview. The webview is sandboxed with restrictive CSP
 *   and cannot reliably open remote WebSocket connections.
 *
 * Step 1 (voice input spike):
 *   - Connects to ws://localhost:8001/ws/session
 *   - Sends audio_frame messages (base64 PCM)
 *   - Receives action_result echoes from the backend stub
 */

import WebSocket from "ws";
import { EventEmitter } from "events";

export interface BackendMessage {
  type: string;
  [key: string]: unknown;
}

export class AngizoWsClient extends EventEmitter {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = true;
  private workspacePath: string | null = null;
  private messageQueue: Record<string, unknown>[] = [];

  constructor(url: string) {
    super();
    this.url = url;
    this.connect();
  }

  setWorkspacePath(path: string): void {
    this.workspacePath = path;
    console.log(`[ws-client] Workspace path set to: ${path}`);
    if (this.isConnected) {
      this.send({ type: "set_workspace", workspace_path: path });
    }
  }

  private connect(): void {
    console.log(`[ws-client] Connecting to ${this.url}`);

    this.ws = new WebSocket(this.url);

    this.ws.on("open", () => {
      console.log("[ws-client] Connected");
      this.emit("connected");

      // Send workspace path upon connection if set
      if (this.workspacePath) {
        this.ws?.send(JSON.stringify({ type: "set_workspace", workspace_path: this.workspacePath }));
      }

      // Flush queued messages
      while (this.messageQueue.length > 0) {
        const msg = this.messageQueue.shift();
        if (msg && this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify(msg));
        }
      }
    });

    this.ws.on("message", (data: WebSocket.Data) => {
      try {
        const msg: BackendMessage = JSON.parse(data.toString());
        this.emit("message", msg);
      } catch (err) {
        console.error("[ws-client] Failed to parse message:", err);
      }
    });

    this.ws.on("close", () => {
      console.log("[ws-client] Disconnected");
      this.emit("disconnected");
      this.scheduleReconnect();
    });

    this.ws.on("error", (err: Error) => {
      console.error("[ws-client] Error:", err.message);
      // close event will fire after this, triggering reconnect
    });
  }

  private scheduleReconnect(): void {
    if (!this.shouldReconnect) {
      return;
    }
    if (this.reconnectTimer) {
      return;
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      console.log("[ws-client] Reconnecting...");
      this.connect();
    }, 3000);
  }

  /**
   * Send a base64-encoded PCM audio frame to the backend.
   * Matches DESIGN.md API contract:
   *   {"type": "audio_frame", "data": "<base64 PCM chunk>"}
   */
  sendAudioFrame(base64Data: string): void {
    this.send({ type: "audio_frame", data: base64Data });
  }

  /**
   * Send a text command to the backend (Step 2+).
   */
  sendTextCommand(text: string): void {
    console.log(`[ws-client] Sending text command: ${text}`);
    this.send({ type: "text_command", text });
  }

  /**
   * Send a confirmation response to the backend (Step 2+).
   */
  sendConfirmResponse(confirmed: boolean): void {
    this.send({ type: "confirm_response", confirmed });
  }

  /**
   * Toggle backend OS microphone recording.
   */
  toggleBackendMic(): void {
    console.log("[ws-client] Toggling backend OS microphone");
    this.send({ type: "toggle_backend_mic" });
  }

  /**
   * Send a Copilot Observer milestone event to the backend.
   * The backend generates instant filler audio on start, and detailed
   * code explanation narration on completion via Groq + Sarvam TTS.
   */
  sendObserverEvent(event: {
    event_type: "copilot_start" | "copilot_complete" | "file_created" | "dependency_updated";
    file?: string;
    modified_files?: string[];
    created_files?: string[];
    lines_added?: number;
    lines_removed?: number;
    error_count?: number;
    warning_count?: number;
    code_snippet?: string;
    by_ai?: boolean;
  }): void {
    // No pop-up here: a screen reader would read every debug notification aloud
    console.log(`[ws-client] Sending observer event: ${event.event_type}`);
    this.send({ type: "copilot_observer_event", ...event });
  }


  /**
   * Send a Manual Coding Observer event (syntax error or runtime exception) to the backend.
   */
  sendManualObserverEvent(event: {
    event_type: "syntax_error" | "runtime_error";
    file: string;
    line?: number;
    column?: number;
    error_message?: string;
    is_resolved?: boolean;
    error_count?: number;
    error_name?: string;
    stack_trace?: string;
    is_summary?: boolean;
  }): void {
    console.log(`[ws-client] Sending manual observer event: ${event.event_type}`);
    this.send({ type: "manual_observer_event", ...event });
  }

  /**
   * Send an interrupt signal (Step 2+).
   */
  sendInterrupt(): void {
    this.send({ type: "interrupt" });
  }

  private send(msg: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      console.warn("[ws-client] Not connected, queueing message:", msg.type);
      this.messageQueue.push(msg);
    }
  }

  get isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  close(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }
}
