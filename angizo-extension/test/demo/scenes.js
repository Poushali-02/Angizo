/**
 * The Angizo demo, scene by scene. Runs inside VS Code (scripts/record_demo.py launches it)
 * against the REAL backend, in a throwaway clone of the sandbox playground.
 *
 * Each step waits for Angizo to finish speaking: the backend saves every clip it sends to
 * ANGIZO_SPEECH_LOG (index.jsonl), so the script waits for new clips and their length
 * instead of guessing with fixed sleeps.
 */

const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

const SPEECH_LOG = process.env.ANGIZO_SPEECH_LOG;
const SIGNAL = process.env.ANGIZO_DEMO_SIGNAL;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function clips() {
  const index = path.join(SPEECH_LOG, "index.jsonl");
  if (!fs.existsSync(index)) return [];
  return fs.readFileSync(index, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
}

function wavSeconds(file) {
  try {
    const buf = fs.readFileSync(path.join(SPEECH_LOG, file));
    const byteRate = buf.readUInt32LE(28);
    return byteRate ? (buf.length - 44) / byteRate : 2;
  } catch {
    return 2;
  }
}

/** Wait until `count` new clips were spoken, then for them to finish playing (plus a beat). */
async function waitForSpeech(count, sinceIndex, timeoutMs = 60000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end && clips().length < sinceIndex + count) await sleep(250);
  // Let any follow-up clip (the second half of a long reply) arrive too
  let last = clips().length;
  for (let quiet = 0; quiet < 10; quiet++) {
    await sleep(300);
    if (clips().length !== last) { last = clips().length; quiet = 0; }
  }
  const spoken = clips().slice(sinceIndex);
  const playing = spoken.reduce((sum, c) => sum + wavSeconds(c.file), 0);
  const elapsedSinceFirst = spoken.length ? Date.now() / 1000 - spoken[0].t : 0;
  await sleep(Math.max(0, playing - elapsedSinceFirst) * 1000 + 1200);
}

async function caption(text, ms = 2500) {
  vscode.window.showInformationMessage(text);
  await sleep(ms);
}

async function typeSlowly(text, delay = 70) {
  for (const ch of text) {
    await vscode.commands.executeCommand("type", { text: ch });
    await sleep(delay);
  }
}

async function say(command) {
  const before = clips().length;
  await vscode.commands.executeCommand("angizo.runCommand", command);
  return before;
}

async function answer(yes) {
  const before = clips().length;
  await vscode.commands.executeCommand(yes ? "angizo.confirm" : "angizo.cancel");
  return before;
}

function git(cwd, ...args) {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}

