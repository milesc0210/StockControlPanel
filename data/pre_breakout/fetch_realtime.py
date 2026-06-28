#!/usr/bin/env python3
"""
抓取 pre_breakout 候選股的 Google Finance 即時報價, 存成 JSON。

用法: python3 fetch_realtime.py [output_path]
若不指定 output_path, 自動存到 data/pre_breakout/realtime_quotes_YYYYMMDD_HHMMSS.json

資料源: Google Finance Beta (https://www.google.com/finance/quote/{code}:TPE)
無需 API key, 純 HTML 解析。

【重要】報價是 Google Finance 提供的盤中即時資料, 但仍可能有 5~15 分鐘延遲;
重大決策請以券商看盤軟體為準。
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

CANDIDATES_PATH = Path("/Users/zhengyulun/0_miles/G/Miles agent/data/pre_breakout/pre_breakout_log.json")
DEFAULT_OUT_DIR = Path("/Users/zhengyulun/0_miles/G/Miles agent/data/pre_breakout/realtime_quotes")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def fetch_one(stock_id: str, market: str = "TPE") -> dict:
    """抓單一個股報價。失敗回傳 error dict。"""
    url = f"https://www.google.com/finance/quote/{stock_id}:{market}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8")
    except Exception as e:
        return {"code": stock_id, "error": f"fetch failed: {e}"}

    # 個股標題區的特徵: NT$X.XX 後 800 字元內同時有 vY9t3b (漲跌幅) 和 xnruHf (漲跌點數)
    # 清單/相關股票/熱門榜 不會同時有這兩個
    matches = list(re.finditer(r"NT\$([0-9]+\.[0-9]+)", html))
    for m in matches:
        end = m.end()
        window = html[end:end + 800]
        if "vY9t3b" in window and "xnruHf" in window:
            price = float(m.group(1))
            mp = re.search(r"vY9t3b[^>]*>.*?>([+\-]?[0-9.]+)%<", window, re.DOTALL)
            change_pct = float(mp.group(1)) if mp else None
            mn = re.search(r"xnruHf[^>]*>.*?>([+\-]?[0-9.]+)<", window, re.DOTALL)
            change = float(mn.group(1)) if mn else None
            ohl = re.findall(r"NT\$([0-9.]+)", window)
            ohl_clean = [p for p in ohl if float(p) != price][:3]
            return {
                "code": stock_id,
                "market": market,
                "price": price,
                "change": change,
                "change_pct": change_pct,
                "open_high_low": ohl_clean,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
    return {"code": stock_id, "error": "no stock header in HTML"}


def main():
    if not CANDIDATES_PATH.exists():
        print(json.dumps({"error": f"candidates not found: {CANDIDATES_PATH}"}))
        sys.exit(1)

    cands = json.loads(CANDIDATES_PATH.read_text())["candidates"]

    results = []
    for c in cands:
        code = c["code"]
        r = fetch_one(code, "TPE")
        r["name"] = c.get("name")
        r["ma5"] = c.get("ma5")
        r["ma10"] = c.get("ma10")
        results.append(r)
        time.sleep(0.3)  # 避免被 rate limit

    if len(sys.argv) > 1:
        out_path = Path(sys.argv[1])
    else:
        out_path = DEFAULT_OUT_DIR / f"quotes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(results),
        "quotes": results,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"OK saved {len(results)} quotes to {out_path}")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
