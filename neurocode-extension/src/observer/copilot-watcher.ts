/**
 * neurocode-extension/src/observer/copilot-watcher.ts
 *
 * Copilot Observer - AI generation detector & event emitter.
 *
 * Watches VS Code events and classifies rapid text insertions as
 * AI-generated (Copilot) vs human typing via an insertion velocity heuristic.
 *
 * Emits structured CopilotObserverEvent objects to a registered callback.
 */

import * as vscode from "vscode";
import { NeurocodeWsClient } from "../ws-client";

// --- Event Types ------------------------------------------------------------

export type CopilotEventType =
  | "copilot_start"
  | "copilot_tick"
  | "copilot_complete"
  | "file_created"
  | "dependency_updated"
  | "diagnostic_result";

export interface CopilotObserverEvent {
  type: CopilotEventType;
  file?: string;
  linesAdded?: number;
  linesRemoved?: number;
  modifiedFiles?: string[];
  createdFiles?: string[];
  errorCount?: number;
  warningCount?: number;
  dependencyFile?: string;
  /** file_created only: true when AI insertions happened around the time the file appeared */
  byAi?: boolean;
}

// --- Constants ---------------------------------------------------------------

/** Min chars in a single contentChange to classify as AI generation */
const AI_CHUNK_THRESHOLD = 10;

/** Ms of silence after last AI chunk before firing copilot_complete */
const COMPLETE_DEBOUNCE_MS = 1500;

/** Wait this long after a file appears before announcing it, to see whether AI code lands in it */
const FILE_CREATED_SETTLE_MS = 2000;

/** File system watchers can fire twice for one new file; ignore repeats within this window */
const DUPLICATE_EVENT_MS = 3000;

/** Dependency files that signal a package install / update */
const DEPENDENCY_FILES = new Set([
  "package.json",
  "package-lock.json",
  "requirements.txt",
  "Cargo.toml",
  "go.mod",
  "pyproject.toml",
  "uv.lock",
]);

// --- CopilotWatcher ---------------------------------------------------------

export class CopilotWatcher {
  private disposables: vscode.Disposable[] = [];
  private onEvent: (event: CopilotObserverEvent) => void;
  private wsClient: NeurocodeWsClient | undefined;

  // Session tracking state
  private isGenerating = false;
  private generatingFile = "";
  private linesAdded = 0;
  private linesRemoved = 0;
  private modifiedFiles: Set<string> = new Set();
  private createdFiles: string[] = [];
  private sessionInsertedCode: string[] = [];
  private modifiedUris: Map<string, vscode.Uri> = new Map();
  private lastAiChunkAt = 0;
  private recentlyCreated: Map<string, number> = new Map();
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;

  // Mute toggle
  private muted = false;

  constructor(
    onEvent: (event: CopilotObserverEvent) => void,
    wsClient?: NeurocodeWsClient
  ) {
    this.onEvent = onEvent;
    this.wsClient = wsClient;
  }

  /** Activate all VS Code event watchers */
  activate(context: vscode.ExtensionContext): void {
    // 1. Text document change - AI classifier
    const textWatcher = vscode.workspace.onDidChangeTextDocument(
      (event) => this.onTextDocumentChange(event)
    );

    // 2. File system watcher - new file & dependency detections
    const fsWatcher = vscode.workspace.createFileSystemWatcher("**/*");
    fsWatcher.onDidCreate((uri) => this.onFileCreated(uri));
    fsWatcher.onDidChange((uri) => this.onFileChanged(uri));

    // 3. Diagnostic watcher - LSP error/warning counts post-generation
    const diagWatcher = vscode.languages.onDidChangeDiagnostics(
      (event) => this.onDiagnosticsChanged(event)
    );

    this.disposables.push(textWatcher, fsWatcher, diagWatcher);
    context.subscriptions.push(...this.disposables);
    console.log("[CopilotWatcher] Activated.");
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    console.log(`[CopilotWatcher] Observer ${muted ? "muted" : "unmuted"}.`);
  }

  isMuted(): boolean {
    return this.muted;
  }

  // --- Private Handlers ------------------------------------------------------

  private onTextDocumentChange(event: vscode.TextDocumentChangeEvent): void {
    if (this.muted) return;
    // Support both saved files ("file") and unsaved tabs ("untitled")
    if (event.document.uri.scheme !== "file" && event.document.uri.scheme !== "untitled") return;

    for (const change of event.contentChanges) {
      const insertedText = change.text;
      const insertedLen = insertedText.length;

      // AI generation heuristic: large single-event insertion (>= 10 chars)
      if (insertedLen >= AI_CHUNK_THRESHOLD) {
        const filePath = event.document.uri.fsPath;
        const fileName = vscode.workspace.asRelativePath(filePath);
        console.log(`[CopilotWatcher] AI insertion detected in ${fileName}: ${insertedLen} chars`);

        const addedLines = (insertedText.match(/\n/g) || []).length;
        this.linesAdded += addedLines;
        this.modifiedFiles.add(fileName);
        this.modifiedUris.set(fileName, event.document.uri);
        this.sessionInsertedCode.push(insertedText);
        this.lastAiChunkAt = Date.now();

        if (!this.isGenerating) {
          this.isGenerating = true;
          this.generatingFile = fileName;
          this.emit({ type: "copilot_start", file: fileName });
        }

        // Reset the completion debounce timer on each chunk
        this.scheduleComplete(fileName);
      }
    }
  }

