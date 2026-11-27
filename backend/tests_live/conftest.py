"""
Live tests: real Groq / Gemini / Sarvam / ElevenLabs calls with the keys in backend/.env.

    ANGIZO_LIVE=1 python -m pytest tests_live -s          (add ANGIZO_LIVE_MIC=1 for the microphone)

Skipped unless ANGIZO_LIVE=1, so they never run by accident or in CI. Every git action happens
in a fresh clone of the sandbox playground (scripts/make_sandbox.py), whose "origin" is a local
bare repo, so push and pull never reach GitHub. A report of every LLM answer and its latency
is written to <sandbox>/runs/live/report.md.
"""

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

LIVE = os.environ.get("ANGIZO_LIVE") == "1"
MIC = os.environ.get("ANGIZO_LIVE_MIC") == "1"


def pytest_collection_modifyitems(config, items):
    if LIVE:
        return
    skip = pytest.mark.skip(reason="live API test: set ANGIZO_LIVE=1 to run")
    for item in items:
        item.add_marker(skip)


def remove_tree(path: Path) -> None:
    """Delete a folder even when git has marked its object files read-only (Windows)."""
    def make_writable_and_retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if path.exists():
        shutil.rmtree(path, onerror=make_writable_and_retry)


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="session")
def sandbox() -> Path:
    path = os.environ.get("ANGIZO_SANDBOX")
    if path:
        return Path(path)
    # No sandbox configured: build a private one for this run
    tmp = BACKEND_DIR / ".live-sandbox"
    subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "make_sandbox.py"), str(tmp)], check=True)
    return tmp


@pytest.fixture(scope="session")
def live_dir(sandbox) -> Path:
    d = sandbox / "runs" / "live"
    remove_tree(d)
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def playground(sandbox, live_dir, request, monkeypatch):
    """A fresh clone of the sandbox playground, with its own copy of the bare origin."""
    import tools.git_tool as git_tool

    case = live_dir / request.node.name.replace("[", "_").replace("]", "").replace(" ", "_")[:60]
    remove_tree(case)
    shutil.copytree(sandbox / "remote.git", case / "remote.git")
    subprocess.run(["git", "clone", "-q", str(case / "remote.git"), str(case / "repo")], check=True)
    repo = case / "repo"
    run_git(repo, "config", "user.name", "Angizo Live Test")
    run_git(repo, "config", "user.email", "live@example.com")
    hooks = case / "no-hooks"
    hooks.mkdir()
    run_git(repo, "config", "core.hooksPath", str(hooks))
    (repo / ".env").write_text("PAYMENT_API_KEY=fake-sandbox-key-not-a-secret\n")
    monkeypatch.setattr(git_tool, "_session_repo_path", str(repo))
    return repo


class Report:
    """Collects what each live call returned, for a human to read afterwards."""

    def __init__(self):
        self.rows = []

    def add(self, area: str, case: str, seconds: float, output: str, verdict: str = "ok"):
        self.rows.append((area, case, seconds, " ".join(str(output).split())[:300], verdict))

    def timed(self, area: str, case: str):
        report = self

        class _Timer:
            def __enter__(self):
                self.start = time.perf_counter()
                return self

            def done(self, output, verdict="ok"):
                report.add(area, case, time.perf_counter() - self.start, output, verdict)

            def __exit__(self, *exc):
                return False

        return _Timer()

    def write(self, path: Path):
        lines = ["# Angizo live test report", "", "| Area | Case | Seconds | Verdict | Output |", "|---|---|---|---|---|"]
        for area, case, secs, out, verdict in self.rows:
            lines.append(f"| {area} | {case} | {secs:.1f} | {verdict} | {out.replace('|', '/')} |")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


_report = Report()


@pytest.fixture(scope="session")
def report(live_dir):
    yield _report
    _report.write(live_dir / "report.md")
    print(f"\n[live] report written to {live_dir / 'report.md'}")
