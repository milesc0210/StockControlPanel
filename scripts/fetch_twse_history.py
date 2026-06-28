#!/usr/bin/env python3
"""
TWSE MI_INDEX Historical Fetcher
抓取 2026/02/02 ~ 2026/05/24 每日收盤行情（上市全市場）
一天一個 request，一次拿 ~1360 檔
"""

import ssl, urllib.request, json, time, random, datetime, os

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "twse", "2026")
os.makedirs(OUT_DIR, exist_ok=True)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://www.twse.com.tw/",
    "Accept": "application/json"
}

def fetch_twse(date_str):
    """抓取單日 TWSE 全市場資料"""
    url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))

def is_weekend(date_obj):
    return date_obj.weekday() >= 5

def get_trading_days(start_date, end_date):
    days = []
    d = start_date
    while d <= end_date:
        if not is_weekend(d):
            days.append(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
    return days

def save_day(date_str, data):
    out_path = f"{OUT_DIR}/{date_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def run(start_date=None, end_date=None):
    if start_date is None:
        start_date = datetime.date(2026, 2, 2)
    if end_date is None:
        end_date = datetime.date(2026, 5, 24)
    
    trading_days = get_trading_days(start_date, end_date)
    print(f"共 {len(trading_days)} 個交易日，開始抓取...")
    success = 0
    fail = 0

    for i, day in enumerate(trading_days):
        out_path = f"{OUT_DIR}/{day}.json"
        if os.path.exists(out_path):
            print(f"[{i+1}/{len(trading_days)}] {day} 已存在，跳過")
            continue

        try:
            data = fetch_twse(day)
            stat = data.get("stat", "")

            target_table = None
            for t in data.get("tables", []):
                if "每日收盤行情" in t.get("title", ""):
                    target_table = t
                    break

            if target_table is None:
                print(f"[{i+1}/{len(trading_days)}] {day} 無每日收盤行情 table，stat={stat}")
                fail += 1
                continue

            rows = target_table.get("data", [])
            fields = target_table.get("fields", [])
            result = {
                "date": day,
                "source": "TWSE MI_INDEX",
                "count": len(rows),
                "fields": fields,
                "data": rows
            }
            save_day(day, result)
            success += 1
            print(f"[{i+1}/{len(trading_days)}] ✅ {day} → {len(rows)} 檔 → {out_path}")

        except Exception as e:
            print(f"[{i+1}/{len(trading_days)}] ❌ {day}: {e}")
            fail += 1

        time.sleep(random.uniform(3.0, 6.0))

    print(f"\n完成：✅ {success} 天，❌ {fail} 天")
    return success, fail

if __name__ == "__main__":
    run()