  private onFileCreated(uri: vscode.Uri): void {
    if (this.muted) return;
    if (uri.scheme !== "file") return;

    const fileName = vscode.workspace.asRelativePath(uri.fsPath);
    if (this.shouldIgnorePath(fileName)) return;

    const now = Date.now();
    const seenAt = this.recentlyCreated.get(fileName);
    if (seenAt !== undefined && now - seenAt < DUPLICATE_EVENT_MS) return; // same file, second event
    this.recentlyCreated.set(fileName, now);

    // Decide who made it only after AI code has had a moment to land in it
    setTimeout(() => {
      if (this.muted) return;
      const byAi = this.isGenerating || Date.now() - this.lastAiChunkAt < FILE_CREATED_SETTLE_MS * 2;
      this.createdFiles.push(fileName);
      this.emit({ type: "file_created", file: fileName, byAi });
      this.wsClient?.sendObserverEvent({
        event_type: "file_created",
        file: fileName,
        created_files: [fileName],
        by_ai: byAi,
      });
    }, FILE_CREATED_SETTLE_MS);
  }

  private onFileChanged(uri: vscode.Uri): void {
    if (this.muted) return;
    if (uri.scheme !== "file") return;

    const fileName = vscode.workspace.asRelativePath(uri.fsPath);
    const basename = fileName.split(/[\\/]/).pop() || "";

    if (DEPENDENCY_FILES.has(basename)) {
      this.emit({ type: "dependency_updated", dependencyFile: fileName });

      if (this.wsClient) {
        this.wsClient.sendObserverEvent({
          event_type: "dependency_updated",
          file: fileName,
        });
      }
    }
  }

  private onDiagnosticsChanged(event: vscode.DiagnosticChangeEvent): void {
    if (this.muted) return;
    for (const uri of event.uris) {
      const fileName = vscode.workspace.asRelativePath(uri.fsPath);
      if (this.modifiedFiles.has(fileName)) {
        const diags = vscode.languages.getDiagnostics(uri);
        const errorCount = diags.filter(
          (d) => d.severity === vscode.DiagnosticSeverity.Error
        ).length;
        const warningCount = diags.filter(
          (d) => d.severity === vscode.DiagnosticSeverity.Warning
        ).length;
        this.emit({
          type: "diagnostic_result",
          file: fileName,
          errorCount,
          warningCount,
        });
      }
    }
  }

  // --- Debounce & Completion -------------------------------------------------

  private scheduleComplete(fileName: string): void {
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      this.fireComplete(fileName);
    }, COMPLETE_DEBOUNCE_MS);
  }

  private fireComplete(fileName: string): void {
    this.isGenerating = false;

    const modifiedList = Array.from(this.modifiedFiles);
    const createdList = [...this.createdFiles];
    const totalAdded = this.linesAdded;

    // Join the EXACT inserted text chunks from this session for Groq LLM code explanation
    const codeSnippet = this.sessionInsertedCode.join("\n").slice(0, 2000);

    // Count what the language servers report for the touched files right now
    let errorCount = 0;
    let warningCount = 0;
    for (const uri of this.modifiedUris.values()) {
      for (const d of vscode.languages.getDiagnostics(uri)) {
        if (d.severity === vscode.DiagnosticSeverity.Error) errorCount++;
        else if (d.severity === vscode.DiagnosticSeverity.Warning) warningCount++;
      }
    }

    this.emit({
      type: "copilot_complete",
      file: fileName,
      linesAdded: totalAdded,
      linesRemoved: this.linesRemoved,
      modifiedFiles: modifiedList,
      createdFiles: createdList,
      errorCount,
      warningCount,
    });

    // Send milestone to backend with exact inserted code snippet for deep AI explanation narration
    if (this.wsClient) {
      this.wsClient.sendObserverEvent({
        event_type: "copilot_complete",
        file: fileName,
        modified_files: modifiedList,
        created_files: createdList,
        lines_added: totalAdded,
        lines_removed: this.linesRemoved,
        error_count: errorCount,
        warning_count: warningCount,
        code_snippet: codeSnippet,
      });
    }

    // Reset session counters and inserted code buffer for next generation
    this.linesAdded = 0;
    this.linesRemoved = 0;
    this.modifiedFiles.clear();
    this.modifiedUris.clear();
    this.createdFiles = [];
    this.sessionInsertedCode = [];
  }

  // --- Helpers ---------------------------------------------------------------

  private emit(event: CopilotObserverEvent): void {
    console.log(`[CopilotWatcher] Event: ${event.type}`, event);
    this.onEvent(event);
  }

  private shouldIgnorePath(fileName: string): boolean {
    const ignoredSegments = [
      "node_modules", ".git", "__pycache__", ".venv",
      "out/", "dist/", ".next/", "build/",
    ];
    return ignoredSegments.some((seg) => fileName.includes(seg));
  }

  dispose(): void {
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
    for (const d of this.disposables) d.dispose();
    this.disposables = [];
    console.log("[CopilotWatcher] Disposed.");
  }
}
