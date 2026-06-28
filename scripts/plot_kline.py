#!/usr/bin/env python3
"""
通用 K 線圖產生器
根據 K 線 JSON 自動繪製 K 線 + 成交量 + MA5/MA10/MA20 均線圖

用法：
  python3 plot_kline.py [json_path] [output_png_path]
預設：
  json_path  = data/tpex/kline_2070_2m.json（相對於 daily_trade_plan 根目錄）
  output_png = 同目錄/kline_{stock_id}_{period}.png
"""

import sys
import os
import json
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Patch
from PIL import Image

# ── 中文字體偵測 ───────────────────────────────────────────────
def detect_chinese_font():
    available = [f.name for f in fm.fontManager.ttflist]
    candidates = ['Arial Unicode MS', 'Heiti TC', 'PingFang SC',
                  'Noto Sans CJK TC', 'WenQuanYi Zen Hei']
    for c in candidates:
        if c in available:
            return c
    cjk = [f for f in available if any(k in f.lower()
               for k in ['cjk', 'heiti', 'pingfang', 'song', 'noto', 'wenquan'])]
    return cjk[0] if cjk else 'DejaVu Sans'

CHINESE_FONT = detect_chinese_font()
plt.rcParams['font.family'] = CHINESE_FONT

# ── 讀取 K線 JSON ──────────────────────────────────────────────
_plot_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
json_path = sys.argv[1] if len(sys.argv) > 1 else \
    os.path.join(_plot_base, 'data', 'tpex', 'kline_2070_2m.json')

data = json.load(open(json_path))
meta = data['meta']
rows = data['data']

# volume 已是「張」，直接用
volumes   = [r['volume'] for r in rows]
dates_str = [r['date'].split('/')[1] + '/' + r['date'].split('/')[2] for r in rows]
opens     = [r['open']  for r in rows]
highs     = [r['high']  for r in rows]
lows      = [r['low']   for r in rows]
closes    = [r['close'] for r in rows]
colors    = ['#d62728' if c > o else '#2ca02c' for o, c in zip(opens, closes)]

n = len(rows)

# ── 均線計算 ────────────────────────────────────────────────────
ma5  = [sum(closes[max(0,i-4):i+1])/min(5,i+1)  for i in range(n)]
ma10 = [sum(closes[max(0,i-9):i+1])/min(10,i+1) for i in range(n)]
ma20 = [sum(closes[max(0,i-19):i+1])/min(20,i+1) for i in range(n)]

# ── 圖表配置 ────────────────────────────────────────────────────
fig, (ax_k, ax_v) = plt.subplots(
    2, 1, figsize=(22, 11),
    gridspec_kw={'height_ratios': [4, 1]},
    sharex=True
)
fig.patch.set_facecolor('white')
ax_k.set_facecolor('white')
ax_v.set_facecolor('white')

for ax in [ax_k, ax_v]:
    ax.tick_params(colors='#333333', labelsize=9)
    ax.spines['top'].set_color('#cccccc')
    ax.spines['bottom'].set_color('#cccccc')
    ax.spines['left'].set_color('#cccccc')
    ax.spines['right'].set_color('#cccccc')
    ax.grid(True, linestyle='--', linewidth=0.5, color='#dddddd')

# ── K線主圖 ─────────────────────────────────────────────────────
for i in range(n):
    col = colors[i]
    ax_k.plot([i, i], [lows[i], highs[i]], color=col, linewidth=1.2)
    body_bottom = min(opens[i], closes[i])
    body_height = abs(closes[i] - opens[i])
    if body_height < 0.001:
        body_height = closes[i] * 0.001
    ax_k.bar(i, body_height, bottom=body_bottom, color=col, width=0.6, edgecolor=col, linewidth=0.8)

# 均線（MA5 / MA10 / MA20）
ax_k.plot(range(n), ma5,  '#1f77b4', linewidth=1.5, label='MA5')
ax_k.plot(range(n), ma10, '#2ca02c', linewidth=1.5, label='MA10')
ax_k.plot(range(n), ma20, '#ff7f0e', linewidth=1.5, label='MA20')

ax_k.set_ylabel('價格（元）', fontsize=10, color='#333333')
ax_k.set_ylim(min(lows) - 1, max(highs) + 1)
ax_k.legend(loc='upper left', fontsize=9, framealpha=0.3)

# ── 成交量副圖 ──────────────────────────────────────────────────
ax_v.bar(range(n), volumes, color=colors, width=0.6, edgecolor='none')
ax_v.set_ylabel('成交量（張）', fontsize=10, color='#333333')

# ── X軸標籤（每5根顯示一個，避免擁擠）──────────────────────────
tick_step = 5
tick_positions = list(range(0, n, tick_step))
tick_labels = [dates_str[i] for i in tick_positions]
ax_v.set_xticks(tick_positions)
ax_v.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=8)
ax_k.set_xticks(tick_positions)
ax_k.set_xticklabels([])  # K線圖不重疊

# ── 標題 & 圖例 ─────────────────────────────────────────────────
fig.suptitle(
    f"{meta['stock_id']} {meta['name']} — {meta['period']}K線（{meta['date_range']}）",
    color='#333333', fontsize=13, y=0.98
)
legend_elements = [
    Patch(facecolor='#d62728', label='紅=漲'),
    Patch(facecolor='#2ca02c', label='綠=跌'),
]
ax_k.legend(handles=legend_elements, loc='upper left',
            fontsize=9, framealpha=0.3, labelcolor='#333333')

plt.tight_layout(rect=[0, 0, 1, 0.97])

# ── 儲存 & 縮圖檢查 ─────────────────────────────────────────────
output_path = sys.argv[2] if len(sys.argv) > 2 else json_path.replace('.json', '.png')
plt.savefig(output_path, dpi=180, bbox_inches='tight', facecolor='white')
plt.close()
print(f'✅ 已儲存：{output_path}')

# Telegram 安全檢查：寬幅 > 1280px 就縮圖
img = Image.open(output_path)
w, h = img.size
if max(w, h) > 1280:
    ratio = 1280 / max(w, h)
    img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
    safe_path = output_path.replace('.png', '_1280.png')
    img.save(safe_path, quality=85)
    print(f'✅ 縮圖已產生（{img.size[0]}px 寬）：{safe_path}')
else:
    print(f'✅ 原始圖寬度 {w}px，無需縮圖')