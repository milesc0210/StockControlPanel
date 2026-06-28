#!/usr/bin/env python3
"""0121 快速族群分析：對 012 均線多頭新成形結果做第一梯隊/成團方向分類。

輸入：
- outputs/screen_ma_alignment_turning_point_<latest_date>.json

輸出：
- 終端摘要
- JSON 檔：outputs/screen_ma_alignment_turning_point_sector_<latest_date>.json
"""

from __future__ import annotations

import argparse
import http.client
import json
import ssl
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

from screen_ma_alignment_turning_point import screen as load_012_candidates

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
INPUT_PREFIX = "screen_ma_alignment_turning_point_"
OUTPUT_PREFIX = "screen_ma_alignment_turning_point_sector_"
TWSE_API = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_API = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

INDUSTRY_NAME_MAP = {
    "01": "水泥工業",
    "02": "食品工業",
    "03": "塑膠工業",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙工業",
    "10": "鋼鐵工業",
    "11": "橡膠工業",
    "12": "汽車工業",
    "14": "建材營造",
    "15": "航運業",
    "16": "觀光餐旅",
    "17": "金融保險",
    "18": "貿易百貨",
    "20": "其他",
    "21": "化學工業",
    "22": "生技醫療",
    "24": "半導體業",
    "25": "電腦及週邊設備業",
    "26": "光電業",
    "27": "通信網路業",
    "28": "電子零組件業",
    "29": "電子通路業",
    "30": "資訊服務業",
    "31": "其他電子業",
    "32": "文化創意業",
    "33": "農業科技業",
    "34": "電子商務",
    "80": "管理股票",
}

THEME_RULES = [
    ("塑化", {"1304", "1305", "1308", "1310", "6505"}),
    ("汽車/車用", {"1563", "1568", "2201", "2206"}),
    ("電子零組件/連接器", {"3021", "6197"}),
    ("光電/面板/光通訊", {"2409", "3234"}),
    ("建材營造", {"1104", "2515"}),
    ("零售/通路", {"2912", "3114"}),
    ("重電/機電", {"1513"}),
    ("電子通路", {"3048"}),
    ("資訊服務/系統整合", {"3537"}),
    ("網通工程", {"6179"}),
    ("被動元件", {"6204"}),
    ("食品", {"1229"}),
    ("電腦週邊", {"3002"}),
    ("電線電纜", {"1612"}),
    ("化工", {"1708"}),
    ("光碟/儲存媒體", {"2323"}),
]

SAFETY_MONITORING_EXCEPTIONS = {
    # 主人指定：這批股票之後一律強制歸到「安全監控」群組
    "2390",  # 云辰
    "3128",  # 昇銳
    "3297",  # 杭特
    "3356",  # 奇偶
    "3434",  # 哲固
    "5251",  # 天鉞電
    "5484",  # 慧友
    "5489",  # 彩富
    "6419",  # 京晨科
    "6556",  # 勝品
    "6560",  # 欣普羅
    "8072",  # 陞泰
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="對 012 結果做快速族群分析，找出第一梯隊與成團主軸")
    parser.add_argument("--latest-date", help="012 結果日期 YYYYMMDD；不帶時自動抓 outputs 中最新檔")
    parser.add_argument("--input-json", help="指定 012 JSON 路徑，優先於 --latest-date")
    parser.add_argument("--no-save", action="store_true", help="只輸出到 stdout，不寫 JSON 檔")
    return parser.parse_args()


def resolve_input_path(latest_date: str | None, input_json: str | None) -> Path:
    if input_json:
        path = Path(input_json).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"找不到 input_json：{path}")
        return path

    if latest_date:
        path = OUTPUT_DIR / f"{INPUT_PREFIX}{latest_date}.json"
        if not path.exists():
            raise SystemExit(f"找不到 latest_date={latest_date} 對應的 012 輸出：{path}")
        return path

    candidates = sorted(OUTPUT_DIR.glob(f"{INPUT_PREFIX}*.json"))
    if not candidates:
        raise SystemExit("outputs 內找不到任何 012 輸出 JSON。")
    return candidates[-1]


