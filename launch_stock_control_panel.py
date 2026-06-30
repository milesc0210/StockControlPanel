from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"
HEALTHCHECK_URL = f"{URL}/api/functions"
STARTUP_TIMEOUT_SECONDS = 20
POLL_INTERVAL_SECONDS = 0.5
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "stock_control_panel.log"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def find_background_python() -> Path:
    candidates = [
        Path(sys.executable).with_name("pythonw.exe"),
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("找不到可用的 Python 執行檔。")


def launch_server() -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = LOG_FILE.open("a", encoding="utf-8")
    python_bin = find_background_python()
    creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    return subprocess.Popen(
        [str(python_bin), "app.py"],
        cwd=str(BASE_DIR),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )


def wait_until_ready() -> bool:
    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTHCHECK_URL, timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(POLL_INTERVAL_SECONDS)
    return False


def main() -> int:
    launch_server()
    if not wait_until_ready():
        print(f"[StockControlPanel] 啟動逾時，請檢查記錄檔：{LOG_FILE}")
        return 1
    webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
