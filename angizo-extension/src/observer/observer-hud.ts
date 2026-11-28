/**
 * angizo-extension/src/observer/observer-hud.ts
 *
 * Floating 1-line HUD banner at the top of the active text editor.
 * Uses TextEditorDecorationType to overlay a non-intrusive status
 * message during Copilot code generation.
 *
 * WCAG 2.1 AAA compliant: high-contrast cyan on deep charcoal background.
 * Auto-hides 3 seconds after generation completes.
 */

import * as vscode from "vscode";

export class ObserverHud {
  private decorationType: vscode.TextEditorDecorationType;
  private errorDecorationType: vscode.TextEditorDecorationType;
  private hideTimer: ReturnType<typeof setTimeout> | null = null;
  private currentMessage = "";

  constructor() {
    this.decorationType = vscode.window.createTextEditorDecorationType({
      isWholeLine: true,
      after: {
        contentText: "",
        color: "#00FFFF",          // Cyan text for high contrast
        backgroundColor: "#1a1a2e", // Deep charcoal background
        fontStyle: "normal",
        fontWeight: "600",
        border: "1px solid #00FFFF33",
        margin: "0 0 4px 0",
      },
    });

    this.errorDecorationType = vscode.window.createTextEditorDecorationType({
      isWholeLine: false,
      after: {
        contentText: " ⚠️ Angizo extension found error",
        color: "#FF4D4D",           // Vivid high-contrast red
        backgroundColor: "#2D1515", // Dark red tint
        fontWeight: "bold",
        fontStyle: "italic",
        margin: "0 0 0 12px",
        border: "1px solid #FF4D4D",
      },
    });
  }

  /** Show the HUD banner on the first line of the active editor */
  show(message: string): void {
    this.currentMessage = message;
    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
      this.hideTimer = null;
    }
    this.applyToActiveEditor(`  ⚡ ${message}`);
  }

  /** Display inline editor decoration 'Angizo extension found error' on target line */
  showInlineError(line: number): void {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;

    const targetLineIdx = Math.max(0, line - 1);
    if (targetLineIdx >= editor.document.lineCount) return;

    const lineObj = editor.document.lineAt(targetLineIdx);
    const range = new vscode.Range(lineObj.range.start, lineObj.range.end);

    editor.setDecorations(this.errorDecorationType, [{ range }]);
  }

  /** Clear inline error decoration */
  clearInlineError(): void {
    vscode.window.visibleTextEditors.forEach((editor) => {
      editor.setDecorations(this.errorDecorationType, []);
    });
  }

  /** Hide the HUD after a 3s delay */
  scheduleHide(): void {
    if (this.hideTimer) clearTimeout(this.hideTimer);
    this.hideTimer = setTimeout(() => {
      this.hide();
      this.hideTimer = null;
    }, 3000);
  }

  /** Immediately hide the HUD from all editors */
  hide(): void {
    vscode.window.visibleTextEditors.forEach((editor) => {
      editor.setDecorations(this.decorationType, []);
    });
    this.currentMessage = "";
  }

  private applyToActiveEditor(text: string): void {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;

    // Place decoration on line 0 (top of file) — shows above line 1
    const firstLine = editor.document.lineAt(0);
    const range = new vscode.Range(firstLine.range.start, firstLine.range.end);

    // Rebuild decoration type with the current message text
    // (VS Code doesn't allow dynamic after.contentText on existing types)
    editor.setDecorations(this.decorationType, [
      {
        range,
        renderOptions: {
          after: {
            contentText: text,
            color: "#00FFFF",
            backgroundColor: "#1a1a2e",
            fontWeight: "600",
            border: "1px solid #00FFFF33",
          },
        },
      },
    ]);
  }

  dispose(): void {
    if (this.hideTimer) clearTimeout(this.hideTimer);
    this.hide();
    this.clearInlineError();
    this.decorationType.dispose();
    this.errorDecorationType.dispose();
  }
}

