/**
 * angizo-extension/src/angizo-view.ts
 *
 * The Angizo panel as a view in the right (secondary) sidebar, instead of an editor tab.
 *
 * The webview is where audio plays, so it has to exist even when nobody opened the sidebar:
 *   - messages sent before the webview's script is ready are queued and delivered once it says
 *     "webview_ready" (nothing is lost while it loads);
 *   - ensureResolved() creates it once, then hands focus straight back to the editor;
 *   - retainContextWhenHidden keeps it (and its audio) alive when the sidebar is closed.
 */

import * as vscode from "vscode";

const MAX_QUEUED = 100;

export class AngizoView implements vscode.WebviewViewProvider, vscode.Disposable {
  static readonly viewId = "angizo.view";

  private view: vscode.WebviewView | undefined;
  private ready = false;
  private queue: unknown[] = [];
  private resolving: Promise<void> | undefined;
  private readonly received = new vscode.EventEmitter<any>();
  private readonly disposables: vscode.Disposable[] = [this.received];

  /** Messages from the webview (except the internal "webview_ready"). */
  readonly onDidReceiveMessage = this.received.event;

  constructor(
    private readonly renderHtml: (webview: vscode.Webview) => string,
    private readonly localResourceRoots: vscode.Uri[]
  ) {}

  get isResolved(): boolean {
    return !!this.view;
  }

  get isReady(): boolean {
    return this.ready;
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    this.ready = false;
    view.webview.options = { enableScripts: true, localResourceRoots: this.localResourceRoots };
    this.disposables.push(
      view.webview.onDidReceiveMessage((msg) => {
        if (msg && msg.type === "webview_ready") {
          this.ready = true;
          this.flush();
          return;
        }
        this.received.fire(msg);
      }),
      view.onDidDispose(() => {
        this.view = undefined;
        this.ready = false;
      })
    );
    view.webview.html = this.renderHtml(view.webview);
  }

  /** Send a message to the webview, or queue it until the webview is ready. */
  postMessage(message: unknown): void {
    if (this.view && this.ready) {
      void this.view.webview.postMessage(message);
      return;
    }
    const m = message as { type?: string; earconType?: string };
    // A progress tick is only useful live; don't replay a backlog of them.
    if (m && m.type === "play_earcon" && m.earconType === "tick") return;
    this.queue.push(message);
    if (this.queue.length > MAX_QUEUED) this.queue.shift();
    void this.ensureResolved();
  }

  /** Create the view if it doesn't exist yet, without leaving focus in it. */
  ensureResolved(): Promise<void> {
    if (this.view) return Promise.resolve();
    if (!this.resolving) {
      this.resolving = (async () => {
        const hadEditor = !!vscode.window.activeTextEditor;
        try {
          await vscode.commands.executeCommand(`${AngizoView.viewId}.focus`);
        } finally {
          if (hadEditor) {
            await vscode.commands.executeCommand("workbench.action.focusActiveEditorGroup");
          }
          this.resolving = undefined;
        }
      })();
    }
    return this.resolving;
  }

  /** Show the sidebar view (the user asked for it, so focus may move there). */
  async reveal(preserveFocus: boolean): Promise<void> {
    if (this.view) {
      this.view.show(preserveFocus);
    } else if (preserveFocus) {
      await this.ensureResolved();
    } else {
      await vscode.commands.executeCommand(`${AngizoView.viewId}.focus`);
    }
  }

  private flush(): void {
    const pending = this.queue;
    this.queue = [];
    for (const message of pending) void this.view?.webview.postMessage(message);
  }

  dispose(): void {
    for (const d of this.disposables) d.dispose();
    this.disposables.length = 0;
  }
}
