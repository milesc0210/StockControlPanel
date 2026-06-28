#!/Users/zhengyulun/miniforge3/bin/python3
"""批次產生12檔K線PNG"""
import json, os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Rectangle
from PIL import Image

DATA_DIR = "/Users/zhengyulun/0_miles/G/Miles agent/data"
OUTPUT_DIR = "/Users/zhengyulun/0_miles/G/Miles agent/data/kline_png"
os.makedirs(OUTPUT_DIR, exist_ok=True)

stocks = {
    '5347': {'name': '世界', 'market': 'tpex'},
    '2338': {'name': '光罩', 'market': 'twse'},
    '8105': {'name': '凌巨', 'market': 'twse'},
    '2345': {'name': '智邦', 'market': 'twse'},
    '6716': {'name': '應廣', 'market': 'tpex'},
    '6190': {'name': '萬泰科', 'market': 'tpex'},
    '3217': {'name': '優群', 'market': 'tpex'},
    '2032': {'name': '新鋼', 'market': 'twse'},
    '6113': {'name': '亞矽', 'market': 'tpex'},
    '2030': {'name': '彰源', 'market': 'twse'},
    '2637': {'name': '慧洋-KY', 'market': 'twse'},
    '3576': {'name': '聯合再生', 'market': 'twse'},
}

# 收集所有每日JSON（最後40個）
all_daily_files = []
for m in ['twse', 'tpex']:
    d = f"{DATA_DIR}/{m}/2026"
    if os.path.exists(d):
        for f in os.listdir(d):
            if f.endswith('.json') and f[:4].isdigit():
                all_daily_files.append((m, f))
all_daily_files.sort(key=lambda x: x[1])
all_daily_files = all_daily_files[-40:]

def parse_num(val):
    if val is None or val == '':
        return 0.0
    s = str(val).replace(',', '').strip()
    return float(s) if s else 0.0

# 收集K線
kline_data = {sid: [] for sid in stocks}
for market, fname in all_daily_files:
    fpath = f"{DATA_DIR}/{market}/2026/{fname}"
    date_str = fname.replace('.json', '')
    mmdd = date_str[4:6]+'/'+date_str[6:8]
    try:
        with open(fpath, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        if market == 'twse':
            for row in data['data']:
                sid = str(row[0]).strip()
                if sid in stocks:
                    # 動態 index：16欄收盤r[8]，10欄收盤r[7]
                    n = len(row)
                    close_idx = 8 if n == 16 else (7 if n == 10 else 2)
                    close = parse_num(row[close_idx]); open_ = parse_num(row[5])
                    high = parse_num(row[6]); low = parse_num(row[7])
                    vol = int(parse_num(row[2])) // 1000
                    if close > 0:
                        kline_data[sid].append({'date': mmdd, 'open': open_, 'high': high, 'low': low, 'close': close, 'volume': vol})
        else:
            for row in data['tables'][0]['data']:
                sid = str(row[0]).strip()
                if sid in stocks:
                    close = parse_num(row[2]); open_ = parse_num(row[4])
                    high = parse_num(row[5]); low = parse_num(row[6])
                    vol = int(parse_num(row[7])) // 1000 if len(row) > 7 else 0
                    if close > 0:
                        kline_data[sid].append({'date': mmdd, 'open': open_, 'high': high, 'low': low, 'close': close, 'volume': vol})
    except Exception as e:
        pass

# 字體
avail = [f.name for f in fm.fontManager.ttflist]
font_ok = None
for c in ['Arial Unicode MS','Heiti TC','PingFang SC','Noto Sans CJK TC','WenQuanYi Zen Hei']:
    if c in avail:
        plt.rcParams['font.family'] = c
        font_ok = c
        break
if not font_ok:
    plt.rcParams['font.family'] = 'DejaVu Sans'
print(f"字體: {plt.rcParams['font.family']}")

def plot_kline(sid, name, data, output_path):
    if not data:
        return False
    n = len(data)
    opens = [d['open'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    closes = [d['close'] for d in data]
    volumes = [d['volume'] for d in data]
    dates = [d['date'] for d in data]

    fig, (ax_k, ax_v) = plt.subplots(2, 1, figsize=(17, 10), gridspec_kw={'height_ratios': [4, 1]})
    fig.patch.set_facecolor('white')

    for i in range(n):
        c = closes[i]; o = opens[i]
        color = '#d62728' if c >= o else '#2ca02c'
        body_bottom = min(o, c)
        body_height = abs(c - o)
        if body_height < 0.001:
            body_height = closes[i] * 0.001
        ax_k.plot([i, i], [lows[i], highs[i]], color=color, linewidth=1.2)
        rect = Rectangle((i-0.35, body_bottom), 0.7, body_height, facecolor=color, edgecolor=color)
        ax_k.add_patch(rect)

    # 均線
    if n >= 5:
        ma5 = [sum(closes[max(0,i-4):i+1])/min(5,i+1) for i in range(n)]
        ax_k.plot(range(n), ma5, '#1f77b4', linewidth=1.5, label='MA5')
    if n >= 10:
        ma10 = [sum(closes[max(0,i-9):i+1])/min(10,i+1) for i in range(n)]
        ax_k.plot(range(n), ma10, '#2ca02c', linewidth=1.5, label='MA10')
    if n >= 20:
        ma20 = [sum(closes[max(0,i-19):i+1])/min(20,i+1) for i in range(n)]
        ax_k.plot(range(n), ma20, '#ff7f0e', linewidth=1.5, label='MA20')

    ax_k.set_xlim(-0.5, n-0.5)
    ax_k.set_xticks(range(n))
    ax_k.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
    ax_k.set_ylabel('價格')
    ax_k.grid(True, alpha=0.3)
    ax_k.legend(loc='upper left', fontsize=9)

    for i in range(n):
        color = '#d62728' if closes[i] >= opens[i] else '#2ca02c'
        ax_v.bar(i, volumes[i], color=color, width=0.7)
    ax_v.set_xlim(-0.5, n-0.5)
    ax_v.set_xticks(range(n))
    ax_v.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
    ax_v.set_ylabel('成交量(張)')
    ax_v.grid(True, alpha=0.3)

    last_close = closes[-1]
    ax_k.set_title(f"{sid} {name} {last_close}", fontsize=14, fontweight='bold')
    plt.tight_layout()
    fig.savefig(output_path, dpi=80, bbox_inches='tight')
    plt.close()

    # 縮圖檢查
    img = Image.open(output_path)
    w, h = img.size
    if w > 1280:
        ratio = 1280 / w
        img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
        img.save(output_path, quality=85)
        w2, h2 = img.size
    else:
        w2, h2 = w, h

    size = os.path.getsize(output_path) / 1024
    print(f"  [{sid}] {name}: {n}筆, {w2}x{h2}, {size:.0f}KB")
    return True

for sid, info in stocks.items():
    d = kline_data[sid]
    out = f"{OUTPUT_DIR}/kline_{sid}.png"
    if d:
        plot_kline(sid, info['name'], d, out)
    else:
        print(f"  [{sid}] {info['name']}: 無K線資料")

print("完成")