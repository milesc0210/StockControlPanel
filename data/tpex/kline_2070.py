#!/usr/bin/env python3
"""
2070 精湛 K線圖產生器
紅漲綠跌標準蠟燭圖 + 成交量副圖
"""

import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import matplotlib.font_manager as fm

# 找可用的中文字體（macOS優先）
def get_chinese_font():
    font_candidates = [
        'Arial Unicode MS',
        'Heiti TC',
        'PingFang SC',
        'SimHei',
        'Noto Sans CJK TC',
        'WenQuanYi Zen Hei',
    ]
    for font in font_candidates:
        path = fm.findfont(fm.FontProperties(family=font))
        if path and 'FontNotFound' not in path:
            print(f"✅ 使用字體：{font}")
            return font
    # 最後 fallback：列出所有可用字體，找含 CJK/Hei/Song 的
    all_fonts = [f.name for f in fm.fontManager.ttflist]
    for keyword in ['CJK', 'Hei', 'Song', 'Yi']:
        matches = [f for f in all_fonts if keyword in f]
        if matches:
            print(f"✅ Fallback 使用：{matches[0]}")
            return matches[0]
    print("⚠️  未找到中文字體，使用預設")
    return 'DejaVu Sans'

chinese_font = get_chinese_font()

# 2070 精湛 7 日 OHLC 資料（收盤日期新到舊）
data = [
    ("2026/05/22", 65.00, 67.50, 65.00, 66.80, 635000),
    ("2026/05/21", 63.50, 65.50, 63.50, 64.50, 433000),
    ("2026/05/20", 65.70, 65.70, 62.80, 63.00, 409000),
    ("2026/05/19", 67.90, 67.90, 65.40, 65.70, 509000),
    ("2026/05/18", 64.60, 67.40, 63.00, 65.70, 674000),
    ("2026/05/15", 64.30, 67.60, 63.80, 65.20, 938000),
    ("2026/05/14", 65.70, 67.00, 62.90, 63.30, 905000),
]

# 反轉為日期升序（舊到新）
data.reverse()

dates_str = [d[0] for d in data]
opens  = [d[1] for d in data]
highs  = [d[2] for d in data]
lows   = [d[3] for d in data]
closes = [d[4] for d in data]
volumes = [d[5] for d in data]

# 成交量從「股」轉「張」÷1000
volumes_unit = [v // 1000 for v in volumes]

# X軸標籤（只當作標籤用，不參與定位）
date_labels = [d[5:] for d in dates_str]  # 取月/日 如 "05/14"

# 漲跌顏色
colors = ['#d62728' if c > o else '#2ca02c' for o, c in zip(opens, closes)]

# ── 圖表設定 ─────────────────────────────────────────────
fig = plt.figure(figsize=(17, 10.2), dpi=400)
fig.patch.set_facecolor('#1e1e1e')

# 使用 GridSpec：上圖 80%，下圖 20%
gs = GridSpec(2, 1, height_ratios=[4, 1], hspace=0.05)

ax = fig.add_subplot(gs[0])   # K線圖
ax_vol = fig.add_subplot(gs[1], sharex=ax)  # 成交量副圖

# K線圖樣式
for spine in ax.spines.values():
    spine.set_color('#444')
ax.tick_params(colors='#cccccc', labelsize=9)
ax.yaxis.label.set_color('#cccccc')
ax.xaxis.label.set_color('#cccccc')
ax.grid(True, linestyle='--', linewidth=0.5, color='#444')

# 成交量圖樣式
for spine in ax_vol.spines.values():
    spine.set_color('#444')
ax_vol.tick_params(colors='#cccccc', labelsize=8)
ax_vol.grid(True, linestyle='--', linewidth=0.5, color='#444')

# 蠟燭：body = 實體柱, shadow = 上下影線
# X軸用 index (0,1,2,3,4,5,6)，標籤顯示日期
for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
    col = '#d62728' if c > o else '#2ca02c'

    # 影線（high→low）—— 用索引 i 定位，無間隙
    ax.plot([i, i], [l, h], color=col, linewidth=1.2)

    # 實體（open→close）—— 用索引 i 定位
    ax.bar(i, abs(c - o), bottom=min(o, c),
           color=col, width=0.6, edgecolor=col, linewidth=0.8)

# 成交量長條圖（紅漲綠跌）—— 用「張」為單位
for i, (c, v) in enumerate(zip(closes, volumes_unit)):
    col = '#d62728' if c > opens[i] else '#2ca02c'
    ax_vol.bar(i, v, color=col, width=0.6, edgecolor=col, linewidth=0.5)

# X軸：分類座標，刻度=索引，標籤=日期字串，解決週末間隙問題
ax.set_xticks(range(7))
ax.set_xticklabels(date_labels)

ax_vol.set_xticks(range(7))
ax_vol.set_xticklabels(date_labels)

plt.setp(ax.get_xticklabels(), visible=False)  # K線圖隱藏X刻度標籤

# X軸標籤旋轉
ax_vol.tick_params(axis='x', rotation=45)

# Y軸（63~68）
ax.set_ylim(62.5, 68.5)
ax.set_yticks(range(63, 69))

# ── 中文化標籤 ───────────────────────────────────────────
font_props = fm.FontProperties(family=chinese_font)

ax.set_ylabel('價格（元）', fontsize=10, fontproperties=font_props)
ax_vol.set_ylabel('成交量（張）', fontsize=9, fontproperties=font_props)
ax_vol.set_xlabel('日期', fontsize=10, fontproperties=font_props)

# 標題
fig.suptitle('2070 精湛 — 一週K線（20260514~0522）',
             color='#ffffff', fontsize=13, y=0.98, fontproperties=font_props)

# 圖例
from matplotlib.patches import Patch
legend_elements = [
    Patch(facecolor='#d62728', label='紅=漲'),
    Patch(facecolor='#2ca02c', label='綠=跌'),
]
ax.legend(handles=legend_elements, loc='upper left',
          fontsize=9, framealpha=0.3, labelcolor='#cccccc',
          prop=font_props)

plt.tight_layout(rect=[0, 0, 1, 0.97])

# 儲存
out = '/Users/zhengyulun/0_miles/G/Miles agent/data/tpex/kline_2070.png'
plt.savefig(out, dpi=180, bbox_inches='tight', facecolor=fig.get_facecolor())
print(f'✅ 已儲存：{out}')