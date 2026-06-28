#!/usr/bin/env python3
"""Convert extracted weekly K-line data to AI-readable digital K-line JSON format."""

import json
import os

# Paths
INPUT_FILE = "/Users/zhengyulun/0_miles/G/Miles agent/data/tpex/output/6147_weekly.json"
OUTPUT_FILE = "/Users/zhengyulun/0_miles/G/Miles agent/data/tpex/output/6147_kline_digital.json"

def compute_body(open_price, close_price):
    """Body = close - open (positive = red/up, negative = green/down)."""
    return round(close_price - open_price, 2)

def compute_upper_shadow(high, open_price, close_price):
    """Upper shadow = high - max(open, close)."""
    return round(high - max(open_price, close_price), 2)

def compute_lower_shadow(open_price, close_price, low):
    """Lower shadow = min(open, close) - low."""
    return round(min(open_price, close_price) - low, 2)

def compute_direction(open_price, close_price):
    """Direction: 'up' if close >= open, else 'down'."""
    return "up" if close_price >= open_price else "down"

def compute_change_pct(current_close, prev_close):
    """Change percentage relative to previous bar's close."""
    if prev_close == 0:
        return None
    return round((current_close - prev_close) / prev_close * 100, 2)

def main():
    # Read source data
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        source = json.load(f)

    stock_id = source["stock"]["id"]
    stock_name = source["stock"]["name"]
    dates = source["date_range"]
    raw_bars = source["bars"]

    # Convert bars
    transformed_bars = []
    for i, bar in enumerate(raw_bars):
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        v = bar["volume"]

        entry = {
            "date": bar["date"],
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "body": compute_body(o, c),
            "upper_shadow": compute_upper_shadow(h, o, c),
            "lower_shadow": compute_lower_shadow(o, c, l),
            "direction": compute_direction(o, c),
        }

        # change_pct relative to previous close (skip first bar)
        if i > 0:
            prev_close = raw_bars[i - 1]["close"]
            entry["change_pct"] = compute_change_pct(c, prev_close)

        transformed_bars.append(entry)

    # Summary
    week_open = raw_bars[0]["open"]
    week_close = raw_bars[-1]["close"]
    week_high = max(b["high"] for b in raw_bars)
    week_low = min(b["low"] for b in raw_bars)
    week_change = round(week_close - week_open, 2)
    week_change_pct = round((week_close - week_open) / week_open * 100, 2) if week_open != 0 else None
    total_volume = sum(b["volume"] for b in raw_bars)
    avg_volume = round(total_volume / len(raw_bars))
    up_days = sum(1 for b in transformed_bars if b["direction"] == "up")
    down_days = sum(1 for b in transformed_bars if b["direction"] == "down")

    # Build output
    output = {
        "meta": {
            "stock_id": stock_id,
            "stock_name": stock_name,
            "period": "weekly",
            "date_range": f"{dates[0]} ~ {dates[-1]}",
            "total_bars": len(transformed_bars),
            "format_description": "AI-readable OHLCV K-line data with candlestick features"
        },
        "bars": transformed_bars,
        "summary": {
            "week_open": week_open,
            "week_close": week_close,
            "week_high": week_high,
            "week_low": week_low,
            "week_change": week_change,
            "week_change_pct": week_change_pct,
            "avg_volume": avg_volume,
            "up_days": up_days,
            "down_days": down_days
        }
    }

    # Write output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ Converted {len(transformed_bars)} bars")
    print(f"   Source: {INPUT_FILE}")
    print(f"   Output: {OUTPUT_FILE}")
    print(f"   Date range: {dates[0]} ~ {dates[-1]}")
    print(f"   Up days: {up_days}, Down days: {down_days}")
    print(f"   Week change: {week_change} ({week_change_pct}%)")

if __name__ == "__main__":
    main()
