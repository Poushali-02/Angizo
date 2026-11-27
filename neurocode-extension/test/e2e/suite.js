/**
 * Runs inside the VS Code extension host (see run.js). Drives the real editor, terminal and
 * commands, then checks the messages the Angizo extension sent to the fake backend.
 * Any failed check throws, which makes VS Code exit with code 1.
 */

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

const LOG = process.env.ANGIZO_E2E_LOG;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function messages() {
  return fs.readFileSync(LOG, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
}

/** Wait until a recorded message matches, or fail with what was received. */
async function waitFor(description, predicate, timeoutMs = 15000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const hit = messages().find(predicate);
    if (hit) return hit;
    await sleep(200);
  }
  const seen = messages().map((m) => `${m.type}/${m.event_type || ""}`).join(", ");
  throw new Error(`Timed out waiting for ${description}. Backend received: ${seen || "nothing"}`);
}

function countWhere(predicate) {
  return messages().filter(predicate).length;
}

async function typeSlowly(text) {
  for (const ch of text) {
    await vscode.commands.executeCommand("type", { text: ch });
    await sleep(40);
  }
}

const results = [];
async function check(name, fn) {
  const started = Date.now();
  try {
    await fn();
    results.push(`✔ ${name} (${((Date.now() - started) / 1000).toFixed(1)}s)`);
    console.log(`[e2e] ✔ ${name}`);
  } catch (err) {
    results.push(`✘ ${name}: ${err.message}`);
    console.log(`[e2e] ✘ ${name}: ${err.message}`);
  }
}

