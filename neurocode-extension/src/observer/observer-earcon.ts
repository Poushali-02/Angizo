/**
 * neurocode-extension/src/observer/observer-earcon.ts
 *
 * Earcon controller for the Copilot Observer.
 *
 * The Extension Host sends "play_earcon" postMessages to the webview.
 * The webview synthesizes tones via Web Audio API (OscillatorNode + GainNode)
 * for <5ms latency — no network round-trip.
 *
 * Earcon types:
 *   "start"    - ascending two-tone chime (generation begins)
 *   "tick"     - short single blip (generation alive, every 1s)
 *   "complete" - satisfying high chime (generation done)
 *   "error"    - low double-tone alert (errors introduced)
 */

import * as vscode from "vscode";

export type EarconType = "start" | "tick" | "complete" | "error";

export class ObserverEarcon {
  private panel: vscode.WebviewPanel | undefined;
  private tickTimer: ReturnType<typeof setInterval> | null = null;
  private muted = false;

  constructor(panel?: vscode.WebviewPanel) {
    this.panel = panel;
  }

  setPanel(panel: vscode.WebviewPanel): void {
    this.panel = panel;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    if (muted) this.stopTick();
  }

  /** Play a one-shot earcon in the webview */
  play(type: EarconType, targetPanel?: vscode.WebviewPanel): void {
    if (this.muted) return;
    const p = targetPanel || this.panel;
    if (!p) return;
    p.webview.postMessage({ type: "play_earcon", earconType: type });
  }

  /** Start repeating tick pulse (every 500ms) */
  startTick(targetPanel?: vscode.WebviewPanel): void {
    if (this.muted) return;
    this.stopTick(); // clear any existing
    this.play("tick", targetPanel);
    this.tickTimer = setInterval(() => {
      if (!this.muted) this.play("tick", targetPanel);
    }, 500);
  }

  /** Stop repeating tick pulse */
  stopTick(): void {
    if (this.tickTimer) {
      clearInterval(this.tickTimer);
      this.tickTimer = null;
    }
  }

  dispose(): void {
    this.stopTick();
  }
}
