#!/usr/bin/env python3
"""今日漲停結果的快速族群分析。

輸入：
- screen_today_limitup.py 產生的 candidates payload

輸出：
- 終端摘要
- JSON 檔：outputs/screen_today_limitup_sector_<latest_date>.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from analyze_012_sector_groups import INDUSTRY_NAME_MAP, THEME_RULES, SAFETY_MONITORING_EXCEPTIONS, build_industry_lookup
from screen_today_limitup import resolve_dates, screen as load_today_limitup_candidates

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_PREFIX = "screen_today_limitup_sector_"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="對今日漲停結果做快速族群分析")
    parser.add_argument("--date", "--latest-date", dest="latest_date", help="日期 YYYYMMDD")
    parser.add_argument("--no-save", action="store_true", help="只輸出到 stdout，不寫 JSON 檔")
    return parser.parse_args()


def classify_theme(code: str, industry_name: str) -> str:
    code = "".join(ch for ch in str(code).strip() if ch.isdigit())
    if code in SAFETY_MONITORING_EXCEPTIONS:
        return "安全監控"

    for theme_name, code_set in THEME_RULES:
        if code in code_set:
            return theme_name

    if industry_name in {"塑膠工業", "化學工業"}:
        return "塑化/化工"
    if industry_name == "汽車工業":
        return "汽車/車用"
    if industry_name == "電子零組件業":
        return "電子零組件"
    if industry_name == "光電業":
        return "光電"
    if industry_name == "通信網路業":
        return "網通"
    if industry_name == "建材營造":
        return "建材營造"
    if industry_name == "電機機械":
        return "電機機械"
    if industry_name == "電子通路業":
        return "電子通路"
    if industry_name == "資訊服務業":
        return "資訊服務"
    return industry_name


def build_payload(latest_date: str) -> dict[str, Any]:
    latest_date, prev_date = resolve_dates(latest_date)
    candidates = load_today_limitup_candidates(latest_date, prev_date)
    return {
        "strategy": "today_limit_up_volume_gt_2000",
        "latest_date": latest_date,
        "prev_date": prev_date,
        "count": len(candidates),
        "candidates": [candidate.__dict__ for candidate in candidates],
    }


def summarize_group(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda x: (-x["latest_volume_lots"], x["code"]))
    return {
        "count": len(items),
        "members": [f"{item['code']} {item['name']}" for item in sorted(items, key=lambda x: x["code"])],
        "avg_volume_lots": round(sum(item["latest_volume_lots"] for item in items) / len(items), 3),
        "top_volume_member": f"{sorted_items[0]['code']} {sorted_items[0]['name']}",
        "top_volume_lots": round(sorted_items[0]["latest_volume_lots"], 3),
    }


def analyze(payload: dict[str, Any], lookup: dict[tuple[str, str], dict[str, str]]) -> dict[str, Any]:
    annotated: list[dict[str, Any]] = []
    theme_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    singletons: list[dict[str, Any]] = []

    for item in payload["candidates"]:
        market = str(item["market"]).strip().lower()
        code = str(item["code"]).strip()
        lookup_row = lookup.get((market, code), {})
        industry_code = lookup_row.get("industry_code", "")
        industry_name = INDUSTRY_NAME_MAP.get(industry_code, f"未知({industry_code})" if industry_code else "未知")
        code_norm = "".join(ch for ch in code if ch.isdigit())
        if code_norm in SAFETY_MONITORING_EXCEPTIONS:
            industry_name = "安全監控"
        theme_name = classify_theme(code, industry_name)
        annotated_item = {
            **item,
            "industry_code": industry_code,
            "industry_name": industry_name,
            "theme_name": theme_name,
        }
        annotated.append(annotated_item)
        theme_groups[theme_name].append(annotated_item)

    theme_summary: list[dict[str, Any]] = []
    for theme_name, items in theme_groups.items():
        row = {"theme_name": theme_name, **summarize_group(items)}
        theme_summary.append(row)
        if len(items) == 1:
            singletons.append(items[0])

    theme_summary.sort(key=lambda x: (-x["count"], -x["avg_volume_lots"], x["theme_name"]))
    leading_themes = [row for row in theme_summary if row["count"] >= 2]
    first_tier = leading_themes[0] if leading_themes else None
    second_tier = leading_themes[1] if len(leading_themes) >= 2 else None
    top_volume = sorted(annotated, key=lambda x: (-x["latest_volume_lots"], x["code"]))[:8]

    return {
        "strategy": "today_limitup_quick_sector_analysis",
        "source_strategy": payload.get("strategy"),
        "latest_date": payload["latest_date"],
        "prev_date": payload.get("prev_date"),
        "count": payload.get("count", len(annotated)),
        "first_tier_theme": first_tier,
        "second_tier_theme": second_tier,
        "leading_themes": leading_themes,
        "theme_summary": theme_summary,
        "singleton_candidates": [
            {
                "code": item["code"],
                "name": item["name"],
                "theme_name": item["theme_name"],
                "industry_name": item["industry_name"],
                "latest_volume_lots": round(item["latest_volume_lots"], 3),
            }
            for item in sorted(singletons, key=lambda x: (-x["latest_volume_lots"], x["code"]))
        ],
        "top_volume": [
            {
                "code": item["code"],
                "name": item["name"],
                "theme_name": item["theme_name"],
                "industry_name": item["industry_name"],
                "latest_volume_lots": round(item["latest_volume_lots"], 3),
            }
            for item in top_volume
        ],
        "annotated_candidates": annotated,
    }


def write_output(latest_date: str, result: dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}{latest_date}.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def print_summary(result: dict[str, Any], output_path: Path | None) -> None:
    print("策略：今日漲停 快速族群分析")
    print(f"比較區間：{result.get('latest_date')}")
    print(f"參考前日：{result.get('prev_date')}")
    print(f"樣本數量：{result.get('count')}")
    print(f"輸出檔案：{output_path if output_path else 'DB cache only'}")
    print()

    first_tier = result.get("first_tier_theme")
    second_tier = result.get("second_tier_theme")

    if first_tier:
        print(
            f"第一梯隊：{first_tier['theme_name']} | {first_tier['count']} 檔 | "
            f"均成交量={first_tier['avg_volume_lots']:.2f}張 | 成員={', '.join(first_tier['members'])}"
        )
    else:
        print("第一梯隊：無明確成團族群（全部偏單兵）")

    if second_tier:
        print(
            f"次主軸：{second_tier['theme_name']} | {second_tier['count']} 檔 | "
            f"均成交量={second_tier['avg_volume_lots']:.2f}張 | 成員={', '.join(second_tier['members'])}"
        )

    print()
    print("族群分布：")
    for row in result["theme_summary"]:
        print(
            f"- {row['theme_name']}: {row['count']} 檔 | 均成交量={row['avg_volume_lots']:.2f}張 | "
            f"成員={', '.join(row['members'])}"
        )

    if result["singleton_candidates"]:
        print()
        print("單兵題材股：")
        for row in result["singleton_candidates"]:
            print(
                f"- {row['code']} {row['name']} | {row['theme_name']} / {row['industry_name']} | "
                f"成交量={row['latest_volume_lots']:.2f}張"
            )

    if result["top_volume"]:
        print()
        print("成交量前段班：")
        for row in result["top_volume"][:5]:
            print(
                f"- {row['code']} {row['name']} | {row['theme_name']} | 成交量={row['latest_volume_lots']:.2f}張"
            )


def main() -> None:
    args = parse_args()
    if not args.latest_date:
        raise SystemExit("請提供 --date YYYYMMDD")
    payload = build_payload(args.latest_date)
    lookup = build_industry_lookup()
    result = analyze(payload, lookup)
    output_path = None if args.no_save else write_output(str(payload["latest_date"]), result)
    print_summary(result, output_path)


if __name__ == "__main__":
    main()