exports.run = async function run() {
  const root = vscode.workspace.workspaceFolders[0].uri;
  const file = (name) => vscode.Uri.joinPath(root, name);

  await check("extension connects and sends the workspace path", async () => {
    const msg = await waitFor("set_workspace", (m) => m.type === "set_workspace", 20000);
    assert.strictEqual(path.resolve(msg.workspace_path), path.resolve(root.fsPath));
  });

  await check("manual stream: a syntax error is reported when the cursor leaves its line", async () => {
    const doc = await vscode.workspace.openTextDocument(file("sample.ts"));
    const editor = await vscode.window.showTextDocument(doc);
    editor.selection = new vscode.Selection(1, 0, 1, 0);
    await typeSlowly("const a = ;");
    // Wait for the TypeScript server to flag the error (a cold start can take several seconds)
    const end = Date.now() + 30000;
    while (!vscode.languages.getDiagnostics(doc.uri).some((d) => d.severity === vscode.DiagnosticSeverity.Error)) {
      if (Date.now() > end) throw new Error("TypeScript never reported the syntax error");
      await sleep(250);
    }
    await sleep(500);
    assert.strictEqual(countWhere((m) => m.event_type === "syntax_error"), 0, "must stay quiet while typing on the line");

    editor.selection = new vscode.Selection(0, 0, 0, 0);
    const msg = await waitFor("syntax_error", (m) => m.event_type === "syntax_error" && !m.is_resolved);
    assert.strictEqual(msg.file, "sample.ts");
    assert.strictEqual(msg.line, 2);
    assert.match(msg.error_message, /Expression expected/);
  });

  await check("manual stream: fixing the error announces it is resolved", async () => {
    const editor = vscode.window.activeTextEditor;
    await editor.edit((e) => e.insert(new vscode.Position(1, 10), "1"));
    await editor.document.save();
    await waitFor("resolved syntax_error", (m) => m.event_type === "syntax_error" && m.is_resolved === true);
  });

  await check("Copilot stream: fast multi-line inserts send the code and the error count", async () => {
    const doc = await vscode.workspace.openTextDocument(file("generated.ts"));
    const editor = await vscode.window.showTextDocument(doc);
    const chunks = [
      "export function charge(amount: number): number {\n",
      "  if (amount <= 0) { throw new Error('amount must be positive'); }\n",
      "  return amount * ;\n}\n", // deliberate syntax error
    ];
    for (const c of chunks) {
      await editor.edit((e) => e.insert(doc.lineAt(doc.lineCount - 1).range.end, c));
      await sleep(300);
    }
    const msg = await waitFor("copilot_complete", (m) => m.event_type === "copilot_complete", 20000);
    assert.strictEqual(msg.file, "generated.ts");
    assert.match(msg.code_snippet, /export function charge/);
    assert.ok(msg.lines_added >= 3, `lines_added was ${msg.lines_added}`);
    assert.ok(msg.error_count >= 1, `error_count was ${msg.error_count}; the inserted code has a syntax error`);
  });

  await check("a file you create is announced once, and not credited to Copilot", async () => {
    await sleep(4500); // well past the last AI insert
    fs.writeFileSync(path.join(root.fsPath, "notes.md"), "# notes\n");
    const msg = await waitFor("file_created", (m) => m.event_type === "file_created" && m.file === "notes.md");
    assert.strictEqual(msg.by_ai, false);
    await sleep(3500);
    assert.strictEqual(countWhere((m) => m.event_type === "file_created" && m.file === "notes.md"), 1, "announced twice");
  });

  await check("terminal: a crashing command is caught and sent for explanation", async () => {
    const terminal = vscode.window.createTerminal({ name: "angizo-e2e", cwd: root.fsPath });
    terminal.show();
    const shell = await new Promise((resolve, reject) => {
      if (terminal.shellIntegration) return resolve(terminal.shellIntegration);
      const timer = setTimeout(() => reject(new Error("shell integration never activated in the terminal")), 20000);
      const sub = vscode.window.onDidChangeTerminalShellIntegration((e) => {
        if (e.terminal === terminal) {
          clearTimeout(timer);
          sub.dispose();
          resolve(e.shellIntegration);
        }
      });
    });
    shell.executeCommand('node -e "const o = null; o.x"');
    const msg = await waitFor("runtime_error", (m) => m.event_type === "runtime_error", 20000);
    assert.strictEqual(msg.error_name, "TypeError");
    assert.match(msg.error_message, /Cannot read properties of null/);
    assert.strictEqual(msg.file, "[eval]"); // node -e code has no file name
    assert.strictEqual(msg.line, 1);
  });

  await check("terminal: a command that succeeds is never reported", async () => {
    const before = countWhere((m) => m.event_type === "runtime_error");
    const terminal = vscode.window.activeTerminal;
    terminal.shellIntegration.executeCommand('node -e "console.log(\'TypeError: just text\')"');
    await sleep(5000);
    assert.strictEqual(countWhere((m) => m.event_type === "runtime_error"), before);
  });

  await check("Alt+Y and Alt+N send the confirmation answer to the backend", async () => {
    await vscode.commands.executeCommand("neurocode.confirm");
    await waitFor("confirm yes", (m) => m.type === "confirm_response" && m.confirmed === true);
    await vscode.commands.executeCommand("neurocode.cancel");
    await waitFor("confirm no", (m) => m.type === "confirm_response" && m.confirmed === false);
  });

  await check("the observer mute command silences the Copilot stream", async () => {
    await vscode.commands.executeCommand("neurocode.toggleObserver"); // mute
    const before = countWhere((m) => m.event_type === "copilot_complete");
    const doc = await vscode.workspace.openTextDocument(file("generated.ts"));
    const editor = await vscode.window.showTextDocument(doc);
    await editor.edit((e) => e.insert(doc.lineAt(doc.lineCount - 1).range.end, "// a long comment from the AI\n"));
    await sleep(3000);
    assert.strictEqual(countWhere((m) => m.event_type === "copilot_complete"), before);
    await vscode.commands.executeCommand("neurocode.toggleObserver"); // unmute again
  });

  console.log("\n[e2e] Results:\n" + results.map((r) => "[e2e]   " + r).join("\n"));
  const failed = results.filter((r) => r.startsWith("✘"));
  if (failed.length) throw new Error(`${failed.length} of ${results.length} checks failed`);
};
