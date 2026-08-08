#!/usr/bin/env python3
"""創高黑量縮：先找前一日 30 日新高上引黑 K，盤中再用即時行情確認。"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
TWSE_DIR = DATA_DIR / "twse" / "2026"
TPEX_DIR = DATA_DIR / "tpex" / "2026"
LOOKBACK_DAYS = 30
EPS = 1e-9


@dataclass
class DailyBar:
    market: str
    code: str
    name: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume_shares: int


@dataclass
class Candidate:
    market: str
    code: str
    name: str
    setup_date: str
    setup_open: float
    setup_high: float
    setup_low: float
    setup_close: float
    setup_volume_shares: int
    setup_volume_lots: float
    ma4_close_sum: float
    prior_29_high: float
    breakout_percent: float
    upper_shadow_percent: float
    rank_score: float
    future_days: list[dict[str, object]]


def parse_num(value: object) -> float | None:
    text = str(value).strip().replace(",", "").replace("--", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: object) -> int:
    number = parse_num(value)
    return int(number) if number is not None else 0


def normalize_field_name(name: str) -> str:
    return re.sub(r"<br.*?>", "", str(name)).replace(" ", "").strip()


def is_valid_twse_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    fields = {normalize_field_name(field) for field in payload.get("fields", [])}
    return {"證券代號", "證券名稱", "成交股數", "開盤價", "最高價", "最低價", "收盤價"}.issubset(fields) and bool(payload.get("data"))


def is_valid_tpex_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    tables = payload.get("tables") or []
    if not tables:
        return False
    fields = {normalize_field_name(field) for field in tables[0].get("fields", [])}
    return {"代號", "名稱", "成交股數", "開盤", "最高", "最低", "收盤"}.issubset(fields) and bool(tables[0].get("data"))


def available_dates() -> list[str]:
    twse_dates = {path.stem for path in TWSE_DIR.glob("2026*.json") if path.is_file() and is_valid_twse_file(path)}
    tpex_dates = {path.stem for path in TPEX_DIR.glob("2026*.json") if path.is_file() and is_valid_tpex_file(path)}
    return sorted(twse_dates & tpex_dates)


def load_twse(date_str: str) -> dict[str, DailyBar]:
    payload = json.loads((TWSE_DIR / f"{date_str}.json").read_text(encoding="utf-8"))
    fields = [normalize_field_name(field) for field in payload.get("fields", [])]
    indices = {name: fields.index(name) for name in ("證券代號", "證券名稱", "成交股數", "開盤價", "最高價", "最低價", "收盤價")}
    rows: dict[str, DailyBar] = {}
    for raw in payload.get("data", []):
        if not isinstance(raw, list):
            continue
        open_price = parse_num(raw[indices["開盤價"]])
        high_price = parse_num(raw[indices["最高價"]])
        low_price = parse_num(raw[indices["最低價"]])
        close_price = parse_num(raw[indices["收盤價"]])
        if None in (open_price, high_price, low_price, close_price):
            continue
        code = str(raw[indices["證券代號"]]).strip()
        rows[code] = DailyBar(
            market="twse",
            code=code,
            name=str(raw[indices["證券名稱"]]).strip(),
            date=date_str,
            open=float(open_price),
            high=float(high_price),
            low=float(low_price),
            close=float(close_price),
            volume_shares=parse_int(raw[indices["成交股數"]]),
        )
    return rows


def load_tpex(date_str: str) -> dict[str, DailyBar]:
    payload = json.loads((TPEX_DIR / f"{date_str}.json").read_text(encoding="utf-8"))
    tables = payload.get("tables") or []
    if not tables:
        return {}
    table = tables[0]
    fields = [normalize_field_name(field) for field in table.get("fields", [])]
    indices = {name: fields.index(name) for name in ("代號", "名稱", "成交股數", "開盤", "最高", "最低", "收盤")}
    rows: dict[str, DailyBar] = {}
    for raw in table.get("data", []):
        if not isinstance(raw, list):
            continue
        open_price = parse_num(raw[indices["開盤"]])
        high_price = parse_num(raw[indices["最高"]])
        low_price = parse_num(raw[indices["最低"]])
        close_price = parse_num(raw[indices["收盤"]])
        if None in (open_price, high_price, low_price, close_price):
            continue
        code = str(raw[indices["代號"]]).strip()
        rows[code] = DailyBar(
            market="tpex",
            code=code,
            name=str(raw[indices["名稱"]]).strip(),
            date=date_str,
            open=float(open_price),
            high=float(high_price),
            low=float(low_price),
            close=float(close_price),
            volume_shares=parse_int(raw[indices["成交股數"]]),
        )
    return rows


def load_market(date_str: str) -> dict[str, DailyBar]:
    rows = load_twse(date_str)
    rows.update(load_tpex(date_str))
    return rows


def is_new_high_black_setup(history: list[DailyBar]) -> bool:
    if len(history) < LOOKBACK_DAYS:
        return False
    window = history[-LOOKBACK_DAYS:]
    setup = window[-1]
    prior_high = max(bar.high for bar in window[:-1])
    return setup.high > prior_high and setup.close < setup.open and setup.high > setup.open


def compute_rank_score(setup: DailyBar, prior_29_high: float) -> float:
    breakout_percent = ((setup.high / prior_29_high) - 1) * 100 if prior_29_high > EPS else 0
    upper_shadow_percent = ((setup.high - setup.open) / setup.open) * 100 if setup.open > EPS else 0
    volume_lots = setup.volume_shares / 1000
    volume_score = min(math.log10(max(volume_lots, 1)), 4.0)
    return round(5 + min(breakout_percent, 10) * 0.8 + min(upper_shadow_percent, 10) * 0.5 + volume_score, 2)


def build_future_days(code: str, base_close: float, future_dates: list[str], daily_maps: dict[str, dict[str, DailyBar]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for date_str in future_dates:
        bar = daily_maps.get(date_str, {}).get(code)
        if bar is None:
            continue
        previous_close = base_close if not rows else float(rows[-1]["close"])
        rows.append(
            {
                "date": date_str,
                "close": round(bar.close, 4),
                "pct_from_signal": round(((bar.close - base_close) / base_close) * 100, 2),
                "pct_from_prev": round(((bar.close - previous_close) / previous_close) * 100, 2),
            }
        )
    return rows


def select_setup_candidates(
    dates: list[str],
    daily_maps: dict[str, dict[str, DailyBar]],
    setup_date: str,
) -> list[Candidate]:
    if setup_date not in dates:
        raise ValueError(f"找不到 setup_date={setup_date}。")
    setup_index = dates.index(setup_date)
    if setup_index < LOOKBACK_DAYS - 1:
        raise ValueError(f"setup_date={setup_date} 前不足 {LOOKBACK_DAYS - 1} 個交易日。")
    lookback_dates = dates[setup_index - LOOKBACK_DAYS + 1:setup_index + 1]
    future_dates = dates[setup_index + 1:setup_index + 6]
    setup_map = daily_maps.get(setup_date, {})
    candidates: list[Candidate] = []
    for code in sorted(setup_map):
        history = [daily_maps.get(date_str, {}).get(code) for date_str in lookback_dates]
        if any(bar is None for bar in history):
            continue
        bars = [bar for bar in history if bar is not None]
        if not is_new_high_black_setup(bars):
            continue
        setup = bars[-1]
        prior_29_high = max(bar.high for bar in bars[:-1])
        breakout_percent = ((setup.high / prior_29_high) - 1) * 100
        upper_shadow_percent = ((setup.high - setup.open) / setup.open) * 100 if setup.open > EPS else 0
        candidates.append(
            Candidate(
                market=setup.market,
                code=setup.code,
                name=setup.name,
                setup_date=setup.date,
                setup_open=setup.open,
                setup_high=setup.high,
                setup_low=setup.low,
                setup_close=setup.close,
                setup_volume_shares=setup.volume_shares,
                setup_volume_lots=round(setup.volume_shares / 1000, 3),
                ma4_close_sum=round(sum(bar.close for bar in bars[-4:]), 4),
                prior_29_high=round(prior_29_high, 4),
                breakout_percent=round(breakout_percent, 2),
                upper_shadow_percent=round(upper_shadow_percent, 2),
                rank_score=compute_rank_score(setup, prior_29_high),
                future_days=build_future_days(code, setup.close, future_dates, daily_maps),
            )
        )
    return sorted(candidates, key=lambda item: (-item.rank_score, item.market, item.code))


def resolve_setup_date(requested_date: str | None) -> tuple[list[str], str]:
    dates = available_dates()
    if len(dates) < LOOKBACK_DAYS:
        raise SystemExit(f"可用共同交易日不足 {LOOKBACK_DAYS} 天。")
    setup_date = requested_date or dates[-1]
    if setup_date not in dates:
        raise SystemExit(f"找不到 date={setup_date} 的 TWSE/TPEX 共同資料。")
    if dates.index(setup_date) < LOOKBACK_DAYS - 1:
        raise SystemExit(f"date={setup_date} 前不足 {LOOKBACK_DAYS - 1} 個交易日。")
    return dates, setup_date


def write_output(setup_date: str, candidates: list[Candidate]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"screen_new_high_black_volume_contraction_{setup_date}.json"
    payload = {
        "strategy": "new_30d_high_black_upper_wick_then_intraday_volume_contraction",
        "setup_date": setup_date,
        "count": len(candidates),
        "candidates": [asdict(item) for item in candidates],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def format_future_days(candidate: Candidate) -> str:
    return ", ".join(
        f"{row['date']}:{row['close']:.2f}/{row['pct_from_signal']:+.2f}%/{row['pct_from_prev']:+.2f}%"
        for row in candidate.future_days
    ) or "(無後續資料)"


def print_summary(setup_date: str, candidates: list[Candidate], output_path: Path | None) -> None:
    print("策略：創高黑量縮（前一日30日新高＋上引收黑，盤中確認未再創高、量縮、股價不低於MA5的-5%）")
    print(f"比較區間：前30個交易日 → {setup_date}")
    print(f"參考前日：{setup_date}")
    print(f"入選數量：{len(candidates)}")
    print(f"輸出檔案：{output_path if output_path else 'DB cache only'}")
    print()
    for item in candidates:
        print(
            f"{item.market.upper():4s} {item.code} {item.name} | "
            f"{item.setup_date} O={item.setup_open:.2f} H={item.setup_high:.2f} "
            f"L={item.setup_low:.2f} C={item.setup_close:.2f} V={item.setup_volume_lots:.3f}張 "
            f"MA4合計={item.ma4_close_sum:.4f} 分數={item.rank_score:.2f} | "
            f"後5日={format_future_days(item)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="創高黑量縮：建立盤中即時確認用候選清單")
    parser.add_argument("--date", help="訊號前日 YYYYMMDD，預設使用本地最新完整交易日")
    parser.add_argument("--no-save", action="store_true", help="只輸出 stdout，不寫 JSON")
    args = parser.parse_args()

    dates, setup_date = resolve_setup_date(args.date)
    setup_index = dates.index(setup_date)
    required_dates = dates[max(0, setup_index - LOOKBACK_DAYS + 1):setup_index + 6]
    daily_maps = {date_str: load_market(date_str) for date_str in required_dates}
    candidates = select_setup_candidates(dates, daily_maps, setup_date)
    output_path = None if args.no_save else write_output(setup_date, candidates)
    print_summary(setup_date, candidates, output_path)


if __name__ == "__main__":
    main()
