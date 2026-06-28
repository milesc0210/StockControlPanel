#!/usr/bin/env python3
"""根據 011 漲停紅箭結果批次產生 K 線圖。

輸入：outputs/screen_limitup_upperwick_<date>.json
輸出：outputs/kline_011_<date>/kline_<code>_<name>.png

預設抓最近 40 個交易日，畫出：
- K 線
- 成交量
- MA5 / MA10 / MA20
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from PIL import Image

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / 'data'
OUTPUT_DIR = BASE_DIR / 'outputs'
TWSE_DIR = DATA_DIR / 'twse' / '2026'
TPEX_DIR = DATA_DIR / 'tpex' / '2026'
DEFAULT_SCREEN_DATE = '20260618'
LOOKBACK_DAYS = 40


def detect_chinese_font() -> str:
    available = [f.name for f in fm.fontManager.ttflist]
    candidates = [
        'Arial Unicode MS', 'PingFang TC', 'Heiti TC',
        'Noto Sans CJK TC', 'Noto Sans CJK SC', 'WenQuanYi Zen Hei'
    ]
    for name in candidates:
        if name in available:
            return name
    for name in available:
        lower = name.lower()
        if any(k in lower for k in ['cjk', 'heiti', 'pingfang', 'noto', 'wenquan']):
            return name
    return 'DejaVu Sans'


plt.rcParams['font.family'] = detect_chinese_font()
plt.rcParams['axes.unicode_minus'] = False


def normalize_field_name(name: str) -> str:
    text = re.sub(r'<br.*?>', '', str(name))
    return text.replace(' ', '').strip()


def parse_num(value: object) -> float:
    return float(str(value).strip().replace(',', ''))


def load_screen_candidates(screen_date: str) -> list[dict]:
    path = OUTPUT_DIR / f'screen_limitup_upperwick_{screen_date}.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    return payload['candidates']


def available_dates() -> list[str]:
    twse_dates = {p.stem for p in TWSE_DIR.glob('2026*.json') if p.is_file()}
    tpex_dates = {p.stem for p in TPEX_DIR.glob('2026*.json') if p.is_file()}
    return sorted(twse_dates & tpex_dates)


def get_date_range(end_date: str, lookback_days: int) -> list[str]:
    dates = available_dates()
    if end_date not in dates:
        raise SystemExit(f'找不到 end_date={end_date} 的共同市場資料')
    end_idx = dates.index(end_date)
    start_idx = max(0, end_idx - lookback_days + 1)
    return dates[start_idx:end_idx + 1]


def parse_twse_row(row: list, fields: list[str]) -> tuple[str, dict] | None:
    code_i = fields.index('證券代號')
    name_i = fields.index('證券名稱')
    open_i = fields.index('開盤價')
    high_i = fields.index('最高價')
    low_i = fields.index('最低價')
    close_i = fields.index('收盤價')
    volume_i = fields.index('成交股數')
    try:
        code = str(row[code_i]).strip()
        return code, {
            'name': str(row[name_i]).strip(),
            'open': parse_num(row[open_i]),
            'high': parse_num(row[high_i]),
            'low': parse_num(row[low_i]),
            'close': parse_num(row[close_i]),
            'volume_lots': int(parse_num(row[volume_i]) / 1000),
        }
    except Exception:
        return None


def parse_tpex_row(row: list, fields: list[str]) -> tuple[str, dict] | None:
    idx = {name: fields.index(name) for name in ['代號', '名稱', '收盤', '開盤', '最高', '最低', '成交股數']}
    try:
        code = str(row[idx['代號']]).strip()
        return code, {
            'name': str(row[idx['名稱']]).strip(),
            'open': parse_num(row[idx['開盤']]),
            'high': parse_num(row[idx['最高']]),
            'low': parse_num(row[idx['最低']]),
            'close': parse_num(row[idx['收盤']]),
            'volume_lots': int(parse_num(row[idx['成交股數']]) / 1000),
        }
    except Exception:
        return None


def build_history(market: str, code: str, end_date: str, lookback_days: int) -> list[dict]:
    date_range = get_date_range(end_date, lookback_days)
    rows = []
    base_dir = TWSE_DIR if market == 'twse' else TPEX_DIR

    for d in date_range:
        payload = json.loads((base_dir / f'{d}.json').read_text(encoding='utf-8'))
        if market == 'twse':
            fields = [normalize_field_name(x) for x in payload.get('fields', [])]
            source_rows = payload.get('data', [])
            parser = lambda r: parse_twse_row(r, fields)
        else:
            table = payload['tables'][0]
            fields = [normalize_field_name(x) for x in table.get('fields', [])]
            source_rows = table.get('data', [])
            parser = lambda r: parse_tpex_row(r, fields)

        found = None
        for row in source_rows:
            parsed = parser(row)
            if not parsed:
                continue
            row_code, data = parsed
            if row_code == code:
                found = data
                break
        if found:
            rows.append({
                'date': d,
                'open': found['open'],
                'high': found['high'],
                'low': found['low'],
                'close': found['close'],
                'volume': found['volume_lots'],
                'name': found['name'],
            })
    return rows


def moving_average(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < period:
            result.append(None)
        else:
            window = values[i - period + 1:i + 1]
            result.append(sum(window) / period)
    return result


def safe_filename(text: str) -> str:
    return re.sub(r'[^0-9A-Za-z一-龥_-]+', '_', text)


def render_chart(code: str, name: str, market: str, rows: list[dict], out_path: Path) -> None:
    closes = [r['close'] for r in rows]
    opens = [r['open'] for r in rows]
    highs = [r['high'] for r in rows]
    lows = [r['low'] for r in rows]
    volumes = [r['volume'] for r in rows]
    dates = [f"{r['date'][4:6]}/{r['date'][6:8]}" for r in rows]
    ma5 = moving_average(closes, 5)
    ma10 = moving_average(closes, 10)
    ma20 = moving_average(closes, 20)

    fig, (ax_k, ax_v) = plt.subplots(
        2, 1, figsize=(14, 8), gridspec_kw={'height_ratios': [4, 1]}, sharex=True
    )
    fig.patch.set_facecolor('white')
    ax_k.set_facecolor('white')
    ax_v.set_facecolor('white')

    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        color = '#d62728' if c >= o else '#2ca02c'
        ax_k.plot([i, i], [l, h], color=color, linewidth=1.0)
        body_bottom = min(o, c)
        body_height = abs(c - o)
        if body_height < 0.001:
            body_height = max(c * 0.001, 0.01)
        ax_k.bar(i, body_height, bottom=body_bottom, color=color if c >= o else 'white',
                 edgecolor=color, width=0.6, linewidth=1.0)

    def plot_ma(ax, series, color, label, linestyle='-'):
        xs = [i for i, v in enumerate(series) if v is not None]
        ys = [v for v in series if v is not None]
        if xs:
            ax.plot(xs, ys, color=color, linewidth=1.2, label=label, linestyle=linestyle)

    plot_ma(ax_k, ma5, '#1f77b4', 'MA5')
    plot_ma(ax_k, ma10, '#ff7f0e', 'MA10')
    plot_ma(ax_k, ma20, 'black', 'MA20', '--')

    colors = ['#d62728' if c >= o else '#2ca02c' for o, c in zip(opens, closes)]
    ax_v.bar(range(len(rows)), volumes, color=colors, width=0.6)

    ax_k.set_title(f'{code} {name} [{market.upper()}] {len(rows)}日K線', fontsize=13)
    ax_k.set_ylabel('價格')
    ax_v.set_ylabel('量(張)')
    ax_k.grid(True, linestyle='--', linewidth=0.4, color='#dddddd')
    ax_v.grid(True, linestyle='--', linewidth=0.4, color='#dddddd', axis='y')
    ax_k.legend(loc='upper left', fontsize=9)

    tick_step = max(1, math.ceil(len(rows) / 8))
    tick_positions = list(range(0, len(rows), tick_step))
    ax_v.set_xticks(tick_positions)
    ax_v.set_xticklabels([dates[i] for i in tick_positions], rotation=45, ha='right', fontsize=8)

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=160, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    img = Image.open(out_path)
    w, h = img.size
    if max(w, h) > 1280:
        ratio = 1280 / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        img.save(out_path, quality=85)


def main() -> None:
    parser = argparse.ArgumentParser(description='為 011 漲停紅箭結果批次產生 K 線圖')
    parser.add_argument('--screen-date', default=DEFAULT_SCREEN_DATE, help='選股輸出日期 YYYYMMDD')
    parser.add_argument('--lookback', type=int, default=LOOKBACK_DAYS, help='回溯交易日數')
    args = parser.parse_args()

    candidates = load_screen_candidates(args.screen_date)
    out_dir = OUTPUT_DIR / f'kline_011_{args.screen_date}'
    created = []

    for item in candidates:
        code = item['code']
        name = item['name']
        market = item['market']
        rows = build_history(market, code, args.screen_date, args.lookback)
        if not rows:
            print(f'⚠️ 無資料：{market} {code} {name}')
            continue
        out_path = out_dir / f"kline_{code}_{safe_filename(name)}.png"
        render_chart(code, name, market, rows, out_path)
        created.append(out_path)
        print(f'✅ {code} {name}: {out_path}')

    print(f'\n總計產出 {len(created)} 張圖，目錄：{out_dir}')


if __name__ == '__main__':
    main()
