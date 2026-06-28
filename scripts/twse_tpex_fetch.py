#!/usr/bin/env python3
"""
twse_tpex_fetch.py — 盤後行情抓取（TWSE + TPEX）
抓取指定日期收盤行情，驗證資料完整性，寫入目前可攜版資料夾下的 data/twse/2026 與 data/tpex/2026。

用法：
  python3 twse_tpex_fetch.py              # 自動抓今天
  python3 twse_tpex_fetch.py 20260608     # 指定日期
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

from portable_runtime import DATA_DIR, load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────
TWSE_DIR = os.path.join(str(DATA_DIR), "twse", "2026")
TPEX_DIR = os.path.join(str(DATA_DIR), "tpex", "2026")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.twse.com.tw/",
    "Accept": "application/json",
}


def fetch_twse(date_str: str) -> dict:
    """Fetch TWSE daily trading data via MI_INDEX API (ALLBUT0999).
    Returns dict with keys: date, source, count, fields, data.
    """
    url = (
        f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
        f"?response=json&date={date_str}&type=ALLBUT0999"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    # Find the table with 16 fields and >1000 rows
    for t in raw.get("tables", []):
        fields = t.get("fields", [])
        data = t.get("data", [])
        if len(fields) == 16 and len(data) > 1000:
            return {
                "date": date_str,
                "source": "TWSE MI_INDEX",
                "count": len(data),
                "fields": fields,
                "data": data,
            }

    raise RuntimeError(f"TWSE:找不到 16 欄的股票資料表 (date={date_str})")


def fetch_tpex(date_str: str) -> dict:
    """Fetch TPEX (OTC) daily trading data.
    Returns dict with keys: tables, date, flagField, stat.
    """
    # Convert to ROC date: 20260608 → 115/06/08
    year = int(date_str[:4]) - 1911
    month = date_str[4:6]
    day = date_str[6:8]
    roc_date = f"{year}/{month}/{day}"

    url = (
        "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/"
        "stk_wn1430_result.php?l=zh-tw"
        f"&d={urllib.parse.quote(roc_date)}"
        f"&se=EW&_={int(time.time() * 1000)}"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    # Validate
    tables = data.get("tables", [])
    total = sum(t.get("totalCount", 0) for t in tables)
    if total == 0:
        raise RuntimeError(f"TPEX:資料為空 (date={date_str}, roc={roc_date})")

    return data


def verify_TWSE(result: dict) -> tuple[bool, str]:
    count = result.get("count", 0)
    if count >= 1000:
        return True, f"✅ TWSE：{count} 檔"
    return False, f"❌ TWSE：{count} 檔（門檻 ≥1000）"


def verify_TPEX(result: dict) -> tuple[bool, str]:
    tables = result.get("tables", [])
    total = sum(t.get("totalCount", 0) for t in tables)
    data_len = sum(len(t.get("data", [])) for t in tables)
    if total >= 500:
        return True, f"✅ TPEX：{total} 檔"
    return False, f"❌ TPEX：{total} 檔（門檻 ≥500）"


def main():
    # Determine date
    if len(sys.argv) > 1:
        date_str = sys.argv[1].replace("-", "")
    else:
        date_str = datetime.now().strftime("%Y%m%d")

    os.makedirs(TWSE_DIR, exist_ok=True)
    os.makedirs(TPEX_DIR, exist_ok=True)

    results = []
    all_ok = True

    # ── TWSE ──
    try:
        twse = fetch_twse(date_str)
        ok, msg = verify_TWSE(twse)
        outpath = os.path.join(TWSE_DIR, f"{date_str}.json")
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(twse, f, ensure_ascii=False)
        results.append(msg)
        if not ok:
            all_ok = False
    except Exception as e:
        results.append(f"❌ TWSE 失敗：{e}")
        all_ok = False

    # ── TPEX ──
    try:
        tpex = fetch_tpex(date_str)
        ok, msg = verify_TPEX(tpex)
        outpath = os.path.join(TPEX_DIR, f"{date_str}.json")
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(tpex, f, ensure_ascii=False)
        results.append(msg)
        if not ok:
            all_ok = False
    except Exception as e:
        results.append(f"❌ TPEX 失敗：{e}")
        all_ok = False

    # ── Output ──
    now = datetime.now().strftime("%H:%M")
    status = "✅" if all_ok else "❌"
    report = f"{status} {' / '.join(results)} | 時間：{now}"
    print(report)

    # Exit code: 0 = all ok, 1 = any failed
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
