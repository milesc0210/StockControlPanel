from __future__ import annotations

import csv
import html
import json
import math
import re
import sqlite3
import statistics
import time
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests


CALCULATION_VERSION = "chip-v1"
TDCC_SOURCE_CODE = "TDCC_1_5"
TDCC_OPENAPI_URL = "https://openapi.tdcc.com.tw/v1/opendata/1-5"
TDCC_HISTORY_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
TWSE_COMPANY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TWSE_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_REVENUE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
TWSE_INSTITUTIONAL_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_INSTITUTIONAL_URL = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
}


def load_forced_sector_groups(path: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    if not path.exists():
        return {}, {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return {}, {}
    groups: dict[str, list[str]] = {}
    current_group = ""
    safety_codes: list[str] = []
    in_safety_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## 安全監控例外"):
            current_group = "安全監控"
            in_safety_section = True
            groups.setdefault(current_group, [])
            continue
        if line.startswith("## "):
            current_group = ""
            in_safety_section = False
            continue
        if line.startswith("### "):
            current_group = re.sub(r"（.*?）", "", line[4:]).strip()
            in_safety_section = current_group == "安全監控"
            groups.setdefault(current_group, [])
            continue
        if not current_group or not line.startswith("-"):
            continue
        for code in re.findall(r"(?<!\d)(\d{4})(?!\d)", line):
            if code not in groups[current_group]:
                groups[current_group].append(code)
            if in_safety_section and code not in safety_codes:
                safety_codes.append(code)
    code_to_group: dict[str, str] = {}
    for group_name, codes in groups.items():
        if group_name == "安全監控":
            continue
        for code in codes:
            code_to_group.setdefault(code, group_name)
    for code in safety_codes:
        code_to_group[code] = "安全監控"
    return groups, code_to_group


def _number(value: Any, default: float = 0.0) -> float:
    text = str(value or "").replace(",", "").replace("+", "").strip()
    if not text or text in {"--", "---", "－"}:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    return int(round(_number(value, float(default))))


def _row_value(row: dict[str, Any], *aliases: str) -> Any:
    normalized = {str(key).replace("\ufeff", "").strip(): value for key, value in row.items()}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def aggregate_tdcc_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    large_holder_shares = 0
    total_shares = 0
    materialized = list(rows)
    total_level = 17 if any(
        _integer(_row_value(row, "持股分級", "level")) == 17 for row in materialized
    ) else 16
    large_holder_start_level = 12
    for row in materialized:
        level = _integer(_row_value(row, "持股分級", "level"))
        shares = _integer(_row_value(row, "股數", "shares"))
        if large_holder_start_level <= level <= 15:
            large_holder_shares += shares
        if level == total_level:
            total_shares = shares
    ratio = (large_holder_shares / total_shares * 100.0) if total_shares > 0 else 0.0
    return {
        "large_holder_shares": large_holder_shares,
        "large_holder_lots": large_holder_shares / 1000.0,
        "total_shares": total_shares,
        "large_holder_ratio": round(ratio, 4),
    }


def calculate_weekly_change(
    current: dict[str, Any], previous: dict[str, Any]
) -> dict[str, Any] | None:
    current_shares = _integer(current.get("large_holder_shares"))
    previous_shares = _integer(previous.get("large_holder_shares"))
    if previous_shares <= 0:
        return None
    change_shares = current_shares - previous_shares
    return {
        "change_shares": change_shares,
        "change_lots": change_shares / 1000.0,
        "change_rate": round(change_shares / previous_shares * 100.0, 4),
        "ratio_change_pp": round(
            _number(current.get("large_holder_ratio"))
            - _number(previous.get("large_holder_ratio")),
            4,
        ),
    }


def institutional_volume_ratio(net_lots: Any, volume_lots: Any) -> float | None:
    volume = _number(volume_lots)
    if volume <= 0:
        return None
    return round(_number(net_lots) / volume * 100.0, 4)


def percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    if len(values) == 1:
        only_key = next(iter(values))
        return {only_key: 100.0}
    sorted_values = sorted(float(value) for value in values.values())
    result: dict[str, float] = {}
    for key, raw_value in values.items():
        value = float(raw_value)
        positions = [index for index, item in enumerate(sorted_values) if item == value]
        average_position = sum(positions) / len(positions)
        result[key] = round(average_position / (len(sorted_values) - 1) * 100.0, 4)
    return result


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chip_stocks (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            industry_code TEXT,
            industry_name TEXT,
            product_type TEXT NOT NULL DEFAULT 'stock',
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chip_stocks_name ON chip_stocks(name);
        CREATE INDEX IF NOT EXISTS idx_chip_stocks_industry ON chip_stocks(industry_name, code);

        CREATE TABLE IF NOT EXISTS chip_tdcc_raw (
            data_date TEXT NOT NULL,
            code TEXT NOT NULL,
            level INTEGER NOT NULL,
            holders INTEGER NOT NULL,
            shares INTEGER NOT NULL,
            ratio REAL,
            source_code TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            PRIMARY KEY (data_date, code, level)
        );
        CREATE INDEX IF NOT EXISTS idx_chip_tdcc_code_date ON chip_tdcc_raw(code, data_date DESC);

        CREATE TABLE IF NOT EXISTS chip_weekly_metrics (
            data_date TEXT NOT NULL,
            code TEXT NOT NULL,
            large_holder_shares INTEGER NOT NULL,
            total_shares INTEGER NOT NULL,
            large_holder_ratio REAL NOT NULL,
            change_shares INTEGER,
            change_rate REAL,
            ratio_change_pp REAL,
            consecutive_increase INTEGER NOT NULL DEFAULT 0,
            consecutive_decrease INTEGER NOT NULL DEFAULT 0,
            market_rank INTEGER,
            industry_rank INTEGER,
            calculation_version TEXT NOT NULL,
            calculated_at TEXT NOT NULL,
            PRIMARY KEY (data_date, code)
        );
        CREATE INDEX IF NOT EXISTS idx_chip_weekly_rank ON chip_weekly_metrics(data_date, change_rate DESC);

        CREATE TABLE IF NOT EXISTS chip_institutional_daily (
            trade_date TEXT NOT NULL,
            code TEXT NOT NULL,
            foreign_lots REAL NOT NULL,
            investment_trust_lots REAL NOT NULL,
            dealer_lots REAL NOT NULL,
            total_lots REAL NOT NULL,
            volume_lots REAL,
            volume_ratio REAL,
            source_code TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, code)
        );

        CREATE TABLE IF NOT EXISTS chip_data_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            data_date TEXT,
            status TEXT NOT NULL,
            raw_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT
        );
        """
    )


def _ordinary_stock_code(code: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", str(code).strip()))


def _now_text() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def upsert_stock_master(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    now = _now_text()
    count = 0
    for row in rows:
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        market = str(row.get("market") or "").strip().upper()
        if not _ordinary_stock_code(code) or not name or market not in {"TWSE", "TPEX"}:
            continue
        conn.execute(
            """
            INSERT INTO chip_stocks (
                code, name, market, industry_code, industry_name,
                product_type, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'stock', 1, ?)
            ON CONFLICT(code) DO UPDATE SET
                name=excluded.name,
                market=excluded.market,
                industry_code=excluded.industry_code,
                industry_name=excluded.industry_name,
                active=1,
                updated_at=excluded.updated_at
            """,
            (
                code,
                name,
                market,
                str(row.get("industry_code") or "").strip(),
                str(row.get("industry_name") or "未分類").strip() or "未分類",
                now,
            ),
        )
        count += 1
    return count


def fetch_stock_master(session: requests.Session | None = None) -> list[dict[str, Any]]:
    http = session or requests.Session()
    http.headers.update(DEFAULT_HEADERS)
    result: list[dict[str, Any]] = []
    sources = [
        ("TWSE", TWSE_COMPANY_URL, TWSE_REVENUE_URL),
        ("TPEX", TPEX_COMPANY_URL, TPEX_REVENUE_URL),
    ]
    for market, company_url, industry_url in sources:
        company_response = http.get(company_url, timeout=60)
        company_response.raise_for_status()
        industry_response = http.get(industry_url, timeout=60)
        industry_response.raise_for_status()
        industry_lookup = {
            str(
                _row_value(row, "公司代號", "SecuritiesCompanyCode") or ""
            ).strip(): str(
                _row_value(
                    row,
                    "產業別",
                    "SecuritiesIndustryName",
                    "IndustryName",
                ) or "未分類"
            ).strip()
            for row in industry_response.json()
        }
        for row in company_response.json():
            code = str(
                _row_value(row, "公司代號", "出表日期", "SecuritiesCompanyCode") or ""
            ).strip()
            if not _ordinary_stock_code(code):
                continue
            result.append(
                {
                    "code": code,
                    "name": str(
                        _row_value(row, "公司簡稱", "公司名稱", "CompanyAbbreviation") or ""
                    ).strip(),
                    "market": market,
                    "industry_code": str(
                        _row_value(row, "產業別", "產業代號", "SecuritiesIndustryCode") or ""
                    ).strip(),
                    "industry_name": industry_lookup.get(code, "未分類"),
                }
            )
    return result


def fetch_tdcc_latest(session: requests.Session | None = None) -> list[dict[str, Any]]:
    http = session or requests.Session()
    response = http.get(TDCC_OPENAPI_URL, headers=DEFAULT_HEADERS, timeout=180)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("TDCC 最新集保資料為空。")
    return payload


def import_tdcc_rows(
    conn: sqlite3.Connection,
    rows: Iterable[dict[str, Any]],
    *,
    source_code: str = TDCC_SOURCE_CODE,
) -> tuple[str, int]:
    imported_at = _now_text()
    data_date = ""
    count = 0
    for row in rows:
        code = str(_row_value(row, "證券代號", "code") or "").strip()
        row_date = str(_row_value(row, "資料日期", "data_date") or "").strip()
        level = _integer(_row_value(row, "持股分級", "level"))
        if not _ordinary_stock_code(code) or not re.fullmatch(r"\d{8}", row_date) or level < 1:
            continue
        data_date = row_date
        conn.execute(
            """
            INSERT INTO chip_tdcc_raw (
                data_date, code, level, holders, shares, ratio, source_code, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(data_date, code, level) DO UPDATE SET
                holders=excluded.holders,
                shares=excluded.shares,
                ratio=excluded.ratio,
                source_code=excluded.source_code,
                imported_at=excluded.imported_at
            """,
            (
                row_date,
                code,
                level,
                _integer(_row_value(row, "人數", "holders")),
                _integer(_row_value(row, "股數", "shares")),
                _number(_row_value(row, "占集保庫存數比例%", "ratio")),
                source_code,
                imported_at,
            ),
        )
        count += 1
    return data_date, count


def _metric_history(conn: sqlite3.Connection, code: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM chip_weekly_metrics WHERE code=? ORDER BY data_date",
        (code,),
    ).fetchall()


def recompute_metrics(conn: sqlite3.Connection) -> int:
    raw = conn.execute(
        """
        SELECT data_date, code, level, shares
        FROM chip_tdcc_raw
        ORDER BY code, data_date, level
        """
    ).fetchall()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        grouped[(str(row["code"]), str(row["data_date"]))].append(dict(row))

    by_code: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for (code, data_date), rows in grouped.items():
        by_code[code].append((data_date, aggregate_tdcc_rows(rows)))

    conn.execute("DELETE FROM chip_weekly_metrics")
    calculated_at = _now_text()
    inserted = 0
    for code, items in by_code.items():
        items.sort(key=lambda item: item[0])
        increase_streak = 0
        decrease_streak = 0
        previous: dict[str, Any] | None = None
        for data_date, metric in items:
            change = calculate_weekly_change(metric, previous) if previous else None
            rate = change["change_rate"] if change else None
            if rate is not None and rate > 0:
                increase_streak += 1
                decrease_streak = 0
            elif rate is not None and rate < 0:
                decrease_streak += 1
                increase_streak = 0
            else:
                increase_streak = decrease_streak = 0
            conn.execute(
                """
                INSERT INTO chip_weekly_metrics (
                    data_date, code, large_holder_shares, total_shares,
                    large_holder_ratio, change_shares, change_rate,
                    ratio_change_pp, consecutive_increase, consecutive_decrease,
                    calculation_version, calculated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data_date,
                    code,
                    metric["large_holder_shares"],
                    metric["total_shares"],
                    metric["large_holder_ratio"],
                    change["change_shares"] if change else None,
                    rate,
                    change["ratio_change_pp"] if change else None,
                    increase_streak,
                    decrease_streak,
                    CALCULATION_VERSION,
                    calculated_at,
                ),
            )
            inserted += 1
            previous = metric

    dates = [row[0] for row in conn.execute("SELECT DISTINCT data_date FROM chip_weekly_metrics")]
    for data_date in dates:
        rows = conn.execute(
            """
            SELECT m.code, m.change_rate, s.industry_name
            FROM chip_weekly_metrics m
            LEFT JOIN chip_stocks s ON s.code=m.code
            WHERE m.data_date=? AND m.change_rate IS NOT NULL
            ORDER BY m.change_rate DESC, m.code
            """,
            (data_date,),
        ).fetchall()
        industry_positions: dict[str, int] = defaultdict(int)
        for market_rank, row in enumerate(rows, 1):
            industry = str(row["industry_name"] or "未分類")
            industry_positions[industry] += 1
            conn.execute(
                """UPDATE chip_weekly_metrics
                   SET market_rank=?, industry_rank=?
                   WHERE data_date=? AND code=?""",
                (market_rank, industry_positions[industry], data_date, row["code"]),
            )
    return inserted


def sync_latest_snapshot(db_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        master_count = upsert_stock_master(conn, fetch_stock_master())
        data_date, raw_count = import_tdcc_rows(conn, fetch_tdcc_latest())
        metric_count = recompute_metrics(conn)
    return {
        "ok": True,
        "data_date": data_date,
        "stock_count": master_count,
        "raw_count": raw_count,
        "metric_count": metric_count,
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def import_local_tdcc_archives(db_path: Path, archive_dir: Path) -> int:
    if not archive_dir.exists():
        return 0
    imported = 0
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        for path in sorted(archive_dir.glob("tdcc_*.csv")):
            try:
                rows = list(csv.DictReader(StringIO(path.read_text(encoding="utf-8-sig"))))
            except (OSError, UnicodeError):
                continue
            _, count = import_tdcc_rows(conn, rows, source_code=TDCC_SOURCE_CODE)
            imported += count
        if imported:
            recompute_metrics(conn)
        conn.commit()
    return imported


def import_local_stock_master(db_path: Path, master_path: Path) -> int:
    if not master_path.exists():
        return 0
    try:
        rows = list(csv.DictReader(StringIO(master_path.read_text(encoding="utf-8-sig"))))
    except (OSError, UnicodeError):
        return 0
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        imported = upsert_stock_master(conn, rows)
        conn.commit()
    return imported


def available_tdcc_dates(session: requests.Session | None = None) -> list[str]:
    http = session or requests.Session()
    response = http.get(TDCC_HISTORY_URL, headers=DEFAULT_HEADERS, timeout=30)
    response.raise_for_status()
    return list(dict.fromkeys(re.findall(r'<option[^>]*value="(\d{8})"', response.text)))


def _strip_html(text: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).replace("\xa0", " ").strip()


def _parse_tdcc_history_page(page: str, data_date: str, code: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.I | re.S):
        cells = [_strip_html(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.I | re.S)]
        if len(cells) < 5 or not re.fullmatch(r"\d{1,2}", cells[0]):
            continue
        rows.append(
            {
                "資料日期": data_date,
                "證券代號": code,
                "持股分級": cells[0],
                "人數": cells[-3],
                "股數": cells[-2],
                "占集保庫存數比例%": cells[-1],
            }
        )
    return rows if len(rows) >= 16 else []


def fetch_tdcc_stock_history(
    code: str,
    *,
    weeks: int = 9,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    if not _ordinary_stock_code(code):
        raise ValueError("股票代號格式錯誤。")
    http = session or requests.Session()
    http.headers.update(DEFAULT_HEADERS)
    first = http.get(TDCC_HISTORY_URL, timeout=30)
    first.raise_for_status()
    dates = list(dict.fromkeys(re.findall(r'<option[^>]*value="(\d{8})"', first.text)))[: max(1, weeks)]
    all_rows: list[dict[str, Any]] = []
    for data_date in dates:
        landing = http.get(TDCC_HISTORY_URL, timeout=30)
        landing.raise_for_status()
        token_match = re.search(
            r'name=["\']SYNCHRONIZER_TOKEN["\'][^>]*value=["\']([^"\']+)',
            landing.text,
        )
        if not token_match:
            continue
        payload = {
            "SYNCHRONIZER_TOKEN": token_match.group(1),
            "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
            "method": "submit",
            "firDate": data_date,
            "scaDate": data_date,
            "sqlMethod": "StockNo",
            "stockNo": code,
            "stockName": "",
        }
        response = http.post(TDCC_HISTORY_URL, data=payload, timeout=30)
        response.raise_for_status()
        all_rows.extend(_parse_tdcc_history_page(response.text, data_date, code))
    return all_rows


def fetch_tdcc_stock_week(
    code: str,
    data_date: str,
    *,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    if not _ordinary_stock_code(code) or not re.fullmatch(r"\d{8}", data_date):
        raise ValueError("股票代號或資料日期格式錯誤。")
    http = session or requests.Session()
    http.headers.update(DEFAULT_HEADERS)
    landing = http.get(TDCC_HISTORY_URL, timeout=30)
    landing.raise_for_status()
    token_match = re.search(
        r'name=["\']SYNCHRONIZER_TOKEN["\'][^>]*value=["\']([^"\']+)',
        landing.text,
    )
    if not token_match:
        raise RuntimeError("TDCC 查詢頁缺少同步權杖。")
    response = http.post(
        TDCC_HISTORY_URL,
        data={
            "SYNCHRONIZER_TOKEN": token_match.group(1),
            "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
            "method": "submit",
            "firDate": data_date,
            "scaDate": data_date,
            "sqlMethod": "StockNo",
            "stockNo": code,
            "stockName": "",
        },
        timeout=30,
    )
    response.raise_for_status()
    return _parse_tdcc_history_page(response.text, data_date, code)


def ensure_stock_history(db_path: Path, code: str, weeks: int = 9) -> int:
    rows = fetch_tdcc_stock_history(code, weeks=weeks)
    if not rows:
        return 0
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        _, count = import_tdcc_rows(conn, rows, source_code="TDCC_HISTORY")
        recompute_metrics(conn)
    return count


def _roc_date(yyyymmdd: str) -> str:
    date = datetime.strptime(yyyymmdd, "%Y%m%d")
    return f"{date.year - 1911:03d}/{date.month:02d}/{date.day:02d}"


def _market_volume_lots(data_root: Path, trade_date: str, market: str) -> dict[str, float]:
    path = data_root / market.lower() / trade_date[:4] / f"{trade_date}.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if market == "TWSE":
        fields = [str(value).replace(" ", "").strip() for value in payload.get("fields", [])]
        rows = payload.get("data", [])
        code_name, volume_name = "證券代號", "成交股數"
    else:
        table = (payload.get("tables") or [{}])[0]
        fields = [str(value).replace(" ", "").strip() for value in table.get("fields", [])]
        rows = table.get("data", [])
        code_name, volume_name = "代號", "成交股數"
    try:
        code_index = fields.index(code_name)
        volume_index = fields.index(volume_name)
    except ValueError:
        return {}
    return {
        str(row[code_index]).strip(): _number(row[volume_index]) / 1000.0
        for row in rows
        if len(row) > max(code_index, volume_index)
    }


def _twse_institutional_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields = [str(value).replace(" ", "").strip() for value in payload.get("fields", [])]
    aliases = {
        "code": "證券代號",
        "foreign": "外陸資買賣超股數(不含外資自營商)",
        "trust": "投信買賣超股數",
        "dealer": "自營商買賣超股數",
        "total": "三大法人買賣超股數",
    }
    index = {key: fields.index(name) for key, name in aliases.items() if name in fields}
    if set(index) != set(aliases):
        return []
    return [
        {
            "code": str(row[index["code"]]).strip(),
            "foreign_lots": _number(row[index["foreign"]]) / 1000.0,
            "investment_trust_lots": _number(row[index["trust"]]) / 1000.0,
            "dealer_lots": _number(row[index["dealer"]]) / 1000.0,
            "total_lots": _number(row[index["total"]]) / 1000.0,
        }
        for row in payload.get("data", [])
        if len(row) > max(index.values())
    ]


def _tpex_institutional_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    table = (payload.get("tables") or [{}])[0]
    fields = [str(value).replace(" ", "").strip() for value in table.get("fields", [])]
    expected_fields = ["代號", "名稱"] + ["買進股數", "賣出股數", "買賣超股數"] * 7 + ["三大法人買賣超股數合計"]
    if fields != expected_fields:
        return []
    rows = table.get("data", [])
    return [
        {
            "code": str(row[0]).strip(),
            "foreign_lots": _number(row[10]) / 1000.0,
            "investment_trust_lots": _number(row[13]) / 1000.0,
            "dealer_lots": _number(row[22]) / 1000.0,
            "total_lots": _number(row[23]) / 1000.0,
        }
        for row in rows
        if len(row) == 24 and _ordinary_stock_code(str(row[0]).strip())
    ]


def import_institutional_day(
    conn: sqlite3.Connection,
    *,
    trade_date: str,
    market: str,
    rows: Iterable[dict[str, Any]],
    volumes: dict[str, float],
) -> int:
    imported_at = _now_text()
    source_code = "TWSE_T86" if market == "TWSE" else "TPEX_3INSTI"
    count = 0
    for row in rows:
        code = str(row.get("code") or "").strip()
        if not _ordinary_stock_code(code):
            continue
        volume = volumes.get(code)
        total_lots = _number(row.get("total_lots"))
        conn.execute(
            """
            INSERT INTO chip_institutional_daily (
                trade_date, code, foreign_lots, investment_trust_lots,
                dealer_lots, total_lots, volume_lots, volume_ratio,
                source_code, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date, code) DO UPDATE SET
                foreign_lots=excluded.foreign_lots,
                investment_trust_lots=excluded.investment_trust_lots,
                dealer_lots=excluded.dealer_lots,
                total_lots=excluded.total_lots,
                volume_lots=excluded.volume_lots,
                volume_ratio=excluded.volume_ratio,
                source_code=excluded.source_code,
                imported_at=excluded.imported_at
            """,
            (
                trade_date, code, _number(row.get("foreign_lots")),
                _number(row.get("investment_trust_lots")), _number(row.get("dealer_lots")),
                total_lots, volume, institutional_volume_ratio(total_lots, volume),
                source_code, imported_at,
            ),
        )
        count += 1
    return count


def ensure_institutional_history(
    db_path: Path,
    data_root: Path,
    trade_dates: list[str],
    *,
    session: requests.Session | None = None,
) -> int:
    http = session or requests.Session()
    http.headers.update(DEFAULT_HEADERS)
    inserted = 0
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        for trade_date in trade_dates[-10:]:
            for market in ("TWSE", "TPEX"):
                source_code = "TWSE_T86" if market == "TWSE" else "TPEX_3INSTI"
                if conn.execute(
                    "SELECT 1 FROM chip_institutional_daily WHERE trade_date=? AND source_code=? LIMIT 1",
                    (trade_date, source_code),
                ).fetchone():
                    continue
                volumes = _market_volume_lots(data_root, trade_date, market)
                if market == "TWSE":
                    response = http.get(TWSE_INSTITUTIONAL_URL, params={"response": "json", "date": trade_date, "selectType": "ALLBUT0999"}, timeout=60)
                    response.raise_for_status()
                    rows = _twse_institutional_rows(response.json())
                else:
                    response = http.get(TPEX_INSTITUTIONAL_URL, params={"l": "zh-tw", "o": "json", "d": _roc_date(trade_date), "s": "0,asc"}, timeout=60)
                    response.raise_for_status()
                    rows = _tpex_institutional_rows(response.json())
                inserted += import_institutional_day(conn, trade_date=trade_date, market=market, rows=rows, volumes=volumes)
    return inserted


def _meta(data_date: str | None, *, from_cache: bool = True) -> dict[str, Any]:
    return {
        "ok": True,
        "data_date": data_date,
        "source_codes": [TDCC_SOURCE_CODE],
        "calculation_version": CALCULATION_VERSION,
        "from_cache": from_cache,
        "is_latest": True,
    }


def _status_tags(row: sqlite3.Row) -> list[str]:
    tags: list[str] = []
    rate = row["change_rate"]
    if row["consecutive_increase"] >= 3:
        tags.append("連 3 週以上增加")
    elif row["consecutive_increase"] >= 2:
        tags.append("連 2 週增加")
    if row["consecutive_decrease"] >= 3:
        tags.append("連 3 週以上減少")
    elif row["consecutive_decrease"] >= 2:
        tags.append("連 2 週減少")
    if rate is not None and abs(float(rate)) < 0.05:
        tags.append("本週變化接近零")
    return tags


def _serialize_metric(
    row: sqlite3.Row,
    *,
    forced_group_by_code: dict[str, str] | None = None,
) -> dict[str, Any]:
    code = str(row["code"])
    if forced_group_by_code is None:
        industry_name = row["industry_name"] or "未分類"
    else:
        industry_name = forced_group_by_code.get(code, "未分類")
    return {
        "code": code,
        "name": row["name"] or row["code"],
        "market": row["market"] or "",
        "industry": industry_name,
        "data_date": row["data_date"],
        "large_holder_lots": round(row["large_holder_shares"] / 1000.0, 2),
        "large_holder_ratio": row["large_holder_ratio"],
        "change_lots": round((row["change_shares"] or 0) / 1000.0, 2),
        "change_rate": row["change_rate"],
        "ratio_change_pp": row["ratio_change_pp"],
        "consecutive_increase": row["consecutive_increase"],
        "consecutive_decrease": row["consecutive_decrease"],
        "market_rank": row["market_rank"],
        "industry_rank": row["industry_rank"],
        "tags": _status_tags(row),
    }


def latest_data_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(data_date) FROM chip_weekly_metrics").fetchone()
    return str(row[0]) if row and row[0] else None


def latest_complete_market_date(
    conn: sqlite3.Connection,
    minimum_market_stocks: int = 500,
) -> str | None:
    row = conn.execute(
        """SELECT data_date
             FROM chip_tdcc_raw
            WHERE source_code=?
            GROUP BY data_date
           HAVING COUNT(DISTINCT code) >= ?
            ORDER BY data_date DESC
            LIMIT 1""",
        (TDCC_SOURCE_CODE, minimum_market_stocks),
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def dashboard_snapshot_ready(
    conn: sqlite3.Connection,
    minimum_market_stocks: int = 500,
    minimum_tpex_stocks: int = 300,
) -> bool:
    master_count = conn.execute(
        "SELECT COUNT(*) FROM chip_stocks WHERE active=1 AND product_type='stock'"
    ).fetchone()[0]
    if master_count < minimum_market_stocks:
        return False
    tpex_count = conn.execute(
        """SELECT COUNT(*) FROM chip_stocks
           WHERE active=1 AND product_type='stock' AND market='TPEX'"""
    ).fetchone()[0]
    if tpex_count < minimum_tpex_stocks:
        return False
    market_dates = conn.execute(
        """SELECT data_date
             FROM chip_tdcc_raw
            WHERE source_code=?
            GROUP BY data_date
           HAVING COUNT(DISTINCT code) >= ?
            ORDER BY data_date DESC
            LIMIT 2""",
        (TDCC_SOURCE_CODE, minimum_market_stocks),
    ).fetchall()
    return len(market_dates) >= 2


def rankings_payload(
    db_path: Path,
    *,
    market: str = "all",
    industry: str = "",
    limit: int = 30,
    forced_groups_path: Path | None = None,
) -> dict[str, Any]:
    groups_path = forced_groups_path or db_path.parent / "FORCED_SECTOR_GROUPS.md"
    _, forced_group_by_code = load_forced_sector_groups(groups_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        data_date = latest_data_date(conn)
        if not data_date:
            return {
                **_meta(None),
                "grouping_source": groups_path.name,
                "is_latest": False,
                "comparison_stock_count": 0,
                "increase": [],
                "decrease": [],
                "message": "尚未匯入集保資料。",
            }
        full_market_dates = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT data_date
                FROM chip_tdcc_raw
                WHERE source_code=?
                GROUP BY data_date
                HAVING COUNT(DISTINCT code) >= 500
                ORDER BY data_date
                """,
                (TDCC_SOURCE_CODE,),
            ).fetchall()
        ]
        if len(full_market_dates) < 2:
            return {
                **_meta(data_date),
                "grouping_source": groups_path.name,
                "comparison_stock_count": 0,
                "increase": [],
                "decrease": [],
                "message": "目前只有一週全市場集保快照；累積下一週後即可產生全市場增減排行。",
            }
        data_date = full_market_dates[-1]
        clauses = ["m.data_date=?", "m.change_rate IS NOT NULL", "s.active=1", "s.product_type='stock'"]
        params: list[Any] = [data_date]
        if market in {"TWSE", "TPEX"}:
            clauses.append("s.market=?")
            params.append(market)
        if industry:
            clauses.append("s.industry_name=?")
            params.append(industry)
        base = f"""
            SELECT m.*, s.name, s.market, s.industry_name
            FROM chip_weekly_metrics m
            JOIN chip_stocks s ON s.code=m.code
            WHERE {' AND '.join(clauses)}
        """
        comparison_stock_count = int(
            conn.execute(f"SELECT COUNT(*) FROM ({base})", params).fetchone()[0]
        )
        increase = conn.execute(base + " AND m.change_rate > 0 ORDER BY m.change_rate DESC, m.code LIMIT ?", (*params, limit)).fetchall()
        decrease = conn.execute(base + " AND m.change_rate < 0 ORDER BY m.change_rate ASC, m.code LIMIT ?", (*params, limit)).fetchall()
        message = "" if increase or decrease else "目前只有一週集保快照；累積下一週後即可產生全市場增減排行。"
        return {
            **_meta(data_date),
            "grouping_source": groups_path.name,
            "comparison_stock_count": comparison_stock_count,
            "increase": [
                _serialize_metric(row, forced_group_by_code=forced_group_by_code)
                for row in increase
            ],
            "decrease": [
                _serialize_metric(row, forced_group_by_code=forced_group_by_code)
                for row in decrease
            ],
            "message": message,
        }


def search_stocks(db_path: Path, query: str, limit: int = 10) -> dict[str, Any]:
    text = str(query or "").strip()
    if len(text) < 2:
        return {"ok": True, "items": []}
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        rows = conn.execute(
            """
            SELECT code, name, market, industry_name
            FROM chip_stocks
            WHERE active=1 AND product_type='stock' AND (code LIKE ? OR name LIKE ?)
            ORDER BY CASE WHEN code=? OR name=? THEN 0 WHEN code LIKE ? THEN 1 ELSE 2 END, code
            LIMIT ?
            """,
            (f"{text}%", f"%{text}%", text, text, f"{text}%", limit),
        ).fetchall()
    return {
        "ok": True,
        "items": [
            {
                "code": row["code"],
                "name": row["name"],
                "market": row["market"],
                "industry": row["industry_name"] or "未分類",
            }
            for row in rows
        ],
    }


def stock_payload(db_path: Path, code: str) -> dict[str, Any]:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        stock = conn.execute("SELECT * FROM chip_stocks WHERE code=? AND active=1", (code,)).fetchone()
        if stock is None:
            raise LookupError("找不到支援範圍內的股票。")
        history = conn.execute(
            """
            SELECT m.*, s.name, s.market, s.industry_name
            FROM chip_weekly_metrics m JOIN chip_stocks s ON s.code=m.code
            WHERE m.code=? ORDER BY m.data_date DESC LIMIT 9
            """,
            (code,),
        ).fetchall()
        data_date = str(history[0]["data_date"]) if history else None
        current = _serialize_metric(history[0]) if history else None
        industry_rows: list[sqlite3.Row] = []
        if data_date:
            industry_rows = conn.execute(
                """
                SELECT m.*, s.name, s.market, s.industry_name
                FROM chip_weekly_metrics m JOIN chip_stocks s ON s.code=m.code
                WHERE m.data_date=? AND s.industry_name=? AND m.change_rate IS NOT NULL
                ORDER BY m.change_rate DESC, m.code LIMIT 20
                """,
                (data_date, stock["industry_name"]),
            ).fetchall()
        institutional = conn.execute(
            "SELECT * FROM chip_institutional_daily WHERE code=? ORDER BY trade_date DESC LIMIT 10",
            (code,),
        ).fetchall()
    return {
        **_meta(data_date),
        "stock": {
            "code": stock["code"],
            "name": stock["name"],
            "market": stock["market"],
            "industry": stock["industry_name"] or "未分類",
        },
        "summary": current,
        "history": [_serialize_metric(row) for row in reversed(history)],
        "institutional": [dict(row) for row in reversed(institutional)],
        "industry_comparison": [_serialize_metric(row) for row in industry_rows],
        "history_complete": len(history) >= 9,
    }


def industries_payload(
    db_path: Path,
    limit: int = 20,
    *,
    forced_groups_path: Path | None = None,
) -> dict[str, Any]:
    groups_path = forced_groups_path or db_path.parent / "FORCED_SECTOR_GROUPS.md"
    _, code_to_group = load_forced_sector_groups(groups_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        data_date = latest_complete_market_date(conn)
        if not data_date:
            return {**_meta(None), "grouping_source": groups_path.name, "items": []}
        rows = conn.execute(
            """
            SELECT m.change_rate, m.consecutive_increase, m.code, s.name
            FROM chip_weekly_metrics m JOIN chip_stocks s ON s.code=m.code
            WHERE m.data_date=? AND m.change_rate IS NOT NULL AND s.active=1
            """,
            (data_date,),
        ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        group_name = code_to_group.get(str(row["code"]))
        if group_name:
            groups[group_name].append(row)
    raw: dict[str, dict[str, Any]] = {}
    for industry, members in groups.items():
        if len(members) < 2:
            continue
        rates = [float(row["change_rate"]) for row in members]
        raw[industry] = {
            "valid_count": len(members),
            "median_change_rate": statistics.median(rates),
            "increase_ratio": sum(rate > 0 for rate in rates) / len(rates) * 100.0,
            "continuous_increase_ratio": sum(int(row["consecutive_increase"] or 0) >= 2 for row in members) / len(members) * 100.0,
            "leader": max(members, key=lambda row: float(row["change_rate"])),
        }
    median_pct = percentile_ranks({key: value["median_change_rate"] for key, value in raw.items()})
    increase_pct = percentile_ranks({key: value["increase_ratio"] for key, value in raw.items()})
    continuous_pct = percentile_ranks({key: value["continuous_increase_ratio"] for key, value in raw.items()})
    items = []
    for industry, metric in raw.items():
        score = median_pct[industry] * 0.5 + increase_pct[industry] * 0.3 + continuous_pct[industry] * 0.2
        items.append(
            {
                "industry": industry,
                "score": round(score, 2),
                "valid_count": metric["valid_count"],
                "median_change_rate": round(metric["median_change_rate"], 4),
                "increase_ratio": round(metric["increase_ratio"], 2),
                "continuous_increase_ratio": round(metric["continuous_increase_ratio"], 2),
                "leader": {"code": metric["leader"]["code"], "name": metric["leader"]["name"]},
            }
        )
    items.sort(key=lambda item: (-item["score"], item["industry"]))
    for index, item in enumerate(items, 1):
        item["rank"] = index
    return {
        **_meta(data_date),
        "grouping_source": groups_path.name,
        "items": items[:limit],
    }


def featured_payload(
    db_path: Path,
    limit: int = 12,
    *,
    forced_groups_path: Path | None = None,
) -> dict[str, Any]:
    groups_path = forced_groups_path or db_path.parent / "FORCED_SECTOR_GROUPS.md"
    _, code_to_group = load_forced_sector_groups(groups_path)
    rankings = rankings_payload(db_path, limit=30)
    industries = industries_payload(db_path, limit=5, forced_groups_path=groups_path)
    forced_increase = [
        {**row, "industry": code_to_group[row["code"]]}
        for row in rankings.get("increase", [])
        if row.get("code") in code_to_group
    ]
    candidates: list[dict[str, Any]] = list(forced_increase[:10])
    leader_codes = {item["leader"]["code"] for item in industries.get("items", []) if item.get("leader")}
    candidates.extend(row for row in forced_increase if row["code"] in leader_codes)
    candidates.extend(row for row in forced_increase if row.get("consecutive_increase", 0) >= 2)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        if item["code"] in seen:
            continue
        seen.add(item["code"])
        unique.append(item)
        if len(unique) >= limit:
            break
    return {
        **_meta(rankings.get("data_date")),
        "grouping_source": groups_path.name,
        "items": unique,
    }