def load_012_result(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "candidates" not in payload or "latest_date" not in payload:
        raise SystemExit(f"012 JSON 結構不符預期：{path}")
    return payload


def build_012_payload(latest_date: str) -> dict[str, Any]:
    prev_date, candidates = load_012_candidates(latest_date)
    return {
        "strategy": "ma5_gt_ma10_gt_ma20_newly_formed",
        "latest_date": latest_date,
        "prev_date": prev_date,
        "count": len(candidates),
        "candidates": [candidate.__dict__ for candidate in candidates],
    }


def fetch_json(url: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    contexts: list[ssl.SSLContext | None] = [None]

    insecure_ctx = ssl.create_default_context()
    insecure_ctx.check_hostname = False
    insecure_ctx.verify_mode = ssl.CERT_NONE
    contexts.append(insecure_ctx)

    last_error: Exception | None = None
    for context in contexts:
        for _ in range(3):
            try:
                with urllib.request.urlopen(request, timeout=90, context=context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except ssl.SSLCertVerificationError as exc:
                last_error = exc
                break
            except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead, json.JSONDecodeError) as exc:
                last_error = exc
                continue

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"抓取 JSON 失敗：{url}")


def build_industry_lookup() -> dict[tuple[str, str], dict[str, str]]:
    lookup: dict[tuple[str, str], dict[str, str]] = {}

    for row in fetch_json(TWSE_API):
        code = str(row.get("公司代號", "")).strip()
        if not code:
            continue
        lookup[("twse", code)] = {
            "industry_code": str(row.get("產業別", "")).strip(),
            "company_name": str(row.get("公司簡稱", "")).strip(),
        }

    for row in fetch_json(TPEX_API):
        code = str(row.get("SecuritiesCompanyCode", "")).strip()
        if not code:
            continue
        lookup[("tpex", code)] = {
            "industry_code": str(row.get("SecuritiesIndustryCode", "")).strip(),
            "company_name": str(row.get("CompanyAbbreviation", "")).strip(),
        }

    return lookup


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


def make_member_label(item: dict[str, Any]) -> str:
    return f"{item['code']} {item['name']}"


def summarize_group(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda x: (-x["volume_ratio_vs_prev"], x["code"]))
    return {
        "count": len(items),
        "members": [make_member_label(item) for item in sorted(items, key=lambda x: x["code"])],
        "avg_volume_ratio": round(sum(item["volume_ratio_vs_prev"] for item in items) / len(items), 4),
        "top_volume_ratio_member": make_member_label(sorted_items[0]),
        "top_volume_ratio": round(sorted_items[0]["volume_ratio_vs_prev"], 4),
    }


def analyze(payload: dict[str, Any], lookup: dict[tuple[str, str], dict[str, str]]) -> dict[str, Any]:
    annotated: list[dict[str, Any]] = []
    industry_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
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
        industry_groups[industry_name].append(annotated_item)
        theme_groups[theme_name].append(annotated_item)

    theme_summary = []
    for theme_name, items in theme_groups.items():
        row = {"theme_name": theme_name, **summarize_group(items)}
        theme_summary.append(row)
        if len(items) == 1:
            singletons.append(items[0])

    industry_summary = []
    for industry_name, items in industry_groups.items():
        industry_summary.append({"industry_name": industry_name, **summarize_group(items)})

    theme_summary.sort(key=lambda x: (-x["count"], -x["avg_volume_ratio"], x["theme_name"]))
    industry_summary.sort(key=lambda x: (-x["count"], -x["avg_volume_ratio"], x["industry_name"]))

    leading_tiers = [row for row in theme_summary if row["count"] >= 2]
    first_tier = leading_tiers[0] if leading_tiers else None
    second_tier = leading_tiers[1] if len(leading_tiers) >= 2 else None

    top_volume_ratio = sorted(
        annotated,
        key=lambda x: (-x["volume_ratio_vs_prev"], x["code"]),
    )[:8]

    result = {
        "strategy": "0121_quick_sector_analysis",
        "source_strategy": payload.get("strategy"),
        "latest_date": payload["latest_date"],
        "prev_date": payload.get("prev_date"),
        "count": payload.get("count", len(annotated)),
        "first_tier_theme": first_tier,
        "second_tier_theme": second_tier,
        "leading_themes": leading_tiers,
        "theme_summary": theme_summary,
        "industry_summary": industry_summary,
        "singleton_candidates": [
            {
                "code": item["code"],
                "name": item["name"],
                "theme_name": item["theme_name"],
                "industry_name": item["industry_name"],
                "volume_ratio_vs_prev": round(item["volume_ratio_vs_prev"], 4),
            }
            for item in sorted(singletons, key=lambda x: (-x["volume_ratio_vs_prev"], x["code"]))
        ],
        "top_volume_ratio": [
            {
                "code": item["code"],
                "name": item["name"],
                "theme_name": item["theme_name"],
                "industry_name": item["industry_name"],
                "volume_ratio_vs_prev": round(item["volume_ratio_vs_prev"], 4),
            }
            for item in top_volume_ratio
        ],
        "annotated_candidates": annotated,
    }
    return result


def write_output(latest_date: str, result: dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}{latest_date}.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def print_summary(result: dict[str, Any], output_path: Path | None) -> None:
    print("策略：0121 快速族群分析（012 均線多頭新成形）")
    print(f"比較區間：{result.get('prev_date')} → {result.get('latest_date')}")
    print(f"樣本數量：{result.get('count')}")
    print(f"輸出檔案：{output_path if output_path else 'DB cache only'}")
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
    for row in result["theme_summary"]:
        print(
            f"- {row['theme_name']}: {row['count']} 檔 | 均量比={row['avg_volume_ratio']:.2f} | "
            f"成員={', '.join(row['members'])}"
        )

    if result["singleton_candidates"]:
        print()
        print("單兵題材股：")
        for row in result["singleton_candidates"]:
            print(
                f"- {row['code']} {row['name']} | {row['theme_name']} / {row['industry_name']} | "
                f"量比={row['volume_ratio_vs_prev']:.2f}"
            )

    if result["top_volume_ratio"]:
        print()
        print("量比前段班：")
        for row in result["top_volume_ratio"][:5]:
            print(
                f"- {row['code']} {row['name']} | {row['theme_name']} | 量比={row['volume_ratio_vs_prev']:.2f}"
            )


def main() -> None:
    args = parse_args()
    if args.input_json:
        input_path = resolve_input_path(args.latest_date, args.input_json)
        payload = load_012_result(input_path)
    elif args.latest_date:
        payload = build_012_payload(args.latest_date)
    else:
        input_path = resolve_input_path(args.latest_date, args.input_json)
        payload = load_012_result(input_path)
    lookup = build_industry_lookup()
    result = analyze(payload, lookup)
    output_path = None if args.no_save else write_output(str(payload["latest_date"]), result)
    print_summary(result, output_path)


if __name__ == "__main__":
    main()
