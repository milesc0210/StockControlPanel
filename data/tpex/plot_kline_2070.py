#!/usr/bin/env python3
"""Plot K-line chart for stock 2070精湛 (2 months)"""

import json
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.font_manager as fm
import numpy as np

# Load data
json_path = "/Users/zhengyulun/0_miles/G/Miles agent/data/tpex/kline_2070_2m.json"
with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

records = data['data']  # 40 records, newest first

# Extract and reverse to chronological order
dates = [r['date'] for r in records][::-1]  # oldest -> newest
opens = [r['open'] for r in records][::-1]
highs = [r['high'] for r in records][::-1]
lows = [r['low'] for r in records][::-1]
closes = [r['close'] for r in records][::-1]
volumes = [r['volume'] / 1000 for r in records][::-1]  # 張

# Determine color: red (up) if close > open, green (down) otherwise
colors = ['#d62728' if c > o else '#2ca02c' for o, c in zip(opens, closes)]

# Prepare x positions
x = np.arange(len(dates))

# Font
font_path = fm.findfont(fm.FontProperties(family='Arial Unicode MS'))
if 'Arial' not in font_path or 'Unicode' not in font_path:
    # Fallback
    font_path = fm.findfont(fm.FontProperties(family='sans-serif'))
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# Create figure
fig = plt.figure(figsize=(22, 11), dpi=180)
fig.patch.set_facecolor('white')

# GridSpec: K-line 80%, volume 20%
gs = gridspec.GridSpec(2, 1, height_ratios=[4, 1])

# === K-line subplot ===
ax1 = fig.add_subplot(gs[0])
ax1.patch.set_facecolor('white')

# Draw candlesticks
for i, (xi, o, h, l, c, col) in enumerate(zip(x, opens, highs, lows, closes, colors)):
    # Shadow (high-low line)
    ax1.plot([xi, xi], [l, h], color=col, linewidth=1.2)
    # Body (open-close rectangle)
    if o == c:
        # Doji - just a small line
        ax1.plot([xi - 0.15, xi + 0.15], [c, c], color=col, linewidth=1.2)
    else:
        bottom = min(o, c)
        height = abs(c - o)
        rect = plt.Rectangle((xi - 0.25, bottom), 0.5, height,
                              facecolor=col if c > o else col,
                              edgecolor=col, linewidth=1.2)
        ax1.add_patch(rect)

ax1.set_xlim(-0.5, len(dates) - 0.5)
ax1.set_ylim(min(lows) - 1, max(highs) + 1)
ax1.set_ylabel('價格', fontsize=12)
ax1.set_title('2070 精湛 — 兩個月K線（20260326~0525）', fontsize=16, fontweight='bold', pad=10)
ax1.grid(True, alpha=0.3, color='gray')
ax1.set_facecolor('#f9f9f9')

# X-axis labels: every 5th date shown as MM/DD
tick_positions = list(range(0, len(dates), 5))
tick_labels = [dates[i][5:].replace('/', '/') for i in tick_positions]  # MM/DD
ax1.set_xticks(tick_positions)
ax1.set_xticklabels(tick_labels, rotation=45, fontsize=10)
ax1.tick_params(axis='x', rotation=45)

# Legend
from matplotlib.patches import Patch
legend_elements = [
    Patch(facecolor='#d62728', edgecolor='#d62728', label='紅=漲'),
    Patch(facecolor='#2ca02c', edgecolor='#2ca02c', label='綠=跌')
]
ax1.legend(handles=legend_elements, loc='upper left', fontsize=10)

# === Volume subplot ===
ax2 = fig.add_subplot(gs[1], sharex=ax1)
ax2.patch.set_facecolor('white')

# Volume bars with same color scheme
bar_colors = colors
ax2.bar(x, volumes, color=bar_colors, width=0.5, edgecolor='none', alpha=0.85)

ax2.set_xlim(-0.5, len(dates) - 0.5)
ax2.set_ylim(0, max(volumes) * 1.1)
ax2.set_ylabel('成交量（張）', fontsize=11)
ax2.set_xlabel('交易日', fontsize=11)
ax2.grid(True, alpha=0.3, color='gray')
ax2.set_facecolor('#f9f9f9')

# Share x-axis ticks with K-line plot
ax2.set_xticks(tick_positions)
ax2.set_xticklabels(tick_labels, rotation=45, fontsize=9)

plt.tight_layout()

# Save
output_path = "/Users/zhengyulun/0_miles/G/Miles agent/data/tpex/kline_2070_2m.png"
plt.savefig(output_path, dpi=180, bbox_inches='tight', facecolor='white')
plt.close()

print(f"Saved: {output_path}")

# Verify file size
import os
size = os.path.getsize(output_path)
print(f"File size: {size / 1024:.1f} KB")
print(f"Number of candles: {len(dates)}")
