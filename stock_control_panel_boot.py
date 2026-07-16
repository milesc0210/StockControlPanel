from __future__ import annotations

import os
import runpy
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

URL = "http://127.0.0.1:8765"
HEALTHCHECK_URL = f"{URL}/api/functions"
STARTUP_TIMEOUT_SECONDS = 25
POLL_INTERVAL_SECONDS = 0.5
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = project_root()
BUNDLE_DIR = bundle_root()
LOG_DIR = BUNDLE_DIR / "logs"
LOG_FILE = LOG_DIR / "stock_control_panel.log"


def emit_message(message: object) -> None:
    text = str(message)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")

    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")
    try:
        print(safe_text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="backslashreplace").decode("ascii"))


def healthcheck_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTHCHECK_URL, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def wait_until_ready() -> bool:
    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if healthcheck_ready():
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return False


def launch_server() -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = LOG_FILE.open("a", encoding="utf-8")
    creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    command = [str(Path(sys.executable).resolve()), str(Path(__file__).resolve()), "--server"]
    if getattr(sys, "frozen", False):
        command = [str(Path(sys.executable).resolve()), "--server"]
    return subprocess.Popen(
        command,
        cwd=str(BASE_DIR),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )


def run_server() -> int:
    os.chdir(BASE_DIR)
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from app import app

    app.run(host="127.0.0.1", port=8765, debug=False)
    return 0


def run_script(relative_script: str, args: list[str]) -> int:
    script_path = (BASE_DIR / relative_script).resolve()
    if not script_path.exists():
        emit_message(f"[StockControlPanel] 找不到腳本：{script_path}")
        return 1

    os.chdir(BASE_DIR)
    sys.argv = [str(script_path), *args]
    sys.path.insert(0, str(script_path.parent))
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

    try:
        runpy.run_path(str(script_path), run_name="__main__")
        return 0
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        if code is None:
            return 0
        emit_message(code)
        return 1


def open_browser() -> int:
    if healthcheck_ready():
        webbrowser.open(URL)
        return 0

    launch_server()
    if not wait_until_ready():
        emit_message(f"[StockControlPanel] 啟動逾時，請檢查記錄檔：{LOG_FILE}")
        return 1

    webbrowser.open(URL)
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--server":
        return run_server()
    if len(sys.argv) >= 3 and sys.argv[1] == "--run-script":
        return run_script(sys.argv[2], sys.argv[3:])
    return open_browser()


if __name__ == "__main__":
    raise SystemExit(main())
