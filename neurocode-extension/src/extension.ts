/**
 * neurocode-extension/src/extension.ts
 *
 * VS Code extension activation and command registration.
 * Creates the webview panel and wires up the postMessage bridge.
 *
 * Architecture (DESIGN.md / 01-architecture.md):
 *   - Webview captures audio via AudioWorklet → postMessage → extension host
 *   - Extension host owns the WebSocket to the backend
 *   - Webview NEVER opens a WebSocket directly
 */

import * as vscode from "vscode";
import * as path from "path";
import { NeurocodeWsClient } from "./ws-client";
import { WebviewBridge } from "./webview-bridge";
import { CopilotWatcher, CopilotObserverEvent } from "./observer/copilot-watcher";
import { ManualWatcher, ManualSyntaxErrorEvent } from "./observer/manual-watcher";
import { TerminalWatcher, TerminalRuntimeErrorEvent } from "./observer/terminal-watcher";
import { ObserverEarcon } from "./observer/observer-earcon";
import { ObserverStatusBar } from "./observer/observer-status-bar";
import { ObserverHud } from "./observer/observer-hud";

let panel: vscode.WebviewPanel | undefined;
let wsClient: NeurocodeWsClient | undefined;
let bridge: WebviewBridge | undefined;

// --- Copilot Observer modules (live for the full extension lifetime) ---
let copilotWatcher: CopilotWatcher | undefined;
let manualWatcher: ManualWatcher | undefined;
let terminalWatcher: TerminalWatcher | undefined;
let observerEarcon: ObserverEarcon | undefined;
let observerStatusBar: ObserverStatusBar | undefined;
let observerHud: ObserverHud | undefined;

