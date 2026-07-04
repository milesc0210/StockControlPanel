from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TWSE_DIR = PROJECT_ROOT / "data" / "twse" / "2026"
TPEX_DIR = PROJECT_ROOT / "data" / "tpex" / "2026"
EXCLUDE_PREFIXES = ("00", "06", "07", "02", "03", "08", "91", "92", "93")


def clean_num(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "---", "----", "X", "除權息", "null"}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def valid_shared_dates():
    dates = sorted({p.stem for p in TWSE_DIR.glob("*.json")} & {p.stem for p in TPEX_DIR.glob("*.json")})
    return [d for d in dates if re.fullmatch(r"\d{8}", d)]


def load_market_bars(shared_dates):
    bars_by_date = {}
    series_by_code = defaultdict(list)

    for date_str in shared_dates:
        day = {}
        twse_payload = json.loads((TWSE_DIR / f"{date_str}.json").read_text(encoding="utf-8"))
        for row in twse_payload.get("data", []):
            try:
                code = str(row[0]).strip()
                if code.startswith(EXCLUDE_PREFIXES):
                    continue
                close = clean_num(row[8])
                if close is None or close <= 0:
                    continue
                rec = {
                    "date": date_str,
                    "code": code,
                    "name": str(row[1]).strip(),
                    "market": "TWSE",
                    "open": clean_num(row[5]),
                    "high": clean_num(row[6]),
                    "low": clean_num(row[7]),
                    "close": close,
                    "vol": int(str(row[2]).replace(",", "")) // 1000 if len(row) > 2 and row[2] else 0,
                }
                day[code] = rec
                series_by_code[code].append(rec)
            except Exception:
                continue

        tpex_payload = json.loads((TPEX_DIR / f"{date_str}.json").read_text(encoding="utf-8"))
        for table in tpex_payload.get("tables", []):
            for row in table.get("data", []):
                try:
                    code = str(row[0]).strip()
                    if code.startswith(EXCLUDE_PREFIXES):
                        continue
                    close = clean_num(row[2])
                    if close is None or close <= 0:
                        continue
                    rec = {
                        "date": date_str,
                        "code": code,
                        "name": str(row[1]).strip(),
                        "market": "TPEX",
                        "open": clean_num(row[4]),
                        "high": clean_num(row[5]),
                        "low": clean_num(row[6]),
                        "close": close,
                        "vol": int(str(row[7]).replace(",", "")) // 1000 if len(row) > 7 and row[7] else 0,
                    }
                    day[code] = rec
                    series_by_code[code].append(rec)
                except Exception:
                    continue

        bars_by_date[date_str] = day

    return bars_by_date, series_by_code


def build_prev40_high_cache(series_by_code):
    cache = {}
    for code, rows in series_by_code.items():
        highs = [row.get("high") for row in rows]
        dates = [row.get("date") for row in rows]
        for index, date_str in enumerate(dates):
            start = max(0, index - 40)
            window = [value for value in highs[start:index] if value is not None]
            if window:
                cache[(code, date_str)] = max(window)
    return cache


def rank_score(grade, dist_ma5, pct, vol_ratio, up_days):
    grade_num = 2 if grade == "A" else 1 if grade == "B" else 0
    score = 0.0
    score += 2.0 * grade_num
    score += 0.6 * min(dist_ma5, 10)
    score += 0.2 * pct
    if dist_ma5 >= 6:
        score += 2.0
    elif dist_ma5 >= 4:
        score += 1.0
    if 2.5 <= pct <= 5.0:
        score += 1.2
    elif 5.0 < pct <= 7.0:
        score += 0.6
    if vol_ratio >= 1.2:
        score += 0.8
    if up_days == 3:
        score += 0.5
    elif up_days >= 4:
        score -= 0.5
    return round(score, 2)


