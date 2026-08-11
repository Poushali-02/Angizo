/**
 * neurocode-extension/src/observer/manual-watcher.ts
 *
 * Stage 1 Manual Coding Observer — Intellisense Syntax Error Interceptor.
 *
 * Multi-Line Tracking & Strict Line-Shift Strategy:
 *   - TRACKS ALL ERRORS ACROSS ALL LINES in every active file (per-line Map).
 *   - INSTANT EARCON (<10ms): Sound chime plays immediately when Intellisense marks a red squiggle.
 *   - STRICT LINE-SHIFT VOICE: Voice narration ONLY fires when the developer EXITS a line with errors.
 *   - RESOLVED STATE: Uses a boolean `fileHasErrors` flag so multiple LSP zero-count passes
 *     all correctly restart the debounce timer (fixes the "resolved never fires" bug).
 */

import * as vscode from "vscode";
import { NeurocodeWsClient } from "../ws-client";

export interface ManualSyntaxErrorEvent {
  type: "syntax_error";
  file: string;
  line: number;
  column: number;
  message: string;
  isResolved: boolean;
  errorCount: number;
}

interface LineErrorEntry {
  payload: ManualSyntaxErrorEvent;
  wsPayload: object;
}

export class ManualWatcher {
  private disposables: vscode.Disposable[] = [];
  private onEvent: (event: ManualSyntaxErrorEvent) => void;
  private wsClient: NeurocodeWsClient | undefined;

  // Active error map per file -> per 0-indexed line -> LineErrorEntry
  private pendingLineErrors: Map<string, Map<number, LineErrorEntry>> = new Map();

  // Boolean flag: does this file currently have active errors?
  // Using a boolean (not a count) avoids the "previousCount already 0" bug where
  // multiple LSP passes with currentCount=0 each cancel the debounce without restarting it.
  private fileHasErrors: Map<string, boolean> = new Map();

  // Debounce timers for the "resolved" notification per file (500ms).
  // The timer is restarted on EVERY diagnostic pass where currentCount=0 AND fileHasErrors=true.
  private resolvedDebounceTimers: Map<string, ReturnType<typeof setTimeout>> = new Map();
  private static readonly RESOLVED_DEBOUNCE_MS = 500;

  // Track if we actually announced an error to the user for this file.
  // If they fix the error before we announce it, we shouldn't say "resolved".
  private hasAnnouncedError: Map<string, boolean> = new Map();

  // Active cursor line per file (0-indexed)
  private currentLinePerFile: Map<string, number> = new Map();

  private enabled = true;

  constructor(
    onEvent: (event: ManualSyntaxErrorEvent) => void,
    wsClient?: NeurocodeWsClient
  ) {
    this.onEvent = onEvent;
    this.wsClient = wsClient;
  }

