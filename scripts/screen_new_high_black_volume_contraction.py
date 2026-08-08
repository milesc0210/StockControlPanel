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


@dataclass
class CompletedSignal:
    market: str
    code: str
    name: str
    setup_date: str
    setup_open: float
    setup_high: float
    setup_low: float
    setup_close: float
    setup_volume_lots: float
    signal_date: str
    signal_open: float
    signal_high: float
    signal_low: float
    signal_close: float
    signal_volume_lots: float
    ma5: float
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


def select_completed_signals(
    dates: list[str],
    daily_maps: dict[str, dict[str, DailyBar]],
    signal_date: str,
) -> list[CompletedSignal]:
    if signal_date not in dates:
        raise ValueError(f"找不到 signal_date={signal_date}。")
    signal_index = dates.index(signal_date)
    if signal_index < LOOKBACK_DAYS:
        raise ValueError(f"signal_date={signal_date} 前不足 {LOOKBACK_DAYS} 個交易日。")

    setup_date = dates[signal_index - 1]
    setup_candidates = select_setup_candidates(dates, daily_maps, setup_date)
    signal_map = daily_maps.get(signal_date, {})
    future_dates = dates[signal_index + 1:signal_index + 6]
    matches: list[CompletedSignal] = []
    for candidate in setup_candidates:
        signal = signal_map.get(candidate.code)
        if signal is None:
            continue
        ma5 = (candidate.ma4_close_sum + signal.close) / 5
        if (
            signal.high > candidate.setup_high
            or signal.volume_shares >= candidate.setup_volume_shares
            or signal.close < ma5 * 0.95
        ):
            continue
        matches.append(
            CompletedSignal(
                market=candidate.market,
                code=candidate.code,
                name=candidate.name,
                setup_date=candidate.setup_date,
                setup_open=candidate.setup_open,
                setup_high=candidate.setup_high,
                setup_low=candidate.setup_low,
                setup_close=candidate.setup_close,
                setup_volume_lots=candidate.setup_volume_lots,
                signal_date=signal.date,
                signal_open=signal.open,
                signal_high=signal.high,
                signal_low=signal.low,
                signal_close=signal.close,
                signal_volume_lots=round(signal.volume_shares / 1000, 3),
                ma5=round(ma5, 4),
                rank_score=candidate.rank_score,
                future_days=build_future_days(candidate.code, signal.close, future_dates, daily_maps),
            )
        )
    return sorted(matches, key=lambda item: (-item.rank_score, item.market, item.code))


def resolve_signal_date(requested_date: str | None) -> tuple[list[str], str]:
    dates = available_dates()
    if len(dates) <= LOOKBACK_DAYS:
        raise SystemExit(f"可用共同交易日不足 {LOOKBACK_DAYS + 1} 天。")
    signal_date = requested_date or dates[-1]
    if signal_date not in dates:
        raise SystemExit(f"找不到 date={signal_date} 的 TWSE/TPEX 共同資料。")
    if dates.index(signal_date) < LOOKBACK_DAYS:
        raise SystemExit(f"date={signal_date} 前不足 {LOOKBACK_DAYS} 個交易日。")
    return dates, signal_date


def write_output(
    signal_date: str,
    setup_date: str,
    matches: list[CompletedSignal],
    intraday_watchlist: list[Candidate],
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"screen_new_high_black_volume_contraction_{signal_date}.json"
    payload = {
        "strategy": "previous_day_new_high_black_then_completed_or_intraday_confirmation",
        "setup_date": setup_date,
        "signal_date": signal_date,
        "count": len(matches),
        "matches": [asdict(item) for item in matches],
        "intraday_watchlist": [asdict(item) for item in intraday_watchlist],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def format_future_days(candidate: Candidate | CompletedSignal) -> str:
    return ", ".join(
        f"{row['date']}:{row['close']:.2f}/{row['pct_from_signal']:+.2f}%/{row['pct_from_prev']:+.2f}%"
        for row in candidate.future_days
    ) or "(無後續資料)"


def print_summary(
    signal_date: str,
    setup_date: str,
    matches: list[CompletedSignal],
    intraday_watchlist: list[Candidate],
    output_path: Path | None,
) -> None:
    print("策略：創高黑量縮（前一交易日30日新高＋上引收黑；指定交易日確認未再創高、量縮、收盤不低於MA5的-5%）")
    print(f"比較區間：前30個交易日 → {setup_date}，訊號日 {signal_date}")
    print(f"參考前日：{setup_date}")
    print(f"訊號日期：{signal_date}")
    print(f"入選數量：{len(matches)}")
    print(f"盤中觀察前日：{signal_date}")
    print(f"盤中觀察數量：{len(intraday_watchlist)}")
    print(f"輸出檔案：{output_path if output_path else 'DB cache only'}")
    print()
    for item in matches:
        print(
            f"RESULT {item.market.upper():4s} {item.code} {item.name} | "
            f"SETUP {item.setup_date} O={item.setup_open:.2f} H={item.setup_high:.2f} "
            f"L={item.setup_low:.2f} C={item.setup_close:.2f} V={item.setup_volume_lots:.3f}張 | "
            f"SIGNAL {item.signal_date} O={item.signal_open:.2f} H={item.signal_high:.2f} "
            f"L={item.signal_low:.2f} C={item.signal_close:.2f} V={item.signal_volume_lots:.3f}張 "
            f"MA5={item.ma5:.4f} 分數={item.rank_score:.2f} | "
            f"後5日={format_future_days(item)}"
        )
    if matches:
        print()
    for item in intraday_watchlist:
        print(
            f"WATCH {item.market.upper():4s} {item.code} {item.name} | "
            f"{item.setup_date} O={item.setup_open:.2f} H={item.setup_high:.2f} "
            f"L={item.setup_low:.2f} C={item.setup_close:.2f} V={item.setup_volume_lots:.3f}張 "
            f"MA4合計={item.ma4_close_sum:.4f} 分數={item.rank_score:.2f} | "
            f"後5日={format_future_days(item)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="創高黑量縮：檢查完成交易日訊號並建立下一交易日盤中觀察清單")
    parser.add_argument("--date", help="訊號交易日 YYYYMMDD，預設使用本地最新完整交易日")
    parser.add_argument("--no-save", action="store_true", help="只輸出 stdout，不寫 JSON")
    args = parser.parse_args()

    dates, signal_date = resolve_signal_date(args.date)
    signal_index = dates.index(signal_date)
    setup_date = dates[signal_index - 1]
    required_dates = dates[max(0, signal_index - LOOKBACK_DAYS):signal_index + 6]
    daily_maps = {date_str: load_market(date_str) for date_str in required_dates}
    matches = select_completed_signals(dates, daily_maps, signal_date)
    intraday_watchlist = select_setup_candidates(dates, daily_maps, signal_date)
    output_path = None if args.no_save else write_output(signal_date, setup_date, matches, intraday_watchlist)
    print_summary(signal_date, setup_date, matches, intraday_watchlist, output_path)


if __name__ == "__main__":
    main()
