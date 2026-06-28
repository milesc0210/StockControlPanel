#!/bin/bash
# 14:00 盤後抓取：上市(TWSE) + 上櫃(TPEX) 當日全市場行情
# 僅平日（Mon-Fri）執行，放假日自動跳過

set -e

BASE_DIR="/Users/zhengyulun/0_miles/G/Miles agent"
TPEX_DIR="$BASE_DIR/data/tpex/2026"
TWSE_DIR="$BASE_DIR/data/twse/2026"

TODAY=$(date +%Y%m%d)
TODAY_ROC=$(date +%Y/%m/%d | awk -F'/' '{print $1-1911"/"$2"/"$3}')

echo "[14:00 盤後行情抓取] $TODAY"

# ── TPEX（上櫃）────────────────────────────────────────
TPEX_OUT="$TPEX_DIR/$TODAY.json"
if [ -f "$TPEX_OUT" ]; then
    echo "  [TPEX] $TODAY 已存在，跳過"
else
    echo "  [TPEX] 抓取中..."
    python3 - "$TODAY" <<'PYEOF'
import urllib.request, json, time, urllib.parse, ssl, sys

date_str = sys.argv[1]
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://www.tpex.org.tw/",
    "Accept": "application/json"
}

# 西元年→民國年（date_str = YYYYMMDD）
year = date_str[0:4]
month = date_str[4:6]
day = date_str[6:8]
roc = f"{int(year) - 1911}/{month}/{day}"
url = f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&d={urllib.parse.quote(roc)}&se=EW&_={int(time.time()*1000)}"

req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
    data = json.loads(resp.read().decode("utf-8"))

out_path = f"/Users/zhengyulun/0_miles/G/Miles agent/data/tpex/2026/{date_str}.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"  [TPEX] ✅ {date_str} → {len(data.get('tables',[[]])[0].get('data',[]))} 檔")
PYEOF
fi

# ── TWSE（上市）────────────────────────────────────────
TWSE_OUT="$TWSE_DIR/$TODAY.json"
if [ -f "$TWSE_OUT" ]; then
    echo "  [TWSE] $TODAY 已存在，跳過"
else
    echo "  [TWSE] 抓取中..."
    python3 - "$TODAY" <<'PYEOF'
import urllib.request, json, time, ssl, sys

date_str = sys.argv[1]
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://www.twse.com.tw/",
    "Accept": "application/json"
}

url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
    data = json.loads(resp.read().decode("utf-8"))

# 從 tables 找每日收盤行情
tables = data.get("tables", [])
target = None
for t in tables:
    if "每日收盤行情" in t.get("title", ""):
        target = t
        break

if target:
    result = {
        "date": date_str,
        "source": "TWSE MI_INDEX",
        "count": len(target.get("data", [])),
        "fields": target.get("fields", []),
        "data": target.get("data", [])
    }
else:
    result = {"date": date_str, "source": "TWSE MI_INDEX", "error": "無每日收盤行情", "stat": data.get("stat","")}

out_path = f"/Users/zhengyulun/0_miles/G/Miles agent/data/twse/2026/{date_str}.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

count = result.get("count", 0)
print(f"  [TWSE] ✅ {date_str} → {count} 檔")
PYEOF
fi

echo "[完成] $TODAY 盤後行情已存入 data/ 目錄"