/**
 * angizo-extension/src/extension.ts
 *
 * VS Code extension activation and command registration.
 * Registers the Angizo sidebar view (right side, see angizo-view.ts) and wires up the bridge.
 *
 * Architecture (DESIGN.md / 01-architecture.md):
 *   - Webview captures audio via AudioWorklet → postMessage → extension host
 *   - Extension host owns the WebSocket to the backend
 *   - Webview NEVER opens a WebSocket directly
 */

import * as vscode from "vscode";
import * as path from "path";
import { AngizoWsClient } from "./ws-client";
import { WebviewBridge } from "./webview-bridge";
import { AngizoView } from "./angizo-view";
import { CopilotWatcher, CopilotObserverEvent } from "./observer/copilot-watcher";
import { ManualWatcher, ManualSyntaxErrorEvent } from "./observer/manual-watcher";
import { TerminalWatcher, TerminalRuntimeErrorEvent } from "./observer/terminal-watcher";
import { ObserverEarcon } from "./observer/observer-earcon";
import { ObserverStatusBar } from "./observer/observer-status-bar";
import { ObserverHud } from "./observer/observer-hud";

let view: AngizoView | undefined;
let wsClient: AngizoWsClient | undefined;
let bridge: WebviewBridge | undefined;

// --- Copilot Observer modules (live for the full extension lifetime) ---
let copilotWatcher: CopilotWatcher | undefined;
let manualWatcher: ManualWatcher | undefined;
let terminalWatcher: TerminalWatcher | undefined;
let observerEarcon: ObserverEarcon | undefined;
let observerStatusBar: ObserverStatusBar | undefined;
let observerHud: ObserverHud | undefined;

/** What activate() returns; the end-to-end test reads it. */
export interface AngizoApi {
  readonly viewReady: boolean;
}

