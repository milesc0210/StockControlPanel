#!/usr/bin/env python3
"""標準選股快速族群分析：沿用 012 手動族群規則，輸出前端可解析的摘要。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from analyze_012_sector_groups import analyze, build_industry_lookup
from pre_breakout_screen import compute_40d_highs, get_latest_date, load_data, screen


BASE_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="對標準選股結果做快速族群分析")
    parser.add_argument("--date", help="交易日 YYYYMMDD；不帶時自動使用最新交易日")
    parser.add_argument("--relaxed", action="store_true", help="使用標準選股的放寬篩選模式")
    parser.add_argument("--no-save", action="store_true", help="僅輸出到 stdout，不寫入檔案")
    return parser.parse_args()


def build_payload(target_date: str, relaxed: bool) -> dict[str, Any]:
    hist = load_data(target_date, relaxed=relaxed)
    if hist is None:
        raise SystemExit(f"找不到 {target_date} 的市場資料")
    candidates = screen(
        hist,
        target_date,
        relaxed=relaxed,
        highs_40d=compute_40d_highs(target_date),
    )
    return {
        "strategy": "pre_breakout_standard",
        "latest_date": target_date,
        "count": len(candidates),
        "candidates": [
            {
                "code": item["code"],
                "name": item["name"],
                "market": item["market"],
                "volume_ratio_vs_prev": float(item.get("vol_ratio", 0) or 0),
            }
            for item in candidates
        ],
    }


def print_summary(result: dict[str, Any]) -> None:
    print("策略：標準選股 快速族群分析")
    print(f"比較區間：標準選股 → {result.get('latest_date')}")
    print(f"樣本數量：{result.get('count', 0)}")
    print()

    first_tier = result.get("first_tier_theme")
    second_tier = result.get("second_tier_theme")
    if first_tier:
        print(
            f"第一梯隊：{first_tier['theme_name']} | {first_tier['count']} 檔 | "
            f"均量比={first_tier['avg_volume_ratio']:.2f} | 成員={', '.join(first_tier['members'])}"
        )
    else:
        print("第一梯隊：無明確成團族群（全部偏單兵）")

    if second_tier:
        print(
            f"次主軸：{second_tier['theme_name']} | {second_tier['count']} 檔 | "
            f"均量比={second_tier['avg_volume_ratio']:.2f} | 成員={', '.join(second_tier['members'])}"
        )

    print()
    print("族群分布：")
    for row in result.get("theme_summary", []):
        print(
            f"- {row['theme_name']}: {row['count']} 檔 | 均量比={row['avg_volume_ratio']:.2f} | "
            f"成員={', '.join(row['members'])}"
        )

    singletons = result.get("singleton_candidates", [])
    if singletons:
        print()
        print("單兵題材股：")
        for row in singletons:
            print(
                f"- {row['code']} {row['name']} | {row['theme_name']} / {row['industry_name']} | "
                f"量比={row['volume_ratio_vs_prev']:.2f}"
            )


def main() -> None:
    args = parse_args()
    target_date = args.date or get_latest_date()
    if not target_date:
        raise SystemExit("找不到可用交易日")
    payload = build_payload(target_date, relaxed=args.relaxed)
    result = analyze(payload, build_industry_lookup())
    print_summary(result)


if __name__ == "__main__":
    main()
