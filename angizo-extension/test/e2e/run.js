#!/usr/bin/env node
/**
 * End-to-end test for the Angizo VS Code extension.
 *
 *   npm run test:e2e
 *
 * 1. Starts a fake Angizo backend (a WebSocket server) that records every message the extension sends.
 * 2. Creates a throwaway git workspace.
 * 3. Launches the VS Code installed on this machine with the extension loaded from this folder,
 *    and runs suite.js inside it. suite.js makes real edits and checks what reached the backend.
 *
 * Needs no API keys, no Python backend and no network. A VS Code window opens for about a minute.
 * Set VSCODE_PATH if VS Code is not installed in the default location.
 */

const { spawn, execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { WebSocketServer } = require("ws");

const EXTENSION_DIR = path.resolve(__dirname, "..", "..");

function findVSCode() {
  if (process.env.VSCODE_PATH) return process.env.VSCODE_PATH;
  const candidates = {
    win32: [
      path.join(process.env.LOCALAPPDATA || "", "Programs", "Microsoft VS Code", "Code.exe"),
      "C:\\Program Files\\Microsoft VS Code\\Code.exe",
    ],
    darwin: ["/Applications/Visual Studio Code.app/Contents/MacOS/Electron"],
    linux: ["/usr/share/code/code", "/usr/bin/code", "/snap/code/current/usr/share/code/code"],
  }[process.platform] || [];
  const found = candidates.find((p) => p && fs.existsSync(p));
  if (!found) {
    console.error("VS Code not found. Set VSCODE_PATH to the VS Code executable.");
    process.exit(2);
  }
  return found;
}

function makeWorkspace(root) {
  const ws = path.join(root, "workspace");
  fs.mkdirSync(ws, { recursive: true });
  const git = (...args) => execFileSync("git", args, { cwd: ws, stdio: "ignore" });
  git("init", "-q", "-b", "main");
  git("config", "user.name", "Angizo E2E");
  git("config", "user.email", "e2e@example.com");
  fs.writeFileSync(path.join(ws, "sample.ts"), "const ok = 1;\n\n");
  fs.writeFileSync(path.join(ws, "generated.ts"), "");
  fs.writeFileSync(path.join(ws, ".gitignore"), ".env\n");
  git("add", ".");
  git("commit", "-q", "--no-verify", "-m", "init");
  return ws;
}

/** Fake backend: records messages, answers like the real one where the extension waits for a reply. */
function startFakeBackend(logFile) {
  return new Promise((resolve) => {
    const server = new WebSocketServer({ port: 0, host: "127.0.0.1" }, () => resolve(server));
    server.on("connection", (socket) => {
      socket.on("message", (raw) => {
        let msg;
        try {
          msg = JSON.parse(raw.toString());
        } catch {
          return;
        }
        fs.appendFileSync(logFile, JSON.stringify({ at: Date.now(), ...msg }) + "\n");
        const reply = (m) => socket.send(JSON.stringify(m));
        if (msg.type === "set_workspace") {
          reply({ type: "workspace_ack", status: "success", detail: `Workspace set to ${msg.workspace_path}` });
        } else if (msg.type === "confirm_response") {
          reply(msg.confirmed
            ? { type: "action_result", status: "success", detail: "Committed 1 file." }
            : { type: "action_result", status: "cancelled", detail: "Action cancelled by user." });
        } else if (msg.type === "manual_observer_event" || msg.type === "copilot_observer_event") {
          reply({ type: "audio_narration", channel: "observer", narration: `fake narration for ${msg.event_type}`, audio_base64: "" });
        }
      });
    });
  });
}

async function main() {
  // With ANGIZO_SANDBOX set (scripts/make_sandbox.py), everything goes in <sandbox>/runs/e2e
  let root;
  if (process.env.ANGIZO_SANDBOX) {
    root = path.join(process.env.ANGIZO_SANDBOX, "runs", "e2e");
    fs.rmSync(root, { recursive: true, force: true });
    fs.mkdirSync(root, { recursive: true });
  } else {
    root = fs.mkdtempSync(path.join(os.tmpdir(), "angizo-e2e-"));
  }
  const logFile = path.join(root, "backend-messages.jsonl");
  fs.writeFileSync(logFile, "");
  const workspace = makeWorkspace(root);
  const server = await startFakeBackend(logFile);
  const port = server.address().port;
  console.log(`[e2e] fake backend on ws://127.0.0.1:${port}, workspace ${workspace}`);

  const args = [
    workspace,
    `--extensionDevelopmentPath=${EXTENSION_DIR}`,
    `--extensionTestsPath=${path.join(__dirname, "suite.js")}`,
    `--user-data-dir=${path.join(root, "user-data")}`,
    `--extensions-dir=${path.join(root, "extensions")}`,
    "--disable-extensions", // other extensions off; built-in TypeScript support stays on
    "--disable-workspace-trust",
    "--skip-welcome",
    "--skip-release-notes",
    "--new-window",
  ];
  const env = { ...process.env, ANGIZO_WS_PORT: String(port), ANGIZO_E2E_LOG: logFile };
  delete env.ELECTRON_RUN_AS_NODE;

  const code = await new Promise((resolve) => {
    const child = spawn(findVSCode(), args, { env, stdio: ["ignore", "pipe", "pipe"] });
    const relay = (chunk) => {
      for (const line of chunk.toString().split(/\r?\n/)) {
        if (/\[(e2e|TerminalWatcher|ManualWatcher|CopilotWatcher|ws-client)\]|✔|✘|Error/.test(line)) console.log(line);
      }
    };
    child.stdout.on("data", relay);
    child.stderr.on("data", relay);
    child.on("exit", (c) => resolve(c ?? 1));
  });

  server.close();
  console.log(code === 0 ? "[e2e] PASSED" : `[e2e] FAILED (exit code ${code}); messages: ${logFile}`);
  process.exit(code);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
