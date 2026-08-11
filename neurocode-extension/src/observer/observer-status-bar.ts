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

  setComplete(linesAdded: number, errorCount: number, fileName: string, source: string = "Copilot"): void {
    const errText = errorCount === 0
      ? "0 errors"
      : `${errorCount} error${errorCount > 1 ? "s" : ""}`;
    
    if (source === "Copilot") {
      this.item.text = `$(check) Copilot: ${linesAdded} lines added · ${errText}`;
    } else {
      this.item.text = `$(check) ${source}: ${errText}`;
    }
    
    this.item.backgroundColor = errorCount > 0
      ? new vscode.ThemeColor("statusBarItem.warningBackground")
      : undefined;
    this.item.accessibilityInformation = {
      label: source === "Copilot" 
        ? `Copilot finished: ${linesAdded} lines added to ${fileName} with ${errText}`
        : `${source} finished in ${fileName} with ${errText}`,
      role: "status",
    };
  }

  setError(errorCount: number, source: string = "Copilot"): void {
    const errorText = `${errorCount} error${errorCount > 1 ? "s" : ""}`;
    this.item.text = `$(warning) ${source}: ${errorText} introduced`;
    this.item.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground"
    );
    this.item.accessibilityInformation = {
      label: `Warning: ${source} introduced ${errorText}`,
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

  getAccessibleLabel(): string {
    return this.item.accessibilityInformation?.label || this.item.text.replace(/\$\([^\)]+\)\s*/g, "");
  }

  private shortName(filePath: string): string {
    return filePath.split(/[\\/]/).pop() || filePath;
  }

  dispose(): void {
    this.item.dispose();
  }
}
