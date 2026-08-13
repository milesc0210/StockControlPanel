from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request
import requests

import chip_dashboard

BASE_DIR = Path(__file__).resolve().parent
MILES_AGENT_ROOT = BASE_DIR
SCRIPTS_DIR = BASE_DIR / "scripts"
DATA_ROOT = BASE_DIR / "data"
OUTPUT_ROOT = BASE_DIR / "outputs"
DB_PATH = BASE_DIR / "stock_control_panel.db"
ENV_FILE_PATH = BASE_DIR / ".env"
PYTHON_BIN = sys.executable
IS_FROZEN = bool(getattr(sys, "frozen", False))
GITHUB_REPO_OWNER = "milesc0210"
GITHUB_REPO_NAME = "StockControlPanel"
GITHUB_ZIP_URL = f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/archive/refs/heads/main.zip"
GITHUB_RAW_BASE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/main"
LOCAL_PRESERVE_NAMES = {".env", "stock_control_panel.db", ".git", ".venv", "Release"}
UPDATE_TRACKED_PATHS = [
    "app.py",
    "chip_dashboard.py",
    "requirements.txt",
    "README.md",
    "FORCED_SECTOR_GROUPS.md",
    "RELEASING.md",
    "build_portable_exe.py",
    "stock_control_panel_boot.py",
    "templates/index.html",
    "static/app.js",
    "static/style.css",
    "scripts/analyze_012_sector_groups.py",
    "scripts/fetch_klines.py",
    "scripts/analyze_today_limitup_sector_groups.py",
    "scripts/screen_today_limitup.py",
    "scripts/screen_new_high_black_volume_contraction.py",
    "scripts/screen_low_base_turnaround.py",
    "scripts/pre_breakout_screen.py",
    "scripts/analyze_pre_breakout_sector_groups.py",
    "scripts/pre_breakout_backtest.py",
    "scripts/twse_tpex_fetch.py",
    "scripts/backfill_tdcc_week.py",
]


