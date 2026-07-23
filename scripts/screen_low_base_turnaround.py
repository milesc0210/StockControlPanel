#!/usr/bin/env python3
"""市場相對型低基期＋轉機潛力選股。"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from statistics import median
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TWSE_DIR = PROJECT_ROOT / "data" / "twse" / "2026"
TPEX_DIR = PROJECT_ROOT / "data" / "tpex" / "2026"
THEME_CACHE_PATH = PROJECT_ROOT / "data" / "company_theme_cache.json"
THEME_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
EXCLUDE_PREFIXES = ("00", "06", "07", "02", "03", "08", "91", "92", "93")


def percentile_rank(values: list[float], value: float) -> float:
    if len(values) <= 1:
        return 50.0
    below = sum(1 for item in values if item < value)
    equal = sum(1 for item in values if item == value)
    return round((below + max(0, equal - 1) / 2) / (len(values) - 1) * 100, 2)


def compute_rank_score(
    market_percentile: float,
    sector_relative_return: float,
    rebound_5d: float,
    volume_ratio: float,
    above_ma20_pct: float,
) -> float:
    """市場相對低基期 40 分＋近期轉強 50 分。"""
    market_lag_score = max(0.0, min(30.0, (50.0 - market_percentile) / 50.0 * 30.0))
    sector_lag_score = max(0.0, min(10.0, -sector_relative_return / 20.0 * 10.0))
    rebound_score = max(0.0, min(20.0, rebound_5d / 8.0 * 20.0))
    volume_score = max(0.0, min(20.0, (volume_ratio - 1.0) / 1.5 * 20.0))
    ma_score = max(0.0, min(10.0, above_ma20_pct / 8.0 * 10.0))
    return round(market_lag_score + sector_lag_score + rebound_score + volume_score + ma_score, 2)


def screen_histories(histories: dict[str, list[dict[str, Any]]], target_date: str) -> dict[str, Any]:
    metrics: dict[str, dict[str, Any]] = {}
    for code, bars in histories.items():
        if len(bars) < 61:
            continue
        closes = [float(bar["close"]) for bar in bars]
        vols = [float(bar.get("vol", 0)) for bar in bars]
        if closes[-61] <= 0 or closes[-6] <= 0:
            continue
        return_60d = (closes[-1] / closes[-61] - 1) * 100
        environment_lookback = min(100, len(closes) - 1)
        environment_return = (closes[-1] / closes[-1 - environment_lookback] - 1) * 100
        rebound_5d = (closes[-1] / closes[-6] - 1) * 100
        ma5 = sum(closes[-5:]) / 5
        ma5_prev = sum(closes[-6:-1]) / 5
        ma20 = sum(closes[-20:]) / 20
        prior_volumes = vols[-23:-3]
        prior_volume = sum(prior_volumes) / len(prior_volumes) if prior_volumes else 0
        recent_volume = sum(vols[-3:]) / 3
        volume_ratio = recent_volume / prior_volume if prior_volume > 0 else 0
        latest = bars[-1]
        metrics[code] = {
            "code": code,
            "name": str(latest.get("name", "")),
            "market": str(latest.get("market", "")),
            "theme": str(latest.get("theme", "未分類") or "未分類"),
            "close": closes[-1],
            "volume": int(vols[-1]),
            "return_60d": return_60d,
            "environment_return": environment_return,
            "environment_lookback": environment_lookback,
            "rebound_5d": rebound_5d,
            "ma5": ma5,
            "ma5_prev": ma5_prev,
            "ma20": ma20,
            "above_ma20_pct": (closes[-1] / ma20 - 1) * 100 if ma20 > 0 else 0,
            "volume_ratio": volume_ratio,
        }

    market_returns = [item["return_60d"] for item in metrics.values()]
    environment_returns = [item["environment_return"] for item in metrics.values()]
    market_median = median(market_returns) if market_returns else 0.0
    environment_median = median(environment_returns) if environment_returns else 0.0
    theme_returns: dict[str, list[float]] = {}
    for item in metrics.values():
        theme_returns.setdefault(item["theme"], []).append(item["return_60d"])

    candidates: list[dict[str, Any]] = []
    for item in metrics.values():
        return_60d_percentile = percentile_rank(market_returns, item["return_60d"])
        environment_percentile = percentile_rank(environment_returns, item["environment_return"])
        market_percentile = round(return_60d_percentile * 0.7 + environment_percentile * 0.3, 2)
        group_values = theme_returns.get(item["theme"], [])
        group_median = median(group_values) if len(group_values) >= 3 else market_median
        sector_relative_return = item["return_60d"] - group_median
        score = compute_rank_score(
            market_percentile=market_percentile,
            sector_relative_return=sector_relative_return,
            rebound_5d=item["rebound_5d"],
            volume_ratio=item["volume_ratio"],
            above_ma20_pct=item["above_ma20_pct"],
        )
        if item["close"] < 10 or item["volume"] < 1000:
            continue
        if return_60d_percentile > 45 or environment_percentile > 65:
            continue
        if not 1.5 <= item["rebound_5d"] <= 12:
            continue
        if item["volume_ratio"] < 1.25:
            continue
        if not (item["close"] > item["ma5"] > item["ma20"]):
            continue
        if item["ma5"] <= item["ma5_prev"]:
            continue
        if not 0 < item["above_ma20_pct"] <= 15:
            continue
        if score < 40:
            continue
        candidates.append(
            {
                **item,
                "market_percentile": market_percentile,
                "return_60d_percentile": return_60d_percentile,
                "environment_percentile": environment_percentile,
                "environment_return": round(item["environment_return"], 2),
                "sector_relative_return": round(sector_relative_return, 2),
                "return_60d": round(item["return_60d"], 2),
                "rebound_5d": round(item["rebound_5d"], 2),
                "volume_ratio": round(item["volume_ratio"], 2),
                "above_ma20_pct": round(item["above_ma20_pct"], 2),
                "rank_score": score,
                "grade": "A" if score >= 70 else "B",
            }
        )

    candidates.sort(key=lambda item: (-item["rank_score"], item["market_percentile"], item["code"]))
    return {
        "strategy": "市場相對低基期 + 近期轉機",
        "target_date": target_date,
        "market_median_return_60d": round(market_median, 2),
        "market_environment_median_return": round(environment_median, 2),
        "environment_lookback_days": max((item["environment_lookback"] for item in metrics.values()), default=0),
        "universe_count": len(metrics),
        "candidates": candidates,
    }


def _number(value: Any) -> float:
    text = str(value).replace(",", "").strip()
    if text in {"", "--", "---"}:
        raise ValueError(text)
    return float(text)


def _valid_common_dates() -> list[str]:
    twse_dates = {path.stem for path in TWSE_DIR.glob("*.json")}
    tpex_dates = {path.stem for path in TPEX_DIR.glob("*.json")}
    return sorted(twse_dates & tpex_dates)


def build_theme_mapping(
    company_lookup: dict[tuple[str, str], dict[str, str]],
    industry_name_map: dict[str, str],
    classifier: Any,
) -> dict[tuple[str, str], str]:
    mapping: dict[tuple[str, str], str] = {}
    for (market, code), row in company_lookup.items():
        industry_code = str(row.get("industry_code", "")).strip()
        industry_name = industry_name_map.get(industry_code, "其他" if industry_code else "未分類")
        theme = str(classifier(str(code), industry_name) or industry_name).strip()
        mapping[(str(market).upper(), str(code))] = theme or "未分類"
    return mapping


def _load_theme_cache(allow_stale: bool = False) -> dict[tuple[str, str], str]:
    if not THEME_CACHE_PATH.exists():
        return {}
    if not allow_stale and time.time() - THEME_CACHE_PATH.stat().st_mtime > THEME_CACHE_MAX_AGE_SECONDS:
        return {}
    try:
        payload = json.loads(THEME_CACHE_PATH.read_text(encoding="utf-8"))
        return {
            tuple(key.split(":", 1)): str(value)
            for key, value in payload.get("mapping", {}).items()
            if ":" in key and value
        }
    except (OSError, ValueError, TypeError):
        return {}


def _save_theme_cache(mapping: dict[tuple[str, str], str]) -> None:
    THEME_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mapping": {f"{market}:{code}": theme for (market, code), theme in sorted(mapping.items())},
    }
    THEME_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _theme_map() -> dict[tuple[str, str], str]:
    cached = _load_theme_cache()
    if cached:
        return cached
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        from analyze_012_sector_groups import (
            INDUSTRY_NAME_MAP,
            THEME_RULES,
            build_industry_lookup,
            classify_theme,
        )
        mapping = build_theme_mapping(build_industry_lookup(), INDUSTRY_NAME_MAP, classify_theme)
        if mapping:
            _save_theme_cache(mapping)
            return mapping
    except Exception:
        stale = _load_theme_cache(allow_stale=True)
        if stale:
            return stale
        try:
            from analyze_012_sector_groups import THEME_RULES
        except Exception:
            return {}

    fallback: dict[tuple[str, str], str] = {}
    for theme, codes in THEME_RULES:
        for code in codes:
            fallback[("TWSE", str(code))] = str(theme)
            fallback[("TPEX", str(code))] = str(theme)
    return fallback


def load_snapshot(date_str: str) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    twse_path = TWSE_DIR / f"{date_str}.json"
    if twse_path.exists():
        payload = json.loads(twse_path.read_text(encoding="utf-8"))
        for row in payload.get("data", []):
            try:
                code = str(row[0]).strip()
                if not re.fullmatch(r"\d{4}", code) or code.startswith(EXCLUDE_PREFIXES):
                    continue
                snapshot[code] = {
                    "date": date_str,
                    "code": code,
                    "name": str(row[1]).strip(),
                    "market": "TWSE",
                    "close": _number(row[8]),
                    "vol": int(_number(row[2]) // 1000),
                }
            except (ValueError, IndexError, TypeError):
                continue

    tpex_path = TPEX_DIR / f"{date_str}.json"
    if tpex_path.exists():
        payload = json.loads(tpex_path.read_text(encoding="utf-8"))
        for table in payload.get("tables", []):
            for row in table.get("data", []):
                try:
                    code = str(row[0]).strip()
                    if not re.fullmatch(r"\d{4}", code) or code.startswith(EXCLUDE_PREFIXES):
                        continue
                    snapshot[code] = {
                        "date": date_str,
                        "code": code,
                        "name": str(row[1]).strip(),
                        "market": "TPEX",
                        "close": _number(row[2]),
                        "vol": int(_number(row[7]) // 1000),
                    }
                except (ValueError, IndexError, TypeError):
                    continue
    return snapshot


def load_histories(target_date: str) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    dates = _valid_common_dates()
    if target_date not in dates:
        raise RuntimeError(f"指定日期 {target_date} 不在可用交易日清單內。")
    target_index = dates.index(target_date)
    history_dates = dates[max(0, target_index - 105): target_index + 1]
    themes = _theme_map()
    histories: dict[str, list[dict[str, Any]]] = {}
    for date_str in history_dates:
        for code, bar in load_snapshot(date_str).items():
            bar["theme"] = themes.get((bar["market"], code), "未分類")
            histories.setdefault(code, []).append(bar)
    return histories, dates


def attach_future_days(payload: dict[str, Any], all_dates: list[str]) -> None:
    target_date = payload["target_date"]
    target_index = all_dates.index(target_date)
    future_dates = all_dates[target_index + 1: target_index + 6]
    snapshots = {date: load_snapshot(date) for date in future_dates}
    for item in payload["candidates"]:
        base_close = float(item["close"])
        prev_close = base_close
        future_days = []
        for date_str in future_dates:
            row = snapshots[date_str].get(item["code"])
            if not row:
                continue
            close = float(row["close"])
            future_days.append(
                {
                    "date": date_str,
                    "close": round(close, 2),
                    "pct_from_signal": round((close / base_close - 1) * 100, 2),
                    "pct_from_prev": round((close / prev_close - 1) * 100, 2),
                }
            )
            prev_close = close
        item["future_days"] = future_days


def _future_text(days: list[dict[str, Any]]) -> str:
    if not days:
        return "(無後續資料)"
    return ", ".join(
        f"{day['date']}:{day['close']:.2f}/{day['pct_from_signal']:+.2f}%/{day['pct_from_prev']:+.2f}%"
        for day in days
    )


def render_output(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates", [])
    lines = [
        "LOW-BASE-TURNAROUND",
        "策略：市場相對低基期 + 近期轉機（不使用一年低點）",
        f"交易日：{payload['target_date']}",
        f"市場60日中位數：{payload['market_median_return_60d']:.2f}%",
        f"評估母體：{payload['universe_count']} 檔",
        f"入選數量：{len(candidates)} 檔",
    ]
    for item in candidates:
        lines.append(
            f"{item['grade']} {item['market']} {item['code']} {item['name']} | "
            f"族群={item['theme']} C={item['close']:.2f} V={item['volume']}張 "
            f"60日={item['return_60d']:+.2f}% 市場百分位={item['market_percentile']:.2f} "
            f"族群差={item['sector_relative_return']:+.2f}% 5日轉強={item['rebound_5d']:.2f}% "
            f"量比={item['volume_ratio']:.2f} 分數={item['rank_score']:.2f} | "
            f"後5日={_future_text(item.get('future_days', []))}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="市場相對型低基期＋轉機選股")
    parser.add_argument("--date", default="")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    dates = _valid_common_dates()
    if not dates:
        raise RuntimeError("找不到可用交易日。")
    target_date = args.date or dates[-1]
    histories, all_dates = load_histories(target_date)
    payload = screen_histories(histories, target_date)
    attach_future_days(payload, all_dates)
    print(render_output(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
