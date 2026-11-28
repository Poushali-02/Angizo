/**
 * angizo-extension/src/observer/observer-earcon.ts
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

/** Anything that can carry a message to the webview (the Angizo sidebar view). */
export interface MessageTarget {
  postMessage(message: unknown): unknown;
}

export type EarconType = "start" | "tick" | "complete" | "error";

export class ObserverEarcon {
  private panel: MessageTarget | undefined;
  private tickTimer: ReturnType<typeof setInterval> | null = null;
  private muted = false;

  constructor(panel?: MessageTarget) {
    this.panel = panel;
  }

  setPanel(panel: MessageTarget): void {
    this.panel = panel;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    if (muted) this.stopTick();
  }

  /** Play a one-shot earcon in the webview */
  play(type: EarconType, targetPanel?: MessageTarget): void {
    if (this.muted) return;
    const p = targetPanel || this.panel;
    if (!p) return;
    p.postMessage({ type: "play_earcon", earconType: type });
  }

  /** Start repeating tick pulse (every 1s) */
  startTick(targetPanel?: MessageTarget): void {
    if (this.muted) return;
    this.stopTick(); // clear any existing
    this.play("tick", targetPanel);
    this.tickTimer = setInterval(() => {
      if (!this.muted) this.play("tick", targetPanel);
    }, 1000);
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