export function activate(context: vscode.ExtensionContext): AngizoApi {
  console.log("Angizo extension activating");
  vscode.window.showInformationMessage("Angizo is listening.");

  // Create persistent WebSocket client immediately on extension startup
  // Backend port: ANGIZO_WS_PORT (used by the end-to-end tests), then the angizo setting, then 7001
  const wsPort =
    process.env.ANGIZO_WS_PORT ||
    String(vscode.workspace.getConfiguration("angizo").get<number>("backendPort", 7001));
  wsClient = new AngizoWsClient(`ws://localhost:${wsPort}/ws/session`);
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (workspaceFolders && workspaceFolders.length > 0) {
    wsClient.setWorkspacePath(workspaceFolders[0].uri.fsPath);
  }

  // The panel lives in the right sidebar, not in an editor tab. It never pops open or takes
  // focus by itself: messages wait until the view is ready (it is created once at startup).
  const angizoView = new AngizoView(
    (webview) => getWebviewContent(webview, context),
    [
      vscode.Uri.file(path.join(context.extensionPath, "src", "webview")),
      vscode.Uri.file(path.join(context.extensionPath, "out", "webview")),
    ]
  );
  view = angizoView;
  context.subscriptions.push(
    angizoView,
    vscode.window.registerWebviewViewProvider(AngizoView.viewId, angizoView, {
      webviewOptions: { retainContextWhenHidden: true },
    })
  );
  bridge = new WebviewBridge(angizoView, wsClient);
  observerEarcon = new ObserverEarcon(angizoView);
  // Audio plays in the webview, so create it now (focus goes straight back to the editor).
  setTimeout(() => void angizoView.ensureResolved(), 500);

  /** Push-to-talk: start listening, or stop and send what was said. Also cuts off any speech. */
  let micOn = false;
  wsClient.on("message", (msg: { type?: string; state?: string }) => {
    if (msg && msg.type === "mic_status") micOn = msg.state === "recording";
  });
  function toggleMic(): void {
    if (!wsClient || !wsClient.isConnected) {
      angizoView.postMessage({ type: "speak_text", text: "Angizo's backend is not running." });
      return;
    }
    angizoView.postMessage({ type: "stop_speech" });
    angizoView.postMessage({ type: "mic_toggled", listening: !micOn });
    wsClient.toggleBackendMic();
  }
  context.subscriptions.push(vscode.commands.registerCommand("angizo.toggleMic", toggleMic));

  context.subscriptions.push(
    vscode.commands.registerCommand("angizo.showPanel", () => angizoView.reveal(false))
  );

  // --- Start Voice Input command ---
  const startCmd = vscode.commands.registerCommand(
    "angizo.startVoiceInput",
    () => {
      void angizoView.reveal(true);
      if (!micOn) toggleMic();
    }
  );

  // --- Run a Command: type a request without the panel's text box ---
  // From the Command Palette it asks in an input box (screen-reader friendly); scripts and
  // the demo pass the text directly: executeCommand("angizo.runCommand", "review my diff").
  const runCommandCmd = vscode.commands.registerCommand(
    "angizo.runCommand",
    async (text?: string) => {
      const command =
        typeof text === "string" && text.trim()
          ? text.trim()
          : (await vscode.window.showInputBox({
              prompt: "What should Angizo do?",
              placeHolder: "e.g. review my diff, commit my changes, push my branch",
            }))?.trim();
      if (!command) return;
      angizoView.postMessage({ type: "stop_speech" });
      angizoView.postMessage({ type: "command_sent", text: command });
      wsClient?.sendTextCommand(command);
    }
  );
  context.subscriptions.push(runCommandCmd);

  // --- Stop Voice Input command ---
  const stopCmd = vscode.commands.registerCommand(
    "angizo.stopVoiceInput",
    () => {
      wsClient?.stopBackendMic();
    }
  );

  // --- Confirm Action command ---
  const confirmCmd = vscode.commands.registerCommand(
    "angizo.confirm",
    () => {
      if (wsClient && wsClient.isConnected) {
        wsClient.sendConfirmResponse(true);
        vscode.window.showInformationMessage("Angizo: Action confirmed");
      } else {
        vscode.window.showWarningMessage("Angizo: WebSocket is not connected");
      }
    }
  );

  // --- Cancel Action command ---
  const cancelCmd = vscode.commands.registerCommand(
    "angizo.cancel",
    () => {
      if (wsClient && wsClient.isConnected) {
        wsClient.sendConfirmResponse(false);
        vscode.window.showInformationMessage("Angizo: Action cancelled");
      } else {
        vscode.window.showWarningMessage("Angizo: WebSocket is not connected");
      }
    }
  );

  // --- Toggle Manual Coding Stream command ---
  const toggleManualStreamCmd = vscode.commands.registerCommand(
    "angizo.toggleManualStream",
    () => {
      if (manualWatcher) {
        const newState = !manualWatcher.isEnabled();
        manualWatcher.setEnabled(newState);
        terminalWatcher?.setEnabled(newState);
        vscode.window.showInformationMessage(
          `Angizo: Manual Coding Stream ${newState ? "ENABLED ⚡" : "DISABLED ⏸️"}`
        );
      }
    }
  );

  context.subscriptions.push(startCmd, stopCmd, confirmCmd, cancelCmd, toggleManualStreamCmd);

  // ─── Copilot Observer ────────────────────────────────────────────────────
  // Observer starts watching immediately (does not require the webview panel)
  observerStatusBar = new ObserverStatusBar();
  observerHud = new ObserverHud();

  // ─── Manual Coding Streamer & Error Interceptors ─────────────────────────
  manualWatcher = new ManualWatcher((event: ManualSyntaxErrorEvent) => {
    const currentPanel = angizoView;
    if (event.isResolved) {
      observerEarcon?.play("complete", currentPanel);
      observerStatusBar?.setComplete(0, 0, event.file, "Manual");
      observerHud?.clearInlineError();
      observerHud?.show(`Angizo: Syntax error resolved in ${event.file}`);
      observerHud?.scheduleHide();
    } else {
      observerEarcon?.play("error", currentPanel);
      observerStatusBar?.setError(event.errorCount, "Manual");
      observerHud?.showInlineError(event.line);
      observerHud?.show(`Angizo extension found error: Syntax error detected in ${event.file}`);
    }
  }, wsClient);
  manualWatcher.activate(context);

  terminalWatcher = new TerminalWatcher((event: TerminalRuntimeErrorEvent) => {
    const currentPanel = angizoView;
    observerEarcon?.play("error", currentPanel);
    observerStatusBar?.setError(1, "Runtime");
    observerHud?.show(`Angizo Intercept: Runtime ${event.errorName} in ${event.file}`);
  }, wsClient);
  terminalWatcher.activate(context);

  /** Routes CopilotObserverEvents to earcon, HUD, status bar, and webview */
  function handleObserverEvent(event: CopilotObserverEvent): void {
    const currentPanel = angizoView;

    switch (event.type) {
      case "copilot_start": {
        const shortName = event.file ? event.file.split(/[\\/]/).pop() : "file";
        observerEarcon?.play("start", currentPanel);
        observerEarcon?.startTick(currentPanel);
        observerStatusBar?.setGenerating(event.file || "unknown file");
        observerHud?.show(`Angizo Observer: Copilot generating in ${event.file}... `);
        currentPanel.postMessage({
          type: "observer_status",
          state: "generating",
          file: event.file,
        });
        break;
      }
      case "copilot_complete": {
        const lines = event.linesAdded ?? 0;
        observerEarcon?.stopTick();
        observerEarcon?.play("complete", currentPanel);
        observerStatusBar?.setComplete(
          lines,
          event.errorCount ?? 0,
          event.file ?? "unknown"
        );
        observerHud?.show(
          `Angizo Observer: Copilot done — ${lines} lines added`
        );
        observerHud?.scheduleHide();
        currentPanel.postMessage({
          type: "observer_status",
          state: "complete",
          linesAdded: lines,
          file: event.file,
        });
        break;
      }
      case "file_created": {
        observerEarcon?.play("start", currentPanel);
        observerStatusBar?.setGenerating(`New file: ${event.file}`);
        observerHud?.show(
          event.byAi ? `Angizo Observer: Copilot created ${event.file}` : `Angizo Observer: New file ${event.file}`
        );
        observerHud?.scheduleHide();
        currentPanel.postMessage({
          type: "observer_status",
          state: "file_created",
          file: event.file,
        });
        break;
      }
      case "dependency_updated": {
        observerEarcon?.play("tick", currentPanel);
        observerStatusBar?.setGenerating(`Dependency updated: ${event.dependencyFile}`);
        observerHud?.show(`Angizo Observer: Dependency file updated — ${event.dependencyFile}`);
        observerHud?.scheduleHide();
        break;
      }
      case "diagnostic_result": {
        if ((event.errorCount ?? 0) > 0) {
          observerEarcon?.play("error", currentPanel);
          observerStatusBar?.setError(event.errorCount ?? 0);
        } else {
          observerStatusBar?.setComplete(0, 0, event.file ?? "");
        }
        break;
      }
    }
  }

  copilotWatcher = new CopilotWatcher(handleObserverEvent, wsClient);
  copilotWatcher.activate(context);

  // --- Toggle Observer command ---
  const toggleObserverCmd = vscode.commands.registerCommand(
    "angizo.toggleObserver",
    () => {
      if (!copilotWatcher || !observerEarcon || !observerStatusBar) return;
      const nowMuted = !copilotWatcher.isMuted();
      copilotWatcher.setMuted(nowMuted);
      observerEarcon.setMuted(nowMuted);
      if (nowMuted) {
        observerStatusBar.setMuted();
        observerHud?.hide();
        vscode.window.showInformationMessage("Angizo Observer: Muted");
      } else {
        observerStatusBar.setIdle();
        vscode.window.showInformationMessage("Angizo Observer: Active");
      }
    }
  );

  // --- Announce Observer Status command (Screen Reader Hotkey Ctrl+Shift+S) ---
  const announceStatusCmd = vscode.commands.registerCommand(
    "angizo.announceStatus",
    () => {
      if (!observerStatusBar) return;
      const label = observerStatusBar.getAccessibleLabel();
      vscode.window.showInformationMessage(`Angizo: ${label}`);
      angizoView.postMessage({ type: "speak_text", text: label });
    }
  );

  context.subscriptions.push(toggleObserverCmd, announceStatusCmd);

  // Guard .env file access for screen-reader (blind/low-vision) users
  function checkEnvAccess(editor: vscode.TextEditor | undefined) {
    if (editor && editor.document) {
      const fileName = editor.document.fileName;
      if (fileName.endsWith(".env") || fileName.split(/[\\/]/).pop() === ".env") {
        const config = vscode.workspace.getConfiguration("angizo");
        const simulateBlindMode = config.get<boolean>("simulateBlindMode", false);
        const isScreenReaderActive = simulateBlindMode || (vscode.env as any).accessibilitySupport === 3;
        if (isScreenReaderActive) {
          angizoView.postMessage({
            type: "speak_text",
            text: "Warning: You are trying to access a dot env file containing sensitive credentials. Do you want to open it? Press Alt+Y to confirm or Alt+N to reject.",
          });
          vscode.window.showWarningMessage(
            "Warning: You are trying to access a .env file containing sensitive credentials. Do you want to open it? Press Alt+Y to confirm or Alt+N to reject.",
            "Yes",
            "No"
          ).then(selection => {
            if (selection !== "Yes") {
              vscode.commands.executeCommand("workbench.action.closeActiveEditor");
            }
          });
        }
      }
    }
  }

  const editorListener = vscode.window.onDidChangeActiveTextEditor(editor => {
    checkEnvAccess(editor);
  });
  context.subscriptions.push(editorListener);
  checkEnvAccess(vscode.window.activeTextEditor);

  context.subscriptions.push(observerStatusBar, observerHud);

  return {
    get viewReady() {
      return angizoView.isReady;
    },
  };
}

export function deactivate() {
  wsClient?.close();
  bridge?.dispose();
  view?.dispose();
  copilotWatcher?.dispose();
  observerEarcon?.dispose();
  observerStatusBar?.dispose();
  observerHud?.dispose();
}

/**
 * Generates the webview HTML content with proper CSP and nonces.
 *
 * CSP allows:
 *   - Scripts from the webview's own origin (nonce-gated)
 *   - blob: URIs for AudioWorklet module loading
 *   - Media (microphone) capture
 */
