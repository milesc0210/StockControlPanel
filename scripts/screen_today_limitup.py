#!/usr/bin/env python3
"""選出指定日期收盤漲停，且成交量 > 2000 張的股票。

預設以 data/twse/2026 與 data/tpex/2026 的本地日資料執行。

條件定義：
1. 指定日期收盤等於漲停價，且最高價 = 收盤價
   - TWSE：以前一交易日收盤價推算漲停價
   - TPEX：優先使用前一交易日檔案中的「次日漲停價」，若缺值則退回 TWSE 同樣推算法
2. 指定日期成交量 > 2000 張（1 張 = 1000 股）

輸出：
- 終端摘要
- JSON 檔：outputs/screen_today_limitup_<date>.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
TWSE_DIR = DATA_DIR / "twse" / "2026"
TPEX_DIR = DATA_DIR / "tpex" / "2026"
EPS = 1e-9
MIN_VOLUME_LOTS = 2000


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
    next_limit_up: float | None = None


@dataclass
class Candidate:
    market: str
    code: str
    name: str
    prev_date: str
    latest_date: str
    prev_close: float
    limit_up_price: float
    latest_open: float
    latest_high: float
    latest_low: float
    latest_close: float
    latest_volume_shares: int
    latest_volume_lots: float
    rank_score: float
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


def tick_size(price: float) -> Decimal:
    if price < 10:
        return Decimal("0.01")
    if price < 50:
        return Decimal("0.05")
    if price < 100:
        return Decimal("0.1")
    if price < 500:
        return Decimal("0.5")
    if price < 1000:
        return Decimal("1")
    return Decimal("5")


def round_to_tick(price: float) -> float:
    raw = Decimal(str(price))
    tick = tick_size(price)
    units = (raw / tick).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return float(units * tick)


def limit_up_price(prev_close: float) -> float:
    return round_to_tick(prev_close * 1.10)


def available_dates() -> list[str]:
    twse_dates = {p.stem for p in TWSE_DIR.glob("2026*.json") if p.is_file() and is_valid_twse_file(p)}
    tpex_dates = {p.stem for p in TPEX_DIR.glob("2026*.json") if p.is_file() and is_valid_tpex_file(p)}
    return sorted(twse_dates & tpex_dates)


def resolve_dates(latest_date: str | None) -> tuple[str, str]:
    dates = available_dates()
    if len(dates) < 2:
        raise SystemExit("可用交易日不足 2 天，無法判斷指定日是否為漲停。")

    if latest_date is None:
        latest_date = dates[-1]
    if latest_date not in dates:
        raise SystemExit(f"找不到 latest_date={latest_date} 的 TWSE/TPEX 共同資料。")

    latest_idx = dates.index(latest_date)
    if latest_idx < 1:
        raise SystemExit(f"latest_date={latest_date} 前面不足一個交易日。")

    prev_date = dates[latest_idx - 1]
    return latest_date, prev_date


def resolve_future_dates(latest_date: str, lookahead: int = 5) -> list[str]:
    dates = available_dates()
    if latest_date not in dates:
        return []
    latest_idx = dates.index(latest_date)
    return dates[latest_idx + 1 : latest_idx + 1 + lookahead]


def load_twse(date_str: str) -> dict[str, DailyBar]:
    path = TWSE_DIR / f"{date_str}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = [normalize_field_name(x) for x in payload.get("fields", [])]

    def idx(field: str) -> int:
        return fields.index(field)

    code_i = idx("證券代號")
    name_i = idx("證券名稱")
    open_i = idx("開盤價")
    high_i = idx("最高價")
    low_i = idx("最低價")
    close_i = idx("收盤價")
    volume_i = idx("成交股數")

    items: dict[str, DailyBar] = {}
    for row in payload.get("data", []):
        if not isinstance(row, list):
            continue
        open_price = parse_num(row[open_i])
        high_price = parse_num(row[high_i])
        low_price = parse_num(row[low_i])
        close_price = parse_num(row[close_i])
        if None in (open_price, high_price, low_price, close_price):
            continue

        code = str(row[code_i]).strip()
        items[code] = DailyBar(
            market="twse",
            code=code,
            name=str(row[name_i]).strip(),
            date=date_str,
            open=open_price,
            high=high_price,
            low=low_price,
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
    open_i = idx("開盤")
    high_i = idx("最高")
    low_i = idx("最低")
    volume_i = idx("成交股數")
    next_limit_i = idx("次日漲停價") if "次日漲停價" in fields else None

    items: dict[str, DailyBar] = {}
    for row in table.get("data", []):
        if not isinstance(row, list):
            continue
        open_price = parse_num(row[open_i])
        high_price = parse_num(row[high_i])
        low_price = parse_num(row[low_i])
        close_price = parse_num(row[close_i])
        if None in (open_price, high_price, low_price, close_price):
            continue

        code = str(row[code_i]).strip()
        next_limit = parse_num(row[next_limit_i]) if next_limit_i is not None else None
        items[code] = DailyBar(
            market="tpex",
            code=code,
            name=str(row[name_i]).strip(),
            date=date_str,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume_shares=parse_int(row[volume_i]),
            next_limit_up=next_limit,
        )
    return items


def load_market(date_str: str) -> dict[str, DailyBar]:
    merged: dict[str, DailyBar] = {}
    merged.update(load_twse(date_str))
    merged.update(load_tpex(date_str))
    return merged


def same_price(a: float, b: float) -> bool:
    tol = max(float(tick_size(max(a, b))) / 2.0, 0.01)
    return abs(a - b) <= tol + EPS


def is_limit_up(latest_bar: DailyBar, prev_bar: DailyBar) -> tuple[bool, float]:
    explicit_limit = prev_bar.next_limit_up if latest_bar.market == "tpex" else None
    hit_price = explicit_limit if explicit_limit is not None else limit_up_price(prev_bar.close)
    close_hit = same_price(latest_bar.close, hit_price)
    high_hit = same_price(latest_bar.high, latest_bar.close)
    return close_hit and high_hit, hit_price


def has_min_volume_lots(bar: DailyBar, min_lots: int = MIN_VOLUME_LOTS) -> bool:
    return (bar.volume_shares / 1000.0) > min_lots


def compute_rank_score(volume_lots: float, open_price: float, close_price: float) -> float:
    """今日漲停排序分數：量能越強、由開盤推升至漲停的幅度越大，分數越高。"""
    volume_multiple = max(volume_lots / MIN_VOLUME_LOTS, 0.0)
    volume_score = min(volume_multiple, 4.0) * 1.25
    intraday_gain_pct = ((close_price - open_price) / open_price) * 100 if open_price > EPS else 0.0
    strength_score = min(max(intraday_gain_pct, 0.0), 10.0) * 0.4
    return round(4.0 + volume_score + strength_score, 2)


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
        pct = ((future_bar.close - base_close) / base_close) * 100 if abs(base_close) > EPS else None
        prev_close = base_close if not rows else rows[-1]["close"]
        pct_from_prev = ((future_bar.close - prev_close) / prev_close) * 100 if abs(prev_close) > EPS else None
        rows.append(
            {
                "date": future_date,
                "close": round(future_bar.close, 4),
                "pct_from_signal": round(pct, 2) if pct is not None else None,
                "pct_from_prev": round(pct_from_prev, 2) if pct_from_prev is not None else None,
            }
        )
    return rows


def screen(latest_date: str, prev_date: str) -> list[Candidate]:
    latest_map = load_market(latest_date)
    prev_map = load_market(prev_date)
    future_dates = resolve_future_dates(latest_date)
    future_maps: dict[str, dict[str, DailyBar]] = {}
    for date in future_dates:
        try:
            future_maps[date] = load_market(date)
        except Exception:
            continue

    candidates: list[Candidate] = []
    shared_codes = sorted(set(latest_map) & set(prev_map))
    for code in shared_codes:
        latest_bar = latest_map[code]
        prev_bar = prev_map[code]

        hit_limit, hit_price = is_limit_up(latest_bar, prev_bar)
        if not hit_limit:
            continue
        if not has_min_volume_lots(latest_bar):
            continue

        candidates.append(
            Candidate(
                market=latest_bar.market,
                code=code,
                name=latest_bar.name,
                prev_date=prev_date,
                latest_date=latest_date,
                prev_close=prev_bar.close,
                limit_up_price=hit_price,
                latest_open=latest_bar.open,
                latest_high=latest_bar.high,
                latest_low=latest_bar.low,
                latest_close=latest_bar.close,
                latest_volume_shares=latest_bar.volume_shares,
                latest_volume_lots=round(latest_bar.volume_shares / 1000.0, 3),
                rank_score=compute_rank_score(
                    latest_bar.volume_shares / 1000.0,
                    latest_bar.open,
                    latest_bar.close,
                ),
                future_days=build_future_days(code, latest_bar.close, future_dates, future_maps),
            )
        )

    return sorted(candidates, key=lambda item: (-item.rank_score, item.market, item.code))


def write_output(latest_date: str, prev_date: str, candidates: Iterable[Candidate]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"screen_today_limitup_{latest_date}.json"
    candidate_list = [asdict(c) for c in candidates]
    payload = {
        "strategy": "today_limit_up_volume_gt_2000",
        "definition": {
            "limit_up": "指定日期收盤等於漲停價，且當日最高價=收盤價",
            "volume_min_lots": "> 2000 張",
        },
        "latest_date": latest_date,
        "prev_date": prev_date,
        "count": len(candidate_list),
        "candidates": candidate_list,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def print_summary(latest_date: str, prev_date: str, candidates: list[Candidate], output_path: Path | None) -> None:
    print("策略：指定日期漲停 + 成交量>2000張")
    print(f"比較區間：{latest_date}")
    print(f"參考前日：{prev_date}")
    print(f"入選數量：{len(candidates)}")
    print(f"輸出檔案：{output_path if output_path else 'DB cache only'}")
    print()
    for item in candidates:
        future_text = ", ".join(
            f"{row['date']}:{row['close']:.2f}/{row['pct_from_signal']:+.2f}%/{row['pct_from_prev']:+.2f}%"
            for row in item.future_days
            if row.get("pct_from_signal") is not None and row.get("pct_from_prev") is not None
        ) or "(無後續資料)"
        print(
            f"{item.market.upper():4s} {item.code} {item.name} | "
            f"{latest_date} 漲停={item.limit_up_price:.2f} | "
            f"{latest_date} O={item.latest_open:.2f} H={item.latest_high:.2f} "
            f"L={item.latest_low:.2f} C={item.latest_close:.2f} V={item.latest_volume_lots:.3f}張 "
            f"分數={item.rank_score:.2f} | "
            f"後5日={future_text}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="選出指定日期收盤漲停且成交量>2000張的股票")
    parser.add_argument("--date", "--latest-date", dest="latest_date", help="指定日期 YYYYMMDD，預設使用資料中最新日期")
    parser.add_argument("--no-save", action="store_true", help="只輸出到 stdout，不寫 JSON 檔")
    args = parser.parse_args()

    latest_date, prev_date = resolve_dates(args.latest_date)
    candidates = screen(latest_date, prev_date)
    output_path = None if args.no_save else write_output(latest_date, prev_date, candidates)
    print_summary(latest_date, prev_date, candidates, output_path)


if __name__ == "__main__":
    main()