export function activate(context: vscode.ExtensionContext) {
  console.log("Angizo extension activating");
  vscode.window.showInformationMessage("Angizo is listening.");

  // Create persistent WebSocket client immediately on extension startup
  // Backend port: ANGIZO_WS_PORT (used by the end-to-end tests), then the angizo setting, then 7001
  const wsPort =
    process.env.ANGIZO_WS_PORT ||
    String(vscode.workspace.getConfiguration("neurocode").get<number>("backendPort", 7001));
  wsClient = new NeurocodeWsClient(`ws://localhost:${wsPort}/ws/session`);
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (workspaceFolders && workspaceFolders.length > 0) {
    wsClient.setWorkspacePath(workspaceFolders[0].uri.fsPath);
  }

  function ensureWebviewPanel(preserveFocus: boolean = true): vscode.WebviewPanel {
    if (panel) {
      if (!preserveFocus) {
        panel.reveal(vscode.ViewColumn.Beside, false);
      }
    } else {
      panel = vscode.window.createWebviewPanel(
        "neurocodePanel",
        "Angizo",
        { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
        {
          enableScripts: true,
          retainContextWhenHidden: true,
          localResourceRoots: [
            vscode.Uri.file(
              path.join(context.extensionPath, "src", "webview")
            ),
            vscode.Uri.file(
              path.join(context.extensionPath, "out", "webview")
            ),
          ],
        }
      );

      panel.onDidDispose(() => {
        panel = undefined;
        bridge?.dispose();
        bridge = undefined;
      });

      panel.webview.html = getWebviewContent(panel.webview, context);

      if (wsClient) {
        bridge = new WebviewBridge(panel, wsClient);
        observerEarcon?.setPanel(panel);
      }
    }
    return panel;
  }

  // --- Start Voice Input command ---
  const startCmd = vscode.commands.registerCommand(
    "neurocode.startVoiceInput",
    () => {
      ensureWebviewPanel();
    }
  );

  // --- Run a Command: type a request without the panel's text box ---
  // From the Command Palette it asks in an input box (screen-reader friendly); scripts and
  // the demo pass the text directly: executeCommand("neurocode.runCommand", "review my diff").
  const runCommandCmd = vscode.commands.registerCommand(
    "neurocode.runCommand",
    async (text?: string) => {
      const command =
        typeof text === "string" && text.trim()
          ? text.trim()
          : (await vscode.window.showInputBox({
              prompt: "What should Angizo do?",
              placeHolder: "e.g. review my diff, commit my changes, push my branch",
            }))?.trim();
      if (!command) return;
      const currentPanel = ensureWebviewPanel();
      currentPanel.webview.postMessage({ type: "command_sent", text: command });
      wsClient?.sendTextCommand(command);
    }
  );
  context.subscriptions.push(runCommandCmd);

  // --- Stop Voice Input command ---
  const stopCmd = vscode.commands.registerCommand(
    "neurocode.stopVoiceInput",
    () => {
      if (panel) {
        panel.webview.postMessage({ type: "stop_mic" });
        vscode.window.showInformationMessage("Angizo: Voice input stopped");
      }
    }
  );

  // --- Confirm Action command ---
  const confirmCmd = vscode.commands.registerCommand(
    "neurocode.confirm",
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
    "neurocode.cancel",
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
    "neurocode.toggleManualStream",
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
  observerEarcon = new ObserverEarcon(); // panel attached later when panel opens

  // ─── Manual Coding Streamer & Error Interceptors ─────────────────────────
  manualWatcher = new ManualWatcher((event: ManualSyntaxErrorEvent) => {
    const currentPanel = ensureWebviewPanel();
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
    const currentPanel = ensureWebviewPanel();
    observerEarcon?.play("error", currentPanel);
    observerStatusBar?.setError(1, "Runtime");
    observerHud?.show(`Angizo Intercept: Runtime ${event.errorName} in ${event.file}`);
  }, wsClient);
  terminalWatcher.activate(context);

  /** Routes CopilotObserverEvents to earcon, HUD, status bar, and webview */
  function handleObserverEvent(event: CopilotObserverEvent): void {
    const currentPanel = ensureWebviewPanel();

    switch (event.type) {
      case "copilot_start": {
        const shortName = event.file ? event.file.split(/[\\/]/).pop() : "file";
        observerEarcon?.play("start", currentPanel);
        observerEarcon?.startTick(currentPanel);
        observerStatusBar?.setGenerating(event.file || "unknown file");
        observerHud?.show(`Angizo Observer: Copilot generating in ${event.file}... `);
        currentPanel.webview.postMessage({
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
        currentPanel.webview.postMessage({
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
        currentPanel.webview.postMessage({
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
    "neurocode.toggleObserver",
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
    "neurocode.announceStatus",
    () => {
      if (!observerStatusBar) return;
      const label = observerStatusBar.getAccessibleLabel();
      vscode.window.showInformationMessage(`Angizo: ${label}`);
      if (panel) {
        panel.webview.postMessage({
          type: "speak_text",
          text: label,
        });
      }
    }
  );

  context.subscriptions.push(toggleObserverCmd, announceStatusCmd);

  // Guard .env file access for screen-reader (blind/low-vision) users
  function checkEnvAccess(editor: vscode.TextEditor | undefined) {
    if (editor && editor.document) {
      const fileName = editor.document.fileName;
      if (fileName.endsWith(".env") || fileName.split(/[\\/]/).pop() === ".env") {
        const config = vscode.workspace.getConfiguration("neurocode");
        const simulateBlindMode = config.get<boolean>("simulateBlindMode", false);
        const isScreenReaderActive = simulateBlindMode || (vscode.env as any).accessibilitySupport === 3;
        if (isScreenReaderActive) {
          if (panel) {
            panel.webview.postMessage({
              type: "speak_text",
              text: "Warning: You are trying to access a dot env file containing sensitive credentials. Do you want to open it? Press Alt+Y to confirm or Alt+N to reject.",
            });
          }
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
}

export function deactivate() {
  wsClient?.close();
  bridge?.dispose();
  panel?.dispose();
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


    <!-- =================================
         MAIN
    ================================= -->

    <main class="main">


      <!-- =================================
           VOICE INTERFACE
      ================================= -->

      <section>

        <div class="section-header">

          <div class="section-title">

            <svg viewBox="0 0 24 24">

              <path
                d="
                  M12 14c1.66 0 3-1.34 3-3V5
                  c0-1.66-1.34-3-3-3S9 3.34 9 5v6
                  c0 1.66 1.34 3 3 3z
                "
              />

              <path
                d="
                  M17 11c0 2.76-2.24 5-5 5
                  s-5-2.24-5-5H5
                  c0 3.53 2.61 6.43 6 6.92V21h2
                  v-3.08c3.39-.49 6-3.39 6-6.92h-2z
                "
              />

            </svg>

            Voice Interface

          </div>

        </div>


        <div class="voice-card">

          <div class="voice-row">


            <div class="voice-info">

              <button
                id="micBtn"
                class="mic-btn"
                title="Toggle Voice Input (Click to speak)"
                aria-label="Toggle Voice Input"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg>
              </button>


              <div class="voice-text">

                <div class="voice-title">

                  Voice Command

                </div>


                <div class="voice-description">

                  Speak naturally to control your codebase

                </div>

              </div>

            </div>


            <!-- AUDIO CONTROLS -->

            <div class="audio-controls">


              <!-- AUDIO PULSE -->

              <div
                id="audioPulse"
                class="audio-pulse"
                title="Audio is playing"
              >

                <span></span>

                <span></span>

                <span></span>

                <span></span>

                <span></span>

              </div>


              <!-- PAUSE -->

              <button
                id="pauseAudioBtn"
                class="audio-btn"
                type="button"
              >

                Pause

              </button>


              <!-- RESUME -->

              <button
                id="resumeAudioBtn"
                class="audio-btn"
                type="button"
              >

                Resume

              </button>


              <!-- STOP -->

              <button
                id="stopAudioBtn"
                class="audio-btn"
                type="button"
              >

                Stop

              </button>


              <div id="status">

                Idle

              </div>

            </div>

          </div>

        </div>

      </section>


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