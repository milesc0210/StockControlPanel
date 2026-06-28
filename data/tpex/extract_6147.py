#!/usr/bin/env python3
"""
Extract stock 6147 (頎邦) daily data from TPEX JSON files (20260518~20260522).
Output structured JSON to /Users/zhengyulun/0_miles/G/Miles agent/data/tpex/output/6147_weekly.json
"""

import json
import os
import re

def clean_number(val):
    """Remove commas and convert to int/float."""
    if isinstance(val, str):
        val = val.replace(",", "").strip()
        if "." in val:
            return float(val)
        return int(val) if val else 0
    return val

def parse_tpex_file(filepath):
    """Parse a TPEX JSON file, find stock 6147, return its data dict."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Get date from the JSON's date field (ROC calendar format: 115/05/18)
    raw_date = data.get("tables", [{}])[0].get("date", "")
    # Convert ROC date 115/05/18 -> 20260518
    parts = raw_date.split("/")
    if len(parts) == 3:
        roc_year = int(parts[0])
        greg_year = roc_year + 1911
        date_str = f"{greg_year}{parts[1]}{parts[2]}".replace(" ", "")
    else:
        # Fallback: extract from filename
        date_str = os.path.basename(filepath).replace(".json", "")
    
    table = data.get("tables", [{}])[0]
    fields = table.get("fields", [])
    rows = table.get("data", [])
    
    # Find 6147 row
    for row in rows:
        if row[0] == "6147":
            return {
                "date": date_str,
                "stock_id": row[0],
                "stock_name": row[1],
                "close": clean_number(row[2]),
                "change": clean_number(row[3]),
                "open": clean_number(row[4]),
                "high": clean_number(row[5]),
                "low": clean_number(row[6]),
                "volume": clean_number(row[7]),
                "amount": clean_number(row[8]),
            }
    
    return None

def main():
    base_dir = "/Users/zhengyulun/0_miles/G/Miles agent/data/tpex"
    dates = ["20260518", "20260519", "20260520", "20260521", "20260522"]
    
    bars = []
    stock_id = None
    stock_name = None
    
    for date_str in dates:
        filepath = os.path.join(base_dir, "2026", f"{date_str}.json")
        if not os.path.exists(filepath):
            print(f"WARNING: File not found: {filepath}")
            continue
        
        record = parse_tpex_file(filepath)
        if record is None:
            print(f"WARNING: Stock 6147 not found in {filepath}")
            continue
        
        stock_id = record["stock_id"]
        stock_name = record["stock_name"]
        
        bar = {
            "date": record["date"],
            "open": record["open"],
            "high": record["high"],
            "low": record["low"],
            "close": record["close"],
            "volume": record["volume"],
            "amount": record["amount"],
            "change": record["change"]
        }
        bars.append(bar)
        print(f"  {record['date']}: O={bar['open']} H={bar['high']} L={bar['low']} C={bar['close']} V={bar['volume']} Chg={bar['change']}")
    
    # Build output
    output = {
        "stock": {
            "id": stock_id or "6147",
            "name": stock_name or "頎邦"
        },
        "date_range": [b["date"] for b in bars],
        "bars": bars
    }
    
    # Ensure output directory exists
    output_dir = os.path.join(base_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, "6147_weekly.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Output written to: {output_path}")
    print(f"   Stock: {output['stock']['id']} {output['stock']['name']}")
    print(f"   Date range: {output['date_range'][0]} ~ {output['date_range'][-1]}")
    print(f"   Records: {len(output['bars'])}")
    
    # Validation
    assert len(bars) == 5, f"Expected 5 bars, got {len(bars)}"
    for bar in bars:
        assert "open" in bar, f"Missing open in {bar['date']}"
        assert "high" in bar, f"Missing high in {bar['date']}"
        assert "low" in bar, f"Missing low in {bar['date']}"
        assert "close" in bar, f"Missing close in {bar['date']}"
        assert "volume" in bar, f"Missing volume in {bar['date']}"
    print("✅ All 5 records validated: open/high/low/close/volume present")

if __name__ == "__main__":
    main()
