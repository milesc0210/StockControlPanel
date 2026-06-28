#!/usr/bin/env python3
"""產出 daily_trade_plan.json — 收盤後篩選，次日執行（波段模式）"""
import json, os, sys
from datetime import datetime, timedelta

# ── 路徑設定（相對於本腳本位置）──
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 讀取資料 ──
with open(os.path.join(_BASE, 'holdings.json')) as f:
    holdings_data = json.load(f)

with open(os.path.join(_BASE, 'data', 'stock_pool.json')) as f:
    sp = json.load(f)

with open(os.path.join(_BASE, 'data', 'sector_filtered_pool.json')) as f:
    sf = json.load(f)

cands = {c['代碼']: c for c in sf.get('candidates', [])}

# ── 參數（固定值，實際跑腳本時由外部置換）──
CURRENT_CASH = 92561
INITIAL_CAPITAL = 100000
PLAN_DATE = '2026-06-04'  # 下一個交易日（6/3收盤→6/4開盤）
GENERATED_AT = datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00')

# ── holdings[]：從 holdings.json 完整複製，mode 改 B，expiration 留空 ──
holdings = []
for h in holdings_data.get('holdings', []):
    entry = {
        'stock_id': h['stock_id'],
        'name': h['name'],
        'shares': h['shares'],
        'cost_price': h['cost_price'],
        'stop_loss': h.get('stop_loss', round(h['cost_price'] * 0.95, 2)),
        'mode': 'B',          # 固定波段
        'expiration': '',      # 每天重新判斷
    }
    holdings.append(entry)

# ── pending_trades[]：immediate 在這裡（Bot 直接執行）──
pending_trades = []

# ── watchlist[]：afternoon_eval 在這裡（Bot 13:00 評估）──
watchlist = []
EXCLUDED = ['3042']  # 晶技：收盤217.5≥200元，不符合進場條件

pool_rr = {s['code']: float((s.get('structure') or {}).get('window_5', {}).get('rr', 0)) for s in sp['pool']}

