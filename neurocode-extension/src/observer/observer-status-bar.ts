/**
 * neurocode-extension/src/observer/observer-status-bar.ts
 *
 * Accessible VS Code Status Bar item for the Copilot Observer.
 *
 * Screen readers (NVDA, JAWS, VoiceOver) can read this on-demand
 * via standard shortcuts (Ctrl+Shift+S / Insert+F12).
 *
 * States:
 *   idle        - "$(pulse) NeuroCode Observer"
 *   generating  - "$(loading~spin) Copilot generating in {file}..."
 *   complete    - "$(check) Copilot: {lines} lines added · {errors} errors"
 *   error       - "$(warning) Copilot: {errors} errors introduced"
 *   muted       - "$(mute) NeuroCode Observer [Muted]"
 */

import * as vscode from "vscode";

export class ObserverStatusBar {
  private item: vscode.StatusBarItem;

  constructor() {
    this.item = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100
    );
    this.item.command = "neurocode.toggleObserver";
    this.item.tooltip = "NeuroCode Copilot Observer — click to toggle mute";
    this.setIdle();
    this.item.show();
  }

  setIdle(): void {
    this.item.text = "$(pulse) NeuroCode Observer";
    this.item.backgroundColor = undefined;
    this.item.accessibilityInformation = {
      label: "NeuroCode Observer idle",
      role: "button",
    };
  }

  setGenerating(fileName: string): void {
    this.item.text = `$(loading~spin) Copilot generating in ${this.shortName(fileName)}...`;
    this.item.backgroundColor = undefined;
    this.item.accessibilityInformation = {
      label: `Copilot is generating code in ${fileName}`,
      role: "status",
    };
  }

  setComplete(linesAdded: number, errorCount: number, fileName: string): void {
    const errText = errorCount === 0
      ? "0 errors"
      : `${errorCount} error${errorCount > 1 ? "s" : ""}`;
    this.item.text = `$(check) Copilot: ${linesAdded} lines added · ${errText}`;
    this.item.backgroundColor = errorCount > 0
      ? new vscode.ThemeColor("statusBarItem.warningBackground")
      : undefined;
    this.item.accessibilityInformation = {
      label: `Copilot finished: ${linesAdded} lines added to ${fileName} with ${errText}`,
      role: "status",
    };
  }

  setError(errorCount: number): void {
    this.item.text = `$(warning) Copilot: ${errorCount} error${errorCount > 1 ? "s" : ""} introduced`;
    this.item.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground"
    );
    this.item.accessibilityInformation = {
      label: `Warning: Copilot introduced ${errorCount} error${errorCount > 1 ? "s" : ""}`,
      role: "status",
    };
  }

  setMuted(): void {
    this.item.text = "$(mute) NeuroCode Observer [Muted]";
    this.item.backgroundColor = undefined;
    this.item.accessibilityInformation = {
      label: "NeuroCode Observer is muted. Click to unmute.",
      role: "button",
    };
  }

  private shortName(filePath: string): string {
    return filePath.split(/[\\/]/).pop() || filePath;
  }

  dispose(): void {
    this.item.dispose();
  }
}