function getWebviewContent(
  webview: vscode.Webview,
  context: vscode.ExtensionContext
): string {
  const nonce = getNonce();

  // URI for the pcm-processor.js AudioWorklet module
  const processorUri = webview.asWebviewUri(
    vscode.Uri.file(
      path.join(context.extensionPath, "src", "webview", "pcm-processor.js")
    )
  );

  // URI for the main webview client script
  const mainScriptUri = webview.asWebviewUri(
    vscode.Uri.file(
      path.join(context.extensionPath, "src", "webview", "main.js")
    )
  );

  return /* html */ `<!DOCTYPE html>

<html lang="en">

<head>

  <meta charset="UTF-8">

  <meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
  >

  <meta
    http-equiv="Content-Security-Policy"
    content="
      default-src 'none';

      script-src
        'nonce-${nonce}'
        ${webview.cspSource}
        'unsafe-eval';

      style-src
        ${webview.cspSource}
        'unsafe-inline'
        https://fonts.googleapis.com;

      img-src
        ${webview.cspSource}
        https:
        data:;

      font-src
        ${webview.cspSource}
        https://fonts.gstatic.com;

      media-src
        *
        blob:
        data:;

      worker-src
        blob:
        ${webview.cspSource};
    "
  >

  <title>Angizo AI Assistant</title>

  <link
    rel="preconnect"
    href="https://fonts.googleapis.com"
  >

  <link
    rel="preconnect"
    href="https://fonts.googleapis.com"
    crossorigin
  >

  <link
    href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap"
    rel="stylesheet"
  >

  <style>

    /* =====================================
       ROOT
    ===================================== */

    :root {

      --nc-accent-indigo: #6366f1;

      --nc-accent-purple: #8b5cf6;

      --nc-accent-emerald: #10b981;

      --nc-font-ui:
        'Plus Jakarta Sans',
        var(--vscode-font-family),
        -apple-system,
        BlinkMacSystemFont,
        'Segoe UI',
        Roboto,
        sans-serif;

      --nc-font-mono:
        'JetBrains Mono',
        var(--vscode-editor-font-family),
        'Fira Code',
        Consolas,
        monospace;
    }

    /* =====================================
       RESET
    ===================================== */

    * {

      box-sizing: border-box;

      margin: 0;

      padding: 0;
    }

    /* =====================================
       BODY
    ===================================== */

    body {

      margin: 0;

      padding: 0;

      height: 100vh;

      overflow: hidden;

      background:
        var(
          --vscode-sideBar-background,
          #0f172a
        );

      color:
        var(
          --vscode-foreground,
          #e2e8f0
        );

      font-family: var(--nc-font-ui);

      font-size: 13px;

      line-height: 1.5;

      -webkit-font-smoothing: antialiased;
    }

    /* =====================================
       APP
    ===================================== */

    .app {

      height: 100vh;

      display: flex;

      flex-direction: column;

      background:
        radial-gradient(
          circle at 50% 0%,
          rgba(99, 102, 241, 0.08) 0%,
          transparent 65%
        );
    }

    /* =====================================
       HEADER
    ===================================== */

    .header {

      height: 54px;

      display: flex;

      align-items: center;

      justify-content: space-between;

      padding: 0 16px;

      border-bottom:
        1px solid
        var(
          --vscode-panel-border,
          rgba(255, 255, 255, 0.08)
        );

      background:
        var(
          --vscode-editor-background,
          rgba(15, 23, 42, 0.85)
        );

      backdrop-filter: blur(12px);

      position: relative;

      z-index: 10;
    }

    .brand {

      display: flex;

      align-items: center;

      gap: 10px;
    }

    .logo-badge {

      width: 32px;

      height: 32px;

      display: flex;

      align-items: center;

      justify-content: center;

      border-radius: 8px;

      background:
        linear-gradient(
          135deg,
          #6366f1 0%,
          #8b5cf6 100%
        );

      color: #ffffff;

      box-shadow:
        0 0 12px
        rgba(99, 102, 241, 0.4);
    }

    .logo-badge svg {

      width: 18px;

      height: 18px;

      fill: currentColor;
    }

    .brand-info {

      display: flex;

      flex-direction: column;
    }

    .brand-title-row {

      display: flex;

      align-items: center;

      gap: 6px;
    }

    .brand-name {

      font-size: 13px;

      font-weight: 700;

      letter-spacing: -0.2px;

      background:
        linear-gradient(
          135deg,
          #ffffff 0%,
          #cbd5e1 100%
        );

      -webkit-background-clip: text;

      -webkit-text-fill-color: transparent;
    }

    .brand-subtitle {

      font-size: 10px;

      color:
        var(
          --vscode-descriptionForeground,
          #94a3b8
        );

      font-weight: 500;
    }

    /* =====================================
       CONNECTION
    ===================================== */

    .connection {

      display: flex;

      align-items: center;

      gap: 6px;

      padding: 4px 10px;

      border-radius: 20px;

      background:
        rgba(16, 185, 129, 0.1);

      border:
        1px solid
        rgba(16, 185, 129, 0.25);

      color: #34d399;

      font-size: 10px;

      font-weight: 600;
    }

    .connection-dot {

      width: 6px;

      height: 6px;

      border-radius: 50%;

      background: #10b981;

      box-shadow:
        0 0 8px #10b981;

      animation:
        pulse-dot
        2s
        infinite
        ease-in-out;
    }

    @keyframes pulse-dot {

      0%,
      100% {

        opacity: 1;

        transform: scale(1);
      }

      50% {

        opacity: 0.4;

        transform: scale(0.85);
      }
    }

    /* =====================================
       MAIN
    ===================================== */

    .main {

      flex: 1;

      min-height: 0;

      display: flex;

      flex-direction: column;

      gap: 14px;

      padding: 14px 16px;
    }

    /* =====================================
       SECTION HEADER
    ===================================== */

    .section-header {

      display: flex;

      align-items: center;

      justify-content: space-between;

      margin-bottom: 6px;
    }

    .section-title {

      color:
        var(
          --vscode-descriptionForeground,
          #94a3b8
        );

      font-size: 10px;

      font-weight: 700;

      letter-spacing: 0.8px;

      text-transform: uppercase;

      display: flex;

      align-items: center;

      gap: 6px;
    }

    .section-title svg {

      width: 12px;

      height: 12px;

      fill: currentColor;

      opacity: 0.7;
    }

    /* =====================================
       VOICE CARD
    ===================================== */

    .voice-card {

      padding: 14px 16px;

      border:
        1px solid
        var(
          --vscode-panel-border,
          rgba(255, 255, 255, 0.08)
        );

      border-radius: 10px;

      background:
        var(
          --vscode-editor-background,
          rgba(30, 41, 59, 0.5)
        );

      backdrop-filter: blur(8px);

      box-shadow:
        0 4px 20px
        rgba(0, 0, 0, 0.15);
    }

    .voice-row {

      display: flex;

      align-items: center;

      justify-content: space-between;

      gap: 12px;
    }

    .voice-info {

      display: flex;

      align-items: center;

      gap: 12px;
    }

    /* =====================================
       MICROPHONE
    ===================================== */

    .mic-btn {

      width: 44px;

      height: 44px;

      display: flex;

      align-items: center;

      justify-content: center;

      border:
        1px solid
        rgba(99, 102, 241, 0.3);

      border-radius: 10px;

      background:
        linear-gradient(
          135deg,
          rgba(99, 102, 241, 0.15),
          rgba(139, 92, 246, 0.15)
        );

      color: #a5b4fc;

      cursor: pointer;

      font-size: 18px;

      outline: none;
    }

    .mic-btn:hover {

      border-color: #6366f1;

      color: #ffffff;
    }

    .mic-btn.recording {

      background:
        linear-gradient(
          135deg,
          #ef4444,
          #dc2626
        ) !important;

      color: #ffffff !important;

      animation:
        pulse-ring
        1.5s
        infinite
        ease-in-out;
    }

    @keyframes pulse-ring {

      0% {

        box-shadow:
          0 0 0 0
          rgba(239, 68, 68, 0.6);
      }

      70% {

        box-shadow:
          0 0 0 12px
          rgba(239, 68, 68, 0);
      }

      100% {

        box-shadow:
          0 0 0 0
          rgba(239, 68, 68, 0);
      }
    }

    .voice-text {

      display: flex;

      flex-direction: column;

      gap: 2px;
    }

    .voice-title {

      font-size: 13px;

      font-weight: 600;

      color:
        var(
          --vscode-foreground,
          #f1f5f9
        );
    }

    .voice-description {

      color:
        var(
          --vscode-descriptionForeground,
          #94a3b8
        );

      font-size: 11px;
    }

    /* =====================================
       AUDIO CONTROL AREA
    ===================================== */

    .audio-controls {

      display: flex;

      align-items: center;

      gap: 6px;
    }

    .audio-btn {

      display: none;

      align-items: center;

      justify-content: center;

      min-width: 64px;

      height: 28px;

      padding: 0 10px;

      border-radius: 6px;

      border:
        1px solid
        rgba(255, 255, 255, 0.1);

      background:
        rgba(255, 255, 255, 0.05);

      color:
        var(
          --vscode-foreground,
          #cbd5e1
        );

      font-size: 10px;

      font-weight: 600;

      cursor: pointer;

      transition: all 0.2s ease;
    }

    .audio-btn:hover {

      background:
        rgba(99, 102, 241, 0.2);

      border-color:
        rgba(99, 102, 241, 0.5);
    }

    .audio-btn.visible {
      display: inline-flex;
    }

    #pauseAudioBtn {
      background: rgba(245, 158, 11, 0.12);
      color: #fbbf24;
      border-color: rgba(245, 158, 11, 0.3);
    }

    #pauseAudioBtn:hover {
      background: rgba(245, 158, 11, 0.25);
      border-color: rgba(245, 158, 11, 0.5);
    }

    #resumeAudioBtn {
      background: rgba(16, 185, 129, 0.12);
      color: #34d399;
      border-color: rgba(16, 185, 129, 0.3);
    }

    #resumeAudioBtn:hover {
      background: rgba(16, 185, 129, 0.25);
      border-color: rgba(16, 185, 129, 0.5);
    }

    #stopAudioBtn {
      background: rgba(239, 68, 68, 0.12);
      color: #f87171;
      border-color: rgba(239, 68, 68, 0.3);
    }

    #stopAudioBtn:hover {
      background: rgba(239, 68, 68, 0.25);
      border-color: rgba(239, 68, 68, 0.5);
    }

    /* =====================================
       AUDIO PULSE
    ===================================== */

    .audio-pulse {
      display: none;
      align-items: center;
      gap: 3px;
      height: 26px;
      padding: 0 8px;
      border-radius: 6px;
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      box-shadow: 0 0 10px rgba(16, 185, 129, 0.15);
    }

    .audio-pulse.active {
      display: flex;
    }

    .audio-pulse span {
      width: 3px;
      height: 8px;
      border-radius: 3px;
      background: #34d399;
      box-shadow: 0 0 4px #34d399;
      animation:
        audio-wave
        0.7s
        infinite
        ease-in-out;
    }

    .audio-pulse span:nth-child(2) {

      animation-delay: 0.15s;
    }

    .audio-pulse span:nth-child(3) {

      animation-delay: 0.3s;
    }

    .audio-pulse span:nth-child(4) {

      animation-delay: 0.45s;
    }

    .audio-pulse span:nth-child(5) {

      animation-delay: 0.6s;
    }

    @keyframes audio-wave {

      0%,
      100% {

        height: 6px;

        opacity: 0.5;
      }

      50% {

        height: 18px;

        opacity: 1;
      }
    }

    /* =====================================
       STATUS
    ===================================== */

    #status {

      padding: 4px 10px;

      border-radius: 6px;

      background:
        var(
          --vscode-badge-background,
          rgba(255, 255, 255, 0.06)
        );

      color:
        var(
          --vscode-badge-foreground,
          #cbd5e1
        );

      font-size: 10px;

      font-weight: 600;

      border:
        1px solid
        var(
          --vscode-panel-border,
          rgba(255, 255, 255, 0.05)
        );
    }

    #status.listening {

      background:
        rgba(16, 185, 129, 0.15);

      color: #34d399;

      border-color:
        rgba(16, 185, 129, 0.3);
    }

    /* =====================================
       COMMAND PALETTE
    ===================================== */

    .command-section {

      display: flex;

      flex-direction: column;

      gap: 8px;
    }

    .input-row {

      display: flex;

      gap: 8px;
    }

    .input-wrapper {

      flex: 1;

      position: relative;

      display: flex;

      align-items: center;
    }

    .input-prefix {

      position: absolute;

      left: 10px;

      color:
        var(
          --vscode-descriptionForeground,
          #64748b
        );

      pointer-events: none;

      font-family: var(--nc-font-mono);

      font-size: 12px;
    }

    #textInput {

      width: 100%;

      padding:
        9px
        12px
        9px
        26px;

      border:
        1px solid
        var(
          --vscode-input-border,
          rgba(255, 255, 255, 0.1)
        );

      border-radius: 8px;

      outline: none;

      background:
        var(
          --vscode-input-background,
          rgba(15, 23, 42, 0.6)
        );

      color:
        var(
          --vscode-input-foreground,
          #f8fafc
        );

      font-family: var(--nc-font-mono);

      font-size: 12px;
    }

    #textInput:focus {

      border-color:
        var(
          --vscode-focusBorder,
          #6366f1
        );

      box-shadow:
        0 0 0 2px
        rgba(99, 102, 241, 0.2);
    }

    #sendBtn {

      padding: 0 16px;

      border: none;

      border-radius: 8px;

      background:
        linear-gradient(
          135deg,
          #6366f1,
          #4f46e5
        );

      color: #ffffff;

      cursor: pointer;

      font-size: 12px;

      font-weight: 600;
    }

    /* =====================================
       CONFIRMATION
    ===================================== */

    #confirmArea {

      display: none;

      padding: 12px 14px;

      border:
        1px solid
        rgba(245, 158, 11, 0.4);

      border-radius: 8px;

      background:
        rgba(245, 158, 11, 0.08);
    }

    .confirm-header {

      margin-bottom: 6px;

      font-weight: 700;

      font-size: 11px;

      color: #fbbf24;
    }

    #confirmPrompt {

      margin-bottom: 10px;

      font-size: 12px;
    }

    .confirm-buttons {

      display: flex;

      gap: 8px;
    }

    .confirm-buttons button {

      padding: 6px 14px;

      border: none;

      border-radius: 6px;

      cursor: pointer;

      font-size: 11px;

      font-weight: 600;
    }

    #yesBtn {

      background: #10b981;

      color: #ffffff;
    }

    #noBtn {

      background:
        rgba(255, 255, 255, 0.1);

      color:
        var(
          --vscode-foreground,
          #e2e8f0
        );
    }

    /* =====================================
       ACTIVITY FEED
    ===================================== */

    .activity {

      flex: 1;

      min-height: 0;

      display: flex;

      flex-direction: column;

      gap: 6px;
    }

    .live {

      color: #38bdf8;

      font-size: 9px;

      font-weight: 700;

      letter-spacing: 0.8px;

      padding: 2px 6px;

      border-radius: 4px;

      background:
        rgba(56, 189, 248, 0.1);

      border:
        1px solid
        rgba(56, 189, 248, 0.2);
    }

    .feed-container {

      flex: 1;

      min-height: 0;

      overflow-y: auto;

      display: flex;

      flex-direction: column;

      gap: 8px;

      padding: 10px;

      border:
        1px solid
        var(
          --vscode-panel-border,
          rgba(255, 255, 255, 0.08)
        );

      border-radius: 8px;

      background:
        var(
          --vscode-terminal-background,
          rgba(15, 23, 42, 0.7)
        );

      font-family: var(--nc-font-mono);

      font-size: 11px;
    }

    .feed-item {

      display: flex;

      flex-direction: column;

      gap: 4px;

      padding: 8px 10px;

      border-left:
        3px solid
        rgba(255, 255, 255, 0.2);

      border-radius: 0;

      background: transparent;

      animation:
        fadeIn
        0.15s
        ease-out;
    }

    .feed-item:hover {

      background: transparent;
    }

    .feed-item.user {

      border-left-color: #6366f1;

      background: transparent;
    }

    .feed-item.assistant {

      border-left-color: #10b981;

      background: transparent;
    }

    .feed-item.system {

      border-left-color: #8b5cf6;

      background: transparent;
    }

    .feed-header-row {

      display: flex;

      align-items: center;

      justify-content: space-between;

      gap: 6px;
    }

    .feed-tag {

      font-size: 9px;

      font-weight: 700;

      letter-spacing: 0.5px;

      padding: 2px 6px;

      border-radius: 4px;

      text-transform: uppercase;
    }

    .tag-user {

      background:
        rgba(99, 102, 241, 0.2);

      color: #818cf8;
    }

    .tag-assistant {

      background:
        rgba(16, 185, 129, 0.2);

      color: #34d399;
    }

    .tag-system {

      background:
        rgba(139, 92, 246, 0.2);

      color: #c084fc;
    }

    .feed-time {

      color:
        var(
          --vscode-descriptionForeground,
          #64748b
        );

      font-size: 9px;
    }

    .feed-body {

      white-space: pre-wrap;

      word-break: break-word;

      color:
        var(
          --vscode-terminal-foreground,
          #cbd5e1
        );
    }

    /* =====================================
       FOOTER
    ===================================== */

    .footer {

      height: 30px;

      display: flex;

      align-items: center;

      justify-content: space-between;

      padding: 0 14px;

      border-top:
        1px solid
        var(
          --vscode-panel-border,
          rgba(255, 255, 255, 0.08)
        );

      background:
        var(
          --vscode-editor-background,
          rgba(15, 23, 42, 0.9)
        );

      color:
        var(
          --vscode-descriptionForeground,
          #64748b
        );

      font-size: 10px;
    }

    .footer-item {

      display: flex;

      align-items: center;

      gap: 5px;
    }

    .footer-dot {

      width: 5px;

      height: 5px;

      border-radius: 50%;

      background: #6366f1;
    }

    /* ================= OBSERVER STRIP ================= */

    .observer-strip {
      display: none;
      align-items: center;
      gap: 8px;
      padding: 7px 12px;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 600;
      transition: background 0.2s ease;
    }

    .observer-strip.generating {
      background: rgba(0, 255, 255, 0.08);
      border: 1px solid rgba(0, 255, 255, 0.3);
      color: #00FFFF;
    }

    .observer-strip.complete {
      background: rgba(46, 160, 67, 0.1);
      border: 1px solid rgba(46, 160, 67, 0.35);
      color: #3fb950;
    }

    .observer-strip.file {
      background: rgba(56, 139, 253, 0.08);
      border: 1px solid rgba(56, 139, 253, 0.3);
      color: #58a6ff;
    }

    .observer-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: currentColor;
      flex-shrink: 0;
      animation: pulse 1.2s infinite;
    }

    .observer-strip.complete .observer-dot,
    .observer-strip.file .observer-dot {
      animation: none;
    }
    /* =====================================
       ANIMATION
    ===================================== */

    @keyframes fadeIn {

      from {

        opacity: 0;

        transform: translateY(3px);
      }

      to {

        opacity: 1;

        transform: translateY(0);
      }
    }

    /* ===== The cat: shows what Angizo is doing. Decorative only (aria-hidden);
       every state is also spoken or played as an earcon. Same pose in every state:
       only the face, ears, paw, tail and the extras change. ===== */
    .cat-stage {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 8px 0 2px;
    }
    .cat { width: 160px; height: 147px; overflow: visible; }
    @media (max-height: 640px) { .cat { width: 112px; height: 103px; } .cat-stage { padding-top: 4px; } }
    .cat * { transform-box: view-box; }
    .cat .ink { fill: none; stroke: var(--vscode-foreground, #ccc); stroke-width: 3.2; stroke-linecap: round; stroke-linejoin: round; }
    .cat .ink-fill { fill: var(--vscode-foreground, #ccc); }
    .cat .bubble { fill: var(--vscode-sideBar-background, #fff); stroke: var(--vscode-foreground, #ccc); stroke-width: 3.2; }
    .cat text { font-family: var(--vscode-font-family, "Segoe UI", sans-serif); font-weight: 800; }
    .cat .z1 { font-size: 18px; } .cat .z2 { font-size: 13px; }
    .cat .qmark { font-size: 20px; } .cat .bang { font-size: 40px; font-weight: 900; }
    .cat .purr { font-size: 12px; font-weight: 400; fill: var(--vscode-descriptionForeground, #999); }
    .cat .term text { font-family: Consolas, "Courier New", monospace; font-size: 12.5px; font-weight: 700; fill: #e6e6e6; }
    .cat .term .t-error { fill: #ff8a80; }

    /* Hidden unless a state shows them */
    .cat .tail-up, .cat .ears-down, .cat .eyes-open, .cat .eyes-closed, .cat .eyes-happy, .cat .eyes-up, .cat .eyes-wide,
    .cat .mouth-open, .cat .mouth-o, .cat .paw-up,
    .cat .x-zzz, .cat .x-listen, .cat .x-think, .cat .x-talk, .cat .x-wait, .cat .x-error,
    .cat .term text { display: none; }

    .cat .head { transform-origin: 120px 120px; transition: transform .3s ease; }
    .cat .ear-l { transform-origin: 90px 56px; }
    .cat .ear-r { transform-origin: 150px 56px; }
    .cat .tail-up { transform-origin: 178px 145px; }
    .cat .paw-up { transform-origin: 150px 140px; }
    .cat .mouth-open { transform-origin: 120px 103px; }
    .cat .breath { transform-origin: 120px 152px; }
    .cat-caption {
      margin-top: 2px;
      font-size: 11px;
      color: var(--vscode-descriptionForeground, #999);
      letter-spacing: .02em;
    }

    /* idle: asleep, ears down, slow breathing, z z floats up */
    .cat[data-state="idle"] .ears-down, .cat[data-state="idle"] .eyes-closed,
    .cat[data-state="idle"] .x-zzz, .cat[data-state="idle"] .t-idle { display: inline; }
    .cat[data-state="idle"] .ears-up { display: none; }
    .cat[data-state="idle"] .head { transform: rotate(-6deg); }
    .cat[data-state="idle"] .breath { animation: cat-breathe 3.2s ease-in-out infinite; }
    .cat[data-state="idle"] .x-zzz { animation: cat-float 2.8s ease-in-out infinite; }

    /* listening: eyes open, ears twitch, sound arcs pulse toward the headphones */
    .cat[data-state="listening"] .eyes-open, .cat[data-state="listening"] .x-listen,
    .cat[data-state="listening"] .t-listening { display: inline; }
    .cat[data-state="listening"] .ear-l { animation: cat-ear-l 1.4s ease-in-out infinite; }
    .cat[data-state="listening"] .ear-r { animation: cat-ear-r 1.4s ease-in-out infinite .2s; }
    .cat[data-state="listening"] .arc1 { animation: cat-pulse 1.2s ease-in-out infinite; }
    .cat[data-state="listening"] .arc2 { animation: cat-pulse 1.2s ease-in-out infinite .3s; }

    /* thinking: eyes look up, tail swishes, dots blink */
    .cat[data-state="thinking"] .eyes-up, .cat[data-state="thinking"] .tail-up,
    .cat[data-state="thinking"] .x-think, .cat[data-state="thinking"] .t-thinking { display: inline; }
    .cat[data-state="thinking"] .tail-down { display: none; }
    .cat[data-state="thinking"] .head { transform: rotate(5deg); }
    .cat[data-state="thinking"] .tail-up { animation: cat-swish .9s ease-in-out infinite alternate; }
    .cat[data-state="thinking"] .d1 { animation: cat-blink 1.2s infinite; }
    .cat[data-state="thinking"] .d2 { animation: cat-blink 1.2s infinite .2s; }
    .cat[data-state="thinking"] .d3 { animation: cat-blink 1.2s infinite .4s; }

    /* speaking: happy eyes, mouth moving, notes drift */
    .cat[data-state="speaking"] .eyes-happy, .cat[data-state="speaking"] .mouth-open,
    .cat[data-state="speaking"] .x-talk, .cat[data-state="speaking"] .t-speaking { display: inline; }
    .cat[data-state="speaking"] .mouth-w { display: none; }
    .cat[data-state="speaking"] .mouth-open { animation: cat-talk .26s ease-in-out infinite alternate; }
    .cat[data-state="speaking"] .note1 { animation: cat-float 2s ease-in-out infinite; }
    .cat[data-state="speaking"] .note2 { animation: cat-float 2s ease-in-out infinite .7s; }

    /* waiting for a yes: looks at you, paw waves, the ? bobs */
    .cat[data-state="waiting"] .eyes-open, .cat[data-state="waiting"] .paw-up,
    .cat[data-state="waiting"] .x-wait, .cat[data-state="waiting"] .t-waiting { display: inline; }
    .cat[data-state="waiting"] .paw-down { display: none; }
    .cat[data-state="waiting"] .paw-up { animation: cat-wave 1.3s ease-in-out infinite; }
    .cat[data-state="waiting"] .x-wait { animation: cat-bob 1.6s ease-in-out infinite; }

    /* error: wide eyes, worried brows, ears down, one startled hop, shock lines flash */
    .cat[data-state="error"] .eyes-wide, .cat[data-state="error"] .ears-down, .cat[data-state="error"] .mouth-o,
    .cat[data-state="error"] .x-error, .cat[data-state="error"] .t-error { display: inline; }
    .cat[data-state="error"] .ears-up, .cat[data-state="error"] .mouth-w, .cat[data-state="error"] .mic { display: none; }
    .cat[data-state="error"] .breath { animation: cat-hop .4s ease-out 1; }
    .cat[data-state="error"] .shock { animation: cat-blink .5s ease-in-out 3; }

    @keyframes cat-breathe { 0%,100% { transform: scale(1, 1); } 50% { transform: scale(1.012, 1.03); } }
    @keyframes cat-float { 0%,100% { opacity: .35; transform: translateY(3px); } 50% { opacity: 1; transform: translateY(-4px); } }
    @keyframes cat-ear-l { 0%,70%,100% { transform: rotate(0); } 80% { transform: rotate(-9deg); } }
    @keyframes cat-ear-r { 0%,70%,100% { transform: rotate(0); } 80% { transform: rotate(9deg); } }
    @keyframes cat-pulse { 0%,100% { opacity: .25; } 50% { opacity: 1; } }
    @keyframes cat-swish { from { transform: rotate(-10deg); } to { transform: rotate(8deg); } }
    @keyframes cat-blink { 0%,100% { opacity: .25; } 50% { opacity: 1; } }
    @keyframes cat-talk { from { transform: scaleY(.35); } to { transform: scaleY(1); } }
    @keyframes cat-wave { 0%,100% { transform: rotate(0); } 50% { transform: rotate(-10deg); } }
    @keyframes cat-bob { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
    @keyframes cat-hop { 0% { transform: translateY(0); } 40% { transform: translateY(-10px); } 100% { transform: translateY(0); } }
    @media (prefers-reduced-motion: reduce) {
      .cat *, .cat { animation: none !important; transition: none !important; }
    }

    /* ===== Sidebar width (about 300 px): wrap rows instead of running off the right edge ===== */
    *, *::before, *::after { box-sizing: border-box; }
    .mic-row { display: flex; justify-content: center; margin: 6px 0 4px; }
    .mic-row .mic-btn { width: 36px; height: 36px; }
    .app { width: 100%; max-width: 100vw; overflow-x: hidden; }
    .app > *, .main > *, section, .voice-card, .voice-row, .voice-info, .brand, .brand-info { min-width: 0; max-width: 100%; }
    .header { gap: 8px; }
    .connection { white-space: nowrap; flex-shrink: 0; }
    .voice-row, .audio-controls { flex-wrap: wrap; }
    .cat-caption { text-align: center; padding: 0 12px; }

  </style>

</head>


<body>

  <div class="app">


    <!-- =================================
         HEADER
    ================================= -->

    <header class="header">

      <div class="brand">

        <div class="logo-badge">

          <svg viewBox="0 0 24 24">

            <path
              d="
                M12 2a10 10 0 0 1 10 10
                10 10 0 0 1-10 10
                A10 10 0 0 1 2 12
                10 10 0 0 1 12 2
                m0 2a8 8 0 0 0-8 8
                8 8 0 0 0 8 8
                8 8 0 0 0 8-8
                8 8 0 0 0-8-8
                m0 3a5 5 0 0 1 5 5
                c0 1.9-1 3.5-2.5 4.3
                l-1-.6
                c1.2-.6 2-1.9 2-3.2
                a3.5 3.5 0 0 0-3.5-3.5
                A3.5 3.5 0 0 0 8.5 12
                c0 1.3.8 2.6 2 3.2
                l-1 .6
                C8 15.5 7 13.9 7 12
                a5 5 0 0 1 5-5z
              "
            />

          </svg>

        </div>


        <div class="brand-info">

          <div class="brand-title-row">

            <span class="brand-name">
              Angizo
            </span>

          </div>


          <div class="brand-subtitle">

            AI Voice & Code Agent

          </div>

        </div>

      </div>


      <div class="connection">

        <span class="connection-dot"></span>

        Connected

      </div>

    </header>

    <!-- The cat (decorative: screen readers skip it; the state is spoken instead) -->
    <div class="cat-stage" aria-hidden="true">
      <svg id="cat" class="cat" data-state="idle" viewBox="0 0 240 220" focusable="false">
        <g class="breath">
          <!-- tail: resting, and raised (thinking) -->
          <g class="tail-down"><path d="M178 150 C206 152 222 132 214 112 C211 104 201 106 204 114 C208 128 198 138 178 138" fill="#d6d6d6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M209 118 l8 -2 M206 130 l8 3" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/></g>
          <g class="tail-up"><path d="M178 150 C204 146 212 120 200 100 C196 92 186 96 190 104 C198 120 192 134 176 136" fill="#d6d6d6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M196 112 l8 -3 M195 124 l9 0" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/></g>
          <!-- body -->
          <path d="M52 152 C52 120 84 110 120 110 C156 110 188 120 188 152 Z" fill="#d6d6d6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
          <path d="M70 128 l10 6 M66 140 l11 3 M170 128 l-10 6 M174 140 l-11 3" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
          <!-- head -->
          <g class="head">
            <g class="ears-up">
              <g class="ear-l"><path d="M72 64 L80 18 L108 48 Z" fill="#d6d6d6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M80 56 L84 32 L99 49 Z" fill="#bcbcbc"/></g>
              <g class="ear-r"><path d="M132 48 L160 18 L168 64 Z" fill="#d6d6d6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M141 49 L156 32 L160 56 Z" fill="#bcbcbc"/></g>
            </g>
            <g class="ears-down"><path d="M70 70 L72 30 L104 52 Z" fill="#d6d6d6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M78 62 L79 40 L96 53 Z" fill="#bcbcbc"/><path d="M136 52 L168 30 L170 70 Z" fill="#d6d6d6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M144 53 L161 40 L162 62 Z" fill="#bcbcbc"/></g>
            <ellipse cx="120" cy="88" rx="54" ry="44" fill="#d6d6d6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
            <path d="M110 46 v11 M120 44 v13 M130 46 v11" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
            <ellipse cx="120" cy="104" rx="25" ry="15" fill="#f4f4f4"/>
            <ellipse cx="90" cy="100" rx="8" ry="4.6" fill="#b8b8b8"/><ellipse cx="150" cy="100" rx="8" ry="4.6" fill="#b8b8b8"/>
            <g class="eyes-open"><circle cx="102" cy="85" r="7" fill="#1c1c1c"/><circle cx="138" cy="85" r="7" fill="#1c1c1c"/><circle cx="104.5" cy="82" r="2.6" fill="#fff"/><circle cx="140.5" cy="82" r="2.6" fill="#fff"/></g>
            <g class="eyes-closed"><path d="M94 86 q8 6 16 0 M130 86 q8 6 16 0" fill="none" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/></g>
            <g class="eyes-happy"><path d="M94 88 q8 -9 16 0 M130 88 q8 -9 16 0" fill="none" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/></g>
            <g class="eyes-up"><circle cx="102" cy="84" r="6.5" fill="#1c1c1c"/><circle cx="138" cy="84" r="6.5" fill="#1c1c1c"/><circle cx="105" cy="80" r="2.4" fill="#fff"/><circle cx="141" cy="80" r="2.4" fill="#fff"/><path d="M95 72 l13 -2 M132 70 l13 2" fill="none" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/></g>
            <g class="eyes-wide"><circle cx="102" cy="84" r="9" fill="#fff" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><circle cx="138" cy="84" r="9" fill="#fff" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><circle cx="102" cy="85" r="4" fill="#1c1c1c"/><circle cx="138" cy="85" r="4" fill="#1c1c1c"/><path d="M92 73 l14 -5 M148 73 l-14 -5" fill="none" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/></g>
            <path d="M115 95 h10 l-5 5 z" fill="#1c1c1c" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
            <path class="mouth-w" d="M112 102 q4 5 8 0 q4 5 8 0" fill="none" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
            <path class="mouth-open" d="M113 103 q7 12 14 0 z" fill="#1c1c1c" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
            <ellipse class="mouth-o" cx="120" cy="107" rx="3.6" ry="4.4" fill="#1c1c1c"/>
            <!-- headphones -->
            <path d="M70 66 A54 50 0 0 1 170 66" fill="none" stroke="#1c1c1c" stroke-width="10" stroke-linecap="round"/>
            <path d="M70 66 A54 50 0 0 1 170 66" fill="none" stroke="#6e6e6e" stroke-width="4" stroke-linecap="round"/>
            <rect x="56" y="70" width="22" height="38" rx="10" fill="#2a2a2a" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><rect x="61" y="77" width="9" height="24" rx="4.5" fill="#6e6e6e"/>
            <rect x="162" y="70" width="22" height="38" rx="10" fill="#2a2a2a" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><rect x="170" y="77" width="9" height="24" rx="4.5" fill="#6e6e6e"/>
          </g>
          <!-- paws: both down, or the right one raised (waiting for a yes) -->
          <ellipse cx="104" cy="142" rx="12" ry="8.5" fill="#f4f4f4" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M100 138 v6 M108 138 v6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
          <g class="paw-down"><ellipse cx="136" cy="142" rx="12" ry="8.5" fill="#f4f4f4" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M132 138 v6 M140 138 v6" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/></g>
          <g class="paw-up">
            <path d="M150 140 C158 124 170 112 182 104" fill="none" stroke="#1c1c1c" stroke-width="20" stroke-linecap="round"/>
            <path d="M150 140 C158 124 170 112 182 104" fill="none" stroke="#d6d6d6" stroke-width="13.6" stroke-linecap="round"/>
            <ellipse cx="186" cy="100" rx="11" ry="10" fill="#f4f4f4" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M182 93 v5 M188 92 v5" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
          </g>
          <!-- mic -->
          <g class="mic"><path d="M120 130 v9" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><rect x="113" y="114" width="14" height="18" rx="7" fill="#6e6e6e" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/><path d="M114 120 h12 M114 125 h12" stroke="#f4f4f4" stroke-width="1.6"/></g>
        </g>
        <!-- extras: drawn in the theme's text colour so they show on light and dark themes -->
        <g class="x-zzz"><text class="ink-fill z1" x="176" y="34">z</text><text class="ink-fill z2" x="192" y="20">z</text></g>
        <g class="x-listen"><path class="ink arc1" d="M44 76 q-8 13 0 26 M196 76 q8 13 0 26"/><path class="ink arc2" d="M34 70 q-12 19 0 38 M206 70 q12 19 0 38"/></g>
        <g class="x-think"><circle class="bubble" cx="200" cy="34" r="20"/><circle class="bubble" cx="180" cy="58" r="4"/><circle class="ink-fill d1" cx="191" cy="34" r="2.6"/><circle class="ink-fill d2" cx="200" cy="34" r="2.6"/><circle class="ink-fill d3" cx="209" cy="34" r="2.6"/><path class="ink" d="M216 98 l9 -6 M219 110 l10 -2"/></g>
        <g class="x-talk"><g class="note1"><path class="ink" d="M40 40 v-20 l14 -4 v20"/><ellipse class="ink-fill" cx="36" cy="40" rx="5" ry="4"/><ellipse class="ink-fill" cx="50" cy="36" rx="5" ry="4"/></g><g class="note2"><path class="ink" d="M200 36 v-18"/><ellipse class="ink-fill" cx="196" cy="36" rx="5" ry="4"/></g><text class="purr" x="186" y="58">purr~</text></g>
        <g class="x-wait"><circle class="bubble" cx="194" cy="36" r="17"/><circle class="bubble" cx="178" cy="58" r="3.5"/><text class="ink-fill qmark" x="188" y="43">?</text></g>
        <g class="x-error"><text class="ink-fill bang" x="190" y="52">!</text><path class="ink shock" d="M48 28 l10 10 M38 46 l13 3 M62 18 l2 13"/></g>
        <!-- terminal -->
        <rect x="30" y="150" width="180" height="62" rx="10" fill="#1e1e1e" stroke="#1c1c1c" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>
        <circle cx="44" cy="161" r="3" fill="#ddd"/><circle cx="54" cy="161" r="3" fill="#999"/><circle cx="64" cy="161" r="3" fill="#666"/>
        <g class="term">
          <text class="t-idle" x="42" y="182">&gt; _</text>
          <text class="t-listening" x="42" y="182">&gt; listening…</text>
          <text class="t-thinking" x="42" y="182">&gt; thinking…</text>
          <text class="t-speaking" x="42" y="182">&gt; speaking</text>
          <text class="t-waiting" x="42" y="182">&gt; yes? Alt+Y / Alt+N</text>
          <text class="t-error" x="42" y="182">! something failed</text>
        </g>
        <rect x="42" y="191" width="96" height="5" rx="2.5" fill="#555"/><rect x="42" y="200" width="60" height="5" rx="2.5" fill="#555"/><rect x="106" y="200" width="26" height="5" rx="2.5" fill="#999"/>
      </svg>
      <div id="catCaption" class="cat-caption">Asleep. Press Ctrl+Alt+Space to talk.</div>
    </div>
    <div class="mic-row">
      <button id="micBtn" class="mic-btn" type="button" aria-pressed="false"
        title="Start or stop listening (Ctrl+Alt+Space)" aria-label="Microphone: start or stop listening, Control Alt Space">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg>
      </button>
    </div>


    <!-- =================================
         MAIN
    ================================= -->

    <main class="main">


      <!-- =================================
           COMMAND PALETTE
      ================================= -->

      <section class="command-section">

        <div class="section-header">

          <div class="section-title">

            <svg viewBox="0 0 24 24">

              <path
                d="
                  M20 4H4c-1.1 0-1.99.9-1.99 2L2 18
                  c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6
                  c0-1.1-.9-2-2-2zm-5 14H4v-4h11v4zm0-5H4V9h11v4zm5 5h-4V9h4v9z
                "
              />

            </svg>

            Command Palette

          </div>

        </div>


        <div class="input-row">

          <div class="input-wrapper">

            <span class="input-prefix">

              >

            </span>


            <input
              type="text"
              id="textInput"
              placeholder="e.g. explain this function, run tests..."
              aria-label="Enter command"
            >

          </div>


          <button
            id="sendBtn"
            type="button"
          >

            Run ↵

          </button>

        </div>

      </section>


      <!-- =================================
           CONFIRMATION
      ================================= -->

      <div id="confirmArea">

        <div class="confirm-header">

          ⚠️ Confirmation Required

        </div>


        <p id="confirmPrompt"></p>


        <div class="confirm-buttons">

          <button id="yesBtn">

            Confirm

          </button>


          <button id="noBtn">

            Cancel

          </button>

        </div>

      </div>


      <!-- =================================
           ACTIVITY FEED
      ================================= -->

      <section
        class="activity"
        aria-label="Action and Activity Stream"
      >

        <div class="section-header">

          <div class="section-title">

            <svg viewBox="0 0 24 24">

              <path
                d="
                  M13 3c-4.97 0-9 4.03-9 9H1
                  l3.89 3.89.07.14L9 12H6
                  c0-3.87 3.13-7 7-7s7 3.13 7 7
                  -3.13 7-7 7
                  c-1.93 0-3.68-.79-4.94-2.06
                  l-1.42 1.42
                  C8.27 19.99 10.51 21 13 21
                  c4.97 0 9-4.03 9-9
                  s-4.03-9-9-9zm-1 5v5
                  l4.28 2.54.72-1.21
                  -3.5-2.08V8H12z
                "
              />

            </svg>

            Action & Voice Feed

          </div>


          <div class="live">

            LIVE AUDIT

          </div>

        </div>


        <div
          id="log"
          class="feed-container"
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-atomic="false"
          aria-label="Activity Feed Log"
          tabindex="0"
        ></div>

      </section>

    </main>


    <!-- =================================
         FOOTER
    ================================= -->

    <footer class="footer">

      <div class="footer-item">

        <span class="footer-dot"></span>

        <span>

          Angizo Engine v0.1

        </span>

      </div>


      <div class="footer-item">

        <span>

          Voice + Diff Intelligence

        </span>

      </div>

    </footer>

  </div>


  <!-- =================================
       WEBVIEW CONFIGURATION
  ================================= -->

  <script nonce="${nonce}">

    window.processorUri =
      "${processorUri.toString()}";

  </script>


  <script
    nonce="${nonce}"
    src="${mainScriptUri.toString()}"
  ></script>

</body>

</html>`;
}

function getNonce(): string {
  let text = "";
  const chars =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return text;
}