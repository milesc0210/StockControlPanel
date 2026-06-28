#!/usr/bin/env python3
"""批次產生K線PNG圖（多檔股票）
用法：python3 batch_kline_png.py

從 data/twse|tpex/2026/Kline/kline_{code}.json 讀取資料，
產出對應的 kline_{code}.png。

注意：volume 單位已是「張」，不可再 ÷1000。"""
import json, os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Rectangle
from PIL import Image

def detect_font():
    avail = [f.name for f in fm.fontManager.ttflist]
    for c in ['Arial Unicode MS','Heiti TC','PingFang SC','Noto Sans CJK TC']:
        if c in avail: return c
    return 'DejaVu Sans'

plt.rcParams['font.family'] = detect_font()
plt.rcParams['axes.unicode_minus'] = False

def plot_kline(code, name, rows, out_path):
    n = len(rows)
    if n < 10: return False
    dates = [r['date'][5:] for r in rows]
    opens = [r['open'] for r in rows]
    highs = [r['high'] for r in rows]
    lows = [r['low'] for r in rows]
    closes = [r['close'] for r in rows]
    volumes = [r['volume'] for r in rows]  # 單位已是張
    ma5 = [sum(closes[max(0,i-4):i+1])/min(5,i+1) for i in range(n)]
    ma10 = [sum(closes[max(0,i-9):i+1])/min(10,i+1) for i in range(n)]
    ma20 = [sum(closes[max(0,i-19):i+1])/min(20,i+1) for i in range(n)]
    fig, (ax_k, ax_v) = plt.subplots(2, 1, figsize=(14, 7),
        gridspec_kw={'height_ratios': [4, 1]}, sharex=True)
    fig.patch.set_facecolor('white')
    for i in range(n):
        color = '#d62728' if closes[i] >= opens[i] else '#2ca02c'
        ax_k.plot([i, i], [lows[i], highs[i]], color=color, linewidth=1)
        rect = Rectangle((i-0.3, min(opens[i], closes[i])), 0.6,
                        abs(closes[i]-opens[i]) or 0.1,
                        facecolor=color, edgecolor=color)
        ax_k.add_patch(rect)
    ax_k.plot(range(n), ma5, color='#1f77b4', linewidth=1.2, label='MA5')
    ax_k.plot(range(n), ma10, color='#2ca02c', linewidth=1.2, label='MA10')
    ax_k.plot(range(n), ma20, color='#ff7f0e', linewidth=1.2, label='MA20')
    ax_k.legend(loc='upper left', fontsize=9)
    ax_k.set_ylabel('Price', fontsize=10)
    ax_k.grid(True, alpha=0.3)
    vol_colors = ['#d62728' if closes[i] >= opens[i] else '#2ca02c' for i in range(n)]
    ax_v.bar(range(n), volumes, color=vol_colors, width=0.6)
    ax_v.set_ylabel('成交量(張)', fontsize=10)
    step = max(1, n // 10)
    ax_v.set_xticks(range(0, n, step))
    ax_v.set_xticklabels([dates[i] for i in range(0, n, step)], rotation=45, fontsize=8)
    ax_k.set_title(f'{code} {name} {rows[-1]["close"]}', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(out_path, dpi=100, bbox_inches='tight')
    plt.close()
    img = Image.open(out_path)
    w, h = img.size
    if max(w, h) > 1280:
        ratio = 1280 / max(w, h)
        img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
        img.save(out_path, quality=85)
    return True

if __name__ == '__main__':
    codes = sys.argv[1:] if len(sys.argv) > 1 else []
    if not codes:
        print('用法: batch_kline_png.py [code1 code2 ...]')
        print('若不指定代碼，掃描 data/*/2026/Kline/kline_*.json')
        sys.exit(1)
    for code in codes:
        for sub in ['twse','tpex']:
            _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            p = os.path.join(_base, 'data', sub, '2026', 'Kline', f'kline_{code}.json')
            if os.path.exists(p):
                with open(p) as f:
                    data = json.load(f)
                meta = data['meta']
                out = p.replace('.json', '.png')
                if plot_kline(code, meta.get('name',''), data['data'], out):
                    print(f'  ✅ {code} {meta.get("name","")} → {out}')
                break
