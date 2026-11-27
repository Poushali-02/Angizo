"""
Build (or rebuild) the Angizo testing sandbox.

    python scripts/make_sandbox.py <sandbox folder>

Creates:
    <sandbox>/
        playground/     a small git project to point Angizo at (manual demos, live tests)
        remote.git/     a bare repo acting as playground's "origin", so push and pull are safe to test
        runs/           scratch space every test suite writes into (wiped per run)
        run-tests.ps1   runs all suites against this sandbox
        README.md

Rebuilding wipes playground/, remote.git/ and runs/; nothing outside the sandbox is touched.
"""

import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

ANGIZO_REPO = Path(__file__).resolve().parent.parent

PLAYGROUND_FILES = {
    "README.md": "# Playground\n\nA tiny project for testing Angizo. Edit, break and commit anything here.\n",
    ".gitignore": ".env\n__pycache__/\nnode_modules/\n",
    ".env": "PAYMENT_API_KEY=fake-sandbox-key-not-a-secret\n",
    "auth.py": textwrap.dedent('''\
        def check(user, password):
            return user == "admin" and password == "hunter2"


        def login(user, password):
            return check(user, password)
        '''),
    "payment.py": textwrap.dedent('''\
        def charge(amount, card):
            if amount <= 0:
                raise ValueError("amount must be positive")
            return {"card": card[-4:], "amount": amount}
        '''),
    "app.ts": textwrap.dedent('''\
        export function total(prices: number[]): number {
          return prices.reduce((sum, p) => sum + p, 0);
        }
        '''),
    "crash.js": "const order = null;\nconsole.log(order.id);\n",
    "crash.py": "def main():\n    items = []\n    return items[0]\n\n\nmain()\n",
}


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def remove(path: Path) -> None:
    if path.exists():
        # git marks object files read-only on Windows
        shutil.rmtree(path, onerror=lambda f, p, _: (Path(p).chmod(stat.S_IWRITE), f(p)))


def build(sandbox: Path) -> None:
    sandbox.mkdir(parents=True, exist_ok=True)
    for name in ("playground", "remote.git", "runs"):
        remove(sandbox / name)

    remote = sandbox / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)

    play = sandbox / "playground"
    play.mkdir()
    git(play, "init", "-q", "-b", "main")
    git(play, "config", "user.name", "Angizo Sandbox")
    git(play, "config", "user.email", "sandbox@example.com")
    hooks = sandbox / "runs" / "no-hooks"
    hooks.mkdir(parents=True)
    git(play, "config", "core.hooksPath", str(hooks))  # global commit hooks never run here
    for name, text in PLAYGROUND_FILES.items():
        (play / name).write_text(text, encoding="utf-8")
    git(play, "add", ".")
    git(play, "commit", "-q", "-m", "Initial playground project")
    git(play, "remote", "add", "origin", str(remote))
    git(play, "push", "-q", "-u", "origin", "main")

    (sandbox / "run-tests.ps1").write_text(RUN_TESTS.replace("{ANGIZO_REPO}", str(ANGIZO_REPO)), encoding="utf-8")
    (sandbox / "README.md").write_text(README.replace("{ANGIZO_REPO}", str(ANGIZO_REPO)), encoding="utf-8")
    print(f"Sandbox ready at {sandbox}")


RUN_TESTS = r'''# Runs every Angizo test suite inside this sandbox.
#   .\run-tests.ps1            offline suites only (no API keys used)
#   .\run-tests.ps1 -Live      also the live LLM, voice and microphone tests (uses your API keys)
param([switch]$Live, [switch]$Mic)
$ErrorActionPreference = "Stop"
$env:ANGIZO_SANDBOX = $PSScriptRoot
$repo = "{ANGIZO_REPO}"
$py = Join-Path $repo "backend\.venv\Scripts\python.exe"

Write-Host "`n== Backend (offline) ==" -ForegroundColor Cyan
Push-Location (Join-Path $repo "backend"); & $py -m pytest; $backend = $LASTEXITCODE; Pop-Location

Write-Host "`n== VS Code end-to-end ==" -ForegroundColor Cyan
Push-Location (Join-Path $repo "neurocode-extension"); npm run -s test:e2e; $e2e = $LASTEXITCODE; Pop-Location

$live = 0
if ($Live) {
  Write-Host "`n== Live LLM and voice ==" -ForegroundColor Cyan
  $env:ANGIZO_LIVE = "1"
  if ($Mic) { $env:ANGIZO_LIVE_MIC = "1" }
  Push-Location (Join-Path $repo "backend"); & $py -m pytest tests_live -s; $live = $LASTEXITCODE; Pop-Location
}

Write-Host "`nbackend=$backend e2e=$e2e live=$live"
exit ([int]($backend -ne 0 -or $e2e -ne 0 -or $live -ne 0))
'''

README = '''# Angizo sandbox

Everything Angizo is tested against lives here, never in a real project.

| Folder | What it is |
|---|---|
| `playground/` | A small git project (Python, TypeScript, a crashing `crash.js`/`crash.py`, a fake `.env`). Open it in VS Code with Angizo for manual demos. |
| `remote.git/` | A bare repo acting as playground's `origin`, so "push" and "pull" by voice are safe. |
| `runs/` | Scratch space the test suites write into. Safe to delete. |

## Run the tests

```powershell
.\\run-tests.ps1          # offline: backend pytest + VS Code end-to-end
.\\run-tests.ps1 -Live    # + live Groq/Sarvam/ElevenLabs tests (uses backend/.env keys)
.\\run-tests.ps1 -Live -Mic   # + microphone: plays a phrase on the speakers and records it
```

## Rebuild from scratch

```powershell
python "{ANGIZO_REPO}\\scripts\\make_sandbox.py" "$PWD"
```
'''

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(Path(sys.argv[1]).resolve())