  activate(context: vscode.ExtensionContext): void {
    // Watch Intellisense LSP diagnostics (red squiggles)
    const diagWatcher = vscode.languages.onDidChangeDiagnostics((event) =>
      this.onDiagnosticsChanged(event)
    );

    // Strict line-shift detection: watch cursor position changes
    const cursorWatcher = vscode.window.onDidChangeTextEditorSelection((event) => {
      if (!this.enabled) return;
      const editor = event.textEditor;
      const uri = editor.document.uri;
      if (uri.scheme !== "file" && uri.scheme !== "untitled") return;

      const relPath = vscode.workspace.asRelativePath(uri);
      const currentLine = editor.selection.active.line;

      const previousLine = this.currentLinePerFile.get(relPath);
      this.currentLinePerFile.set(relPath, currentLine);

      // Fire voice narration ONLY when the developer moves to a DIFFERENT line
      if (previousLine !== undefined && previousLine !== currentLine) {
        const fileMap = this.pendingLineErrors.get(relPath);
        if (fileMap && fileMap.has(previousLine)) {
          const entry = fileMap.get(previousLine)!;
          this.firePendingNarration(relPath, entry);
          fileMap.delete(previousLine); // Fire once per line exit
        }
      }
    });

    this.disposables.push(diagWatcher, cursorWatcher);
    context.subscriptions.push(...this.disposables);
    console.log("[ManualWatcher] Stage 1 Syntax Interceptor activated.");
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
    console.log(`[ManualWatcher] Manual stream ${enabled ? "enabled" : "disabled"}.`);
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  private onDiagnosticsChanged(event: vscode.DiagnosticChangeEvent): void {
    if (!this.enabled) return;

    for (const uri of event.uris) {
      if (uri.scheme !== "file" && uri.scheme !== "untitled") continue;
      const relPath = vscode.workspace.asRelativePath(uri);
      this.processDiagnostics(uri, relPath);
    }
  }

  private processDiagnostics(uri: vscode.Uri, relPath: string): void {
    const diags = vscode.languages.getDiagnostics(uri);

    // ONLY track Error severity — Warnings come from linters in separate passes
    // and clearing them causes false "resolved" notifications.
    const syntaxErrors = diags.filter(
      (d) => d.severity === vscode.DiagnosticSeverity.Error
    );

    const hadErrors = this.fileHasErrors.get(relPath) ?? false;
    const currentCount = syntaxErrors.length;
    const nowHasErrors = currentCount > 0;

    if (!this.pendingLineErrors.has(relPath)) {
      this.pendingLineErrors.set(relPath, new Map());
    }
    const fileMap = this.pendingLineErrors.get(relPath)!;

    if (nowHasErrors) {
      // ── Errors present: cancel any pending resolved debounce ────────────
      if (this.resolvedDebounceTimers.has(relPath)) {
        clearTimeout(this.resolvedDebounceTimers.get(relPath)!);
        this.resolvedDebounceTimers.delete(relPath);
      }

      this.fileHasErrors.set(relPath, true);

      // Build per-line error map
      const activeLinesInDiags = new Set<number>();

      for (const diag of syntaxErrors) {
        const lineIdx = diag.range.start.line;
        activeLinesInDiags.add(lineIdx);

        const lineNum = lineIdx + 1; // 1-indexed for display
        const colNum = diag.range.start.character + 1;
        const msg = diag.message;

        const payload: ManualSyntaxErrorEvent = {
          type: "syntax_error",
          file: relPath,
          line: lineNum,
          column: colNum,
          message: msg,
          isResolved: false,
          errorCount: currentCount,
        };

        const wsPayload = {
          event_type: "syntax_error",
          file: relPath,
          line: lineNum,
          column: colNum,
          error_message: msg,
          is_resolved: false,
          error_count: currentCount,
        };

        fileMap.set(lineIdx, { payload, wsPayload });
      }

      // Clean up line entries that no longer have errors (fixed)
      for (const existingLineIdx of Array.from(fileMap.keys())) {
        if (!activeLinesInDiags.has(existingLineIdx)) {
          fileMap.delete(existingLineIdx);
        }
      }
      
      // Removed instant earcon & websocket narration here.
      // Errors will now only trigger when the user exits the line with an error (handled in firePendingNarration).

    } else if (hadErrors && !nowHasErrors) {
      // ── Errors just cleared (or still 0 from previous LSP pass) ────────
      // Clear pending narrations IMMEDIATELY so stale entries don't fire.
      fileMap.clear();
      this.fileHasErrors.set(relPath, false);

      // Always restart the debounce timer here — even if LSP fires multiple
      // zero-count passes, we keep restarting until 500ms of sustained silence.
      if (this.resolvedDebounceTimers.has(relPath)) {
        clearTimeout(this.resolvedDebounceTimers.get(relPath)!);
      }

      const timer = setTimeout(() => {
        this.resolvedDebounceTimers.delete(relPath);

        // Double-check errors haven't come back during the debounce window
        if (this.fileHasErrors.get(relPath)) return;

        // Only announce "resolved" if we actually told them there was an error
        if (this.hasAnnouncedError.get(relPath)) {
          const resolvedPayload: ManualSyntaxErrorEvent = {
            type: "syntax_error",
            file: relPath,
            line: 0,
            column: 0,
            message: "All syntax errors resolved",
            isResolved: true,
            errorCount: 0,
          };

          this.onEvent(resolvedPayload);

          if (this.wsClient && this.wsClient.isConnected) {
            this.wsClient.sendManualObserverEvent({
              event_type: "syntax_error",
              file: relPath,
              line: 0,
              column: 0,
              error_message: "Syntax errors resolved",
              is_resolved: true,
              error_count: 0,
            });
          }
          
          // Reset the flag since we announced resolution
          this.hasAnnouncedError.set(relPath, false);
        }
      }, ManualWatcher.RESOLVED_DEBOUNCE_MS);

      this.resolvedDebounceTimers.set(relPath, timer);
    }
    // If !hadErrors && !nowHasErrors: file had no errors and still has none — do nothing.
  }

  /** Fire the queued voice narration WebSocket event when user exits a specific line */
  private firePendingNarration(relPath: string, entry: LineErrorEntry): void {
    console.log(`[ManualWatcher] User exited line ${entry.payload.line} — firing voice for ${relPath}`);
    
    // Mark that we actually announced an error to the user for this file
    this.hasAnnouncedError.set(relPath, true);
    
    // Trigger Earcon and HUD
    this.onEvent(entry.payload);
    
    // Trigger backend voice narration
    if (this.wsClient && this.wsClient.isConnected) {
      this.wsClient.sendManualObserverEvent(entry.wsPayload as any);
    }
  }

  dispose(): void {
    for (const d of this.disposables) {
      d.dispose();
    }
    this.pendingLineErrors.clear();
    this.resolvedDebounceTimers.forEach((t) => clearTimeout(t));
    this.resolvedDebounceTimers.clear();
  }
}