def select_candidates(signal_date, relaxed, shared_dates, idx_of, series_by_code, prev40_high_cache):
    signal_index = idx_of[signal_date]
    if signal_index < 11:
        return []

    range_max = 25 if relaxed else 10
    up_days_max = 4 if relaxed else 3
    expected_dates = shared_dates[signal_index - 11 : signal_index + 1]
    candidates = []

    for code, rows in series_by_code.items():
        pos = None
        for row_index in range(len(rows) - 1, -1, -1):
            row_date = rows[row_index].get("date")
            if row_date == signal_date:
                pos = row_index
                break
            if row_date < signal_date:
                break
        if pos is None:
            continue

        window = rows[max(0, pos - 11) : pos + 1]
        if len(window) < 12 or [item.get("date") for item in window] != expected_dates:
            continue

        latest = window[-1]
        close = latest["close"]
        vol = latest["vol"]
        if close < 10 or vol < 1000:
            continue

        closes = [item["close"] for item in window]
        vols = [item["vol"] for item in window]
        ma5_today = sum(closes[-6:-1]) / 5
        ma5_prev = sum(closes[-7:-2]) / 5
        ma10_today = sum(closes[-11:-1]) / 10
        if ma5_today <= ma10_today or ma5_today <= ma5_prev or close <= ma5_today:
            continue

        prev_close = window[-2]["close"]
        pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0
        if abs(pct) >= 7:
            continue
        if abs(pct) >= 4:
            high_40 = prev40_high_cache.get((code, signal_date))
            if high_40 is None or close >= high_40:
                continue

        prices_10 = [item["close"] for item in window[-11:-1]]
        low_10 = min(prices_10)
        high_10 = max(prices_10)
        range_pct = (high_10 - low_10) / low_10 * 100 if low_10 > 0 else 0
        if range_pct >= range_max:
            continue

        up_days = sum(
            1
            for item_index in range(max(0, len(window) - 8), len(window) - 1)
            if window[item_index]["close"] > window[item_index - 1]["close"]
        )
        if up_days > up_days_max:
            continue

        avg_vol_10 = sum(vols[-11:-1]) / 10 if len(vols) >= 11 else 0
        vol_ratio = vol / avg_vol_10 if avg_vol_10 > 0 else 0
        dist_ma5 = (close - ma5_today) / ma5_today * 100
        grade = "A" if dist_ma5 >= 3 else "B" if dist_ma5 >= 1 else "C"
        if grade != "A":
            continue

        candidates.append(
            {
                "code": code,
                "name": latest["name"],
                "market": latest["market"],
                "signal_close": round(close, 2),
                "rank_score": rank_score(grade, dist_ma5, pct, vol_ratio, up_days),
            }
        )

    candidates.sort(key=lambda item: (-item["rank_score"], item["code"]))
    return candidates


