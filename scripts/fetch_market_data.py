#!/usr/bin/env python3
"""Fetch TWSE + TPEX daily closing market data into the portable StockControlPanel/data folder."""

from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from portable_runtime import DATA_DIR, load_dotenv

load_dotenv()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept": "application/json",
}

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def target_paths(date_str: str) -> tuple[Path, Path]:
    year = date_str[:4]
    twse_out = DATA_DIR / "twse" / year / f"{date_str}.json"
    tpex_out = DATA_DIR / "tpex" / year / f"{date_str}.json"
    twse_out.parent.mkdir(parents=True, exist_ok=True)
    tpex_out.parent.mkdir(parents=True, exist_ok=True)
    return twse_out, tpex_out


def main() -> int:
    date_str = (sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")).replace("-", "")
    twse_out, tpex_out = target_paths(date_str)

    results: dict[str, dict] = {}

    print("[TPEX] 抓取中...")
    year = date_str[0:4]
    month = date_str[4:6]
    day = date_str[6:8]
    roc = f"{int(year) - 1911}/{month}/{day}"
    tpex_url = (
        "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/"
        f"stk_wn1430_result.php?l=zh-tw&d={urllib.parse.quote(roc)}&se=EW&_={int(time.time() * 1000)}"
    )

    tpex_headers = dict(HEADERS)
    tpex_headers["Referer"] = "https://www.tpex.org.tw/"

    try:
        req = urllib.request.Request(tpex_url, headers=tpex_headers)
        with urllib.request.urlopen(req, timeout=15, context=CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tpex_count = len(data.get("tables", [[]])[0].get("data", []))
        results["tpex"] = {"count": tpex_count, "file": str(tpex_out), "status": "ok"}
        tpex_out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [TPEX] ✅ {date_str} → {tpex_count} 檔")
    except Exception as exc:
        results["tpex"] = {"count": 0, "file": str(tpex_out), "status": "error", "error": str(exc)}
        print(f"  [TPEX] ❌ {exc}")

    print("[TWSE] 抓取中...")
    twse_url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    twse_headers = dict(HEADERS)
    twse_headers["Referer"] = "https://www.twse.com.tw/"

    try:
        req = urllib.request.Request(twse_url, headers=twse_headers)
        with urllib.request.urlopen(req, timeout=20, context=CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tables = data.get("tables", [])
        target = None
        for table in tables:
            if "每日收盤行情" in table.get("title", ""):
                target = table
                break

        if target:
            result = {
                "date": date_str,
                "source": "TWSE MI_INDEX",
                "count": len(target.get("data", [])),
                "fields": target.get("fields", []),
                "data": target.get("data", []),
            }
            twse_count = result["count"]
        else:
            result = {"date": date_str, "source": "TWSE MI_INDEX", "error": "無每日收盤行情", "stat": data.get("stat", "")}
            twse_count = 0

        results["twse"] = {"count": twse_count, "file": str(twse_out), "status": "ok"}
        twse_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [TWSE] ✅ {date_str} → {twse_count} 檔")
    except Exception as exc:
        results["twse"] = {"count": 0, "file": str(twse_out), "status": "error", "error": str(exc)}
        print(f"  [TWSE] ❌ {exc}")

    print(f"\n{'=' * 40}")
    print("結果摘要:")
    print(f"  TWSE: {results['twse']['count']} 檔 | {'✅' if results['twse']['status'] == 'ok' else '❌'}")
    print(f"  TPEX: {results['tpex']['count']} 檔 | {'✅' if results['tpex']['status'] == 'ok' else '❌'}")
    print(f"{'=' * 40}")

    summary = {
        "date": date_str,
        "twse": results["twse"],
        "tpex": results["tpex"],
        "success": results["twse"]["count"] >= 1000 and results["tpex"]["count"] >= 500,
    }
    print(f"\nSUMMARY_JSON:{json.dumps(summary, ensure_ascii=False)}")
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
