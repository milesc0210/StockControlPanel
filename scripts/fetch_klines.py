#!/usr/bin/env python3
"""fetch_klines.py — 抓 FinMind K線並直接產 PNG"""
import os, json, subprocess
from FinMind.data import DataLoader

from portable_runtime import DATA_DIR, get_env, load_dotenv

load_dotenv()

PY = 'python3'
BASE = str(DATA_DIR)
today = '2026-05-28'
start = '2026-03-01'

stocks = {
    '6150': ('tpex', '撼訊'),
    '5410': ('tpex', '國眾'),
    '6546': ('tpex', '正基'),
    '8096': ('tpex', '擎亞'),
    '3066': ('tpex', '李洲'),
}

dl = DataLoader()
finmind_token = get_env('FINMIND_TOKEN')
if not finmind_token:
    raise RuntimeError('缺少 FINMIND_TOKEN，請先在可攜版設定頁或 .env 設定。')
dl.login_by_token(api_token=finmind_token)

for code, (mkt, name) in stocks.items():
    out_json = f'{BASE}/{mkt}/2026/Kline/kline_{code}.json'
    if os.path.exists(out_json):
        print(f'{code}: JSON 已存在，跳過')
        continue
    print(f'{code}: 抓取中...')
    df = dl.taiwan_stock_daily(stock_id=code, start_date=start, end_date=today)
    df = df.sort_values('date').reset_index(drop=True)
    df['date_str'] = df['date'].str.replace('-', '/')
    rows = []
    for _, r in df.iterrows():
        rows.append({
            'date': r['date_str'],
            'open': float(r['open']),
            'high': float(r['max']),
            'low': float(r['min']),
            'close': float(r['close']),
            'volume': int(r['Trading_Volume'])
        })
    data = {
        'meta': {
            'stock_id': code,
            'name': name,
            'source': 'FinMind daily',
            'period': f'{len(rows)} trading days',
            'date_range': f'{rows[0]["date"]}~{rows[-1]["date"]}',
            'count': len(rows),
        },
        'data': rows
    }
    os.makedirs(f'{BASE}/{mkt}/2026/Kline', exist_ok=True)
    with open(out_json, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'  → {out_json}')

print('K線 JSON 完成')