def run_backtest(args):
    shared_dates = valid_shared_dates()
    if not shared_dates:
        raise RuntimeError("找不到可用的共同交易日資料。")
    idx_of = {date_str: index for index, date_str in enumerate(shared_dates)}

    if args.start_date not in idx_of or args.end_date not in idx_of:
        raise RuntimeError("起訖日期不在可用交易日清單內。")
    if args.start_date > args.end_date:
        raise RuntimeError("開始日期不可晚於結束日期。")

    relaxed = args.function_key == "pre_breakout_standard"
    bars_by_date, series_by_code = load_market_bars(shared_dates)
    prev40_high_cache = build_prev40_high_cache(series_by_code)
    signal_dates = [date_str for date_str in shared_dates if args.start_date <= date_str <= args.end_date]

    trades = []
    skipped = []
    selection_days = []
    tp_mul = 1 + args.take_profit_pct / 100.0
    sl_mul = 1 - args.stop_loss_pct / 100.0
    entry_band = args.entry_band_pct / 100.0

    for signal_date in signal_dates:
        signal_index = idx_of[signal_date]
        if signal_index + 1 >= len(shared_dates):
            continue
        candidates = select_candidates(signal_date, relaxed, shared_dates, idx_of, series_by_code, prev40_high_cache)
        selection_days.append({"signal_date": signal_date, "candidate_count": len(candidates)})

        entry_date = shared_dates[signal_index + 1]
        for candidate in candidates:
            code = candidate["code"]
            signal_bar = bars_by_date.get(signal_date, {}).get(code)
            entry_bar = bars_by_date.get(entry_date, {}).get(code)
            if not signal_bar or not entry_bar:
                skipped.append({"reason": "missing_bar", "signal_date": signal_date, "code": code})
                continue

            signal_close = float(signal_bar["close"])
            entry_close = float(entry_bar["close"])
            entry_gap_pct = (entry_close / signal_close - 1) * 100
            if abs(entry_gap_pct / 100.0) > entry_band:
                skipped.append({"reason": "entry_out_of_band", "signal_date": signal_date, "code": code})
                continue

            tp_price = entry_close * tp_mul
            sl_price = entry_close * sl_mul
            future_dates = shared_dates[signal_index + 2 : signal_index + 2 + args.max_hold_days]
            exit_date = entry_date
            exit_price = entry_close
            exit_reason = "no_future_bar"
            days_held = 0

            for hold_index, future_date in enumerate(future_dates, start=1):
                future_bar = bars_by_date.get(future_date, {}).get(code)
                if not future_bar:
                    continue
                days_held = hold_index
                open_price = future_bar.get("open")
                high_price = future_bar.get("high")
                low_price = future_bar.get("low")
                close_price = future_bar.get("close")

                if open_price is not None and open_price <= sl_price:
                    exit_date, exit_price, exit_reason = future_date, float(open_price), "gap_stop"
                    break
                if open_price is not None and open_price >= tp_price:
                    exit_date, exit_price, exit_reason = future_date, float(open_price), "gap_tp"
                    break
                hit_stop = low_price is not None and low_price <= sl_price
                hit_take = high_price is not None and high_price >= tp_price
                if hit_stop and hit_take:
                    exit_date, exit_price, exit_reason = future_date, sl_price, "both_hit_stop_first"
                    break
                if hit_stop:
                    exit_date, exit_price, exit_reason = future_date, sl_price, "stop"
                    break
                if hit_take:
                    exit_date, exit_price, exit_reason = future_date, tp_price, "tp"
                    break
                exit_date, exit_price, exit_reason = future_date, float(close_price), "time_exit"

            pnl = (exit_price - entry_close) * args.shares
            ret_pct = (exit_price / entry_close - 1) * 100
            trades.append(
                {
                    "signal_date": signal_date,
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                    "code": code,
                    "name": candidate["name"],
                    "market": candidate["market"],
                    "signal_close": round(signal_close, 2),
                    "entry_close": round(entry_close, 2),
                    "exit_price": round(exit_price, 2),
                    "entry_gap_pct": round(entry_gap_pct, 3),
                    "ret_pct": round(ret_pct, 3),
                    "pnl": round(pnl, 2),
                    "days_held": days_held,
                    "exit_reason": exit_reason,
                    "cost": round(entry_close * args.shares, 2),
                }
            )

    wins = sum(1 for trade in trades if trade["pnl"] > 0)
    losses = sum(1 for trade in trades if trade["pnl"] < 0)
    flats = len(trades) - wins - losses
    net_pnl = round(sum(trade["pnl"] for trade in trades), 2)
    total_cost = round(sum(trade["cost"] for trade in trades), 2)
    aggregate_roi_pct = round((net_pnl / total_cost) * 100, 3) if total_cost else 0.0
    gross_profit = sum(trade["pnl"] for trade in trades if trade["pnl"] > 0)
    gross_loss = -sum(trade["pnl"] for trade in trades if trade["pnl"] < 0)
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss else None

    realized_curve = 0.0
    realized_peak = 0.0
    max_drawdown = 0.0
    for trade in sorted(trades, key=lambda item: (item["exit_date"], item["entry_date"], item["code"])):
        realized_curve += trade["pnl"]
        realized_peak = max(realized_peak, realized_curve)
        max_drawdown = min(max_drawdown, realized_curve - realized_peak)

    monthly = {}
    for trade in trades:
        month_key = trade["entry_date"][:6]
        bucket = monthly.setdefault(month_key, {"trades": 0, "pnl": 0.0, "cost": 0.0, "wins": 0})
        bucket["trades"] += 1
        bucket["pnl"] += trade["pnl"]
        bucket["cost"] += trade["cost"]
        if trade["pnl"] > 0:
            bucket["wins"] += 1

    monthly_rows = []
    for month_key in sorted(monthly.keys()):
        bucket = monthly[month_key]
        monthly_rows.append(
            {
                "month": month_key,
                "trades": bucket["trades"],
                "net_pnl": round(bucket["pnl"], 2),
                "roi_pct": round((bucket["pnl"] / bucket["cost"]) * 100, 3) if bucket["cost"] else 0.0,
                "win_rate_pct": round((bucket["wins"] / bucket["trades"]) * 100, 2) if bucket["trades"] else 0.0,
            }
        )

    active_capital_by_day = {}
    for trade in trades:
        for date_str in shared_dates:
            if trade["entry_date"] <= date_str <= trade["exit_date"]:
                active_capital_by_day[date_str] = active_capital_by_day.get(date_str, 0.0) + trade["cost"]
    peak_day = max(active_capital_by_day, key=active_capital_by_day.get) if active_capital_by_day else None
    peak_capital = round(active_capital_by_day.get(peak_day, 0.0), 2) if peak_day else 0.0

    return {
        "ok": True,
        "function_key": args.function_key,
        "function_name": "標準選股" if args.function_key == "pre_breakout_standard" else "保守選股",
        "params": {
            "start_date": args.start_date,
            "end_date": args.end_date,
            "take_profit_pct": args.take_profit_pct,
            "stop_loss_pct": args.stop_loss_pct,
            "entry_band_pct": args.entry_band_pct,
            "max_hold_days": args.max_hold_days,
            "shares": args.shares,
            "entry_rule": "隔日收盤、相對訊號日收盤在 ±範圍內才買進",
            "same_day_rule": "同日若停利停損都觸發，先算停損",
            "position_size_label": f"{args.shares} 股",
        },
        "summary": {
            "latest_market_date": shared_dates[-1],
            "selection_days": len(selection_days),
            "selection_total_candidates": sum(row["candidate_count"] for row in selection_days),
            "trade_count": len(trades),
            "skip_count": len(skipped),
            "win": wins,
            "loss": losses,
            "flat": flats,
            "win_rate_pct": round((wins / len(trades)) * 100, 3) if trades else 0.0,
            "net_pnl_ntd": net_pnl,
            "total_deployed_ntd": total_cost,
            "aggregate_roi_pct": aggregate_roi_pct,
            "avg_pnl_ntd": round(net_pnl / len(trades), 2) if trades else 0.0,
            "avg_holding_days": round(sum(trade["days_held"] for trade in trades) / len(trades), 3) if trades else 0.0,
            "profit_factor": profit_factor,
            "max_drawdown_ntd": round(max_drawdown, 2),
            "peak_concurrent_capital_ntd": peak_capital,
            "peak_concurrent_capital_day": peak_day,
        },
        "monthly": monthly_rows,
        "selection_days_top10": sorted(selection_days, key=lambda item: item["candidate_count"], reverse=True)[:10],
        "exit_reason_counts": {key: sum(1 for trade in trades if trade["exit_reason"] == key) for key in sorted({trade["exit_reason"] for trade in trades})},
        "skip_reason_counts": {key: sum(1 for item in skipped if item["reason"] == key) for key in sorted({item["reason"] for item in skipped})},
        "best_trades": sorted(trades, key=lambda item: item["pnl"], reverse=True)[:10],
        "worst_trades": sorted(trades, key=lambda item: item["pnl"])[:10],
    }


def main():
    parser = argparse.ArgumentParser(description="Pre-breakout backtest")
    parser.add_argument("--function-key", required=True, choices=["pre_breakout_standard", "pre_breakout_conservative"])
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--take-profit-pct", type=float, default=10.0)
    parser.add_argument("--stop-loss-pct", type=float, default=5.0)
    parser.add_argument("--entry-band-pct", type=float, default=3.0)
    parser.add_argument("--max-hold-days", type=int, default=5)
    parser.add_argument("--shares", type=int, default=1000)
    args = parser.parse_args()

    result = run_backtest(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
