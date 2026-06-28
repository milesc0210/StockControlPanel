import json, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from PIL import Image

plt.rcParams['font.sans-serif'] = ['Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

with open('/tmp/kline_tpex_9.json') as f:
    data = json.load(f)

output_dir = '/Users/zhengyulun/0_miles/G/Miles agent/data/kline_png'
os.makedirs(output_dir, exist_ok=True)

for code, info in data.items():
    hist = info['hist']
    name = info['name']
    
    closes = [x['close'] for x in hist]
    volumes = [x['volume'] for x in hist]
    dates_str = [x['date'] for x in hist]
    
    # MA
    ma5 = []
    ma10 = []
    ma20 = []
    for i in range(len(closes)):
        ma5.append(sum(closes[max(0,i-4):i+1]) / min(5, i+1))
        ma10.append(sum(closes[max(0,i-9):i+1]) / min(10, i+1))
        ma20.append(sum(closes[max(0,i-19):i+1]) / min(20, i+1))
    
    last_close = closes[-1]
    last_date = dates_str[-1]
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={'height_ratios': [4, 1]}, sharex=True)
    
    # Price chart
    ax1.plot(range(len(closes)), closes, color='#1f77b4', linewidth=1.5, label='收盤價')
    ax1.plot(range(len(closes)), ma5, color='#2ca02c', linewidth=1, label='MA5')
    ax1.plot(range(len(closes)), ma10, color='#ff7f0e', linewidth=1, label='MA10')
    ax1.plot(range(len(closes)), ma20, color='red', linewidth=1, label='MA20')
    ax1.fill_between(range(len(closes)), closes, alpha=0.1, color='#1f77b4')
    
    # Add annotation for last point
    ax1.annotate(f'{last_close}', xy=(len(closes)-1, last_close), fontsize=10, color='#1f77b4', va='bottom')
    
    ax1.set_title(f'{code} {name} — TPEX 40日收盤線（{dates_str[0]}~{last_date}）', fontsize=14, pad=10)
    ax1.legend(loc='upper left', fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylabel('收盤價', fontsize=10)
    
    # MA values annotation
    ax1.text(0.98, 0.95, f'MA5={ma5[-1]:.2f}\nMA10={ma10[-1]:.2f}\nMA20={ma20[-1]:.2f}',
             transform=ax1.transAxes, fontsize=8, va='top', ha='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Volume chart
    colors = ['#1f77b4' if closes[i] >= closes[i-1] else '#ef4040' for i in range(1, len(volumes))]
    colors = ['#1f77b4' if closes[i] >= (closes[i-1] if i > 0 else closes[0]) else '#ef4040' for i in range(len(volumes))]
    ax2.bar(range(len(volumes)), volumes, color=colors, width=0.7, alpha=0.7)
    ax2.set_ylabel('成交量（張）', fontsize=10)
    ax2.set_xlabel('交易日', fontsize=10)
    ax2.grid(True, alpha=0.3, axis='y')
    
    # X-axis labels (every 5th day)
    tick_positions = list(range(0, len(dates_str), 5))
    tick_labels = [dates_str[i] for i in tick_positions]
    ax2.set_xticks(tick_positions)
    ax2.set_xticklabels(tick_labels, rotation=45, fontsize=8)
    
    plt.tight_layout()
    
    out_path = f'{output_dir}/kline_{code}_40d.png'
    plt.savefig(out_path, dpi=100, bbox_inches='tight')
    plt.close()
    
    # Resize if width > 1280
    img = Image.open(out_path)
    if img.width > 1280:
        new_height = int(1280 * img.height / img.width)
        img = img.resize((1280, new_height), Image.LANCZOS)
        img.save(out_path, quality=85)
    
    print(f'Saved: {out_path}')
