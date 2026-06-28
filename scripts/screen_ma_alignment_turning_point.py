#!/usr/bin/env python3
"""012 選股：最近一個交易日剛達成 MA5 > MA10 > MA20，且前一交易日尚未達成。

使用本地 data/twse/2026 與 data/tpex/2026 的日資料，不手動推估。

輸出：
- 終端摘要
- JSON 檔：outputs/screen_ma_alignment_turning_point_<latest_date>.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
TWSE_DIR = DATA_DIR / "twse" / "2026"
TPEX_DIR = DATA_DIR / "tpex" / "2026"
MIN_REQUIRED_DATES = 21
MIN_VOLUME_LOTS = 1000
MIN_VOLUME_RATIO = 1.3
EPS = 1e-9


@dataclass
class DailyBar:
    market: str
    code: str
    name: str
    date: str
    close: float
    volume_shares: int


@dataclass
class Candidate:
    market: str
    code: str
    name: str
    latest_date: str
    prev_date: str
    latest_close: float
    latest_volume_shares: int
    latest_volume_lots: float
    prev_volume_shares: int
    prev_volume_lots: float
    volume_ratio_vs_prev: float
    ma5_latest: float
    ma10_latest: float
    ma20_latest: float
    ma5_prev: float
    ma10_prev: float
    ma20_prev: float
    future_days: list[dict[str, object]]


def parse_num(value: object) -> float | None:
    text = str(value).strip().replace(",", "")
    text = text.replace("--", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: object) -> int:
    num = parse_num(value)
    if num is None:
        return 0
    return int(num)


def normalize_field_name(name: str) -> str:
    text = re.sub(r"<br.*?>", "", str(name))
    return text.replace(" ", "").strip()


def average(values: list[float]) -> float:
    return sum(values) / len(values)


def is_bullish_alignment(ma5: float, ma10: float, ma20: float) -> bool:
    return (ma5 - ma10) > EPS and (ma10 - ma20) > EPS


def is_valid_twse_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    fields = [normalize_field_name(x) for x in payload.get("fields", [])]
    required = {"證券代號", "證券名稱", "成交股數", "收盤價"}
    return required.issubset(set(fields)) and bool(payload.get("data"))


def is_valid_tpex_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    tables = payload.get("tables", [])
    if not tables:
        return False
    table = tables[0]
    fields = [normalize_field_name(x) for x in table.get("fields", [])]
    required = {"代號", "名稱", "成交股數", "收盤"}
    return required.issubset(set(fields)) and bool(table.get("data"))


def available_dates() -> list[str]:
    twse_dates = {p.stem for p in TWSE_DIR.glob("2026*.json") if p.is_file() and is_valid_twse_file(p)}
    tpex_dates = {p.stem for p in TPEX_DIR.glob("2026*.json") if p.is_file() and is_valid_tpex_file(p)}
    return sorted(twse_dates & tpex_dates)


def resolve_dates(latest_date: str | None) -> tuple[str, str]:
    dates = available_dates()
    if len(dates) < MIN_REQUIRED_DATES:
        raise SystemExit(f"可用共同交易日不足 {MIN_REQUIRED_DATES} 天，無法計算前一日 MA20。")

    if latest_date is None:
        latest_date = dates[-1]
    if latest_date not in dates:
        raise SystemExit(f"找不到 latest_date={latest_date} 的 TWSE/TPEX 共同資料。")

    latest_idx = dates.index(latest_date)
    if latest_idx < 20:
        raise SystemExit(
            f"latest_date={latest_date} 之前不足 20 個交易日，無法同時比較最新日與前一日的 MA20。"
        )

    return latest_date, dates[latest_idx - 1]


def resolve_future_dates(latest_date: str, lookahead: int = 5) -> list[str]:
    dates = available_dates()
    if latest_date not in dates:
        return []
    latest_idx = dates.index(latest_date)
    return dates[latest_idx + 1: latest_idx + 1 + lookahead]


def load_twse(date_str: str) -> dict[str, DailyBar]:
    path = TWSE_DIR / f"{date_str}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = [normalize_field_name(x) for x in payload.get("fields", [])]

    def idx(field: str) -> int:
        return fields.index(field)

    code_i = idx("證券代號")
    name_i = idx("證券名稱")
    close_i = idx("收盤價")
    volume_i = idx("成交股數")

    items: dict[str, DailyBar] = {}
    for row in payload.get("data", []):
        if not isinstance(row, list):
            continue
        close_price = parse_num(row[close_i])
        if close_price is None:
            continue

        code = str(row[code_i]).strip()
        items[code] = DailyBar(
            market="twse",
            code=code,
            name=str(row[name_i]).strip(),
            date=date_str,
            close=close_price,
            volume_shares=parse_int(row[volume_i]),
        )
    return items


def load_tpex(date_str: str) -> dict[str, DailyBar]:
    path = TPEX_DIR / f"{date_str}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    tables = payload.get("tables", [])
    if not tables:
        return {}

    table = tables[0]
    fields = [normalize_field_name(x) for x in table.get("fields", [])]

    def idx(field: str) -> int:
        return fields.index(field)

    code_i = idx("代號")
    name_i = idx("名稱")
    close_i = idx("收盤")
    volume_i = idx("成交股數")

    items: dict[str, DailyBar] = {}
    for row in table.get("data", []):
        if not isinstance(row, list):
            continue
        close_price = parse_num(row[close_i])
        if close_price is None:
            continue

        code = str(row[code_i]).strip()
        items[code] = DailyBar(
            market="tpex",
            code=code,
            name=str(row[name_i]).strip(),
            date=date_str,
            close=close_price,
            volume_shares=parse_int(row[volume_i]),
        )
    return items


def load_market(date_str: str) -> dict[str, DailyBar]:
    merged: dict[str, DailyBar] = {}
    merged.update(load_twse(date_str))
    merged.update(load_tpex(date_str))
    return merged


def build_daily_maps(dates: list[str]) -> dict[str, dict[str, DailyBar]]:
    return {date_str: load_market(date_str) for date_str in dates}


def build_future_days(
    code: str,
    base_close: float,
    future_dates: list[str],
    future_maps: dict[str, dict[str, DailyBar]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for future_date in future_dates:
        future_bar = future_maps.get(future_date, {}).get(code)
        if future_bar is None:
            continue
        pct_from_signal = ((future_bar.close - base_close) / base_close) * 100 if abs(base_close) > EPS else None
        prev_close = base_close if not rows else rows[-1]["close"]
        pct_from_prev = ((future_bar.close - prev_close) / prev_close) * 100 if abs(prev_close) > EPS else None
        rows.append(
            {
                "date": future_date,
                "close": round(future_bar.close, 4),
                "pct_from_signal": round(pct_from_signal, 2) if pct_from_signal is not None else None,
                "pct_from_prev": round(pct_from_prev, 2) if pct_from_prev is not None else None,
            }
        )
    return rows


def screen(latest_date: str) -> tuple[str, list[Candidate]]:
    dates = available_dates()
    latest_idx = dates.index(latest_date)
    prev_date = dates[latest_idx - 1]
    relevant_dates = dates[: latest_idx + 1]
    daily_maps = build_daily_maps(relevant_dates)
    future_dates = resolve_future_dates(latest_date, lookahead=5)
    future_maps: dict[str, dict[str, DailyBar]] = {}
    for future_date in future_dates:
        try:
            future_maps[future_date] = load_market(future_date)
        except Exception:
            continue

    all_codes: set[str] = set()
    for daily_map in daily_maps.values():
        all_codes.update(daily_map.keys())

    latest_dates_for_ma20 = relevant_dates[-20:]
    prev_dates_for_ma20 = relevant_dates[-21:-1]

    candidates: list[Candidate] = []
    for code in sorted(all_codes):
        latest_window = []
        prev_window = []

        for date_str in latest_dates_for_ma20:
            bar = daily_maps[date_str].get(code)
            if bar is None:
                latest_window = []
                break
            latest_window.append(bar)

        for date_str in prev_dates_for_ma20:
            bar = daily_maps[date_str].get(code)
            if bar is None:
                prev_window = []
                break
            prev_window.append(bar)

        if len(latest_window) != 20 or len(prev_window) != 20:
            continue

        latest_bar = latest_window[-1]
        prev_bar = prev_window[-1]
        latest_closes = [bar.close for bar in latest_window]
        prev_closes = [bar.close for bar in prev_window]

        ma5_latest = average(latest_closes[-5:])
        ma10_latest = average(latest_closes[-10:])
        ma20_latest = average(latest_closes)

        ma5_prev = average(prev_closes[-5:])
        ma10_prev = average(prev_closes[-10:])
        ma20_prev = average(prev_closes)

        latest_ok = is_bullish_alignment(ma5_latest, ma10_latest, ma20_latest)
        prev_ok = is_bullish_alignment(ma5_prev, ma10_prev, ma20_prev)
        latest_volume_lots = latest_bar.volume_shares / 1000.0
        prev_volume_lots = prev_bar.volume_shares / 1000.0
        volume_ratio_vs_prev = (
            latest_bar.volume_shares / prev_bar.volume_shares if prev_bar.volume_shares > 0 else 0.0
        )

        if (
            not latest_ok
            or prev_ok
            or latest_volume_lots < MIN_VOLUME_LOTS
            or volume_ratio_vs_prev < MIN_VOLUME_RATIO
        ):
            continue

        future_days = build_future_days(
            code=code,
            base_close=latest_bar.close,
            future_dates=future_dates,
            future_maps=future_maps,
        )

        candidates.append(
            Candidate(
                market=latest_bar.market,
                code=code,
                name=latest_bar.name,
                latest_date=latest_bar.date,
                prev_date=prev_bar.date,
                latest_close=round(latest_bar.close, 4),
                latest_volume_shares=latest_bar.volume_shares,
                latest_volume_lots=round(latest_volume_lots, 3),
                prev_volume_shares=prev_bar.volume_shares,
                prev_volume_lots=round(prev_volume_lots, 3),
                volume_ratio_vs_prev=round(volume_ratio_vs_prev, 4),
                ma5_latest=round(ma5_latest, 4),
                ma10_latest=round(ma10_latest, 4),
                ma20_latest=round(ma20_latest, 4),
                ma5_prev=round(ma5_prev, 4),
                ma10_prev=round(ma10_prev, 4),
                ma20_prev=round(ma20_prev, 4),
                future_days=future_days,
            )
        )

    return prev_date, sorted(candidates, key=lambda x: (x.market, x.code))


def write_output(latest_date: str, prev_date: str, candidates: list[Candidate]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"screen_ma_alignment_turning_point_{latest_date}.json"
    payload = {
        "strategy": "ma5_gt_ma10_gt_ma20_newly_formed",
        "definition": {
            "latest_day": "最近交易日 MA5 > MA10 > MA20",
            "prev_day": "前一交易日不滿足 MA5 > MA10 > MA20",
            "latest_volume_min_lots": ">= 1000 張",
            "latest_volume_vs_prev": ">= 前一交易日的 1.3 倍",
            "ma_formula": "簡單移動平均 SMA，使用收盤價計算",
        },
        "latest_date": latest_date,
        "prev_date": prev_date,
        "count": len(candidates),
        "candidates": [asdict(item) for item in candidates],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def print_summary(latest_date: str, prev_date: str, candidates: list[Candidate], output_path: Path | None) -> None:
    print("策略：最近交易日剛達成 MA5 > MA10 > MA20，且前一交易日尚未達成，最近一日成交量 >= 1000 張，且為前一天的 1.3 倍以上")
    print(f"比較區間：{prev_date} → {latest_date}")
    print(f"入選數量：{len(candidates)}")
    print(f"輸出檔案：{output_path if output_path else 'DB cache only'}")
    print()
    for item in candidates:
        if item.future_days:
            future_text = ", ".join(
                f"{day['date']}:{day['close']:.2f}/{day['pct_from_signal']:+.2f}%/{day['pct_from_prev']:+.2f}%"
                for day in item.future_days
                if day.get("pct_from_signal") is not None and day.get("pct_from_prev") is not None
            )
            future_text = future_text or "(無後續資料)"
        else:
            future_text = "(無後續資料)"

        print(
            f"{item.market.upper():4s} {item.code} {item.name} | "
            f"C={item.latest_close:.2f} V={item.latest_volume_lots:.3f}張 倍數={item.volume_ratio_vs_prev:.2f} | "
            f"後5日={future_text}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="選出最近交易日剛達成 MA5 > MA10 > MA20，且前一交易日尚未達成的股票")
    parser.add_argument("--latest-date", help="最近交易日 YYYYMMDD，預設使用資料中最新日期")
    parser.add_argument("--no-save", action="store_true", help="只輸出到 stdout，不寫 JSON 檔")
    args = parser.parse_args()

    latest_date, _ = resolve_dates(args.latest_date)
    prev_date, candidates = screen(latest_date)
    output_path = None if args.no_save else write_output(latest_date, prev_date, candidates)
    print_summary(latest_date, prev_date, candidates, output_path)


if __name__ == "__main__":
    main()
