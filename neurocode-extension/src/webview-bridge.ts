/**
 * neurocode-extension/src/webview-bridge.ts
 *
 * postMessage relay between the webview and ws-client.ts.
 *
 * Data flow (DESIGN.md):
 *   Webview → postMessage → this bridge → ws-client → WebSocket → backend
 *   Backend → WebSocket → ws-client → this bridge → postMessage → webview
 *
 * The webview NEVER talks to the network directly.
 */

import * as vscode from "vscode";
import { NeurocodeWsClient, BackendMessage } from "./ws-client";

export class WebviewBridge {
  private disposables: vscode.Disposable[] = [];

  constructor(
    private panel: vscode.WebviewPanel,
    private wsClient: NeurocodeWsClient
  ) {
    // --- Webview → Backend ---
    // Listen for postMessage from the webview and forward to ws-client
    const webviewListener = panel.webview.onDidReceiveMessage(
      (msg: { type: string; data?: string; text?: string; confirmed?: boolean }) => {
        if (msg.type === "audio_frame" && msg.data) {
          // Forward PCM audio frame to backend via extension-host WebSocket
          wsClient.sendAudioFrame(msg.data);
        } else if (msg.type === "text_command" && msg.text) {
          wsClient.sendTextCommand(msg.text);
        } else if (msg.type === "confirm_response") {
          wsClient.sendConfirmResponse(!!msg.confirmed);
        } else if (msg.type === "toggle_backend_mic") {
          wsClient.toggleBackendMic();
        }
      }
    );
    this.disposables.push(webviewListener);

    // --- Backend → Webview ---
    // Listen for messages from the backend and relay to webview
    const onBackendMessage = (msg: BackendMessage) => {
      // Wrap in a backend_message envelope so the webview can distinguish
      // backend responses from extension-host commands (start_mic, etc.)
      panel.webview.postMessage({
        type: "backend_message",
        payload: msg,
      });
    };
    wsClient.on("message", onBackendMessage);

    // Clean up the listener when disposed
    this.disposables.push(
      new vscode.Disposable(() => {
        wsClient.removeListener("message", onBackendMessage);
      })
    );
  }

  dispose(): void {
    for (const d of this.disposables) {
      d.dispose();
    }
    this.disposables = [];
  }
}