for s in sp['pool']:
    code = s['code']
    if code in EXCLUDED:
        continue
    c = cands.get(code, {})
    price = float(c.get('成交', 0) or 0)
    if price <= 0:
        continue
    vol = float(c.get('總量', 0) or 0)
    name = s.get('name', c.get('商品', ''))

    w5 = (s.get('structure') or {}).get('window_5') or {}
    supports = w5.get('supports', [])
    resistances = w5.get('resistances', [])
    rr = float(w5.get('rr', 0))
    nearest_support = float(supports[0]) if supports else 0
    nearest_resistance = float(resistances[0]) if resistances else 0

    # 計算距支撐%
    pct_from_support = (price / nearest_support - 1) * 100 if nearest_support > 0 else 0

    # zone 判斷
    if pct_from_support < 5:
        zone = '低檔'
    elif pct_from_support < 15:
        zone = '換手區'
    else:
        zone = '醞釀區'

    # 波段模式：全部走 afternoon_eval，保留 immediate 只用於極佳進場點
    week_pct = float(c.get('一週%', 0) or 0)
    can_immediate = (
        pct_from_support <= 10      # 距支撐 10% 以內
        and rr >= 1.0               # RR ≥ 1.0（68天資料RR天然偏低，放寬門檻）
        and week_pct > 0            # 一週動能正
    )

    if can_immediate:
        execute_type = 'immediate'
        trigger_price = None
        entry_condition = {
            'open_range_pct': [-2, 1],
            'volume_check': {
                'min_pct_of_yesterday_5min': 10,
                'min_volume_5min_abs': 300,
            }
        }
        limit_price = round(price * 0.99, 2)
        reason = f'低接訊號，距支撐{pct_from_support:.1f}%，RR={rr:.1f}，一週+{week_pct:.1f}%'
    else:
        execute_type = 'afternoon_eval'
        trigger_price = nearest_support if nearest_support > 0 else None
        entry_condition = None
        limit_price = round(nearest_support * 1.03, 2) if nearest_support > 0 else price
        reason = f'波段候選，RR={rr:.1f}，支撐{nearest_support:.1f}，壓力{nearest_resistance:.1f}'

    # 股數計算（固定100股，不按資金比例）
    shares = 100 if price * 100 <= CURRENT_CASH * 0.2 else (CURRENT_CASH * 0.2 // price // 100) * 100
    shares = max(100, shares)

    entry = {
        'stock_id': code,
        'name': name,
        'action': 'buy',
        'zone': zone,
        'close': price,
        'volume': int(vol),
        'reason': reason,
        'execute_type': execute_type,
        'trigger_price': trigger_price,
        'entry_condition': entry_condition,
        'suggested': {
            'shares': shares,
            'order_type': 'limit',
            'limit_price': limit_price,
            'max_price': limit_price,
            'mode': 'B',           # 固定波段
            'stop_loss_pct': 5,
            'take_profit_pct': None,
        },
        'priority': 99,
    }

    # immediate → pending_trades；afternoon_eval → watchlist
    if execute_type == 'immediate':
        pending_trades.append({
            'id': f'{code}-buy-{PLAN_DATE.replace("-","")}090500',
            'stock_id': code,
            'name': name,
            'action': 'buy',
            'shares': shares,
            'order_type': 'limit',
            'limit_price': limit_price,
            'max_price': limit_price,
            'mode': 'B',
            'time_slot': '09:05',
            'execute_type': 'immediate',
            'trigger_price': None,
            'entry_condition': entry_condition,
            'stop_loss_pct': 5,
            'take_profit_pct': None,
            'expiration': '',
            'reason': reason,
        })
    else:
        watchlist.append(entry)

# 依 RR 排序
watchlist.sort(key=lambda w: -pool_rr.get(w['stock_id'], 0))
for i, w in enumerate(watchlist):
    w['priority'] = i + 1

# ── rules ──
rules = {
    'general': {
        'max_position_pct': 30,
        'max_single_pct': 30,
        'min_cash_reserve_pct': 20,
        'max_total_exposure_pct': 80,
        'mode_b_max_days': 5,
        'stop_loss_hard_pct': 5,
    }
}

# ── screening_summary ──
imm_cnt = len(pending_trades)
aft_cnt = len(watchlist)
screening_summary = {
    'date': PLAN_DATE,
    'total_stocks': 2003,
    'pass1_count': sp.get('total_candidates', 0),
    'candidates_after_rules': len(watchlist) + len(pending_trades),
    'note': (
        f'波段模式（mode=B）。'
        f'immediate×{imm_cnt}進pending_trades，afternoon_eval×{aft_cnt}進watchlist。'
        f'expiration每日重新判斷。'
    ),
}

# ── 組裝 ──
plan = {
    'date': PLAN_DATE,
    'generated_at': GENERATED_AT,
    'version': '2.2',
    'generator': 'Ivy (Hermes Agent)',
    'current_cash': CURRENT_CASH,
    'initial_capital': INITIAL_CAPITAL,
    'holdings': holdings,
    'watchlist': watchlist,
    'pending_trades': pending_trades,
    'rules': rules,
    'screening_summary': screening_summary,
}

# ── 寫入 ──
output_path = os.path.join(_BASE, 'daily_trade_plan.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(plan, f, ensure_ascii=False, indent=2)

print(f'✅ daily_trade_plan.json 已寫入')
print(f'   日期: {PLAN_DATE}')
print(f'   現金: NT${CURRENT_CASH:,}')
print(f'   持倉: {len(holdings)} 檔')
print(f'   pending_trades: {len(pending_trades)} 檔 (immediate)')
print(f'   watchlist: {len(watchlist)} 檔 (afternoon_eval)')

total_cost = sum(p['shares'] * p['limit_price'] for p in pending_trades)
for w in watchlist:
    total_cost += w['suggested']['shares'] * w['suggested']['limit_price']
print(f'   總成本: NT${total_cost:,.0f} (80%=NT${CURRENT_CASH*0.8:,.0f})')