exports.run = async function run() {
  const root = vscode.workspace.workspaceFolders[0].uri;
  const repo = root.fsPath;

  // Tidy window: no chat sidebar, Angizo panel open
  await vscode.commands.executeCommand("workbench.action.closeAuxiliaryBar").then(undefined, () => {});
  await vscode.commands.executeCommand("workbench.action.closeAllEditors");
  await vscode.commands.executeCommand("angizo.startVoiceInput");
  await sleep(4000); // let the extension connect to the backend

  // Tell the recorder the window is ready, and wait until it is recording
  fs.writeFileSync(SIGNAL, "ready");
  for (let i = 0; i < 120 && fs.readFileSync(SIGNAL, "utf8") !== "recording"; i++) await sleep(250);
  await sleep(1000);

  await caption("Angizo: an audio assistant in VS Code for blind and low-vision developers.", 4000);

  // ── Scene 1: a syntax error is spoken when you leave the line, then "resolved" ──
  await caption("1 · Manual coding: Angizo speaks syntax errors when you leave the line.");
  const appTs = await vscode.workspace.openTextDocument(vscode.Uri.joinPath(root, "app.ts"));
  const editor = await vscode.window.showTextDocument(appTs, vscode.ViewColumn.One);
  const end = appTs.lineCount;
  editor.selection = new vscode.Selection(end, 0, end, 0);
  await typeSlowly("\nconst discount = ;");
  for (let i = 0; i < 60 && !vscode.languages.getDiagnostics(appTs.uri).some((d) => d.severity === 0); i++) await sleep(250);
  let mark = clips().length;
  await vscode.commands.executeCommand("cursorUp"); // leave the line
  await waitForSpeech(1, mark);
  const errLine = editor.document.lineCount - 1;
  editor.selection = new vscode.Selection(errLine, 17, errLine, 17);
  mark = clips().length;
  await typeSlowly("10");
  await vscode.commands.executeCommand("cursorUp");
  await waitForSpeech(1, mark);

  // ── Scene 2: Copilot-style code arriving in big chunks gets a one-line summary ──
  await caption("2 · Copilot observer: AI-written code is summarised in one sentence.");
  mark = clips().length;
  const chunks = [
    "\n\nexport function applyCoupon(total: number, percent: number): number {\n",
    "  if (percent < 0 || percent > 100) {\n    throw new Error('invalid coupon');\n  }\n",
    "  return Math.round(total * (1 - percent / 100) * 100) / 100;\n}\n",
  ];
  for (const c of chunks) {
    await editor.edit((e) => e.insert(editor.document.lineAt(editor.document.lineCount - 1).range.end, c));
    await sleep(350);
  }
  await waitForSpeech(1, mark);
  await editor.document.save();

  // ── Scene 3: a crash in the terminal is explained ──
  await caption("3 · Terminal: when a program crashes, Angizo explains why.");
  const terminal = vscode.window.createTerminal({ name: "demo", cwd: repo });
  terminal.show();
  const shell = await new Promise((resolve) => {
    if (terminal.shellIntegration) return resolve(terminal.shellIntegration);
    const sub = vscode.window.onDidChangeTerminalShellIntegration((e) => {
      if (e.terminal === terminal) { sub.dispose(); resolve(e.shellIntegration); }
    });
    setTimeout(() => resolve(null), 20000);
  });
  mark = clips().length;
  if (shell) shell.executeCommand("node crash.js");
  else terminal.sendText("node crash.js");
  await waitForSpeech(1, mark);

  // ── Scene 4: voice Git agent, read-only ──
  await caption("4 · Git by voice: \"review my diff\".");
  mark = await say("review my diff");
  await waitForSpeech(2, mark);

  // ── Scene 5: commit, with a spoken yes ──
  await caption("5 · \"commit my changes\": Angizo reads the files and message, then waits for a yes.");
  mark = await say("commit my changes");
  await waitForSpeech(2, mark);
  await caption("Pressing Alt+Y (yes).", 1500);
  mark = await answer(true);
  await waitForSpeech(2, mark);

  // ── Scene 6: the recovery loop ──
  await caption("6 · A teammate pushed first. Watch the agent recover from the rejected push.");
  const teammate = path.join(path.dirname(repo), "teammate");
  if (!fs.existsSync(teammate)) {
    git(path.dirname(repo), "clone", "-q", git(repo, "remote", "get-url", "origin"), teammate);
  }
  fs.writeFileSync(path.join(teammate, "TEAM.md"), "Notes from a teammate\n");
  git(teammate, "add", ".");
  git(teammate, "-c", "user.name=Teammate", "-c", "user.email=t@example.com", "commit", "-q", "-m", "docs: add team notes");
  git(teammate, "push", "-q", "origin", "main");

  mark = await say("push my branch");
  await waitForSpeech(2, mark);
  await caption("Alt+Y: push.", 1500);
  mark = await answer(true);
  await waitForSpeech(2, mark); // rejected: "Should I pull them and push again?"
  await caption("Alt+Y: pull, merge and push again.", 1500);
  mark = await answer(true);
  await waitForSpeech(2, mark);

  await caption("Angizo: the LLM plans, code acts, and nothing changes without a spoken yes.", 5000);
  fs.writeFileSync(SIGNAL, "done");
};
