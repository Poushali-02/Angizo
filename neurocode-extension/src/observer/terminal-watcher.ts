/**
 * neurocode-extension/src/observer/terminal-watcher.ts
 *
 * Stage 2 Runtime & Compilation Error Interceptor.
 *
 * Dual detection strategy:
 *   1. vscode.window.onDidWriteTerminalData — captures terminal stdout/stderr text (requires VS Code 1.93+)
 *   2. vscode.debug events — captures debugger exception events
 *
 * Intercepts unhandled exceptions, crash stack traces, and compilation failures.
 * Sends stack trace + file/line numbers over WebSocket to Python backend for Groq LLM trigger cause analysis.
 */

import * as vscode from "vscode";
import { NeurocodeWsClient } from "../ws-client";

export interface TerminalRuntimeErrorEvent {
  type: "runtime_error";
  file: string;
  line: number;
  errorName: string;
  errorMessage: string;
  stackTraceSnippet: string;
}

export class TerminalWatcher {
  private disposables: vscode.Disposable[] = [];
  private onEvent: (event: TerminalRuntimeErrorEvent) => void;
  private wsClient: NeurocodeWsClient | undefined;

  private terminalBuffer = "";
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private lastReportedError = ""; // Prevent duplicate reports for same error
  private enabled = true;

  constructor(
    onEvent: (event: TerminalRuntimeErrorEvent) => void,
    wsClient?: NeurocodeWsClient
  ) {
    this.onEvent = onEvent;
    this.wsClient = wsClient;
  }

  activate(context: vscode.ExtensionContext): void {
    // ── Strategy 1: Terminal data stream ────────────────────────────────────
    // Wrapped in try/catch because accessing onDidWriteTerminalData throws a strict
    // "CANNOT use API proposal" error in standard VS Code unless --enable-proposed-api is used.
    try {
      if ("onDidWriteTerminalData" in vscode.window) {
        const termWatcher = (vscode.window as any).onDidWriteTerminalData((e: any) => {
          if (!this.enabled) return;
          // Strip ANSI escape codes before buffering
          const cleanData = (e.data as string).replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, "");
          this.terminalBuffer += cleanData;

          // Keep buffer manageable (last 8,000 chars)
          if (this.terminalBuffer.length > 8000) {
            this.terminalBuffer = this.terminalBuffer.slice(-8000);
          }

          // Debounce: analyse 900ms after last data arrives
          if (this.debounceTimer) clearTimeout(this.debounceTimer);
          this.debounceTimer = setTimeout(() => {
            this.analyzeTerminalOutput();
          }, 900);
        });
        this.disposables.push(termWatcher);
        console.log("[TerminalWatcher] onDidWriteTerminalData hooked.");
      }
    } catch (err) {
      console.log("[TerminalWatcher] Proposed API 'onDidWriteTerminalData' not available, skipping Strategy 1.");
    }

    // ── Strategy 2: Debug session exception events ───────────────────────────
    const debugWatcher = vscode.debug.onDidReceiveDebugSessionCustomEvent((e) => {
      if (!this.enabled) return;
      if (e.event === "output" && e.body?.category === "stderr") {
        const text: string = e.body.output || "";
        this.terminalBuffer += text;
        if (this.debounceTimer) clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(() => this.analyzeTerminalOutput(), 900);
      }
    });
    this.disposables.push(debugWatcher);

    context.subscriptions.push(...this.disposables);
    console.log("[TerminalWatcher] Stage 2 Runtime Interceptor activated.");
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
  }

  private analyzeTerminalOutput(): void {
    const text = this.terminalBuffer;
    this.terminalBuffer = ""; // Clear buffer after each analysis pass

    if (!text || text.length < 10) return;

    // ── Python Traceback (most specific pattern first) ────────────────────────
    // Matches: File "path/to/file.py", line 42, in <func>
    //          SomeError: message
    const pyTraceRegex = /File "([^"]+\.py)", line (\d+), in [^\n]+[\s\S]*?([A-Za-z][A-Za-z0-9_.]*(?:Error|Exception|Warning)): ([^\n]+)/;
    const pyTrace = pyTraceRegex.exec(text);
    if (pyTrace) {
      const [, fullPath, lineStr, errName, errMsg] = pyTrace;
      return this.triggerRuntimeError(
        vscode.workspace.asRelativePath(fullPath),
        parseInt(lineStr, 10),
        errName,
        `${errName}: ${errMsg}`,
        text.slice(0, 1500)
      );
    }

    // ── Python simple exception (no traceback header) ────────────────────────
    const pySimple = /([A-Za-z][A-Za-z0-9_.]*(?:Error|Exception)): (.+)/.exec(text);
    if (pySimple) {
      // Try to extract file & line from context
      const lineHint = /line (\d+)/.exec(text);
      const fileHint = /"([^"]+\.py)"/.exec(text);
      return this.triggerRuntimeError(
        fileHint ? vscode.workspace.asRelativePath(fileHint[1]) : "python script",
        lineHint ? parseInt(lineHint[1], 10) : 1,
        pySimple[1],
        `${pySimple[1]}: ${pySimple[2]}`,
        text.slice(0, 1500)
      );
    }

    // ── JavaScript / Node / TypeScript ──────────────────────────────────────
    const jsRegex = /([A-Za-z][A-Za-z0-9]*Error): ([^\n]+)\n\s+at [^\n]*\(?([^\s:)]+):(\d+):\d+\)?/;
    const jsMatch = jsRegex.exec(text);
    if (jsMatch) {
      return this.triggerRuntimeError(
        vscode.workspace.asRelativePath(jsMatch[3]),
        parseInt(jsMatch[4], 10),
        jsMatch[1],
        `${jsMatch[1]}: ${jsMatch[2]}`,
        text.slice(0, 1500)
      );
    }

    // ── Generic compile error (e.g. gcc, javac, dotnet) ─────────────────────
    const compileRegex = /([^:\n]+):(\d+):\d+: (error|fatal error): (.+)/i;
    const compileMatch = compileRegex.exec(text);
    if (compileMatch) {
      return this.triggerRuntimeError(
        vscode.workspace.asRelativePath(compileMatch[1]),
        parseInt(compileMatch[2], 10),
        "CompileError",
        `Compile error: ${compileMatch[4]}`,
        text.slice(0, 1500)
      );
    }
  }

  private triggerRuntimeError(
    file: string,
    line: number,
    errorName: string,
    errorMessage: string,
    snippet: string
  ): void {
    // Deduplicate: don't fire same error + line twice in a row
    const key = `${file}:${line}:${errorName}`;
    if (key === this.lastReportedError) return;
    this.lastReportedError = key;
    setTimeout(() => { this.lastReportedError = ""; }, 10000); // Reset after 10s

    console.log(`[TerminalWatcher] Runtime error detected: ${errorMessage} in ${file}:${line}`);

    const eventPayload: TerminalRuntimeErrorEvent = {
      type: "runtime_error",
      file,
      line,
      errorName,
      errorMessage,
      stackTraceSnippet: snippet,
    };

    this.onEvent(eventPayload);

    if (this.wsClient && this.wsClient.isConnected) {
      this.wsClient.sendManualObserverEvent({
        event_type: "runtime_error",
        file,
        line,
        error_name: errorName,
        error_message: errorMessage,
        stack_trace: snippet,
      });
    }
  }

  dispose(): void {
    for (const d of this.disposables) {
      d.dispose();
    }
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
  }
}