def _strip_env_value(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text



def load_env_file(path: Path = ENV_FILE_PATH, override: bool = False) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = _strip_env_value(value)


load_env_file()


def build_script_command(script_path: Path, *args: str) -> list[str]:
    if IS_FROZEN:
        relative_path = script_path.resolve().relative_to(MILES_AGENT_ROOT.resolve()).as_posix()
        return [PYTHON_BIN, "--run-script", relative_path, *args]
    return [PYTHON_BIN, str(script_path), *args]


OUTPUT_WATCH_DIRS = [
    OUTPUT_ROOT,
    DATA_ROOT / "pre_breakout",
]
PRE_BREAKOUT_FUNCTION_KEYS = {"pre_breakout_standard", "pre_breakout_conservative"}
BACKTESTABLE_FUNCTION_KEYS = PRE_BREAKOUT_FUNCTION_KEYS
INTRADAY_FUNCTION_KEYS = {
    "new_high_black_volume_contraction",
    "low_base_turnaround",
    "pre_breakout_standard",
    "pre_breakout_conservative",
    "ma_bullish_turning_point",
    "limit_up_red_arrow",
}
DIRECT_CURRENT_INTRADAY_FUNCTION_KEYS = {
    "new_high_black_volume_contraction",
    "pre_breakout_standard",
}
NEW_HIGH_BLACK_MIN_VOLUME_LOTS = 1000
FEAR_GREED_FUNCTION_KEY = "cnn_fear_greed_index"
CUSTOM_SECTOR_FUNCTION_KEY = "custom_stock_sectors"
CHIP_DASHBOARD_FUNCTION_KEY = "chip_dashboard"
CNN_FEAR_GREED_URL = "https://www.cnn.com/markets/fear-and-greed"
CNN_FEAR_GREED_API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
TW_MM_FEAR_GREED_URL = "https://www.macromicro.me/charts/50108/tw-market-fear-and-greed"
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
INTRADAY_QUOTE_CACHE_TTL_SECONDS = 20
FEAR_GREED_CACHE_TTL_SECONDS = 15 * 60
KLINE_CACHE_MAX_ENTRIES = 256
AUTO_FETCH_CUTOFF = dt_time(15, 0)
intraday_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
market_data_sync_lock = threading.Lock()
fear_greed_cache_lock = threading.Lock()
kline_cache_lock = threading.Lock()
chip_dashboard_sync_lock = threading.Lock()
chip_bundle_imported = False
chip_stock_history_lock = threading.Lock()
chip_stock_history_jobs: set[str] = set()
chip_institutional_job_lock = threading.Lock()
chip_institutional_job_running = False
fear_greed_cache_state: dict[str, Any] = {"fetched_at": 0.0, "payload": None}
kline_payload_cache: OrderedDict[tuple[str, str, int], dict[str, Any]] = OrderedDict()
market_data_sync_state: dict[str, Any] = {
    "status": "idle",
    "message": "尚未檢查最新資料",
    "checked_for": None,
    "last_run": None,
    "fetched": False,
}

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


@app.after_request
def add_security_headers(response: Any) -> Any:
    if request.path.endswith(".js") and response.mimetype == "text/plain":
        response.mimetype = "application/javascript"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@dataclass(frozen=True)
class FunctionSpec:
    key: str
    name: str
    category: str
    description: str
    executable: bool


FUNCTIONS: list[FunctionSpec] = [
    FunctionSpec(
        key=CHIP_DASHBOARD_FUNCTION_KEY,
        name="台股籌碼分析儀表板",
        category="籌碼分析",
        description="整合每週集保大戶持股、三大法人與自訂族群分類，查看排行榜、9 週趨勢及族群強弱。",
        executable=False,
    ),
    FunctionSpec(
        key=FEAR_GREED_FUNCTION_KEY,
        name="美國 / 台灣 恐懼與貪婪指數",
        category="市場情緒",
        description="同頁查看美國 CNN 與台灣 MM 的恐懼與貪婪指數。",
        executable=False,
    ),
    FunctionSpec(
        key=CUSTOM_SECTOR_FUNCTION_KEY,
        name="自訂股票族群",
        category="自訂功能",
        description="只顯示主人建立的手動股票族群，每個族群一個區塊。",
        executable=False,
    ),
    FunctionSpec(
        key="limit_up_red_arrow",
        name="漲停紅箭",
        category="訊號型功能",
        description="前一日漲停，最近一日上引紅。",
        executable=True,
    ),
    FunctionSpec(
        key="today_limit_up",
        name="今日漲停",
        category="訊號型功能",
        description="指定日期收盤漲停，且成交量大於 2000 張。",
        executable=True,
    ),
    FunctionSpec(
        key="new_high_black_volume_contraction",
        name="創高黑量縮",
        category="訊號型功能",
        description="前一交易日創 30 日新高且上引收黑；指定交易日確認未再創高、量縮、成交量至少 1000 張且收盤不低於 MA5 的 -5%，盤中則用即時行情確認。",
        executable=True,
    ),
    FunctionSpec(
        key="ma_bullish_turning_point",
        name="均線多頭新成形",
        category="訊號型功能",
        description="均線多頭剛成形。",
        executable=True,
    ),
    FunctionSpec(
        key="low_base_turnaround",
        name="低基期選股",
        category="主流程執行",
        description="依目前市場環境找相對低基期、且近期開始轉強的股票；不使用一年低點。",
        executable=True,
    ),
    FunctionSpec(
        key="pre_breakout_standard",
        name="標準選股",
        category="主流程執行",
        description="標準模式。",
        executable=True,
    ),
    FunctionSpec(
        key="pre_breakout_conservative",
        name="保守選股",
        category="主流程執行",
        description="保守模式。",
        executable=True,
    ),
]
FUNCTION_MAP = {item.key: item for item in FUNCTIONS}
CACHEABLE_FUNCTION_KEYS = {item.key for item in FUNCTIONS if item.executable}
SERENITY_FUNCTION_KEYS = CACHEABLE_FUNCTION_KEYS
SERENITY_MAX_STOCKS = 30
SERENITY_TIMEOUT_SECONDS = 900
SERENITY_FAST_MAX_TURNS = 12
SERENITY_FAST_TIMEOUT_SECONDS = 480
SERENITY_MAX_PARALLEL_WORKERS = 3


def resolve_pre_breakout_script() -> Path:
    candidates: list[Path] = []

    env_path = os.environ.get("PRE_BREAKOUT_SCRIPT")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    candidates.append(SCRIPTS_DIR / "pre_breakout_screen.py")

    for candidate in candidates:
        candidate = candidate.expanduser()
        if candidate.exists():
            return candidate

    searched = "\n- ".join(str(path) for path in candidates)
    raise RuntimeError(
        "找不到 pre_breakout_screen.py。請確認 scripts/pre_breakout_screen.py 存在，"
        "或設定 PRE_BREAKOUT_SCRIPT 環境變數。已搜尋：\n- "
        f"{searched}"
    )


def normalize_field_name(name: str) -> str:
    return (
        str(name)
        .replace(" ", "")
        .replace("<br>", "")
        .replace("<br/>", "")
        .replace("<br />", "")
        .strip()
    )


def is_valid_twse_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    fields = [normalize_field_name(x) for x in payload.get("fields", [])]
    required = {"證券代號", "證券名稱", "成交股數", "收盤價"}
    return required.issubset(set(fields)) and bool(payload.get("data"))


def is_valid_tpex_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    tables = payload.get("tables", [])
    if not tables:
        return False
    table = tables[0]
    fields = [normalize_field_name(x) for x in table.get("fields", [])]
    required = {"代號", "名稱", "成交股數", "收盤"}
    return required.issubset(set(fields)) and bool(table.get("data"))


def valid_shared_dates() -> list[str]:
    twse_dir = MILES_AGENT_ROOT / "data" / "twse" / "2026"
    tpex_dir = MILES_AGENT_ROOT / "data" / "tpex" / "2026"
    twse_dates = {path.stem for path in twse_dir.glob("*.json") if is_valid_twse_file(path)}
    tpex_dates = {path.stem for path in tpex_dir.glob("*.json") if is_valid_tpex_file(path)}
    return sorted(twse_dates.intersection(tpex_dates))


def latest_valid_shared_date() -> str:
    common_dates = valid_shared_dates()
    if not common_dates:
        raise RuntimeError("找不到可用的 TWSE/TPEX 共同有效交易日。")
    return common_dates[-1]



def fetch_twse_holiday_schedule(year: int) -> list[list[str]]:
    url = (
        "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
        f"?response=json&queryYear={year}"
    )
    headers = {"User-Agent": "Mozilla/5.0", "accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("stat") != "ok":
        raise RuntimeError(f"TWSE 行事曆回傳異常：{payload.get('stat')}")
    return payload.get("data", []) or []



def trading_dates_for_year(year: int) -> list[str]:
    holiday_rows = fetch_twse_holiday_schedule(year)
    non_trading: set[str] = set()
    for row in holiday_rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        date_text = str(row[0]).strip().replace("-", "")
        name = str(row[1]).strip()
        note = str(row[2]).strip() if len(row) > 2 else ""
        combined = f"{name} {note}"
        if any(keyword in combined for keyword in ["無交易", "放假", "補假", "停止交易"]):
            non_trading.add(date_text)

    current = datetime(year, 1, 1)
    end = datetime(year, 12, 31)
    dates: list[str] = []
    while current <= end:
        ymd = current.strftime("%Y%m%d")
        if current.weekday() < 5 and ymd not in non_trading:
            dates.append(ymd)
        current += timedelta(days=1)
    return dates



def expected_latest_market_date(now: datetime | None = None) -> str | None:
    current = now or taipei_now()
    trading_dates = trading_dates_for_year(current.year)
    if not trading_dates:
        return None

    today = current.strftime("%Y%m%d")
    if today in trading_dates and current.time() >= AUTO_FETCH_CUTOFF:
        return today

    earlier_dates = [date for date in trading_dates if date < today]
    if earlier_dates:
        return earlier_dates[-1]
    return None


def missing_market_dates_through(expected_date: str) -> list[str]:
    shared_dates = valid_shared_dates()
    if not shared_dates:
        return [expected_date]

    first_local_date = shared_dates[0]
    available = set(shared_dates)
    unavailable = known_unavailable_market_dates()
    trading_dates = trading_dates_for_year(int(expected_date[:4]))
    return [
        date
        for date in trading_dates
        if first_local_date <= date <= expected_date
        and date not in available
        and date not in unavailable
    ]



def current_data_sync_status() -> dict[str, Any]:
    return dict(market_data_sync_state)



def ensure_latest_market_data() -> dict[str, Any]:
    now = taipei_now()
    try:
        expected_date = expected_latest_market_date(now)
        missing_dates = missing_market_dates_through(expected_date) if expected_date else []
    except Exception as exc:
        status = {
            "status": "error",
            "message": f"最新資料檢查失敗：{exc}",
            "checked_for": None,
            "last_run": now.isoformat(timespec="seconds"),
            "fetched": False,
        }
        market_data_sync_state.update(status)
        return status

    if not expected_date:
        status = {
            "status": "skipped",
            "message": "目前無需自動補抓最新資料",
            "checked_for": None,
            "last_run": now.isoformat(timespec="seconds"),
            "fetched": False,
        }
        market_data_sync_state.update(status)
        return status

    if not missing_dates:
        latest_local = valid_shared_dates()[-1] if valid_shared_dates() else None
        status = {
            "status": "up_to_date",
            "message": f"交易日資料已完整（最新 {latest_local}）",
            "checked_for": expected_date,
            "last_run": now.isoformat(timespec="seconds"),
            "fetched": False,
            "missing_dates": [],
        }
        market_data_sync_state.update(status)
        return status

    with market_data_sync_lock:
        missing_dates = missing_market_dates_through(expected_date)
        if not missing_dates:
            latest_local = valid_shared_dates()[-1] if valid_shared_dates() else None
            status = {
                "status": "up_to_date",
                "message": f"交易日資料已完整（最新 {latest_local}）",
                "checked_for": expected_date,
                "last_run": now.isoformat(timespec="seconds"),
                "fetched": False,
                "missing_dates": [],
            }
            market_data_sync_state.update(status)
            return status

        fetched_dates: list[str] = []
        skipped_dates: list[str] = []
        failed_dates: list[str] = []
        commands: list[list[str]] = []
        failure_messages: list[str] = []
        for missing_date in missing_dates:
            command = build_script_command(SCRIPTS_DIR / "twse_tpex_fetch.py", missing_date)
            commands.append(command)
            child_env = os.environ.copy()
            child_env.setdefault("PYTHONUTF8", "1")
            child_env.setdefault("PYTHONIOENCODING", "utf-8")
            result = subprocess.run(
                command,
                cwd=MILES_AGENT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=child_env,
            )
            output = (result.stdout or result.stderr or "").strip()
            date_is_valid = missing_date in set(valid_shared_dates())
            if result.returncode == 0 and date_is_valid:
                fetched_dates.append(missing_date)
                continue
            is_confirmed_historical_closure = (
                missing_date < expected_date
                and "TWSE:找不到 16 欄的股票資料表" in output
                and "TPEX:資料為空" in output
            )
            if is_confirmed_historical_closure:
                remember_unavailable_market_date(missing_date, output)
                skipped_dates.append(missing_date)
                continue
            failed_dates.append(missing_date)
            failure_messages.append(f"{missing_date}: {output[:160]}")

        all_ok = not failed_dates
        status_name = "fetched" if fetched_dates and all_ok else "up_to_date" if all_ok else "failed"
        if failed_dates:
            message = f"部分交易日補抓失敗：{'；'.join(failure_messages)}"
        elif fetched_dates:
            message = f"已自動補齊 {len(fetched_dates)} 個交易日：{', '.join(fetched_dates)}"
        else:
            message = f"已確認休市日期：{', '.join(skipped_dates)}"
        status = {
            "status": status_name,
            "message": message,
            "checked_for": expected_date,
            "last_run": now.isoformat(timespec="seconds"),
            "fetched": bool(fetched_dates) and all_ok,
            "fetched_dates": fetched_dates,
            "skipped_dates": skipped_dates,
            "failed_dates": failed_dates,
            "missing_dates": missing_dates,
            "commands": commands,
            "returncode": 0 if all_ok else 1,
        }
        market_data_sync_state.update(status)
        return status



def get_date_window(end_date: str, lookback_days: int = 60) -> list[str]:
    common_dates = valid_shared_dates()
    if not common_dates:
        raise RuntimeError("找不到可用的 TWSE/TPEX 共同有效交易日。")
    if end_date not in common_dates:
        raise RuntimeError(f"指定日期 {end_date} 不在可用交易日清單內。")
    end_index = common_dates.index(end_date)
    start_index = max(0, end_index - lookback_days + 1)
    return common_dates[start_index : end_index + 1]


def parse_num(value: Any) -> float:
    return float(str(value).replace(",", "").strip())


def parse_twse_stock_row(row: list[Any], fields: list[str]) -> tuple[str, dict[str, Any]] | None:
    required = ["證券代號", "證券名稱", "開盤價", "最高價", "最低價", "收盤價", "成交股數"]
    try:
        index_map = {name: fields.index(name) for name in required}
        code = str(row[index_map["證券代號"]]).strip()
        return code, {
            "name": str(row[index_map["證券名稱"]]).strip(),
            "open": parse_num(row[index_map["開盤價"]]),
            "high": parse_num(row[index_map["最高價"]]),
            "low": parse_num(row[index_map["最低價"]]),
            "close": parse_num(row[index_map["收盤價"]]),
            "volume": int(parse_num(row[index_map["成交股數"]]) / 1000),
        }
    except Exception:
        return None


def parse_tpex_stock_row(row: list[Any], fields: list[str]) -> tuple[str, dict[str, Any]] | None:
    required = ["代號", "名稱", "收盤", "開盤", "最高", "最低", "成交股數"]
    try:
        index_map = {name: fields.index(name) for name in required}
        code = str(row[index_map["代號"]]).strip()
        return code, {
            "name": str(row[index_map["名稱"]]).strip(),
            "open": parse_num(row[index_map["開盤"]]),
            "high": parse_num(row[index_map["最高"]]),
            "low": parse_num(row[index_map["最低"]]),
            "close": parse_num(row[index_map["收盤"]]),
            "volume": int(parse_num(row[index_map["成交股數"]]) / 1000),
        }
    except Exception:
        return None


def find_stock_market(code: str, end_date: str, lookback_days: int = 60) -> tuple[str, str] | None:
    for current_date in reversed(get_date_window(end_date, lookback_days=lookback_days)):
        twse_path = MILES_AGENT_ROOT / "data" / "twse" / "2026" / f"{current_date}.json"
        if twse_path.exists() and is_valid_twse_file(twse_path):
            payload = json.loads(twse_path.read_text(encoding="utf-8"))
            fields = [normalize_field_name(x) for x in payload.get("fields", [])]
            for row in payload.get("data", []):
                parsed = parse_twse_stock_row(row, fields)
                if parsed and parsed[0] == code:
                    return "twse", parsed[1]["name"]

        tpex_path = MILES_AGENT_ROOT / "data" / "tpex" / "2026" / f"{current_date}.json"
        if tpex_path.exists() and is_valid_tpex_file(tpex_path):
            payload = json.loads(tpex_path.read_text(encoding="utf-8"))
            table = payload.get("tables", [{}])[0]
            fields = [normalize_field_name(x) for x in table.get("fields", [])]
            for row in table.get("data", []):
                parsed = parse_tpex_stock_row(row, fields)
                if parsed and parsed[0] == code:
                    return "tpex", parsed[1]["name"]
    return None


def build_kline_rows(code: str, end_date: str, lookback_days: int = 60) -> dict[str, Any]:
    market_info = find_stock_market(code, end_date, lookback_days)
    if not market_info:
        raise RuntimeError(f"找不到股票代號 {code} 的市場資料。")

    market, stock_name = market_info
    date_window = get_date_window(end_date, lookback_days=lookback_days)
    base_dir = MILES_AGENT_ROOT / "data" / market / "2026"
    rows: list[dict[str, Any]] = []

    for current_date in date_window:
        path = base_dir / f"{current_date}.json"
        if market == "twse":
            if not is_valid_twse_file(path):
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            fields = [normalize_field_name(x) for x in payload.get("fields", [])]
            source_rows = payload.get("data", [])
            parser = lambda item: parse_twse_stock_row(item, fields)
        else:
            if not is_valid_tpex_file(path):
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            table = payload.get("tables", [{}])[0]
            fields = [normalize_field_name(x) for x in table.get("fields", [])]
            source_rows = table.get("data", [])
            parser = lambda item: parse_tpex_stock_row(item, fields)

        for row in source_rows:
            parsed = parser(row)
            if not parsed or parsed[0] != code:
                continue
            rows.append(
                {
                    "date": current_date,
                    "open": parsed[1]["open"],
                    "high": parsed[1]["high"],
                    "low": parsed[1]["low"],
                    "close": parsed[1]["close"],
                    "volume": parsed[1]["volume"],
                }
            )
            break

    if not rows:
        raise RuntimeError(f"股票代號 {code} 在 {end_date} 前 {lookback_days} 個交易日內沒有可用 K 線資料。")

    return {
        "code": code,
        "name": stock_name,
        "market": market.upper(),
        "rows": rows,
    }



def kline_cache_key(code: str, end_date: str, lookback_days: int) -> tuple[str, str, int]:
    return (str(code).strip(), str(end_date).strip(), int(lookback_days))



def get_cached_kline_payload(code: str, end_date: str, lookback_days: int) -> dict[str, Any] | None:
    key = kline_cache_key(code=code, end_date=end_date, lookback_days=lookback_days)
    with kline_cache_lock:
        cached = kline_payload_cache.get(key)
        if cached is None:
            return None
        kline_payload_cache.move_to_end(key)
        return deepcopy(cached)



def set_cached_kline_payload(code: str, end_date: str, lookback_days: int, payload: dict[str, Any]) -> dict[str, Any]:
    key = kline_cache_key(code=code, end_date=end_date, lookback_days=lookback_days)
    snapshot = deepcopy(payload)
    with kline_cache_lock:
        kline_payload_cache[key] = snapshot
        kline_payload_cache.move_to_end(key)
        while len(kline_payload_cache) > KLINE_CACHE_MAX_ENTRIES:
            kline_payload_cache.popitem(last=False)
    return deepcopy(snapshot)



def build_full_kline_payload(code: str, end_date: str, lookback_days: int = 60) -> dict[str, Any]:
    cached = get_cached_kline_payload(code=code, end_date=end_date, lookback_days=lookback_days)
    if cached is not None:
        return cached

    payload = build_kline_rows(code=code, end_date=end_date, lookback_days=lookback_days)
    rows = payload["rows"]
    closes = [float(item["close"]) for item in rows]
    payload["ma5"] = moving_average(closes, 5)
    payload["ma10"] = moving_average(closes, 10)
    payload["ma20"] = moving_average(closes, 20)
    payload["end_date"] = end_date
    payload["count"] = len(rows)
    payload["start_date"] = rows[0]["date"]
    return set_cached_kline_payload(code=code, end_date=end_date, lookback_days=lookback_days, payload=payload)



def build_kline_batch_rows(codes: list[str], end_date: str, lookback_days: int = 40) -> dict[str, Any]:
    requested_codes = [str(code).strip() for code in codes if str(code).strip()]
    if not requested_codes:
        return {}

    date_window = get_date_window(end_date, lookback_days=lookback_days)
    requested_set = set(requested_codes)
    rows_by_code: dict[str, list[dict[str, Any]]] = {code: [] for code in requested_codes}
    market_by_code: dict[str, str] = {}
    name_by_code: dict[str, str] = {}

    for current_date in date_window:
        twse_path = MILES_AGENT_ROOT / "data" / "twse" / "2026" / f"{current_date}.json"
        if is_valid_twse_file(twse_path):
            payload = json.loads(twse_path.read_text(encoding="utf-8"))
            fields = [normalize_field_name(x) for x in payload.get("fields", [])]
            for row in payload.get("data", []):
                parsed = parse_twse_stock_row(row, fields)
                if not parsed:
                    continue
                code, stock = parsed
                if code not in requested_set:
                    continue
                market_by_code.setdefault(code, "twse")
                name_by_code.setdefault(code, stock["name"])
                rows_by_code[code].append(
                    {
                        "date": current_date,
                        "open": stock["open"],
                        "high": stock["high"],
                        "low": stock["low"],
                        "close": stock["close"],
                        "volume": stock["volume"],
                    }
                )

        tpex_path = MILES_AGENT_ROOT / "data" / "tpex" / "2026" / f"{current_date}.json"
        if is_valid_tpex_file(tpex_path):
            payload = json.loads(tpex_path.read_text(encoding="utf-8"))
            table = payload.get("tables", [{}])[0]
            fields = [normalize_field_name(x) for x in table.get("fields", [])]
            for row in table.get("data", []):
                parsed = parse_tpex_stock_row(row, fields)
                if not parsed:
                    continue
                code, stock = parsed
                if code not in requested_set:
                    continue
                market_by_code.setdefault(code, "tpex")
                name_by_code.setdefault(code, stock["name"])
                rows_by_code[code].append(
                    {
                        "date": current_date,
                        "open": stock["open"],
                        "high": stock["high"],
                        "low": stock["low"],
                        "close": stock["close"],
                        "volume": stock["volume"],
                    }
                )

    result: dict[str, Any] = {}
    for code in requested_codes:
        rows = rows_by_code.get(code) or []
        if not rows:
            result[code] = {"error": f"股票代號 {code} 在 {end_date} 前 {lookback_days} 個交易日內沒有可用 K 線資料。"}
            continue

        result[code] = {
            "code": code,
            "name": name_by_code.get(code, ""),
            "market": market_by_code.get(code, "").upper(),
            "rows": rows,
            "count": len(rows),
            "start_date": rows[0]["date"],
            "end_date": end_date,
        }

    return result


def load_market(result_date: str) -> dict[str, dict[str, Any]]:
    """Load one day's TWSE/TPEX rows keyed by stock code.

    The custom-sector page needs the complete manual group membership, not only
    stocks that pass the MA screen.  This small loader therefore reuses the
    existing row parsers without applying any screening rule.
    """
    result: dict[str, dict[str, Any]] = {}
    for market in ("twse", "tpex"):
        path = MILES_AGENT_ROOT / "data" / market / "2026" / f"{result_date}.json"
        if market == "twse":
            if not is_valid_twse_file(path):
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            fields = [normalize_field_name(x) for x in payload.get("fields", [])]
            source_rows = payload.get("data", [])
            parser = lambda row: parse_twse_stock_row(row, fields)
        else:
            if not is_valid_tpex_file(path):
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            table = payload.get("tables", [{}])[0]
            fields = [normalize_field_name(x) for x in table.get("fields", [])]
            source_rows = table.get("data", [])
            parser = lambda row: parse_tpex_stock_row(row, fields)

        for source_row in source_rows:
            parsed = parser(source_row)
            if not parsed:
                continue
            code, stock = parsed
            result[code] = {
                **stock,
                "code": code,
                "market": market.upper(),
                "date": result_date,
            }
    return result


def load_custom_sector_rules() -> list[tuple[str, set[str]]]:
    """Return manually maintained sector rules in classifier precedence order."""
    script_path = SCRIPTS_DIR / "analyze_012_sector_groups.py"
    module_name = "_stock_control_panel_custom_sector_rules"
    module_spec = importlib.util.spec_from_file_location(module_name, script_path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"無法載入自訂族群規則：{script_path}")

    scripts_path = str(SCRIPTS_DIR)
    path_added = scripts_path not in sys.path
    if path_added:
        sys.path.insert(0, scripts_path)
    try:
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    finally:
        if path_added:
            sys.path.remove(scripts_path)

    rules: list[tuple[str, set[str]]] = []
    for name, codes in getattr(module, "THEME_RULES", []):
        normalized_codes = {
            "".join(ch for ch in str(code).strip() if ch.isdigit())
            for code in codes
            if "".join(ch for ch in str(code).strip() if ch.isdigit())
        }
        if normalized_codes:
            rules.append((str(name), normalized_codes))
    return rules


def _custom_sector_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _custom_sector_rank_score(
    volume_ratio: float,
    close_price: float,
    ma5: float,
    ma10: float,
    ma20: float,
) -> float:
    """Keep the MA page's score formula for the shared custom-sector columns."""
    volume_score = min(max(volume_ratio - 1.0, 0.0), 3.0) * 2.0
    ma_spread_pct = ((ma5 - ma10) + (ma10 - ma20)) / close_price * 100 if close_price > 1e-9 else 0.0
    spread_score = min(max(ma_spread_pct, 0.0), 5.0) * 1.2
    return round(4.0 + volume_score + spread_score, 2)


def _custom_sector_future_days(
    rows: list[dict[str, Any]],
    result_date: str,
    current_close: float,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if current_close <= 0:
        return []
    ordered_rows = sorted(rows, key=lambda row: str(row.get("date", "")))
    future_rows = [row for row in ordered_rows if str(row.get("date", "")) > result_date]
    result: list[dict[str, Any]] = []
    previous_close = current_close
    for row in future_rows[:limit]:
        close = _custom_sector_number(row.get("close"))
        if close is None or close <= 0:
            continue
        result.append(
            {
                "date": str(row.get("date", "")),
                "close": f"{close:.2f}",
                "pctFromSignal": f"{(close / current_close - 1) * 100:+.2f}%",
                "pctFromPrev": f"{(close / previous_close - 1) * 100:+.2f}%",
            }
        )
        previous_close = close
    return result


def build_custom_sector_rankings(groups: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    """Rank manual groups by the average of their available stock ranking scores."""
    ranked: list[dict[str, Any]] = []
    for group_index, group in enumerate(groups):
        scores = [
            score
            for stock in group.get("stocks", [])
            if (score := _custom_sector_number(stock.get("rankScore"))) is not None
        ]
        average_score = round(sum(scores) / len(scores), 2) if scores else None
        group["averageRankScore"] = average_score
        if average_score is None:
            continue
        ranked.append(
            {
                "name": str(group.get("name") or "—"),
                "averageRankScore": average_score,
                "count": int(group.get("count") or len(group.get("stocks", []))),
                "groupIndex": group_index,
            }
        )

    ranked.sort(key=lambda item: (-item["averageRankScore"], item["groupIndex"]))
    for rank, item in enumerate(ranked[:limit], start=1):
        item["rank"] = rank
    return ranked[:limit]


def build_custom_sector_payload(result_date: str) -> dict[str, Any]:
    """Build every manual group, retaining the MA page's stock-row fields."""
    common_dates = valid_shared_dates()
    if result_date not in common_dates:
        raise RuntimeError(f"指定日期 {result_date} 不在可用交易日清單內。")

    rules = load_custom_sector_rules()
    all_codes: list[str] = []
    seen_codes: set[str] = set()
    for _, codes in rules:
        for code in sorted(codes):
            if code not in seen_codes:
                seen_codes.add(code)
                all_codes.append(code)

    date_index = common_dates.index(result_date)
    future_dates = common_dates[date_index + 1 : date_index + 6]
    data_end_date = future_dates[-1] if future_dates else result_date
    lookback_days = 60 if future_dates else 40
    kline_items = build_kline_batch_rows(all_codes, end_date=data_end_date, lookback_days=lookback_days)
    market_items = load_market(result_date)

    stock_payloads: dict[str, dict[str, Any]] = {}
    for code in all_codes:
        item = kline_items.get(code) or {}
        market_item = market_items.get(code) or {}
        rows = sorted(item.get("rows") or [], key=lambda row: str(row.get("date", "")))
        historical_rows = [row for row in rows if str(row.get("date", "")) <= result_date]
        current_row = next(
            (row for row in historical_rows if str(row.get("date", "")) == result_date),
            None,
        )
        if current_row is None and market_item:
            current_row = {
                "date": result_date,
                "open": market_item.get("open"),
                "high": market_item.get("high"),
                "low": market_item.get("low"),
                "close": market_item.get("close"),
                "volume": market_item.get("volume"),
            }
            historical_rows.append(current_row)
            historical_rows.sort(key=lambda row: str(row.get("date", "")))
        elif current_row is None and historical_rows:
            current_row = historical_rows[-1]

        name = str(item.get("name") or market_item.get("name") or "—")
        market = str(item.get("market") or market_item.get("market") or "—")
        current_close = _custom_sector_number((current_row or {}).get("close"))
        current_volume = _custom_sector_number((current_row or {}).get("volume"))
        previous_row = historical_rows[-2] if len(historical_rows) >= 2 else None
        previous_volume = _custom_sector_number((previous_row or {}).get("volume"))
        volume_ratio = current_volume / previous_volume if current_volume is not None and previous_volume and previous_volume > 0 else None

        close_values = [
            number
            for number in (_custom_sector_number(row.get("close")) for row in historical_rows)
            if number is not None
        ]
        ma5 = sum(close_values[-5:]) / 5 if len(close_values) >= 5 else None
        ma10 = sum(close_values[-10:]) / 10 if len(close_values) >= 10 else None
        ma20 = sum(close_values[-20:]) / 20 if len(close_values) >= 20 else None
        rank_score = (
            _custom_sector_rank_score(volume_ratio, current_close, ma5, ma10, ma20)
            if volume_ratio is not None and current_close and ma5 is not None and ma10 is not None and ma20 is not None
            else None
        )

        stock_payloads[code] = {
            "code": code,
            "name": name,
            "market": market,
            "rankScore": f"{rank_score:.2f}" if rank_score is not None else "",
            "close": f"{current_close:.2f}" if current_close is not None else "",
            "volume": str(int(current_volume)) if current_volume is not None else "",
            "multiple": f"{volume_ratio:.2f}" if volume_ratio is not None else "",
            "futureDays": _custom_sector_future_days(rows, result_date, current_close or 0.0),
        }

    groups: list[dict[str, Any]] = []
    claimed_codes: set[str] = set()
    for group_name, codes in rules:
        members = []
        for code in sorted(codes):
            if code in claimed_codes:
                continue
            claimed_codes.add(code)
            members.append(stock_payloads[code])
        groups.append({"name": group_name, "count": len(members), "stocks": members})

    rankings = build_custom_sector_rankings(groups)
    return {
        "result_date": result_date,
        "groups": groups,
        "rankings": rankings,
        "group_count": len(groups),
        "stock_count": sum(group["count"] for group in groups),
    }


def moving_average(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < period:
            result.append(None)
            continue
        window = values[index - period + 1 : index + 1]
        result.append(round(sum(window) / period, 2))
    return result


def resolve_target_date(spec: FunctionSpec, requested_date: str | None = None) -> str | None:
    if spec.key not in CACHEABLE_FUNCTION_KEYS:
        return None
    common_dates = valid_shared_dates()
    if not common_dates:
        raise RuntimeError("找不到可用的 TWSE/TPEX 共同有效交易日。")
    if requested_date:
        if requested_date not in common_dates:
            raise RuntimeError(f"指定日期 {requested_date} 不在可用交易日清單內。")
        return requested_date
    return common_dates[-1]


def build_commands(spec: FunctionSpec, target_date: str | None = None) -> list[list[str]]:
    latest_date = resolve_target_date(spec, target_date)
    scripts_dir = MILES_AGENT_ROOT / "scripts"

    if spec.key == "limit_up_red_arrow":
        return [build_script_command(scripts_dir / "screen_limitup_upperwick.py", "--latest-date", latest_date, "--no-save")]
    if spec.key == "today_limit_up":
        return [
            build_script_command(scripts_dir / "screen_today_limitup.py", "--date", latest_date, "--no-save"),
            build_script_command(scripts_dir / "analyze_today_limitup_sector_groups.py", "--date", latest_date, "--no-save"),
        ]
    if spec.key == "new_high_black_volume_contraction":
        return [
            build_script_command(
                scripts_dir / "screen_new_high_black_volume_contraction.py",
                "--date",
                latest_date,
                "--no-save",
            )
        ]
    if spec.key == "ma_bullish_turning_point":
        return [
            build_script_command(scripts_dir / "screen_ma_alignment_turning_point.py", "--latest-date", latest_date, "--no-save"),
            build_script_command(scripts_dir / "analyze_012_sector_groups.py", "--latest-date", latest_date, "--no-save"),
        ]
    if spec.key == "low_base_turnaround":
        return [build_script_command(scripts_dir / "screen_low_base_turnaround.py", "--date", latest_date, "--no-save")]
    if spec.key == "pre_breakout_standard":
        pre_breakout_script = resolve_pre_breakout_script()
        sector_script = scripts_dir / "analyze_pre_breakout_sector_groups.py"
        return [
            build_script_command(pre_breakout_script, "--date", latest_date, "--relaxed"),
            build_script_command(sector_script, "--date", latest_date, "--relaxed", "--no-save"),
        ]
    if spec.key == "pre_breakout_conservative":
        pre_breakout_script = resolve_pre_breakout_script()
        return [build_script_command(pre_breakout_script, "--date", latest_date)]
    return []


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def known_unavailable_market_dates() -> set[str]:
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT result_date FROM unavailable_market_dates").fetchall()
    except sqlite3.OperationalError:
        return set()
    return {str(row["result_date"]) for row in rows}


def remember_unavailable_market_date(result_date: str, reason: str) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO unavailable_market_dates (result_date, reason, checked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(result_date) DO UPDATE SET
                reason = excluded.reason,
                checked_at = excluded.checked_at
            """,
            (result_date, reason, taipei_now().isoformat(timespec="seconds")),
        )


def init_db() -> None:
    with get_db() as conn:
        chip_dashboard.init_schema(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                function_key TEXT NOT NULL,
                function_name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_seconds REAL,
                output_text TEXT NOT NULL,
                artifacts_json TEXT NOT NULL DEFAULT '[]',
                result_date TEXT
            )
            """
        )
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        if "result_date" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN result_date TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_function_key ON runs(function_key, id DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS screening_cache (
                function_key TEXT NOT NULL,
                result_date TEXT NOT NULL,
                function_name TEXT NOT NULL,
                status TEXT NOT NULL,
                output_text TEXT NOT NULL,
                artifacts_json TEXT NOT NULL DEFAULT '[]',
                started_at TEXT,
                finished_at TEXT,
                duration_seconds REAL,
                cached_at TEXT NOT NULL,
                PRIMARY KEY (function_key, result_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS institutional_cache (
                function_key TEXT NOT NULL,
                result_date TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'finmind',
                started_at TEXT,
                finished_at TEXT,
                duration_seconds REAL,
                cached_at TEXT NOT NULL,
                PRIMARY KEY (function_key, result_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS serenity_cache (
                function_key TEXT NOT NULL,
                result_date TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                cached_at TEXT NOT NULL,
                PRIMARY KEY (function_key, result_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS unavailable_market_dates (
                result_date TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                checked_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                params_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def snapshot_watch_dirs() -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for watch_dir in OUTPUT_WATCH_DIRS:
        if not watch_dir.exists():
            continue
        for path in watch_dir.rglob("*"):
            if path.is_file():
                try:
                    snapshot[str(path.resolve())] = path.stat().st_mtime
                except FileNotFoundError:
                    continue
    return snapshot


def detect_new_artifacts(before: dict[str, float]) -> list[str]:
    artifacts: list[str] = []
    for watch_dir in OUTPUT_WATCH_DIRS:
        if not watch_dir.exists():
            continue
        for path in watch_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue
            previous_mtime = before.get(str(path.resolve()))
            if previous_mtime is None or mtime > previous_mtime:
                artifacts.append(str(path.resolve()))
    artifacts.sort(reverse=True)
    return artifacts[:20]


def serialize_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "function_key": row["function_key"],
        "function_name": row["function_name"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_seconds": row["duration_seconds"],
        "output_text": row["output_text"],
        "artifacts": json.loads(row["artifacts_json"] or "[]"),
        "result_date": row["result_date"],
    }


def lookup_cache(function_key: str, result_date: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM screening_cache
            WHERE function_key = ? AND result_date = ?
            """,
            (function_key, result_date),
        ).fetchone()
    if row is None:
        return None

    output_text = row["output_text"] or ""
    if (
        function_key in {
            "limit_up_red_arrow",
            "today_limit_up",
            "new_high_black_volume_contraction",
            "ma_bullish_turning_point",
        }
        and ("後5日=" not in output_text or "分數=" not in output_text)
    ):
        return None
    if function_key == "today_limit_up" and "策略：今日漲停 快速族群分析" not in output_text:
        return None
    if (
        function_key == "new_high_black_volume_contraction"
        and ("訊號日期：" not in output_text or "盤中觀察數量：" not in output_text)
    ):
        return None
    if (
        function_key == "ma_bullish_turning_point"
        and "策略：0121 快速族群分析" not in output_text
        and "族群快速分類整合失敗：" not in output_text
    ):
        return None
    if function_key == "ma_bullish_turning_point":
        safety_codes = {
            "2390",
            "3128",
            "3297",
            "3356",
            "3434",
            "5251",
            "5484",
            "5489",
            "6419",
            "6556",
            "6560",
            "8072",
        }
        has_safety_code = any(code in output_text for code in safety_codes)
        if has_safety_code and "安全監控" not in output_text:
            return None
    if function_key in {"pre_breakout_standard", "pre_breakout_conservative"} and "後5日=" not in output_text:
        return None
    if function_key in {"pre_breakout_standard", "pre_breakout_conservative"} and "漲幅口徑：市場口徑=對前日（前收） | 研究口徑=對訊號日" not in output_text:
        return None
    if function_key == "pre_breakout_standard" and "策略：標準選股 快速族群分析" not in output_text:
        return None

    latest_date = latest_valid_shared_date()
    if (
        function_key in {
            "limit_up_red_arrow",
            "new_high_black_volume_contraction",
            "ma_bullish_turning_point",
            "pre_breakout_standard",
            "pre_breakout_conservative",
        }
        and result_date < latest_date
        and "後5日=(無後續資料)" in output_text
    ):
        return None

    return {
        "function_key": row["function_key"],
        "function_name": row["function_name"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_seconds": row["duration_seconds"],
        "output_text": output_text,
        "artifacts": json.loads(row["artifacts_json"] or "[]"),
        "result_date": row["result_date"],
        "cached_at": row["cached_at"],
    }


def lookup_institutional_cache(function_key: str, result_date: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM institutional_cache
            WHERE function_key = ? AND result_date = ?
            """,
            (function_key, result_date),
        ).fetchone()
    if row is None:
        return None
    return {
        "status": row["status"],
        "payload": json.loads(row["payload_json"] or "{}"),
        "source": row["source"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_seconds": row["duration_seconds"],
        "cached_at": row["cached_at"],
    }


def upsert_institutional_cache(
    function_key: str,
    result_date: str,
    status: str,
    payload: dict[str, Any],
    source: str,
    started_at: datetime,
    finished_at: datetime,
    duration_seconds: float,
) -> None:
    cached_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO institutional_cache (
                function_key,
                result_date,
                status,
                payload_json,
                source,
                started_at,
                finished_at,
                duration_seconds,
                cached_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(function_key, result_date) DO UPDATE SET
                status = excluded.status,
                payload_json = excluded.payload_json,
                source = excluded.source,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_seconds = excluded.duration_seconds,
                cached_at = excluded.cached_at
            """,
            (
                function_key,
                result_date,
                status,
                json.dumps(payload, ensure_ascii=False),
                source,
                started_at.isoformat(timespec="seconds"),
                finished_at.isoformat(timespec="seconds"),
                duration_seconds,
                cached_at,
            ),
        )


def clear_institutional_cache(function_key: str, result_date: str) -> None:
    with get_db() as conn:
        conn.execute(
            "DELETE FROM institutional_cache WHERE function_key = ? AND result_date = ?",
            (function_key, result_date),
        )


def lookup_serenity_cache(function_key: str, result_date: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT payload_json, cached_at
            FROM serenity_cache
            WHERE function_key = ? AND result_date = ?
            """,
            (function_key, result_date),
        ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload_json"] or "{}")
    payload["from_cache"] = True
    payload["cached_at"] = row["cached_at"]
    return payload


def upsert_serenity_cache(function_key: str, result_date: str, payload: dict[str, Any]) -> None:
    cached_at = datetime.now().astimezone().isoformat(timespec="seconds")
    stored_payload = dict(payload)
    stored_payload["from_cache"] = False
    stored_payload["cached_at"] = cached_at
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO serenity_cache (function_key, result_date, payload_json, cached_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(function_key, result_date) DO UPDATE SET
                payload_json = excluded.payload_json,
                cached_at = excluded.cached_at
            """,
            (
                function_key,
                result_date,
                json.dumps(stored_payload, ensure_ascii=False),
                cached_at,
            ),
        )


def attach_institutional_cache(payload: dict[str, Any]) -> dict[str, Any]:
    function_key = payload.get("function_key")
    result_date = payload.get("result_date")
    if function_key not in PRE_BREAKOUT_FUNCTION_KEYS or not result_date:
        return payload
    payload["institutional"] = lookup_institutional_cache(function_key, result_date)
    return payload


def taipei_now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def is_intraday_market_open(now: datetime | None = None) -> bool:
    current = now or taipei_now()
    if current.weekday() >= 5:
        return False
    try:
        if current.strftime("%Y%m%d") not in trading_dates_for_year(current.year):
            return False
    except Exception:
        # 行事曆無法驗證時採保守策略，不開放盤中功能。
        return False
    current_time = current.time()
    return dt_time(9, 0) <= current_time <= dt_time(13, 30)


def current_intraday_date(now: datetime | None = None) -> str | None:
    current = now or taipei_now()
    return current.strftime("%Y%m%d") if is_intraday_market_open(current) else None


def parse_pre_breakout_candidates(output_text: str) -> list[dict[str, str]]:
    pattern = re.compile(r"^([ABC])\s+(\d+)\s+(\S+)\s+\|\s+C=([\d.]+)\s+V=(\d+)張(?:\s+分數=([\d.]+))?\s+\|\s+後5日=(.+)$")
    stocks: list[dict[str, str]] = []
    for raw_line in output_text.splitlines():
        line = raw_line.strip()
        match = pattern.match(line)
        if not match:
            continue
        stocks.append(
            {
                "grade": match.group(1),
                "code": match.group(2),
                "name": match.group(3),
                "close": match.group(4),
                "volume": match.group(5),
                "rank_score": match.group(6) or "",
            }
        )
    return stocks


def parse_limit_up_candidates(output_text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"^(TWSE|TPEX)\s+(\d+)\s+(.+?)\s+\|\s+.+?C=([\d.]+)\s+V=([\d.]+)張(?:\s+\|\s+上影=([\d.]+)\s+實體=([\d.]+)\s+比=([\d.-]+))?(?:\s+分數=([\d.]+))?(?:\s+\|\s+後5日=(.+))?$"
    )
    stocks: list[dict[str, str]] = []
    for raw_line in output_text.splitlines():
        line = raw_line.strip()
        match = pattern.match(line)
        if not match:
            continue
        stocks.append(
            {
                "code": match.group(2),
                "name": match.group(3),
                "close": match.group(4),
                "volume": match.group(5),
            }
        )
    return stocks


def parse_ma_bullish_candidates(output_text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"^(TWSE|TPEX)\s+(\d+)\s+(.+?)\s+\|\s+C=([\d.]+)\s+V=([\d.]+)張\s+倍數=([\d.]+)(?:\s+分數=([\d.]+))?\s+\|\s+後5日=(.+)$"
    )
    stocks: list[dict[str, str]] = []
    for raw_line in output_text.splitlines():
        line = raw_line.strip()
        match = pattern.match(line)
        if not match:
            continue
        stocks.append(
            {
                "code": match.group(2),
                "name": match.group(3),
                "close": match.group(4),
                "volume": match.group(5),
            }
        )
    return stocks


def parse_new_high_black_candidates(output_text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"^WATCH\s+(TWSE|TPEX)\s+([0-9A-Z]+)\s+(.+?)\s+\|\s+(\d{8})\s+"
        r"O=([\d.]+)\s+H=([\d.]+)\s+L=([\d.]+)\s+C=([\d.]+)\s+"
        r"V=([\d.]+)張\s+MA4合計=([\d.]+)\s+分數=([\d.]+)\s+\|\s+後5日=(.+)$"
    )
    stocks: list[dict[str, str]] = []
    for raw_line in output_text.splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        stocks.append(
            {
                "market": match.group(1),
                "code": match.group(2),
                "name": match.group(3),
                "setup_date": match.group(4),
                "close": match.group(8),
                "volume": match.group(9),
                "setup_high": match.group(6),
                "setup_volume": match.group(9),
                "ma4_close_sum": match.group(10),
            }
        )
    return stocks


def parse_new_high_black_result_candidates(output_text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"^RESULT\s+(TWSE|TPEX)\s+([0-9A-Z]+)\s+(.+?)\s+\|\s+SETUP\s+(\d{8})\s+"
        r"O=([\d.]+)\s+H=([\d.]+)\s+L=([\d.]+)\s+C=([\d.]+)\s+V=([\d.]+)張\s+\|\s+"
        r"SIGNAL\s+(\d{8})\s+O=([\d.]+)\s+H=([\d.]+)\s+L=([\d.]+)\s+C=([\d.]+)\s+"
        r"V=([\d.]+)張\s+MA5=([\d.]+)\s+分數=([\d.]+)\s+\|\s+後5日=(.+)$"
    )
    stocks: list[dict[str, str]] = []
    for raw_line in output_text.splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        signal_close = float(match.group(14))
        ma5 = float(match.group(16))
        stocks.append(
            {
                "market": match.group(1),
                "code": match.group(2),
                "name": match.group(3),
                "setup_date": match.group(4),
                "close": match.group(14),
                "volume": match.group(15),
                "setup_high": match.group(6),
                "setup_volume": match.group(9),
                "ma4_close_sum": f"{ma5 * 5 - signal_close:.4f}",
            }
        )
    return stocks


def evaluate_new_high_black_intraday(candidate: dict[str, str], quote: dict[str, Any]) -> dict[str, Any]:
    def finite_quote_number(value: Any, *, allow_zero: bool = False) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
            return None
        return number

    last_price = finite_quote_number(quote.get("lastPrice"))
    if last_price is None:
        last_price = finite_quote_number(quote.get("closePrice"))
    high_price = finite_quote_number(quote.get("highPrice"))
    raw_trade_volume = (quote.get("total") or {}).get("tradeVolume")
    trade_volume = finite_quote_number(raw_trade_volume, allow_zero=True)
    volume_available = trade_volume is not None
    setup_high = float(candidate.get("setup_high") or 0)
    setup_volume = float(candidate.get("setup_volume") or 0)
    ma4_close_sum = float(candidate.get("ma4_close_sum") or 0)
    ma5 = (ma4_close_sum + last_price) / 5 if last_price is not None else 0
    ma5_floor = ma5 * 0.95
    matched = (
        last_price is not None
        and high_price is not None
        and volume_available
        and high_price <= setup_high
        and trade_volume < setup_volume
        and trade_volume >= NEW_HIGH_BLACK_MIN_VOLUME_LOTS
        and last_price >= ma5_floor
    )
    return {
        "matched": matched,
        "ma5": round(ma5, 4),
        "ma5_floor": round(ma5_floor, 4),
        "intraday_high": high_price or 0,
        "setup_high": setup_high,
        "setup_volume": setup_volume,
        "volume_available": volume_available,
    }


def evaluate_pre_breakout_intraday(
    candidate: dict[str, str],
    quote: dict[str, Any],
    history_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """用今日即時價量重算標準選股的 A 級盤中條件。"""

    def finite_number(value: Any, *, allow_zero: bool = False) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
            return None
        return number

    last_price = finite_number(quote.get("lastPrice"))
    if last_price is None:
        last_price = finite_number(quote.get("closePrice"))
    trade_volume = finite_number((quote.get("total") or {}).get("tradeVolume"), allow_zero=True)

    try:
        closes = [finite_number(row.get("close")) for row in history_rows]
        volumes = [finite_number(row.get("volume"), allow_zero=True) for row in history_rows]
    except AttributeError:
        closes = []
        volumes = []

    if (
        last_price is None
        or trade_volume is None
        or len(closes) < 11
        or any(value is None or value <= 0 for value in closes)
        or any(value is None or value < 0 for value in volumes)
    ):
        return {
            "matched": False,
            "last_price": last_price,
            "trade_volume": trade_volume,
            "ma5": 0,
            "ma10": 0,
            "dist_ma5": 0,
        }

    numeric_closes = [float(value) for value in closes]
    numeric_volumes = [float(value) for value in volumes]
    ma5 = sum(numeric_closes[-5:]) / 5
    ma5_prev = sum(numeric_closes[-6:-1]) / 5
    ma10 = sum(numeric_closes[-10:]) / 10
    previous_close = numeric_closes[-1]
    pct = (last_price - previous_close) / previous_close * 100 if previous_close > 0 else 0

    range_closes = numeric_closes[-10:]
    low_10 = min(range_closes)
    range_pct = (max(range_closes) - low_10) / low_10 * 100 if low_10 > 0 else 0
    up_days = sum(
        1
        for index in range(len(numeric_closes) - 7, len(numeric_closes))
        if numeric_closes[index] > numeric_closes[index - 1]
    )
    avg_vol_10 = sum(numeric_volumes[-10:]) / 10
    vol_ratio = trade_volume / avg_vol_10 if avg_vol_10 > 0 else 0
    dist_ma5 = (last_price - ma5) / ma5 * 100 if ma5 > 0 else 0
    high_40d = max(
        (float(row.get("high") or 0) for row in history_rows[-40:]),
        default=0.0,
    )
    below_prior_high = abs(pct) < 4 or (high_40d > 0 and last_price < high_40d)
    candidate_grade = str(candidate.get("grade") or "").strip().upper()
    matched = (
        candidate_grade == "A"
        and last_price >= 10
        and trade_volume >= 1000
        and ma5 > ma10
        and ma5 > ma5_prev
        and last_price > ma5
        and abs(pct) < 7
        and below_prior_high
        and range_pct < 25
        and up_days <= 4
        and dist_ma5 >= 3
    )
    return {
        "matched": matched,
        "last_price": last_price,
        "trade_volume": trade_volume,
        "change_percent": pct,
        "previous_close": previous_close,
        "ma5": round(ma5, 4),
        "ma10": round(ma10, 4),
        "dist_ma5": round(dist_ma5, 4),
        "range_pct": round(range_pct, 4),
        "up_days": up_days,
        "volume_ratio": round(vol_ratio, 4),
        "high_40d": round(high_40d, 4),
    }


def parse_intraday_candidates(function_key: str, output_text: str, *, use_watchlist: bool = False) -> list[dict[str, str]]:
    if function_key in PRE_BREAKOUT_FUNCTION_KEYS:
        return parse_pre_breakout_candidates(output_text)
    if function_key == "new_high_black_volume_contraction":
        return parse_new_high_black_candidates(output_text) if use_watchlist else parse_new_high_black_result_candidates(output_text)
    if function_key == "limit_up_red_arrow":
        return parse_limit_up_candidates(output_text)
    if function_key == "ma_bullish_turning_point":
        return parse_ma_bullish_candidates(output_text)
    return []


def fetch_fugle_intraday_quote(symbol: str) -> dict[str, Any]:
    cache_key = str(symbol).strip()
    cached = intraday_quote_cache.get(cache_key)
    now_ts = time.time()
    if cached and now_ts - cached[0] < INTRADAY_QUOTE_CACHE_TTL_SECONDS:
        return cached[1]

    fugle_api_key = get_secret_value("FUGLE_INTRADAY_API_KEY")
    if not fugle_api_key:
        raise RuntimeError("缺少 FUGLE_INTRADAY_API_KEY，請先到設定頁輸入富果 API Key。")

    url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{urllib.parse.quote(cache_key)}"
    req = urllib.request.Request(
        url,
        headers={
            "X-API-KEY": fugle_api_key,
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.load(resp)
    intraday_quote_cache[cache_key] = (now_ts, payload)
    return payload


def build_intraday_payload(
    function_key: str,
    result_date: str,
    output_text: str,
    *,
    source_result_date: str | None = None,
    current_intraday: bool = False,
) -> tuple[str, dict[str, Any], float]:
    if function_key not in INTRADAY_FUNCTION_KEYS:
        raise RuntimeError("這個選股功能目前不支援即時行情。")
    if current_intraday and function_key not in DIRECT_CURRENT_INTRADAY_FUNCTION_KEYS:
        raise RuntimeError("這個選股功能目前不支援當日盤中直接選股。")
    if function_key == "new_high_black_volume_contraction":
        latest_date = latest_valid_shared_date()
        if not current_intraday and result_date != latest_date and result_date != current_intraday_date():
            raise RuntimeError("創高黑量縮只能用最新完整交易日或當日盤中日期查詢。")
    if not is_intraday_market_open():
        raise RuntimeError("目前非盤中時段，即時行情功能暫不啟用。")
    if not get_secret_value("FUGLE_INTRADAY_API_KEY"):
        raise RuntimeError("缺少 FUGLE_INTRADAY_API_KEY，請先到設定頁輸入富果 API Key。")

    started_at = taipei_now()
    started_perf = time.perf_counter()
    use_watchlist = function_key == "new_high_black_volume_contraction" and (
        current_intraday or result_date == current_intraday_date()
    )
    candidates = parse_intraday_candidates(function_key, output_text, use_watchlist=use_watchlist)
    if not candidates:
        raise RuntimeError("目前結果沒有可查詢的股票清單。")

    history_by_code: dict[str, dict[str, Any]] = {}
    if current_intraday and function_key == "pre_breakout_standard":
        history_source_date = source_result_date or latest_valid_shared_date()
        history_by_code = build_kline_batch_rows(
            [stock["code"] for stock in candidates],
            end_date=history_source_date,
            lookback_days=40,
        )

    quotes: dict[str, Any] = {}
    success_count = 0
    matched_count = 0
    for stock in candidates:
        code = stock["code"]
        try:
            quote = fetch_fugle_intraday_quote(code)
            total = quote.get("total") or {}
            last_trade = quote.get("lastTrade") or {}
            quote_payload = {
                "code": code,
                "name": stock["name"],
                "market": stock.get("market", ""),
                "grade": stock.get("grade", ""),
                "rank_score": stock.get("rank_score", ""),
                "close": stock.get("close", ""),
                "volume": stock.get("volume", ""),
                "last_price": quote.get("lastPrice") or quote.get("closePrice"),
                "trade_volume": total.get("tradeVolume"),
                "change_percent": quote.get("changePercent"),
                "last_trade_time": last_trade.get("time") or total.get("time"),
                "is_close": quote.get("isClose"),
            }
            if function_key == "new_high_black_volume_contraction":
                condition = evaluate_new_high_black_intraday(stock, quote)
                quote_payload.update(condition)
                if condition["matched"]:
                    matched_count += 1
            elif current_intraday and function_key == "pre_breakout_standard":
                condition = evaluate_pre_breakout_intraday(
                    stock,
                    quote,
                    (history_by_code.get(code) or {}).get("rows") or [],
                )
                quote_payload.update(condition)
                if condition["matched"]:
                    matched_count += 1
            quotes[code] = quote_payload
            success_count += 1
        except Exception as exc:
            quotes[code] = {
                "code": code,
                "name": stock["name"],
                "error": str(exc),
            }

    finished_at = taipei_now()
    duration_seconds = round(time.perf_counter() - started_perf, 3)
    payload = {
        "function_key": function_key,
        "result_date": result_date,
        "count": len(candidates),
        "success_count": success_count,
        "matched_count": (
            matched_count
            if function_key == "new_high_black_volume_contraction"
            or (current_intraday and function_key in DIRECT_CURRENT_INTRADAY_FUNCTION_KEYS)
            else success_count
        ),
        "quotes": quotes,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "quote_date": finished_at.strftime("%Y%m%d"),
        "market_open": True,
    }
    if source_result_date:
        payload["source_result_date"] = source_result_date
    status = "success" if success_count > 0 else "failed"
    return status, payload, duration_seconds

def get_secret_value(key: str) -> str:
    load_env_file()
    return os.environ.get(key, "").strip()


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _title_case_rating(text: str) -> str:
    cleaned = _normalize_space(text).replace("_", " ")
    return cleaned.title()


def _find_headless_browser_path() -> str:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("找不到可用的 Edge/Chrome，無法抓取 CNN 恐懼與貪婪指數。")


def _extract_fear_greed_history(html: str, block_name: str, label: str) -> dict[str, Any] | None:
    pattern = re.compile(
        rf'<div class="market-fng-gauge__historical-item market-fng-gauge__historical-item--{block_name}"[^>]*data-index-label="([^"]+)"[^>]*>.*?<div class="market-fng-gauge__historical-item-index-value">(\d+)</div>',
        re.S,
    )
    match = pattern.search(html)
    if not match:
        return None
    return {
        "label": label,
        "rating": _title_case_rating(match.group(1)),
        "score": int(match.group(2)),
    }


def _extract_fear_greed_indicators(html: str) -> list[dict[str, Any]]:
    matches = re.finditer(
        r'<div class="market-fng-indicator"[^>]*data-id="([^"]+)"[^>]*>.*?<div class="market-fng-indicator__name">([^<]+)</div>.*?data-index="([^"]+)".*?<h3 class="market-line-chart__title">([^<]+)</h3>',
        html,
        re.S,
    )
    indicators: list[dict[str, Any]] = []
    for match in matches:
        indicators.append(
            {
                "id": _normalize_space(match.group(1)),
                "name": _normalize_space(match.group(2)).title(),
                "rating": _title_case_rating(match.group(3)),
                "detail_title": _normalize_space(match.group(4)),
            }
        )
    return indicators


def _format_cnn_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return _normalize_space(value)
    return dt.astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _build_fear_greed_recommendation(score: float) -> dict[str, Any]:
    rounded = round(float(score), 2)
    if rounded >= 75:
        return {"action": "sell", "label": "75 以上偏熱", "message": "指數高於 75，市場偏貪婪，可留意分批賣出或降低追價。"}
    if rounded <= 25:
        return {"action": "buy", "label": "25 以下偏冷", "message": "指數低於 25，市場偏恐懼，可留意分批買進或觀察布局機會。"}
    return {"action": "hold", "label": "25~75 中性區", "message": "目前介於 25 到 75 之間，先觀察，不急著追買或殺低。"}


def _build_fear_greed_market_payload(
    *,
    market_key: str,
    market_label: str,
    source: str,
    score: float,
    rating: str,
    status_text: str,
    updated_at: str,
    history: list[dict[str, Any]],
    one_year_history: list[dict[str, Any]],
    recommendation: dict[str, Any] | None = None,
    available: bool = True,
    error_message: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    current_score = round(float(score), 2)
    return {
        "market_key": market_key,
        "market_label": market_label,
        "source": source,
        "available": available,
        "score": current_score,
        "rating": rating,
        "status_text": status_text,
        "updated_at": updated_at,
        "history": history,
        "one_year_history": one_year_history,
        "recommendation": recommendation or _build_fear_greed_recommendation(current_score),
        "thresholds": {"buy": 25, "neutral": 50, "sell": 75},
        "error_message": error_message,
        "source_url": source_url,
    }


def _build_unavailable_fear_greed_market_payload(
    *,
    market_key: str,
    market_label: str,
    source: str,
    error_message: str,
    source_url: str = "",
) -> dict[str, Any]:
    return _build_fear_greed_market_payload(
        market_key=market_key,
        market_label=market_label,
        source=source,
        score=0,
        rating="",
        status_text="目前暫時抓不到資料",
        updated_at="",
        history=[],
        one_year_history=[],
        recommendation={"action": "hold", "label": "暫無資料", "message": error_message},
        available=False,
        error_message=error_message,
        source_url=source_url,
    )


def _fetch_cnn_fear_greed_api_payload() -> dict[str, Any]:
    request = urllib.request.Request(
        CNN_FEAR_GREED_API_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": CNN_FEAR_GREED_URL,
            "Origin": "https://www.cnn.com",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8", "ignore"))

    current = payload.get("fear_and_greed") or {}
    historical = (payload.get("fear_and_greed_historical") or {}).get("data") or []
    history_points: list[dict[str, Any]] = []
    for item in historical:
        try:
            ts_ms = int(float(item.get("x")))
            score = round(float(item.get("y")), 2)
        except Exception:
            continue
        dt_value = datetime.fromtimestamp(ts_ms / 1000, tz=TAIPEI_TZ)
        history_points.append(
            {
                "date": dt_value.strftime("%Y-%m-%d"),
                "timestamp": ts_ms,
                "score": score,
                "rating": _title_case_rating(item.get("rating", "")),
            }
        )

    current_score = round(float(current.get("score") or 0), 2)
    return _build_fear_greed_market_payload(
        market_key="us_cnn",
        market_label="美國 CNN 恐懼與貪婪指數",
        source="CNN Fear & Greed Index",
        score=current_score,
        rating=_title_case_rating(current.get("rating", "")),
        status_text=f"{_title_case_rating(current.get('rating', ''))} is driving the US market",
        updated_at=_format_cnn_timestamp(str(current.get("timestamp") or "")),
        history=[
            {"label": "前一收盤", "score": round(float(current.get("previous_close") or 0), 2)},
            {"label": "1 週前", "score": round(float(current.get("previous_1_week") or 0), 2)},
            {"label": "1 個月前", "score": round(float(current.get("previous_1_month") or 0), 2)},
            {"label": "1 年前", "score": round(float(current.get("previous_1_year") or 0), 2)},
        ],
        one_year_history=history_points,
    )


def fetch_cnn_fear_greed_payload() -> dict[str, Any]:
    try:
        return _fetch_cnn_fear_greed_api_payload()
    except Exception:
        browser_path = _find_headless_browser_path()
        command = [
            browser_path,
            "--headless",
            "--disable-gpu",
            "--virtual-time-budget=15000",
            "--dump-dom",
            CNN_FEAR_GREED_URL,
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=90)
        if completed.returncode != 0 and not completed.stdout.strip():
            raise RuntimeError("CNN 恐懼與貪婪指數頁面抓取失敗。")

        html = completed.stdout
        score_match = re.search(r'<span class="market-fng-gauge__dial-number-value">\s*(\d+)\s*</span>', html)
        rating_match = re.search(r'class="market-fng-gauge__text"[^>]*data-index-label="([^"]+)"', html)
        timestamp_match = re.search(r'<div class="market-fng-gauge__timestamp"[^>]*>([^<]+)</div>', html)
        if not score_match or not rating_match:
            raise RuntimeError("目前無法從 CNN 頁面解析恐懼與貪婪指數。")

        fallback_score = int(score_match.group(1))
        return _build_fear_greed_market_payload(
            market_key="us_cnn",
            market_label="美國 CNN 恐懼與貪婪指數",
            source="CNN Fear & Greed Index",
            score=fallback_score,
            rating=_title_case_rating(rating_match.group(1)),
            status_text=f"{_title_case_rating(rating_match.group(1))} is driving the US market",
            updated_at=_normalize_space(timestamp_match.group(1)) if timestamp_match else "",
            history=[
                item
                for item in [
                    _extract_fear_greed_history(html, "prevClose", "前一收盤"),
                    _extract_fear_greed_history(html, "weekClose", "1 週前"),
                    _extract_fear_greed_history(html, "monthClose", "1 個月前"),
                    _extract_fear_greed_history(html, "yearClose", "1 年前"),
                ]
                if item is not None
            ],
            one_year_history=[],
            recommendation=_build_fear_greed_recommendation(fallback_score),
        )


def fetch_tw_mm_fear_greed_payload() -> dict[str, Any]:
    browser_path = _find_headless_browser_path()
    command = [
        browser_path,
        "--headless",
        "--disable-gpu",
        "--virtual-time-budget=15000",
        "--dump-dom",
        TW_MM_FEAR_GREED_URL,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=90)
    html = completed.stdout or completed.stderr or ""
    if completed.returncode != 0 and not html.strip():
        raise RuntimeError("MM 頁面抓取失敗。")

    if "Performing security verification" in html or "正在執行安全驗證" in html or "驗證您是人類" in html:
        raise RuntimeError("MM 網站目前有 Cloudflare 驗證，暫時無法自動抓取。")

    score_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*</[^>]+>\s*<[^>]+[^>]*>\s*(Extreme Fear|Fear|Neutral|Greed|Extreme Greed)', html, re.I)
    if not score_match:
        raise RuntimeError("目前無法從 MM 頁面解析出台灣恐懼與貪婪指數。")

    score = round(float(score_match.group(1)), 2)
    rating = _title_case_rating(score_match.group(2))
    return _build_fear_greed_market_payload(
        market_key="tw_mm",
        market_label="台灣-MM 恐懼與貪婪指數",
        source="MacroMicro 台灣市場恐懼與貪婪指數",
        score=score,
        rating=rating,
        status_text=f"{rating} is driving the Taiwan market",
        updated_at="",
        history=[],
        one_year_history=[],
    )


def fetch_fear_greed_payload(force_refresh: bool = False) -> dict[str, Any]:
    now_ts = time.time()
    with fear_greed_cache_lock:
        cached_payload = fear_greed_cache_state.get("payload")
        fetched_at = float(fear_greed_cache_state.get("fetched_at") or 0.0)
        if not force_refresh and cached_payload and now_ts - fetched_at < FEAR_GREED_CACHE_TTL_SECONDS:
            response = deepcopy(cached_payload)
            response["from_cache"] = True
            return response

    us_payload = fetch_cnn_fear_greed_payload()
    try:
        tw_payload = fetch_tw_mm_fear_greed_payload()
    except Exception as exc:
        tw_payload = _build_unavailable_fear_greed_market_payload(
            market_key="tw_mm",
            market_label="台灣-MM 恐懼與貪婪指數",
            source="MacroMicro 台灣市場恐懼與貪婪指數",
            error_message="此區不顯示內容，請直接點下方連結查看 MM 原頁。",
            source_url="https://www.macromicro.me/charts/128747/taiwan-mm-fear-and-greed-index-vs-taiex",
        )

    payload = {
        "source": "Fear & Greed",
        "markets": [us_payload, tw_payload],
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "from_cache": False,
    }

    with fear_greed_cache_lock:
        fear_greed_cache_state["payload"] = deepcopy(payload)
        fear_greed_cache_state["fetched_at"] = now_ts
    return payload


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(len(value) - 8, 4)}{value[-4:]}"



def read_settings_payload() -> dict[str, Any]:
    finmind = get_secret_value("FINMIND_TOKEN")
    fugle = get_secret_value("FUGLE_INTRADAY_API_KEY")
    return {
        "finmind_token": finmind,
        "fugle_intraday_api_key": fugle,
        "has_finmind_token": bool(finmind),
        "has_fugle_intraday_api_key": bool(fugle),
        "masked_finmind_token": mask_secret(finmind),
        "masked_fugle_intraday_api_key": mask_secret(fugle),
        "env_file": str(ENV_FILE_PATH),
    }



def write_settings_payload(finmind_token: str | None, fugle_intraday_api_key: str | None) -> dict[str, Any]:
    existing: dict[str, str] = {}
    if ENV_FILE_PATH.exists():
        for raw_line in ENV_FILE_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            existing[key.strip()] = _strip_env_value(value)

    updates = {
        "FINMIND_TOKEN": finmind_token,
        "FUGLE_INTRADAY_API_KEY": fugle_intraday_api_key,
    }
    for key, value in updates.items():
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            existing[key] = normalized
        else:
            existing.pop(key, None)
            os.environ.pop(key, None)

    lines = [
        "# StockControlPanel portable settings",
        "# Leave values blank in .env.example; real secrets live in local .env",
    ]
    for key in ["FINMIND_TOKEN", "FUGLE_INTRADAY_API_KEY"]:
        value = existing.get(key, "")
        if value:
            safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key}="{safe_value}"')
            os.environ[key] = value

    ENV_FILE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_env_file(override=True)
    intraday_quote_cache.clear()
    return read_settings_payload()


def run_command(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(
        command,
        cwd=MILES_AGENT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        env=env,
    )


def normalize_serenity_stocks(raw_stocks: Any) -> list[dict[str, str]]:
    if not isinstance(raw_stocks, list):
        return []

    stocks: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_stocks:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip()
        if not re.fullmatch(r"\d{4,6}", code) or code in seen:
            continue
        seen.add(code)
        stocks.append(
            {
                "code": code,
                "name": str(raw.get("name") or "").strip()[:40],
                "theme": str(raw.get("theme") or raw.get("theme_name") or "").strip()[:60],
                "grade": str(raw.get("grade") or "").strip()[:8],
                "rank_score": str(raw.get("rank_score") or "").strip()[:20],
                "close": str(raw.get("close") or "").strip()[:20],
                "volume": str(raw.get("volume") or "").strip()[:20],
            }
        )
        if len(stocks) >= SERENITY_MAX_STOCKS:
            break
    return stocks


def build_serenity_prompt(
    function_name: str,
    result_date: str,
    stocks: list[dict[str, str]],
    *,
    fast: bool = False,
) -> str:
    date_label = result_date
    if re.fullmatch(r"\d{8}", result_date):
        date_label = f"{result_date[:4]}-{result_date[4:6]}-{result_date[6:]}"

    rows: list[str] = []
    for stock in stocks:
        details = []
        if stock.get("theme"):
            details.append(f"族群={stock['theme']}")
        if stock.get("grade"):
            details.append(f"等級={stock['grade']}")
        if stock.get("rank_score"):
            details.append(f"排序分數={stock['rank_score']}")
        if stock.get("close"):
            details.append(f"收盤={stock['close']}")
        if stock.get("volume"):
            details.append(f"成交量={stock['volume']}")
        suffix = f"｜{'、'.join(details)}" if details else ""
        rows.append(f"- {stock['code']} {stock.get('name') or ''}{suffix}".rstrip())

    stock_text = "\n".join(rows)
    if fast:
        research_instruction = "你是快速研究代理，只分析上方分配給你的股票，不要延伸研究其他股票。必須先實際呼叫 browser_navigate / browser_snapshot 查證最新資料，不可因 web_search 不可用就直接停止分析。每檔最多查 2～3 個可靠公開來源，優先公司 IR、公開資訊觀測站、交易所、Yahoo 股市或 MoneyDJ；不要重複搜尋相同資料。"
        output_instruction = "請用繁體中文，控制在精簡篇幅，依序輸出：1. 產業鏈位置與瓶頸關聯；2. 具體證據與來源；3. 證據強度；4. 主要風險與反方條件；5. 下一步查證項目。"
    else:
        research_instruction = "請使用目前可查到的公開資料，先辨識候選股所屬族群與產業鏈，再找真正難擴產、供應商少、驗證期長或掌握關鍵技術的瓶頸環節。你已獲得 browser 瀏覽器工具。必須先實際呼叫 browser_navigate / browser_snapshot 查證最新資料，不可因 web_search 不可用就直接停止分析。可以用 Bing 搜尋公司代號、公司名稱、月營收、法說會、產能與訂單，再開啟搜尋結果。若個別官網被 Cloudflare 阻擋，請改查公開資訊觀測站、交易所、Yahoo 股市、鉅亨、MoneyDJ 或其他可讀的公開來源，並明確標示來源品質。候選超過 10 檔時，先挑最有瓶頸潛力的 10 檔深入核對，其餘做初步分類。"
        output_instruction = "請用繁體中文，依序輸出：1. 先講結論與最值得優先研究的產業鏈層級。2. 候選股研究優先順序，逐檔說明產業鏈位置、瓶頸關聯、具體證據、證據強度與主要風險。3. 指出哪些股票可能只是題材沾邊。4. 列出會讓判斷失效的反方條件。5. 給出下一步應查證的公告、月營收、產能、客戶或訂單指標。"
    return f"""請使用 Serenity Skill，針對 StockControlPanel 的選股結果做台股供應鏈深度分析。

選股功能：{function_name}
交易日期：{date_label}
候選清單：
{stock_text}

{research_instruction}

{output_instruction}

這是研究輔助，不要給出保證獲利、直接買進或直接賣出的指令；資料不足時請明確標示尚待查證。"""


def run_serenity_cli(
    prompt: str,
    *,
    max_turns: int = 35,
    timeout_seconds: int = SERENITY_TIMEOUT_SECONDS,
) -> str:
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        raise RuntimeError("找不到 Hermes CLI。請先安裝並登入 Hermes Agent，再使用 Serenity 深度分析。")

    command = [
        hermes_bin,
        "chat",
        "-Q",
        "--source",
        "tool",
        "--max-turns",
        str(max_turns),
        "-t",
        "browser,web",
        "-s",
        "serenity-skill",
        "-q",
        prompt,
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            command,
            cwd=MILES_AGENT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=env,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Serenity 深度分析超過 {max(1, timeout_seconds // 60)} 分鐘，請縮小候選清單後再試。") from exc

    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        detail = (completed.stderr or output or "Hermes CLI 執行失敗").strip()
        raise RuntimeError(detail[-2000:])
    if not output:
        raise RuntimeError("Serenity 沒有回傳分析內容。")
    return output


def split_serenity_stocks(stocks: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    worker_count = min(SERENITY_MAX_PARALLEL_WORKERS, len(stocks))
    if worker_count <= 1:
        return [list(stocks)] if stocks else []
    batches = [[] for _ in range(worker_count)]
    for index, stock in enumerate(stocks):
        batches[index % worker_count].append(stock)
    return [batch for batch in batches if batch]


def run_serenity_research(
    function_name: str,
    result_date: str,
    stocks: list[dict[str, str]],
) -> tuple[str, int, str]:
    batches = split_serenity_stocks(stocks)
    if not batches:
        raise RuntimeError("目前沒有可供 Serenity 分析的股票清單。")

    def run_batch(index: int, batch: list[dict[str, str]]) -> tuple[int, str]:
        prompt = build_serenity_prompt(function_name, result_date, batch, fast=True)
        report = run_serenity_cli(
            prompt,
            max_turns=SERENITY_FAST_MAX_TURNS,
            timeout_seconds=SERENITY_FAST_TIMEOUT_SECONDS,
        )
        return index, report

    if len(batches) == 1:
        _, report = run_batch(0, batches[0])
        return report, 1, "快速單一研究代理"

    reports: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=len(batches), thread_name_prefix="serenity-worker") as executor:
        futures = {
            executor.submit(run_batch, index, batch): (index, batch)
            for index, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            index, batch = futures[future]
            try:
                _, report = future.result()
            except Exception as exc:
                codes = ", ".join(stock["code"] for stock in batch)
                raise RuntimeError(f"Serenity 平行研究代理（{codes}）失敗：{exc}") from exc
            reports[index] = report

    sections = []
    for index, batch in enumerate(batches):
        codes = ", ".join(stock["code"] for stock in batch)
        sections.append(f"【平行研究代理 {index + 1}｜{codes}】\n{reports[index]}")
    return "\n\n".join(sections), len(batches), f"平行快速研究（{len(batches)} 個代理）"


def build_local_update_signature() -> str:
    digest = hashlib.sha256()
    for relative_path in UPDATE_TRACKED_PATHS:
        file_path = MILES_AGENT_ROOT / relative_path
        if not file_path.exists():
            digest.update(f"missing:{relative_path}\n".encode("utf-8"))
            continue
        digest.update(f"file:{relative_path}\n".encode("utf-8"))
        digest.update(file_path.read_bytes())
    return digest.hexdigest()


def build_remote_update_signature() -> str:
    digest = hashlib.sha256()
    for relative_path in UPDATE_TRACKED_PATHS:
        url = f"{GITHUB_RAW_BASE_URL}/{relative_path}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            remote_bytes = response.read()
        digest.update(f"file:{relative_path}\n".encode("utf-8"))
        digest.update(remote_bytes)
    return digest.hexdigest()


def get_update_status() -> dict[str, Any]:
    if IS_FROZEN:
        return {
            "ok": True,
            "mode": "portable_exe",
            "branch": "bundled",
            "update_available": False,
            "button_label": "EXE版請下載新版",
            "button_enabled": False,
            "message": "可攜式 EXE 版請直接下載新的發佈包覆蓋。",
        }

    git_dir = MILES_AGENT_ROOT / ".git"
    if git_dir.exists():
        branch_result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if branch_result.returncode != 0:
            raise RuntimeError(branch_result.stderr.strip() or branch_result.stdout.strip() or "無法取得目前分支。")
        branch = branch_result.stdout.strip() or "main"

        local_result = run_command(["git", "rev-parse", "HEAD"])
        remote_result = run_command(["git", "ls-remote", "origin", f"refs/heads/{branch}"])
        if local_result.returncode != 0 or remote_result.returncode != 0:
            raise RuntimeError("無法檢查 GitHub 最新版本。")

        local_rev = local_result.stdout.strip()
        remote_rev = (remote_result.stdout.strip().split()[0] if remote_result.stdout.strip() else "")
        update_available = bool(local_rev and remote_rev and local_rev != remote_rev)
        return {
            "ok": True,
            "mode": "git",
            "branch": branch,
            "update_available": update_available,
            "button_label": "一鍵更新" if update_available else "已是最新版",
            "button_enabled": update_available,
        }

    local_signature = build_local_update_signature()
    remote_signature = build_remote_update_signature()
    update_available = local_signature != remote_signature
    return {
        "ok": True,
        "mode": "zip",
        "branch": "main",
        "update_available": update_available,
        "button_label": "一鍵更新" if update_available else "已是最新版",
        "button_enabled": update_available,
    }


def update_project_from_git() -> dict[str, Any]:
    status_result = run_command(["git", "status", "--porcelain"])
    if status_result.returncode != 0:
        raise RuntimeError(status_result.stderr.strip() or status_result.stdout.strip() or "無法檢查 git 狀態。")
    if status_result.stdout.strip():
        raise RuntimeError("目前有未提交的本機修改，請先提交或備份後再更新。")

    branch_result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if branch_result.returncode != 0:
        raise RuntimeError(branch_result.stderr.strip() or branch_result.stdout.strip() or "無法取得目前分支。")
    branch = branch_result.stdout.strip() or "main"

    pull_result = run_command(["git", "pull", "--ff-only", "origin", branch], timeout=600)
    pull_output = "\n".join(part for part in [pull_result.stdout.strip(), pull_result.stderr.strip()] if part).strip()
    if pull_result.returncode != 0:
        raise RuntimeError(pull_output or "git pull 失敗。")

    updated = "Already up to date." not in pull_output and "Already up-to-date." not in pull_output
    changed_files: list[str] = []
    if updated:
        changed_result = run_command(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"])
        if changed_result.returncode == 0:
            changed_files = [line.strip() for line in changed_result.stdout.splitlines() if line.strip()]

    requirements_updated = any(Path(path).name == "requirements.txt" for path in changed_files)
    pip_output = ""
    if requirements_updated:
        pip_result = run_command([PYTHON_BIN, "-m", "pip", "install", "-r", "requirements.txt"], timeout=1200)
        pip_output = "\n".join(part for part in [pip_result.stdout.strip(), pip_result.stderr.strip()] if part).strip()
        if pip_result.returncode != 0:
            raise RuntimeError(pip_output or "requirements 安裝失敗。")

    return {
        "ok": True,
        "mode": "git",
        "updated": updated,
        "branch": branch,
        "changed_files": changed_files,
        "requirements_updated": requirements_updated,
        "restart_required": updated,
        "pull_output": pull_output,
        "pip_output": pip_output,
        "message": "更新完成，請關閉並重新啟動程式。" if updated else "目前已是最新版本。",
    }


def update_project_from_zip() -> dict[str, Any]:
    requirements_before = (MILES_AGENT_ROOT / "requirements.txt").read_text(encoding="utf-8", errors="ignore") if (MILES_AGENT_ROOT / "requirements.txt").exists() else ""

    with tempfile.TemporaryDirectory(prefix="stockcontrolpanel-update-") as tmpdir:
        tmp_root = Path(tmpdir)
        zip_path = tmp_root / "update.zip"
        urllib.request.urlretrieve(GITHUB_ZIP_URL, zip_path)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(tmp_root)

        extracted_dirs = [path for path in tmp_root.iterdir() if path.is_dir() and path.name.startswith(f"{GITHUB_REPO_NAME}-")]
        if not extracted_dirs:
            raise RuntimeError("找不到下載後的更新內容。")
        source_root = extracted_dirs[0]

        changed_files: list[str] = []
        for source_path in source_root.rglob("*"):
            relative = source_path.relative_to(source_root)
            if not relative.parts:
                continue
            if relative.parts[0] in LOCAL_PRESERVE_NAMES:
                continue
            destination_path = MILES_AGENT_ROOT / relative
            if source_path.is_dir():
                destination_path.mkdir(parents=True, exist_ok=True)
                continue
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            if not destination_path.exists() or destination_path.read_bytes() != source_path.read_bytes():
                changed_files.append(relative.as_posix())
            shutil.copy2(source_path, destination_path)

    requirements_after = (MILES_AGENT_ROOT / "requirements.txt").read_text(encoding="utf-8", errors="ignore") if (MILES_AGENT_ROOT / "requirements.txt").exists() else ""
    requirements_updated = requirements_before != requirements_after
    pip_output = ""
    if requirements_updated:
        pip_result = run_command([PYTHON_BIN, "-m", "pip", "install", "-r", "requirements.txt"], timeout=1200)
        pip_output = "\n".join(part for part in [pip_result.stdout.strip(), pip_result.stderr.strip()] if part).strip()
        if pip_result.returncode != 0:
            raise RuntimeError(pip_output or "requirements 安裝失敗。")

    return {
        "ok": True,
        "mode": "zip",
        "updated": True,
        "branch": "main",
        "changed_files": changed_files,
        "requirements_updated": requirements_updated,
        "restart_required": True,
        "pull_output": "已從 GitHub 下載 ZIP 並覆蓋本機檔案。",
        "pip_output": pip_output,
        "message": "更新完成，請關閉並重新啟動程式。",
    }


def update_project_from_github() -> dict[str, Any]:
    git_dir = MILES_AGENT_ROOT / ".git"
    if git_dir.exists():
        return update_project_from_git()
    return update_project_from_zip()


def resolve_finmind_token() -> str:

    return get_secret_value("FINMIND_TOKEN")

def format_finmind_date(result_date: str) -> str:
    return f"{result_date[:4]}-{result_date[4:6]}-{result_date[6:8]}"


def parse_pre_breakout_codes(output_text: str) -> list[str]:
    codes: list[str] = []
    for line in output_text.splitlines():
        match = re.search(r"^\s*[ABC]\s+(\d{4,6})\s+\S+\s+\|\s+C=", line.strip())
        if match:
            codes.append(match.group(1))
    return codes


def fetch_single_finmind_institutional(code: str, result_date: str, token: str) -> dict[str, float]:
    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": code,
        "start_date": format_finmind_date(result_date),
        "end_date": format_finmind_date(result_date),
        "token": token,
    }
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{FINMIND_API_URL}?{query}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != 200:
        raise RuntimeError(payload.get("msg") or f"FinMind status={payload.get('status')}")

    rows = payload.get("data") or []
    foreign = 0.0
    foreign_dealer = 0.0
    investment = 0.0
    dealer_self = 0.0
    dealer_hedging = 0.0
    for row in rows:
        net = float(row.get("buy", 0) or 0) - float(row.get("sell", 0) or 0)
        name = row.get("name")
        if name == "Foreign_Investor":
            foreign += net
        elif name == "Foreign_Dealer_Self":
            foreign_dealer += net
        elif name == "Investment_Trust":
            investment += net
        elif name == "Dealer_self":
            dealer_self += net
        elif name == "Dealer_Hedging":
            dealer_hedging += net

    foreign_total = foreign + foreign_dealer
    dealer_total = dealer_self + dealer_hedging
    total = foreign_total + investment + dealer_total
    return {
        "foreign": round(foreign_total / 1000, 1),
        "investment_trust": round(investment / 1000, 1),
        "dealer": round(dealer_total / 1000, 1),
        "total": round(total / 1000, 1),
    }


def build_institutional_payload(function_key: str, result_date: str, output_text: str) -> tuple[str, dict[str, Any], float]:
    started_at = datetime.now().astimezone()
    started_perf = time.perf_counter()
    codes = parse_pre_breakout_codes(output_text)
    if not codes:
        raise RuntimeError("目前結果內找不到可查詢法人的股票代號。")

    token = resolve_finmind_token()
    if not token:
        raise RuntimeError("找不到 FINMIND_TOKEN，請先到設定頁輸入 FinMind Token。")

    stocks: dict[str, Any] = {}
    failures: list[str] = []
    for index, code in enumerate(codes, start=1):
        try:
            stocks[code] = fetch_single_finmind_institutional(code, result_date, token)
        except Exception as exc:
            stocks[code] = {
                "foreign": 0,
                "investment_trust": 0,
                "dealer": 0,
                "total": 0,
                "error": str(exc),
            }
            failures.append(code)
        if index < len(codes):
            time.sleep(0.12)

    duration_seconds = round(time.perf_counter() - started_perf, 3)
    finished_at = datetime.now().astimezone()
    payload = {
        "function_key": function_key,
        "result_date": result_date,
        "stocks": stocks,
        "count": len(codes),
        "success_count": len(codes) - len(failures),
        "failure_count": len(failures),
        "failures": failures,
        "message": f"法人資料 {len(codes) - len(failures)}/{len(codes)} 檔完成",
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": duration_seconds,
    }
    status = "success" if not failures else "partial"
    return status, payload, duration_seconds


def upsert_cache(
    spec: FunctionSpec,
    result_date: str,
    status: str,
    output_text: str,
    artifacts: list[str],
    started_at: datetime,
    finished_at: datetime,
    duration_seconds: float,
) -> None:
    cached_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO screening_cache (
                function_key,
                result_date,
                function_name,
                status,
                output_text,
                artifacts_json,
                started_at,
                finished_at,
                duration_seconds,
                cached_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(function_key, result_date) DO UPDATE SET
                function_name = excluded.function_name,
                status = excluded.status,
                output_text = excluded.output_text,
                artifacts_json = excluded.artifacts_json,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_seconds = excluded.duration_seconds,
                cached_at = excluded.cached_at
            """,
            (
                spec.key,
                result_date,
                spec.name,
                status,
                output_text,
                json.dumps(artifacts, ensure_ascii=False),
                started_at.isoformat(timespec="seconds"),
                finished_at.isoformat(timespec="seconds"),
                duration_seconds,
                cached_at,
            ),
        )
    if spec.key in PRE_BREAKOUT_FUNCTION_KEYS:
        clear_institutional_cache(spec.key, result_date)


def latest_runs_by_function() -> dict[str, dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.*
            FROM runs r
            JOIN (
                SELECT function_key, MAX(id) AS max_id
                FROM runs
                GROUP BY function_key
            ) x ON x.max_id = r.id
            ORDER BY r.id DESC
            """
        ).fetchall()
    return {row["function_key"]: serialize_run(row) for row in rows}


def recent_runs(function_key: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    query = "SELECT * FROM runs"
    params: list[Any] = []
    if function_key:
        query += " WHERE function_key = ?"
        params.append(function_key)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [serialize_run(row) for row in rows]


def run_function(spec: FunctionSpec, requested_date: str | None = None, skip_cache: bool = False) -> dict[str, Any]:
    try:
        result_date = resolve_target_date(spec, requested_date)
    except Exception as exc:
        result_date = None
        cache_error = f"解析交易日時失敗：{exc}"
    else:
        cache_error = None

    if result_date and not skip_cache:
        cached = lookup_cache(spec.key, result_date)
        if cached and cached.get("status") == "success":
            return attach_institutional_cache({
                "id": f"cache:{spec.key}:{result_date}",
                "function_key": spec.key,
                "function_name": spec.name,
                "status": cached["status"],
                "started_at": cached["started_at"],
                "finished_at": cached["finished_at"],
                "duration_seconds": cached["duration_seconds"],
                "output_text": cached["output_text"],
                "artifacts": cached["artifacts"],
                "result_date": result_date,
                "from_cache": True,
                "cached_at": cached["cached_at"],
            })

    started_at = datetime.now().astimezone()
    started_perf = time.perf_counter()
    before_snapshot = snapshot_watch_dirs()
    outputs: list[str] = []
    status = "success"

    if cache_error:
        status = "failed"
        outputs.append(cache_error)

    if status == "success":
        try:
            commands = build_commands(spec, result_date)
        except Exception as exc:
            commands = []
            status = "failed"
            outputs.append(f"準備執行指令時失敗：{exc}")
    else:
        commands = []

    for step_index, command in enumerate(commands, start=1):
        result = subprocess.run(
            command,
            cwd=MILES_AGENT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=os.environ.copy(),
        )
        step_header = f"$ {' '.join(command)}"
        step_body = (result.stdout or "").strip()
        step_error = (result.stderr or "").strip()
        section_lines = [f"## Step {step_index}", step_header]
        if step_body:
            section_lines.extend(["", step_body])
        if step_error:
            section_lines.extend(["", "[stderr]", step_error])
        outputs.append("\n".join(section_lines).strip())
        if result.returncode != 0:
            if spec.key == "ma_bullish_turning_point" and step_index == 2:
                outputs.append("族群快速分類整合失敗：已保留均線多頭新成形主結果，請稍後再按一次更新後5日重跑。")
                continue
            status = "failed"
            outputs.append(f"\nReturn code: {result.returncode}")
            break

    finished_at = datetime.now().astimezone()
    duration_seconds = round(time.perf_counter() - started_perf, 3)
    artifacts = detect_new_artifacts(before_snapshot)
    output_text = "\n\n".join(part for part in outputs if part).strip() or "(無輸出)"

    if result_date and status == "success":
        upsert_cache(
            spec=spec,
            result_date=result_date,
            status=status,
            output_text=output_text,
            artifacts=artifacts,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
        )

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (
                function_key,
                function_name,
                status,
                started_at,
                finished_at,
                duration_seconds,
                output_text,
                artifacts_json,
                result_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                spec.key,
                spec.name,
                status,
                started_at.isoformat(timespec="seconds"),
                finished_at.isoformat(timespec="seconds"),
                duration_seconds,
                output_text,
                json.dumps(artifacts, ensure_ascii=False),
                result_date,
            ),
        )
        run_id = cursor.lastrowid

    return attach_institutional_cache({
        "id": run_id,
        "function_key": spec.key,
        "function_name": spec.name,
        "status": status,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": duration_seconds,
        "output_text": output_text,
        "artifacts": artifacts,
        "result_date": result_date,
        "from_cache": False,
    })


def run_current_intraday(
    spec: FunctionSpec,
    current_date: str,
    skip_cache: bool = False,
) -> dict[str, Any]:
    """盤中直接執行：以前一完整交易日結果作為母體，再查當日即時行情。"""
    if spec.key not in DIRECT_CURRENT_INTRADAY_FUNCTION_KEYS:
        raise RuntimeError("這個選股功能目前不支援當日盤中直接選股。")
    if current_date != current_intraday_date():
        raise RuntimeError("當日盤中直接選股只能在目前交易時段使用。")

    started_at = taipei_now()
    started_perf = time.perf_counter()
    source_result_date = latest_valid_shared_date()
    base_run = run_function(spec, requested_date=source_result_date, skip_cache=skip_cache)
    if base_run.get("status") != "success":
        base_run["result_date"] = current_date
        return base_run

    status, intraday_payload, intraday_duration = build_intraday_payload(
        function_key=spec.key,
        result_date=current_date,
        output_text=base_run["output_text"],
        source_result_date=source_result_date,
        current_intraday=True,
    )
    intraday_payload["result_date"] = current_date
    intraday_payload["source_result_date"] = source_result_date
    finished_at = taipei_now()
    result = dict(base_run)
    result.update(
        {
            "status": status,
            "result_date": current_date,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "duration_seconds": round(time.perf_counter() - started_perf, 3),
            "from_cache": False,
            "current_intraday": True,
            "intraday": {
                "status": status,
                "payload": intraday_payload,
                "source": "fugle_intraday_quote",
                "started_at": intraday_payload["started_at"],
                "finished_at": intraday_payload["finished_at"],
                "duration_seconds": intraday_duration,
            },
        }
    )
    return result


def run_current_new_high_intraday(
    spec: FunctionSpec,
    current_date: str,
    skip_cache: bool = False,
) -> dict[str, Any]:
    """保留舊函式名稱，讓既有呼叫與測試相容。"""
    return run_current_intraday(spec, current_date, skip_cache=skip_cache)


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/functions")
def api_functions() -> Any:
    latest_map = latest_runs_by_function()
    payload = []
    for item in FUNCTIONS:
        payload.append(
            {
                "key": item.key,
                "name": item.name,
                "category": item.category,
                "description": item.description,
                "executable": item.executable,
                "latest_run": latest_map.get(item.key),
            }
        )
    return jsonify(payload)


@app.route("/api/dates")
def api_dates() -> Any:
    sync_status = ensure_latest_market_data()
    dates = sorted(valid_shared_dates(), reverse=True)
    latest_date = dates[0] if dates else None
    return jsonify({
        "dates": dates,
        "latest_date": latest_date,
        "intraday_date": current_intraday_date(),
        "sync_status": sync_status,
    })


@app.route("/api/custom_sectors")
def api_custom_sectors() -> Any:
    result_date = str(request.args.get("result_date") or "").strip()
    if not re.fullmatch(r"\d{8}", result_date):
        return jsonify({"ok": False, "error": "交易日期格式錯誤。"}), 400
    try:
        return jsonify(build_custom_sector_payload(result_date))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def ensure_chip_dashboard_snapshot() -> None:
    global chip_bundle_imported
    with chip_dashboard_sync_lock:
        if not chip_bundle_imported:
            chip_dashboard.import_local_stock_master(DB_PATH, DATA_ROOT / "chip_stock_master.csv")
            chip_dashboard.import_local_tdcc_archives(DB_PATH, DATA_ROOT / "tdcc")
            chip_bundle_imported = True
        with get_db() as conn:
            chip_dashboard.init_schema(conn)
            if chip_dashboard.dashboard_snapshot_ready(conn):
                return
        chip_dashboard.sync_latest_snapshot(DB_PATH)


def ensure_chip_institutional_snapshot() -> None:
    trade_dates = valid_shared_dates()
    if not trade_dates:
        return
    chip_dashboard.ensure_institutional_history(DB_PATH, DATA_ROOT, trade_dates)


def schedule_chip_institutional_snapshot() -> None:
    global chip_institutional_job_running
    with chip_institutional_job_lock:
        if chip_institutional_job_running:
            return
        chip_institutional_job_running = True

    def worker() -> None:
        global chip_institutional_job_running
        try:
            ensure_chip_institutional_snapshot()
        except Exception:
            app.logger.exception("法人歷史背景補抓失敗")
        finally:
            with chip_institutional_job_lock:
                chip_institutional_job_running = False

    threading.Thread(
        target=worker,
        name="chip-institutional-history",
        daemon=True,
    ).start()


def chip_stock_history_count(stock_code: str) -> int:
    with get_db() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM chip_weekly_metrics WHERE code=?", (stock_code,)
            ).fetchone()[0]
        )


def schedule_chip_stock_history(stock_code: str) -> None:
    with chip_stock_history_lock:
        if stock_code in chip_stock_history_jobs:
            return
        chip_stock_history_jobs.add(stock_code)

    def worker() -> None:
        try:
            chip_dashboard.ensure_stock_history(DB_PATH, stock_code, weeks=9)
        except Exception:
            app.logger.exception("個股籌碼歷史背景補抓失敗: %s", stock_code)
        finally:
            with chip_stock_history_lock:
                chip_stock_history_jobs.discard(stock_code)

    threading.Thread(
        target=worker,
        name=f"chip-history-{stock_code}",
        daemon=True,
    ).start()


def build_chip_rankings_payload() -> dict[str, Any]:
    ensure_chip_dashboard_snapshot()
    market = str(request.args.get("market") or "all").upper()
    if market not in {"ALL", "TWSE", "TPEX"}:
        market = "ALL"
    industry = str(request.args.get("industry") or "").strip()
    return chip_dashboard.rankings_payload(
        DB_PATH,
        market=market.lower() if market == "ALL" else market,
        industry=industry,
        forced_groups_path=BASE_DIR / "FORCED_SECTOR_GROUPS.md",
    )


@app.route("/api/chips/rankings")
def api_chip_rankings() -> Any:
    try:
        return jsonify(build_chip_rankings_payload())
    except Exception as exc:
        app.logger.exception("籌碼排行榜載入失敗")
        return jsonify({"ok": False, "error": f"籌碼排行榜載入失敗：{exc}"}), 500


@app.route("/api/chips/stocks/search")
def api_chip_stock_search() -> Any:
    query = str(request.args.get("q") or "").strip()
    try:
        ensure_chip_dashboard_snapshot()
        return jsonify(chip_dashboard.search_stocks(DB_PATH, query))
    except Exception as exc:
        return jsonify({"ok": False, "error": f"股票搜尋失敗：{exc}"}), 500


@app.route("/api/chips/stocks/<stock_code>")
def api_chip_stock(stock_code: str) -> Any:
    if not re.fullmatch(r"\d{4}", stock_code):
        return jsonify({"ok": False, "error": "股票代號格式錯誤。"}), 400
    try:
        ensure_chip_dashboard_snapshot()
        if chip_stock_history_count(stock_code) < 9:
            schedule_chip_stock_history(stock_code)
        schedule_chip_institutional_snapshot()
        return jsonify(chip_dashboard.stock_payload(DB_PATH, stock_code))
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:
        app.logger.exception("個股籌碼載入失敗: %s", stock_code)
        return jsonify({"ok": False, "error": f"個股籌碼載入失敗：{exc}"}), 500


@app.route("/api/chips/industries")
def api_chip_industries() -> Any:
    try:
        ensure_chip_dashboard_snapshot()
        return jsonify(
            chip_dashboard.industries_payload(
                DB_PATH,
                forced_groups_path=BASE_DIR / "FORCED_SECTOR_GROUPS.md",
            )
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"族群排名載入失敗：{exc}"}), 500


@app.route("/api/chips/featured")
def api_chip_featured() -> Any:
    try:
        ensure_chip_dashboard_snapshot()
        return jsonify(
            chip_dashboard.featured_payload(
                DB_PATH,
                forced_groups_path=BASE_DIR / "FORCED_SECTOR_GROUPS.md",
            )
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"熱門股票載入失敗：{exc}"}), 500


@app.route("/api/market_state")
def api_market_state() -> Any:
    now = taipei_now()
    return jsonify(
        {
            "market_open": is_intraday_market_open(now),
            "now": now.isoformat(timespec="seconds"),
            "timezone": "Asia/Taipei",
        }
    )


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings() -> Any:
    if request.method == "GET":
        return jsonify(read_settings_payload())

    payload = request.get_json(silent=True) or {}
    settings = write_settings_payload(
        finmind_token=payload.get("finmind_token"),
        fugle_intraday_api_key=payload.get("fugle_intraday_api_key"),
    )
    return jsonify({"ok": True, "settings": settings})


@app.route("/api/self_update", methods=["POST"])
def api_self_update() -> Any:
    if IS_FROZEN:
        return jsonify({"ok": False, "error": "可攜式 EXE 版不支援程式內自動更新，請直接下載新的發佈包。"}), 400
    try:
        result = update_project_from_github()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(result)


@app.route("/api/update_status")
def api_update_status() -> Any:
    try:
        result = get_update_status()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(result)


@app.route("/api/fear_greed")
def api_fear_greed() -> Any:
    force_refresh = request.args.get("force_refresh") == "1"
    try:
        return jsonify(fetch_fear_greed_payload(force_refresh=force_refresh))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/serenity/<function_key>", methods=["GET", "POST"])
def api_serenity(function_key: str) -> Any:
    spec = FUNCTION_MAP.get(function_key)
    if spec is None:
        return jsonify({"ok": False, "error": "找不到指定功能。"}), 404
    if function_key not in SERENITY_FUNCTION_KEYS:
        return jsonify({"ok": False, "error": "這個頁面不是選股功能，無法執行 Serenity 分析。"}), 400

    if request.method == "GET":
        result_date = str(request.args.get("result_date") or "").strip()
        if not re.fullmatch(r"\d{8}", result_date):
            return jsonify({"ok": False, "error": "交易日期格式錯誤。"}), 400
        cached = lookup_serenity_cache(function_key, result_date)
        if cached is None:
            return jsonify({"ok": True, "cached": False}), 404
        return jsonify(cached)

    payload = request.get_json(silent=True) or {}
    result_date = str(payload.get("result_date") or "").strip()
    if not re.fullmatch(r"\d{8}", result_date):
        return jsonify({"ok": False, "error": "交易日期格式錯誤。"}), 400

    stocks = normalize_serenity_stocks(payload.get("stocks"))
    if not stocks:
        return jsonify({"ok": False, "error": "目前結果沒有可供 Serenity 分析的股票清單。"}), 400

    force_refresh = payload.get("force_refresh") is True
    requested_codes = [stock["code"] for stock in stocks]
    if not force_refresh:
        cached = lookup_serenity_cache(function_key, result_date)
        cached_codes = cached.get("stock_codes") if cached else None
        if cached is not None and cached_codes == requested_codes:
            return jsonify(cached)

    started = time.perf_counter()
    try:
        analysis, worker_count, research_mode = run_serenity_research(
            spec.name,
            result_date,
            stocks,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    response_payload = {
        "ok": True,
        "function_key": spec.key,
        "function_name": spec.name,
        "result_date": result_date,
        "stock_count": len(stocks),
        "stock_codes": [stock["code"] for stock in stocks],
        "research_mode": research_mode,
        "worker_count": worker_count,
        "analysis": analysis,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "from_cache": False,
    }
    upsert_serenity_cache(function_key, result_date, response_payload)
    return jsonify(response_payload)


@app.route("/api/result")
def api_result() -> Any:
    function_key = request.args.get("function_key") or None
    result_date = request.args.get("result_date") or None
    if not function_key or not result_date:
        return jsonify({"error": "缺少 function_key 或 result_date。"}), 400
    cached = lookup_cache(function_key, result_date)
    if cached is None:
        return jsonify(None)
    return jsonify(attach_institutional_cache(cached))


@app.route("/api/kline/<stock_code>")
def api_kline(stock_code: str) -> Any:
    try:
        end_date = request.args.get("end_date") or latest_valid_shared_date()
        lookback_days = min(max(int(request.args.get("lookback_days") or 1000), 1), 1000)
        payload = build_full_kline_payload(code=stock_code, end_date=end_date, lookback_days=lookback_days)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(payload)


@app.route("/api/kline_batch", methods=["POST"])
def api_kline_batch() -> Any:
    payload = request.get_json(silent=True) or {}
    raw_codes = payload.get("codes") or []
    try:
        end_date = payload.get("end_date") or latest_valid_shared_date()
        lookback_days = min(max(int(payload.get("lookback_days") or 40), 1), 1000)
    except (TypeError, ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400
    codes = [str(code).strip() for code in raw_codes if str(code).strip()]
    if not codes:
        return jsonify({"error": "缺少股票代號清單。"}), 400

    result: dict[str, Any] = {
        "end_date": end_date,
        "lookback_days": lookback_days,
        "items": build_kline_batch_rows(codes=codes, end_date=end_date, lookback_days=lookback_days),
    }
    return jsonify(result)


@app.route("/api/runs")
def api_runs() -> Any:
    function_key = request.args.get("function_key") or None
    return jsonify(recent_runs(function_key=function_key))


@app.route("/api/run/<function_key>", methods=["POST"])
def api_run(function_key: str) -> Any:
    spec = FUNCTION_MAP.get(function_key)
    if spec is None:
        return jsonify({"error": "找不到指定功能。"}), 404
    if not spec.executable:
        return jsonify({"error": "這個項目是展示頁，不需要執行。"}), 400
    payload = request.get_json(silent=True) or {}
    result_date = payload.get("result_date")
    try:
        if function_key in DIRECT_CURRENT_INTRADAY_FUNCTION_KEYS and result_date == current_intraday_date():
            return jsonify(run_current_intraday(spec, result_date))
        return jsonify(run_function(spec, requested_date=result_date))
    except Exception as exc:
        app.logger.exception("選股功能執行失敗: %s", function_key)
        return jsonify({"error": f"選股執行失敗：{exc}"}), 500


@app.route("/api/refresh_future/<function_key>", methods=["POST"])
def api_refresh_future(function_key: str) -> Any:
    """強制重新執行，跳過快取，更新後5日資料。"""
    spec = FUNCTION_MAP.get(function_key)
    if spec is None:
        return jsonify({"error": "找不到指定功能。"}), 404
    if not spec.executable:
        return jsonify({"error": "這個項目不可執行。"}), 400
    payload = request.get_json(silent=True) or {}
    result_date = payload.get("result_date")
    try:
        if function_key in DIRECT_CURRENT_INTRADAY_FUNCTION_KEYS and result_date == current_intraday_date():
            return jsonify(run_current_intraday(spec, result_date, skip_cache=True))
        return jsonify(run_function(spec, requested_date=result_date, skip_cache=True))
    except Exception as exc:
        app.logger.exception("強制重跑失敗: %s", function_key)
        return jsonify({"error": f"強制重跑失敗：{exc}"}), 500


@app.route("/api/backtest-presets", methods=["GET", "POST"])
def api_backtest_presets() -> Any:
    if request.method == "GET":
        with get_db() as conn:
            rows = conn.execute("SELECT id, description, params_json, created_at FROM backtest_presets ORDER BY id DESC").fetchall()
        return jsonify({"presets": [{"id": row["id"], "description": row["description"], "params": json.loads(row["params_json"]), "created_at": row["created_at"]} for row in rows]})

    payload = request.get_json(silent=True) or {}
    description = str(payload.get("description") or "").strip()
    params = payload.get("params")
    if not description:
        return jsonify({"error": "請輸入回測條件說明。"}), 400
    if not isinstance(params, dict):
        return jsonify({"error": "回測條件格式錯誤。"}), 400
    created_at = taipei_now().isoformat(timespec="seconds")
    with get_db() as conn:
        cursor = conn.execute("INSERT INTO backtest_presets (description, params_json, created_at) VALUES (?, ?, ?)", (description, json.dumps(params, ensure_ascii=False), created_at))
        preset_id = cursor.lastrowid
    return jsonify({"ok": True, "preset": {"id": preset_id, "description": description, "params": params, "created_at": created_at}})


@app.route("/api/backtest-presets/<int:preset_id>", methods=["DELETE"])
def api_delete_backtest_preset(preset_id: int) -> Any:
    with get_db() as conn:
        conn.execute("DELETE FROM backtest_presets WHERE id = ?", (preset_id,))
    return jsonify({"ok": True})


@app.route("/api/backtest/<function_key>", methods=["POST"])
def api_backtest(function_key: str) -> Any:
    if function_key not in BACKTESTABLE_FUNCTION_KEYS:
        return jsonify({"error": "只有標準選股與保守選股支援回測。"}), 400

    payload = request.get_json(silent=True) or {}
    start_date = str(payload.get("start_date") or "").strip()
    end_date_value = payload.get("end_date")
    take_profit_value = payload.get("take_profit_pct")
    stop_loss_value = payload.get("stop_loss_pct")
    entry_max_value = payload.get("entry_max_pct")
    entry_min_value = payload.get("entry_min_pct")
    top_n_value = payload.get("top_n")
    max_hold_value = payload.get("max_hold_days")
    total_capital_value = payload.get("total_capital")

    end_date = str(end_date_value if end_date_value not in (None, "") else latest_valid_shared_date()).strip()
    take_profit_pct = str(take_profit_value if take_profit_value not in (None, "") else "10").strip()
    stop_loss_pct = str(stop_loss_value if stop_loss_value not in (None, "") else "5").strip()
    entry_max_pct = str(entry_max_value if entry_max_value not in (None, "") else "3").strip()
    entry_min_pct = str(entry_min_value if entry_min_value not in (None, "") else "-3").strip()
    top_n = str(top_n_value if top_n_value not in (None, "") else "10").strip()
    max_hold_days = str(max_hold_value if max_hold_value not in (None, "") else "5").strip()
    total_capital = str(total_capital_value if total_capital_value not in (None, "") else "100000").strip()
    if not start_date:
        return jsonify({"error": "缺少開始日期。"}), 400

    script_path = SCRIPTS_DIR / "pre_breakout_backtest.py"
    if not script_path.exists():
        return jsonify({"error": "找不到 pre_breakout_backtest.py。"}), 400

    command = build_script_command(
        script_path,
        "--function-key",
        function_key,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--take-profit-pct",
        take_profit_pct,
        "--stop-loss-pct",
        stop_loss_pct,
        "--entry-max-pct",
        entry_max_pct,
        "--entry-min-pct",
        entry_min_pct,
        "--top-n",
        top_n,
        "--max-hold-days",
        max_hold_days,
        "--total-capital",
        total_capital,
    )
    try:
        result = run_command(command, timeout=600)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip() or result.stdout.strip() or "回測失敗。"}), 400
    try:
        return jsonify(json.loads(result.stdout.strip()))
    except Exception:
        return jsonify({"error": "回測輸出不是有效 JSON。", "raw": result.stdout.strip()[:1000]}), 400


@app.route("/api/institutional/<function_key>", methods=["POST"])
def api_institutional(function_key: str) -> Any:
    if function_key not in PRE_BREAKOUT_FUNCTION_KEYS:
        return jsonify({"error": "只有標準選股與保守選股支援法人查詢。"}), 400

    payload = request.get_json(silent=True) or {}
    result_date = payload.get("result_date")
    if not result_date:
        return jsonify({"error": "缺少 result_date。"}), 400

    cached_run = lookup_cache(function_key, result_date)
    if cached_run is None:
        return jsonify({"error": "請先執行選股，再跑法人資料。"}), 400

    cached_institutional = lookup_institutional_cache(function_key, result_date)
    if cached_institutional is not None:
        response = dict(cached_institutional)
        response["from_cache"] = True
        return jsonify(response)

    try:
        status, institutional_payload, duration_seconds = build_institutional_payload(
            function_key=function_key,
            result_date=result_date,
            output_text=cached_run["output_text"],
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    started_at = datetime.fromisoformat(institutional_payload["started_at"])
    finished_at = datetime.fromisoformat(institutional_payload["finished_at"])
    upsert_institutional_cache(
        function_key=function_key,
        result_date=result_date,
        status=status,
        payload=institutional_payload,
        source="finmind",
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
    )
    return jsonify(
        {
            "status": status,
            "payload": institutional_payload,
            "source": "finmind",
            "started_at": institutional_payload["started_at"],
            "finished_at": institutional_payload["finished_at"],
            "duration_seconds": duration_seconds,
            "cached_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "from_cache": False,
        }
    )


@app.route("/api/intraday/<function_key>", methods=["POST"])
def api_intraday(function_key: str) -> Any:
    if function_key not in INTRADAY_FUNCTION_KEYS:
        return jsonify({"error": "這個選股功能目前不支援即時行情。"}), 400

    payload = request.get_json(silent=True) or {}
    result_date = payload.get("result_date")
    if not result_date:
        return jsonify({"error": "缺少 result_date。"}), 400

    if not is_intraday_market_open():
        return jsonify({"error": "目前非盤中時段，即時行情功能暫不啟用。"}), 400

    current_intraday = (
        function_key in DIRECT_CURRENT_INTRADAY_FUNCTION_KEYS
        and result_date == current_intraday_date()
    )
    source_result_date = result_date
    if current_intraday:
        source_result_date = latest_valid_shared_date()
    cached_run = lookup_cache(function_key, source_result_date)
    if cached_run is None:
        return jsonify({"error": "請先執行選股功能，再查即時行情。"}), 400

    try:
        status, intraday_payload, duration_seconds = build_intraday_payload(
            function_key=function_key,
            result_date=result_date,
            output_text=cached_run["output_text"],
            source_result_date=source_result_date if current_intraday else None,
            current_intraday=current_intraday,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "status": status,
            "payload": intraday_payload,
            "source": "fugle_intraday_quote",
            "started_at": intraday_payload["started_at"],
            "finished_at": intraday_payload["finished_at"],
            "duration_seconds": duration_seconds,
            "from_cache": False,
            "current_intraday": current_intraday,
        }
    )


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765, debug=False)
