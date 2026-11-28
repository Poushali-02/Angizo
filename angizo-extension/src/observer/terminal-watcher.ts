/**
 * angizo-extension/src/observer/terminal-watcher.ts
 *
 * Stage 2 Runtime & Compilation Error Interceptor.
 *
 * Dual detection strategy:
 *   1. Terminal shell integration (onDidStart/EndTerminalShellExecution, stable since VS Code 1.93):
 *      reads each command's output and scans it when the command fails.
 *   2. vscode.debug events — captures debugger stderr.
 *
 * Intercepts unhandled exceptions, crash stack traces, and compilation failures.
 * Sends stack trace + file/line numbers over WebSocket to Python backend for Groq LLM trigger cause analysis.
 */

import * as vscode from "vscode";
import { AngizoWsClient } from "../ws-client";

export interface TerminalRuntimeErrorEvent {
  type: "runtime_error";
  file: string;
  line: number;
  errorName: string;
  errorMessage: string;
  stackTraceSnippet: string;
}

// Colour codes, cursor moves and VS Code's own shell-integration markers (OSC 633)
// OSC sequences end with BEL (\x07) or ESC + backslash; CSI sequences are ESC [ ... letter
const ANSI_ESCAPES = /\x1B\][^\x07\x1B]*(?:\x07|\x1B\x5C)|\x1B\[[0-?]*[ -/]*[@-~]/g;

export class TerminalWatcher {
  private disposables: vscode.Disposable[] = [];
  private onEvent: (event: TerminalRuntimeErrorEvent) => void;
  private wsClient: AngizoWsClient | undefined;

  private terminalBuffer = "";
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private lastReportedError = ""; // Prevent duplicate reports for same error
  private enabled = true;

  constructor(
    onEvent: (event: TerminalRuntimeErrorEvent) => void,
    wsClient?: AngizoWsClient
  ) {
    this.onEvent = onEvent;
    this.wsClient = wsClient;
  }

  activate(context: vscode.ExtensionContext): void {
    // ── Strategy 1: terminal shell integration (stable API since VS Code 1.93) ──
    // Each command's output is read as it runs; when it ends with a non-zero exit code
    // the output is scanned for a stack trace. (The old onDidWriteTerminalData is a
    // proposed API that normal VS Code never enables, so it caught nothing.)
    const pendingReads = new Map<vscode.TerminalShellExecution, Promise<string>>();

    const startWatcher = vscode.window.onDidStartTerminalShellExecution((e) => {
      if (!this.enabled) return;
      pendingReads.set(e.execution, this.readExecution(e.execution));
    });

    const endWatcher = vscode.window.onDidEndTerminalShellExecution(async (e) => {
      const reading = pendingReads.get(e.execution);
      pendingReads.delete(e.execution);
      if (!this.enabled || !reading) return;
      const output = await reading;
      if (e.exitCode === 0) return; // a successful command is never a crash
      this.terminalBuffer = output;
      this.analyzeTerminalOutput();
    });
    this.disposables.push(startWatcher, endWatcher);

    // ── Strategy 2: debugger stderr ─────────────────────────────────────────────
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
    console.log("[TerminalWatcher] Runtime interceptor activated (shell integration + debugger).");
  }

  /** Collects a command's output, without ANSI colour codes, keeping the last 8,000 characters. */
  private async readExecution(execution: vscode.TerminalShellExecution): Promise<string> {
    let output = "";
    try {
      for await (const chunk of execution.read()) {
        output += chunk.replace(ANSI_ESCAPES, "");
        if (output.length > 8000) output = output.slice(-8000);
      }
    } catch (err) {
      console.log("[TerminalWatcher] Could not read terminal output:", err);
    }
    return output;
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

    // ── JavaScript / Node / TypeScript ──────────────────────────────────────
    // First stack frame: "at fn (C:\app\x.js:3:5)" or "at [eval]:1:23" or "at /srv/x.js:3:5"
    const jsRegex = /([A-Za-z][A-Za-z0-9]*Error): ([^\n]+)\n\s+at (?:[^\n(]*\()?([^\s()]+?):(\d+):\d+\)?/;
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

    // ── Python simple exception (no traceback header) ────────────────────────
    const pySimple = /([A-Za-z][A-Za-z0-9_.]*(?:Error|Exception)): (.+)/.exec(text);
    if (pySimple) {
      // Try to extract file & line from context
      const lineHint = /line (\d+)/.exec(text);
      const fileHint = /"([^"]+\.py)"/.exec(text);
      return this.triggerRuntimeError(
        fileHint ? vscode.workspace.asRelativePath(fileHint[1]) : "your program",
        lineHint ? parseInt(lineHint[1], 10) : 1,
        pySimple[1],
        `${pySimple[1]}: ${pySimple[2]}`,
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
