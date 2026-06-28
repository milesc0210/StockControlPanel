#!/usr/bin/env python3
"""
validate_expiration.py — daily_trade_plan.json expiration 規則驗證（2026-06-03 新增）

規則：
- 統一 = date + 5 天（波段持有 5 天）
- 禁止當沖 (expiration == date)
- 禁止隔日沖 (expiration == date + 1)

使用：
  python3 validate_expiration.py [plan_path]
  python3 validate_expiration.py /path/to/daily_trade_plan.json

退出碼：
  0 = 通過
  1 = 有錯誤（plan 不可寫入）
"""
import json
import sys
from datetime import date, timedelta


def validate_expiration(plan_path: str) -> bool:
    d = json.load(open(plan_path, encoding='utf-8'))
    plan_date = date.fromisoformat(d['date'])
    expected = plan_date + timedelta(days=5)

    issues = []

    # pending_trades
    for pt in d.get('pending_trades', []):
        exp_str = pt.get('expiration', '')
        if not exp_str:
            continue
        exp = date.fromisoformat(exp_str)
        et = pt.get('execute_type', '')
        sid = pt.get('stock_id', '?')
        if exp <= plan_date:
            issues.append(f"❌ pending_trades {sid} ({et}) expiration={exp_str} 當沖（<= plan_date={plan_date.isoformat()}）")
        elif exp == plan_date + timedelta(days=1):
            issues.append(f"❌ pending_trades {sid} ({et}) expiration={exp_str} 隔日沖（= plan_date + 1）")
        elif exp != expected:
            issues.append(f"⚠️  pending_trades {sid} ({et}) expiration={exp_str}，建議統一為 {expected.isoformat()}（plan_date + 5 天）")

    # holdings
    for h in d.get('holdings', []):
        exp_str = h.get('expiration', '')
        if not exp_str:
            continue
        exp = date.fromisoformat(exp_str)
        sid = h.get('stock_id', '?')
        if exp <= plan_date:
            issues.append(f"❌ holdings {sid} expiration={exp_str} 當沖（<= plan_date）")
        elif exp == plan_date + timedelta(days=1):
            issues.append(f"❌ holdings {sid} expiration={exp_str} 隔日沖（= plan_date + 1）")

    # watchlist — 不該有 expiration 欄位（Bot 不讀，且可能觸發到期邏輯）
    for w in d.get('watchlist', []):
        if 'expiration' in w:
            sid = w.get('stock_id', '?')
            exp_str = w['expiration']
            issues.append(f"❌ watchlist {sid} 不可有 expiration 欄位（{exp_str}）。watchlist 不需要 expiration，Bot 會誤讀導致當沖賣出")

    if issues:
        for iss in issues:
            print(iss)
        print(f"\n❌ 驗證失敗！請修正 expiration 後重新產出。預期值：{expected.isoformat()}（plan_date + 5 天）")
        return False

    print(f"✅ expiration 驗證通過：所有交易 expiration = {expected.isoformat()}（plan_date + 5 天）")
    return True


if __name__ == '__main__':
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_path = os.path.join(_base, 'daily_trade_plan.json')
    path = sys.argv[1] if len(sys.argv) > 1 else default_path
    ok = validate_expiration(path)
    sys.exit(0 if ok else 1)
