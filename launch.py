"""One-click launcher for SmallBiz Finance Agent.

Started by start.bat (Windows) / start.command (macOS) / start.sh (Linux), which create a private
Python environment in .venv and run this file with it. This script:
  1. installs or updates the packages when requirements change,
  2. on Windows, adds a "SmallBiz Finance" shortcut to the desktop (first run only),
  3. starts the API and the dashboard, waits until both answer, and opens the browser,
  4. stops everything when you close the window or press Ctrl+C.

Only the standard library is used here, so it can run before anything is installed.
Options: --no-browser, --no-shortcut, --api-port N, --ui-port N
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = [ROOT / "requirements.txt", ROOT / "dashboard" / "requirements.txt"]
# Kept in the project folder: sys.prefix is read-only when run with a system-wide Python.
MARKER = ROOT / "data" / ".packages.sha256"
APP_NAME = "SmallBiz Finance Agent"


def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def requirements_hash() -> str:
    h = hashlib.sha256(sys.executable.encode())
    for path in REQUIREMENTS:
        h.update(path.read_bytes())
    return h.hexdigest()


def ensure_packages() -> None:
    wanted = requirements_hash()
    if MARKER.exists() and MARKER.read_text().strip() == wanted:
        return
    say("Installing / updating packages (first run takes a few minutes)...")
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    for req in REQUIREMENTS:
        cmd += ["-r", str(req)]
    if subprocess.call(cmd) != 0:
        raise SystemExit(
            "\n  Package installation failed. Check your internet connection and try again."
        )
    with contextlib.suppress(OSError):
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text(wanted)
    say("Packages ready.")


def create_windows_shortcut() -> None:
    if os.name != "nt":
        return
    desktop = Path(os.environ.get("USERPROFILE", "~")).expanduser() / "Desktop"
    link = desktop / "SmallBiz Finance.lnk"
    if link.exists() or not desktop.exists():
        return
    target = ROOT / "start.bat"
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:SBFA_LINK);"
        "$s.TargetPath=$env:SBFA_TARGET;$s.WorkingDirectory=$env:SBFA_DIR;"
        '$s.IconLocation="$env:SystemRoot\\System32\\imageres.dll,109";'
        f"$s.Description='{APP_NAME}';$s.Save()"
    )
    env = {**os.environ, "SBFA_LINK": str(link), "SBFA_TARGET": str(target), "SBFA_DIR": str(ROOT)}
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            env=env,
            check=True,
            capture_output=True,
            timeout=30,
        )
        say('Added a "SmallBiz Finance" shortcut to your desktop.')
    except (OSError, subprocess.SubprocessError):
        pass  # a missing shortcut is not worth failing the launch for


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url: str, proc: subprocess.Popen | None, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


def _install_signal_handlers() -> None:
    """Treat 'terminal closed' / 'terminate' like Ctrl+C so child processes are stopped."""

    def handler(_signum, _frame):
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with contextlib.suppress(OSError, ValueError):
                signal.signal(sig, handler)
    with contextlib.suppress(OSError, ValueError):
        signal.signal(signal.SIGINT, signal.default_int_handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"Start {APP_NAME}")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-shortcut", action="store_true")
    ap.add_argument("--api-port", type=int, default=int(os.getenv("API_PORT", "8000")))
    ap.add_argument("--ui-port", type=int, default=int(os.getenv("UI_PORT", "8501")))
    args = ap.parse_args(argv)

    if sys.version_info < (3, 10):  # noqa: UP036 - clear message for old Pythons
        raise SystemExit("  Python 3.10 or newer is required.")
    os.chdir(ROOT)
    _install_signal_handlers()
    print(f"\n  === {APP_NAME} ===\n", flush=True)
    ensure_packages()
    if not args.no_shortcut:
        create_windows_shortcut()

    api_url = f"http://127.0.0.1:{args.api_port}"
    ui_url = f"http://localhost:{args.ui_port}"
    env = {**os.environ, "API_URL": api_url, "PYTHONUNBUFFERED": "1"}
    api = ui = None
    try:
        if port_open(args.api_port):
            if wait_for(f"{api_url}/health", None, 3):
                say(f"API already running on port {args.api_port} — reusing it.")
            else:
                raise SystemExit(f"  Port {args.api_port} is used by another program.")
        else:
            say("Starting the API...")
            api = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "finagent.main:app",
                 "--host", "127.0.0.1", "--port", str(args.api_port), "--log-level", "warning"],
                cwd=ROOT, env=env,
            )  # fmt: skip
            if not wait_for(f"{api_url}/health", api, 90):
                raise SystemExit("  The API did not start. See the messages above.")

        if port_open(args.ui_port):
            raise SystemExit(
                f"  Port {args.ui_port} is already in use — is the app already open? Try {ui_url}"
            )
        say("Starting the dashboard...")
        ui = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "app.py"),
             "--server.port", str(args.ui_port), "--server.headless", "true",
             "--server.address", "127.0.0.1",  # this computer only — there is no login yet
             "--browser.gatherUsageStats", "false", "--logger.level", "warning"],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL,  # hide Streamlit's own banner
        )  # fmt: skip
        if not wait_for(f"http://127.0.0.1:{args.ui_port}/_stcore/health", ui, 90):
            raise SystemExit("  The dashboard did not start. See the messages above.")

        print(f"\n  Ready!  Open {ui_url} in your browser.", flush=True)
        print(
            "  Keep this window open while you use the app. Close it (or press Ctrl+C) to stop.\n"
        )
        if not args.no_browser:
            webbrowser.open(ui_url)

        while (api is None or api.poll() is None) and ui.poll() is None:
            time.sleep(1)
        say("A component stopped unexpectedly — shutting down.")
        return 1
    except KeyboardInterrupt:
        say("Stopping...")
        return 0
    finally:
        stop(ui)
        stop(api)


if __name__ == "__main__":
    sys.exit(main())
