import json, matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib import font_manager as fm
from PIL import Image
import numpy as np

# 設定字體
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS']
plt.rcParams['font.family'] = 'Arial Unicode MS'
plt.rcParams['axes.unicode_minus'] = False

json_path = '/Users/zhengyulun/0_miles/G/Miles agent/data/twse/2026/Kline/kline_2634_40d.json'
output_png = '/Users/zhengyulun/0_miles/G/Miles agent/data/kline_png/kline_2634_40d.png'

data = json.load(open(json_path))
meta = data['meta']
rows = data['data']

closes = [r['close'] for r in rows]

c = np.array(closes, dtype=float)
ma5  = np.convolve(c, np.ones(5)/5,  mode='valid')
ma10 = np.convolve(c, np.ones(10)/10, mode='valid')
ma20 = np.convolve(c, np.ones(20)/20, mode='valid')

n = len(rows)
dates_str = [r['date'][4:6]+'/'+r['date'][6:] for r in rows]
opens  = [r['open']  for r in rows]
highs  = [r['high']  for r in rows]
lows   = [r['low']   for r in rows]
closes = [r['close'] for r in rows]
volumes = [r['volume'] for r in rows]
colors = ['#d62728' if c > o else '#2ca02c' for o, c in zip(opens, closes)]

fig, (ax_k, ax_v) = plt.subplots(2, 1, figsize=(22, 11), gridspec_kw={'height_ratios': [4, 1]}, sharex=True)
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

for i in range(n):
    col = colors[i]
    ax_k.plot([i,i], [lows[i], highs[i]], color=col, linewidth=1.2)
    body_bottom = min(opens[i], closes[i])
    body_height = abs(closes[i] - opens[i])
    ax_k.bar(i, body_height, bottom=body_bottom, color=col, width=0.6, edgecolor=col, linewidth=0.8)

ax_k.plot(range(4, n), ma5,  color='#1f77b4', linewidth=1.8, label='MA5')
ax_k.plot(range(9, n), ma10, color='#2ca02c', linewidth=1.8, label='MA10')
ax_k.plot(range(19, n), ma20, color='#ff7f0e', linewidth=1.8, label='MA20')

ax_k.set_ylabel('價格（元）', fontsize=10, color='#333333')
ax_k.set_ylim(min(lows)-1, max(highs)+1)

ax_v.bar(range(n), volumes, color=colors, width=0.6, edgecolor='none')
ax_v.set_ylabel('成交量（張）', fontsize=10, color='#333333')

tick_step = 5
tick_positions = list(range(0, n, tick_step))
tick_labels = [dates_str[i] for i in tick_positions]
ax_v.set_xticks(tick_positions)
ax_v.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=8)
ax_k.set_xticks(tick_positions)
ax_k.set_xticklabels([])

last_close = closes[-1]
fig.suptitle(f"2634 漢翔 40天K線（{meta['date_range']}） 收盤{last_close}", color='#333333', fontsize=13, y=0.98)
legend_elements = [
    Patch(facecolor='#d62728', label='紅=漲'),
    Patch(facecolor='#2ca02c', label='綠=跌')
]
ax_k.legend(handles=legend_elements, loc='upper left', fontsize=9, framealpha=0.3, labelcolor='#333333')

plt.tight_layout(rect=[0, 0, 1, 0.97])
plt.savefig(output_png, dpi=180, bbox_inches='tight', facecolor='white')
plt.close()

img = Image.open(output_png)
w, h = img.size
print(f'Original: {w}x{h}px')
if max(w, h) > 1280:
    ratio = 1280/max(w, h)
    img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
    img.save(output_png, quality=85)
    print(f'Resized to {img.size[0]}px wide')
else:
    print('No resize needed')
print('Done')
