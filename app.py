from __future__ import annotations

import base64
import hashlib
import json
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

BASE_DIR = Path(__file__).resolve().parent
MILES_AGENT_ROOT = BASE_DIR
SCRIPTS_DIR = BASE_DIR / "scripts"
DATA_ROOT = BASE_DIR / "data"
OUTPUT_ROOT = BASE_DIR / "outputs"
DB_PATH = BASE_DIR / "stock_control_panel.db"
ENV_FILE_PATH = BASE_DIR / ".env"
PYTHON_BIN = sys.executable
GITHUB_REPO_OWNER = "milesc0210"
GITHUB_REPO_NAME = "StockControlPanel"
GITHUB_ZIP_URL = f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/archive/refs/heads/main.zip"
GITHUB_RAW_BASE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/main"
LOCAL_PRESERVE_NAMES = {".env", "stock_control_panel.db", ".git", ".venv", "Release"}
UPDATE_TRACKED_PATHS = [
    "app.py",
    "requirements.txt",
    "start_stock_control_panel.bat",
    "launch_stock_control_panel.py",
    "templates/index.html",
    "static/app.js",
    "static/style.css",
    "scripts/fetch_klines.py",
    "scripts/analyze_today_limitup_sector_groups.py",
    "scripts/screen_today_limitup.py",
    "scripts/pre_breakout_screen.py",
    "scripts/pre_breakout_backtest.py",
    "scripts/twse_tpex_fetch.py",
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

OUTPUT_WATCH_DIRS = [
    OUTPUT_ROOT,
    DATA_ROOT / "pre_breakout",
]
PRE_BREAKOUT_FUNCTION_KEYS = {"pre_breakout_standard", "pre_breakout_conservative"}
BACKTESTABLE_FUNCTION_KEYS = PRE_BREAKOUT_FUNCTION_KEYS
INTRADAY_FUNCTION_KEYS = {
    "pre_breakout_standard",
    "pre_breakout_conservative",
    "ma_bullish_turning_point",
    "limit_up_red_arrow",
}
FEAR_GREED_FUNCTION_KEY = "cnn_fear_greed_index"
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


@dataclass(frozen=True)
class FunctionSpec:
    key: str
    name: str
    category: str
    description: str
    executable: bool


FUNCTIONS: list[FunctionSpec] = [
    FunctionSpec(
        key=FEAR_GREED_FUNCTION_KEY,
        name="美國 CNN 恐懼與貪婪指數",
        category="市場情緒",
        description="查看美股市場目前偏向恐懼或貪婪。",
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
        key="ma_bullish_turning_point",
        name="均線多頭新成形",
        category="訊號型功能",
        description="均線多頭剛成形。",
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
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
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
        if any(keyword in combined for keyword in ["無交易", "放假", "停止交易"]):
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



def current_data_sync_status() -> dict[str, Any]:
    return dict(market_data_sync_state)



def ensure_latest_market_data() -> dict[str, Any]:
    now = taipei_now()
    try:
        expected_date = expected_latest_market_date(now)
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

    latest_local = valid_shared_dates()[-1] if valid_shared_dates() else None
    if latest_local and latest_local >= expected_date:
        status = {
            "status": "up_to_date",
            "message": f"最新資料已存在（{latest_local}）",
            "checked_for": expected_date,
            "last_run": now.isoformat(timespec="seconds"),
            "fetched": False,
        }
        market_data_sync_state.update(status)
        return status

    with market_data_sync_lock:
        latest_local = valid_shared_dates()[-1] if valid_shared_dates() else None
        if latest_local and latest_local >= expected_date:
            status = {
                "status": "up_to_date",
                "message": f"最新資料已存在（{latest_local}）",
                "checked_for": expected_date,
                "last_run": now.isoformat(timespec="seconds"),
                "fetched": False,
            }
            market_data_sync_state.update(status)
            return status

        command = [PYTHON_BIN, str(SCRIPTS_DIR / "twse_tpex_fetch.py"), expected_date]
        result = subprocess.run(
            command,
            cwd=MILES_AGENT_ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        latest_after = valid_shared_dates()[-1] if valid_shared_dates() else None
        fetched_ok = result.returncode == 0 and latest_after and latest_after >= expected_date
        output = (result.stdout or result.stderr or "").strip()
        status = {
            "status": "fetched" if fetched_ok else "failed",
            "message": (
                f"已自動補抓最新資料（{expected_date}）"
                if fetched_ok
                else f"自動補抓 {expected_date} 失敗：{output[:240]}"
            ),
            "checked_for": expected_date,
            "last_run": now.isoformat(timespec="seconds"),
            "fetched": bool(fetched_ok),
            "command": command,
            "returncode": result.returncode,
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


def find_stock_market(code: str, end_date: str) -> tuple[str, str] | None:
    for current_date in reversed(get_date_window(end_date, lookback_days=60)):
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
    market_info = find_stock_market(code, end_date)
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
        return [[PYTHON_BIN, str(scripts_dir / "screen_limitup_upperwick.py"), "--latest-date", latest_date, "--no-save"]]
    if spec.key == "today_limit_up":
        return [
            [PYTHON_BIN, str(scripts_dir / "screen_today_limitup.py"), "--date", latest_date, "--no-save"],
            [PYTHON_BIN, str(scripts_dir / "analyze_today_limitup_sector_groups.py"), "--date", latest_date, "--no-save"],
        ]
    if spec.key == "ma_bullish_turning_point":
        return [
            [PYTHON_BIN, str(scripts_dir / "screen_ma_alignment_turning_point.py"), "--latest-date", latest_date, "--no-save"],
            [PYTHON_BIN, str(scripts_dir / "analyze_012_sector_groups.py"), "--latest-date", latest_date, "--no-save"],
        ]
    if spec.key == "pre_breakout_standard":
        pre_breakout_script = resolve_pre_breakout_script()
        return [[PYTHON_BIN, str(pre_breakout_script), "--date", latest_date, "--relaxed"]]
    if spec.key == "pre_breakout_conservative":
        pre_breakout_script = resolve_pre_breakout_script()
        return [[PYTHON_BIN, str(pre_breakout_script), "--date", latest_date]]
    return []


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
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
    if function_key in {"limit_up_red_arrow", "today_limit_up", "ma_bullish_turning_point"} and "後5日=" not in output_text:
        return None
    if function_key == "today_limit_up" and "策略：今日漲停 快速族群分析" not in output_text:
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

    latest_date = latest_valid_shared_date()
    if (
        function_key in {
            "limit_up_red_arrow",
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
    current_time = current.time()
    return dt_time(9, 0) <= current_time <= dt_time(13, 30)


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
            }
        )
    return stocks


def parse_limit_up_candidates(output_text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"^(TWSE|TPEX)\s+(\d+)\s+(.+?)\s+\|\s+.+?C=([\d.]+)\s+V=([\d.]+)張(?:\s+\|\s+上影=([\d.]+)\s+實體=([\d.]+)\s+比=([\d.-]+))?(?:\s+\|\s+後5日=(.+))?$"
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
        r"^(TWSE|TPEX)\s+(\d+)\s+(.+?)\s+\|\s+C=([\d.]+)\s+V=([\d.]+)張\s+倍數=([\d.]+)\s+\|\s+後5日=(.+)$"
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


def parse_intraday_candidates(function_key: str, output_text: str) -> list[dict[str, str]]:
    if function_key in PRE_BREAKOUT_FUNCTION_KEYS:
        return parse_pre_breakout_candidates(output_text)
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


def build_intraday_payload(function_key: str, result_date: str, output_text: str) -> tuple[str, dict[str, Any], float]:
    if function_key not in INTRADAY_FUNCTION_KEYS:
        raise RuntimeError("只有標準選股、保守選股、均線多頭新成形、漲停紅箭支援即時行情。")
    if not is_intraday_market_open():
        raise RuntimeError("目前非盤中時段，即時行情功能暫不啟用。")
    if not get_secret_value("FUGLE_INTRADAY_API_KEY"):
        raise RuntimeError("缺少 FUGLE_INTRADAY_API_KEY，請先到設定頁輸入富果 API Key。")

    started_at = taipei_now()
    started_perf = time.perf_counter()
    candidates = parse_intraday_candidates(function_key, output_text)
    if not candidates:
        raise RuntimeError("目前結果沒有可查詢的股票清單。")

    quotes: dict[str, Any] = {}
    success_count = 0
    for stock in candidates:
        code = stock["code"]
        try:
            quote = fetch_fugle_intraday_quote(code)
            total = quote.get("total") or {}
            last_trade = quote.get("lastTrade") or {}
            quotes[code] = {
                "code": code,
                "name": stock["name"],
                "last_price": quote.get("lastPrice") or quote.get("closePrice"),
                "trade_volume": total.get("tradeVolume"),
                "change_percent": quote.get("changePercent"),
                "last_trade_time": last_trade.get("time") or total.get("time"),
                "is_close": quote.get("isClose"),
            }
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
        "quotes": quotes,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "market_open": True,
    }
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


def _fetch_cnn_fear_greed_api_payload() -> dict[str, Any]:
    request = urllib.request.Request(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.cnn.com/markets/fear-and-greed",
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
    recommendation = _build_fear_greed_recommendation(current_score)
    return {
        "source": "CNN Fear & Greed Index",
        "score": current_score,
        "rating": _title_case_rating(current.get("rating", "")),
        "status_text": f"{_title_case_rating(current.get('rating', ''))} is driving the US market",
        "updated_at": _format_cnn_timestamp(str(current.get("timestamp") or "")),
        "history": [
            {"label": "前一收盤", "score": round(float(current.get("previous_close") or 0), 2)},
            {"label": "1 週前", "score": round(float(current.get("previous_1_week") or 0), 2)},
            {"label": "1 個月前", "score": round(float(current.get("previous_1_month") or 0), 2)},
            {"label": "1 年前", "score": round(float(current.get("previous_1_year") or 0), 2)},
        ],
        "one_year_history": history_points,
        "recommendation": recommendation,
        "thresholds": {"buy": 25, "neutral": 50, "sell": 75},
        "indicators": [],
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "from_cache": False,
    }


def fetch_cnn_fear_greed_payload(force_refresh: bool = False) -> dict[str, Any]:
    now_ts = time.time()
    with fear_greed_cache_lock:
        cached_payload = fear_greed_cache_state.get("payload")
        fetched_at = float(fear_greed_cache_state.get("fetched_at") or 0.0)
        if not force_refresh and cached_payload and now_ts - fetched_at < FEAR_GREED_CACHE_TTL_SECONDS:
            response = dict(cached_payload)
            response["from_cache"] = True
            return response

    try:
        payload = _fetch_cnn_fear_greed_api_payload()
    except Exception:
        browser_path = _find_headless_browser_path()
        command = [
            browser_path,
            "--headless",
            "--disable-gpu",
            "--virtual-time-budget=15000",
            "--dump-dom",
            "https://www.cnn.com/markets/fear-and-greed",
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
        payload = {
            "source": "CNN Fear & Greed Index",
            "score": fallback_score,
            "rating": _title_case_rating(rating_match.group(1)),
            "status_text": f"{_title_case_rating(rating_match.group(1))} is driving the US market",
            "updated_at": _normalize_space(timestamp_match.group(1)) if timestamp_match else "",
            "history": [
                item
                for item in [
                    _extract_fear_greed_history(html, "prevClose", "前一收盤"),
                    _extract_fear_greed_history(html, "weekClose", "1 週前"),
                    _extract_fear_greed_history(html, "monthClose", "1 個月前"),
                    _extract_fear_greed_history(html, "yearClose", "1 年前"),
                ]
                if item is not None
            ],
            "one_year_history": [],
            "recommendation": _build_fear_greed_recommendation(fallback_score),
            "thresholds": {"buy": 25, "neutral": 50, "sell": 75},
            "indicators": _extract_fear_greed_indicators(html),
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "from_cache": False,
        }

    with fear_greed_cache_lock:
        fear_greed_cache_state["payload"] = dict(payload)
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
    return subprocess.run(
        command,
        cwd=MILES_AGENT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
    )


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
            env=os.environ.copy(),
        )
        step_header = f"$ {' '.join(command)}"
        step_body = result.stdout.strip()
        step_error = result.stderr.strip()
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
    return jsonify({"dates": dates, "latest_date": latest_date, "sync_status": sync_status})


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
        return jsonify(fetch_cnn_fear_greed_payload(force_refresh=force_refresh))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


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
    end_date = request.args.get("end_date") or latest_valid_shared_date()
    lookback_days = int(request.args.get("lookback_days") or 60)
    try:
        payload = build_full_kline_payload(code=stock_code, end_date=end_date, lookback_days=lookback_days)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(payload)


@app.route("/api/kline_batch", methods=["POST"])
def api_kline_batch() -> Any:
    payload = request.get_json(silent=True) or {}
    raw_codes = payload.get("codes") or []
    end_date = payload.get("end_date") or latest_valid_shared_date()
    lookback_days = int(payload.get("lookback_days") or 40)
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
    return jsonify(run_function(spec, requested_date=result_date))


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
    return jsonify(run_function(spec, requested_date=result_date, skip_cache=True))


@app.route("/api/backtest/<function_key>", methods=["POST"])
def api_backtest(function_key: str) -> Any:
    if function_key not in BACKTESTABLE_FUNCTION_KEYS:
        return jsonify({"error": "只有標準選股與保守選股支援回測。"}), 400

    payload = request.get_json(silent=True) or {}
    start_date = str(payload.get("start_date") or "").strip()
    end_date = str(payload.get("end_date") or latest_valid_shared_date()).strip()
    take_profit_pct = str(payload.get("take_profit_pct") or "10").strip()
    stop_loss_pct = str(payload.get("stop_loss_pct") or "5").strip()
    entry_band_pct = str(payload.get("entry_band_pct") or "3").strip()
    max_hold_days = str(payload.get("max_hold_days") or "5").strip()
    shares = str(payload.get("shares") or "1000").strip()
    if not start_date:
        return jsonify({"error": "缺少開始日期。"}), 400

    script_path = SCRIPTS_DIR / "pre_breakout_backtest.py"
    if not script_path.exists():
        return jsonify({"error": "找不到 pre_breakout_backtest.py。"}), 400

    command = [
        PYTHON_BIN,
        str(script_path),
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
        "--entry-band-pct",
        entry_band_pct,
        "--max-hold-days",
        max_hold_days,
        "--shares",
        shares,
    ]
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
        return jsonify({"error": "只有標準選股、保守選股、均線多頭新成形、漲停紅箭支援即時行情。"}), 400

    payload = request.get_json(silent=True) or {}
    result_date = payload.get("result_date")
    if not result_date:
        return jsonify({"error": "缺少 result_date。"}), 400

    if not is_intraday_market_open():
        return jsonify({"error": "目前非盤中時段，即時行情功能暫不啟用。"}), 400

    cached_run = lookup_cache(function_key, result_date)
    if cached_run is None:
        return jsonify({"error": "請先執行選股功能，再查即時行情。"}), 400

    try:
        status, intraday_payload, duration_seconds = build_intraday_payload(
            function_key=function_key,
            result_date=result_date,
            output_text=cached_run["output_text"],
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
        }
    )


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765, debug=False)
