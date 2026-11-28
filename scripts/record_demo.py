"""
Record the Angizo demo video.

    python scripts/record_demo.py --sandbox <sandbox folder> [--out <folder>] [--no-record]

1. Clones the sandbox playground into <out>/work (its origin is a local bare repo).
2. Starts the real backend (backend/.env keys) with ANGIZO_SPEECH_LOG, so every clip the
   panel plays is saved with the time it was sent.
3. Opens VS Code with the extension and runs angizo-extension/test/demo/scenes.js.
4. Records the screen area of the VS Code window with ffmpeg (gdigrab; capturing the window itself
   gives black frames because VS Code draws with the GPU), stopping when the last scene ends.
5. Builds the soundtrack from the saved clips, placed where they played, and writes
   <out>/angizo-demo.mp4.

Needs ffmpeg on PATH. Uses the real APIs: about 25 short Sarvam requests and 6 Groq calls.
Don't use the computer while it records (about 4 minutes): only the VS Code window is
captured, but anything moved on top of it would be recorded too.
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
EXTENSION = ROOT / "angizo-extension"
TITLE = "Angizo Demo"
PORT = 7001


def remove_tree(path: Path):
    if path.exists():
        shutil.rmtree(path, onerror=lambda f, p, _: (os.chmod(p, stat.S_IWRITE), f(p)))


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def find_vscode() -> str:
    candidates = [
        os.environ.get("VSCODE_PATH", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Microsoft VS Code", "Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys.exit("VS Code not found: set VSCODE_PATH")


def prepare_workspace(sandbox: Path, work: Path) -> Path:
    remove_tree(work)
    work.mkdir(parents=True)
    shutil.copytree(sandbox / "remote.git", work / "remote.git")
    repo = work / "playground"
    git(work, "clone", "-q", str(work / "remote.git"), str(repo))
    hooks = work / "no-hooks"
    hooks.mkdir()
    for key, value in (("user.name", "Angizo Demo"), ("user.email", "demo@example.com"), ("core.hooksPath", str(hooks))):
        git(repo, "config", key, value)
    return repo


def vscode_settings(user_dir: Path):
    settings = {
        "window.title": TITLE,
        "window.newWindowDimensions": "maximized",
        "window.zoomLevel": 1,
        "workbench.colorTheme": "Default Dark Modern",
        "workbench.startupEditor": "none",
        "workbench.tips.enabled": False,
        "workbench.secondarySideBar.defaultVisibility": "hidden",
        "chat.commandCenter.enabled": False,
        "editor.fontSize": 16,
        "editor.minimap.enabled": False,
        "security.workspace.trust.enabled": False,
        "terminal.integrated.shellIntegration.enabled": True,
        "telemetry.telemetryLevel": "off",
        "update.mode": "none",
    }
    (user_dir / "User").mkdir(parents=True, exist_ok=True)
    (user_dir / "User" / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")


def wait_for_health(timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    sys.exit("The backend did not start")


def window_title() -> str:
    """The exact title of the demo window (VS Code may decorate the configured title)."""
    ps = ("Get-Process Code -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*%s*' } "
          "| Select-Object -First 1 -ExpandProperty MainWindowTitle" % TITLE)
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    return out


_RECT_PS = r"""
Add-Type @'
using System; using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  public struct RECT { public int L, T, R, B; }
}
'@
[Win]::SetProcessDPIAware() | Out-Null
$p = Get-Process Code -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*TITLE*' } | Select-Object -First 1
if ($p) {
  Add-Type -AssemblyName System.Windows.Forms
  [Win]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  $r = New-Object Win+RECT
  [Win]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
  $s = [System.Windows.Forms.Screen]::FromHandle($p.MainWindowHandle).WorkingArea
  "$($r.L) $($r.T) $($r.R) $($r.B) $($s.Left) $($s.Top) $($s.Right) $($s.Bottom)"
}
"""


def window_rect():
    """
    (x, y, width, height) of the demo window on screen, in physical pixels. VS Code draws with
    the GPU, so capturing the window itself gives black frames: the recorder captures this
    area of the screen instead (the window is brought to the front first).
    """
    out = subprocess.run(["powershell", "-NoProfile", "-Command", _RECT_PS.replace("TITLE", TITLE)],
                         capture_output=True, text=True).stdout.split()
    if len(out) != 8:
        return None
    w_left, w_top, w_right, w_bottom, s_left, s_top, s_right, s_bottom = (int(v) for v in out)
    # Maximized windows overhang the screen edge: keep only the part on the window's monitor
    left, top = max(w_left, s_left), max(w_top, s_top)
    right, bottom = min(w_right, s_right), min(w_bottom, s_bottom)
    width, height = (right - left) // 2 * 2, (bottom - top) // 2 * 2
    if width <= 0 or height <= 0:
        return None
    return left, top, width, height


def screen_capture_args(rect):
    x, y, w, h = rect
    return ["-f", "gdigrab", "-framerate", "15", "-draw_mouse", "0", "-offset_x", str(x), "-offset_y", str(y),
            "-video_size", f"{w}x{h}", "-i", "desktop"]


def build_soundtrack(video: Path, speech_dir: Path, t0: float, out_file: Path):
    index = speech_dir / "index.jsonl"
    clips = [json.loads(l) for l in index.read_text(encoding="utf-8").splitlines()] if index.exists() else []
    clips = [c for c in clips if c["t"] >= t0 - 1]
    if not clips:
        shutil.copy(video, out_file)
        print("[demo] no speech clips recorded; video has no sound")
        return
    # The panel plays clips one after another: a clip starts when it arrives or when the
    # previous one ends, whichever is later
    schedule, cursor = [], 0.0
    for c in clips:
        with wave.open(str(speech_dir / c["file"])) as w:
            length = w.getnframes() / w.getframerate()
        start = max(c["t"] - t0, cursor)
        schedule.append((speech_dir / c["file"], start))
        cursor = start + length
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video)]
    for path, _ in schedule:
        cmd += ["-i", str(path)]
    parts = [f"[{i + 1}:a]adelay={int(start * 1000)}:all=1[a{i}]" for i, (_, start) in enumerate(schedule)]
    mix = "".join(f"[a{i}]" for i in range(len(schedule)))
    graph = ";".join(parts) + f";{mix}amix=inputs={len(schedule)}:normalize=0:duration=longest,apad[aout]"
    cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "128k", "-shortest", str(out_file)]
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox", default=os.environ.get("ANGIZO_SANDBOX", ""))
    parser.add_argument("--out", default="")
    parser.add_argument("--no-record", action="store_true", help="run the demo without recording")
    args = parser.parse_args()
    sandbox = Path(args.sandbox)
    if not (sandbox / "remote.git").exists():
        sys.exit("--sandbox must be a folder made by scripts/make_sandbox.py")
    out = Path(args.out) if args.out else sandbox / "demo"
    work = out / "work"
    repo = prepare_workspace(sandbox, work)
    speech_dir = work / "speech"
    signal = work / "signal.txt"
    signal.write_text("starting")
    user_dir = work / "vscode-user"
    vscode_settings(user_dir)

    env = {**os.environ, "ANGIZO_SPEECH_LOG": str(speech_dir), "ANGIZO_DEMO_SIGNAL": str(signal)}
    env.pop("ELECTRON_RUN_AS_NODE", None)
    python = BACKEND / ".venv" / "Scripts" / "python.exe"
    backend = subprocess.Popen(
        [str(python if python.exists() else sys.executable), "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(PORT)],
        cwd=BACKEND, env=env, stdout=open(work / "backend.log", "w"), stderr=subprocess.STDOUT,
    )
    recorder = None
    try:
        wait_for_health()
        time.sleep(4)  # let the acknowledgement phrases be cached
        subprocess.run(["npx", "--no-install", "tsc", "-p", "./"], cwd=EXTENSION, check=True, shell=True)
        code = subprocess.Popen(
            [find_vscode(), str(repo), f"--extensionDevelopmentPath={EXTENSION}",
             f"--extensionTestsPath={EXTENSION / 'test' / 'demo' / 'scenes.js'}",
             f"--user-data-dir={user_dir}", f"--extensions-dir={work / 'vscode-ext'}", "--disable-extensions",
             "--skip-welcome", "--skip-release-notes", "--new-window"],
            env=env, stdout=open(work / "vscode.log", "w"), stderr=subprocess.STDOUT,
        )
        for _ in range(240):
            if signal.read_text() == "ready":
                break
            time.sleep(0.5)
        rect = window_rect()
        if rect is None:
            sys.exit("Could not find the demo window to record")
        print(f"[demo] recording screen area {rect} ({window_title()!r})")
        video = work / "screen.mp4"
        t0 = time.time()
        if not args.no_record:
            recorder = subprocess.Popen(
                ["ffmpeg", "-y", "-loglevel", "error", *screen_capture_args(rect), "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", str(video)],
                stdin=subprocess.PIPE,
            )
            time.sleep(1.0)
            t0 = time.time()
        signal.write_text("recording")
        # Stop recording the moment the scenes finish, BEFORE VS Code closes: after it closes,
        # the recorded screen area would show whatever window is underneath.
        deadline = time.time() + 900
        while time.time() < deadline and code.poll() is None and signal.read_text() != "done":
            time.sleep(0.2)
        if recorder:
            try:
                recorder.communicate(b"q", timeout=30)
            except Exception:
                recorder.kill()
            recorder = None
        code.wait(timeout=120)
    finally:
        if recorder:
            try:
                recorder.communicate(b"q", timeout=30)
            except Exception:
                recorder.kill()
        backend.terminate()

    if args.no_record:
        print("[demo] finished (not recorded)")
        return
    final = out / "angizo-demo.mp4"
    build_soundtrack(video, speech_dir, t0, final)
    print(f"[demo] wrote {final}")


if __name__ == "__main__":
    main()
