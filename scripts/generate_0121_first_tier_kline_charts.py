#!/usr/bin/env python3
"""為 0121 第一梯隊股票產生 40 日 K 線圖。

輸入：
- outputs/screen_ma_alignment_turning_point_sector_<latest_date>.json

輸出：
- outputs/kline_0121_first_tier_<latest_date>/kline_<code>_<name>_40d.png
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang TC", "Heiti TC", "Noto Sans CJK TC"]
plt.rcParams["axes.unicode_minus"] = False

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
TWSE_DIR = DATA_DIR / "twse" / "2026"
TPEX_DIR = DATA_DIR / "tpex" / "2026"
INPUT_PREFIX = "screen_ma_alignment_turning_point_sector_"
WINDOW = 40


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="為 0121 第一梯隊股票產生 40 日 K 線圖")
    parser.add_argument("--latest-date", help="0121 輸出日期 YYYYMMDD；不帶時自動抓最新檔")
    parser.add_argument("--input-json", help="指定 0121 JSON 路徑，優先於 --latest-date")
    return parser.parse_args()


def normalize_field_name(name: str) -> str:
    text = re.sub(r"<br.*?>", "", str(name))
    return text.replace(" ", "").strip()


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


def is_valid_twse_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    fields = [normalize_field_name(x) for x in payload.get("fields", [])]
    required = {"證券代號", "證券名稱", "成交股數", "開盤價", "最高價", "最低價", "收盤價"}
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
    required = {"代號", "名稱", "開盤", "最高", "最低", "收盤", "成交股數"}
    return required.issubset(set(fields)) and bool(table.get("data"))


def available_dates() -> list[str]:
    twse_dates = {p.stem for p in TWSE_DIR.glob("2026*.json") if p.is_file() and is_valid_twse_file(p)}
    tpex_dates = {p.stem for p in TPEX_DIR.glob("2026*.json") if p.is_file() and is_valid_tpex_file(p)}
    return sorted(twse_dates & tpex_dates)


def resolve_input_path(latest_date: str | None, input_json: str | None) -> Path:
    if input_json:
        path = Path(input_json).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"找不到 input_json：{path}")
        return path
    if latest_date:
        path = OUTPUT_DIR / f"{INPUT_PREFIX}{latest_date}.json"
        if not path.exists():
            raise SystemExit(f"找不到 latest_date={latest_date} 對應的 0121 輸出：{path}")
        return path
    paths = sorted(OUTPUT_DIR.glob(f"{INPUT_PREFIX}*.json"))
    if not paths:
        raise SystemExit("找不到任何 0121 族群分析輸出 JSON。")
    return paths[-1]


def load_analysis(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "first_tier_theme" not in payload or "latest_date" not in payload:
        raise SystemExit(f"0121 JSON 結構不符預期：{path}")
    return payload


def load_twse_day(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = [normalize_field_name(x) for x in payload.get("fields", [])]

    def idx(name: str) -> int:
        return fields.index(name)

    code_i = idx("證券代號")
    name_i = idx("證券名稱")
    open_i = idx("開盤價")
    high_i = idx("最高價")
    low_i = idx("最低價")
    close_i = idx("收盤價")
    volume_i = idx("成交股數")

    result: dict[str, dict] = {}
    for row in payload.get("data", []):
        if not isinstance(row, list):
            continue
        o = parse_num(row[open_i])
        h = parse_num(row[high_i])
        l = parse_num(row[low_i])
        c = parse_num(row[close_i])
        if None in (o, h, l, c):
            continue
        code = str(row[code_i]).strip()
        result[code] = {
            "market": "twse",
            "code": code,
            "name": str(row[name_i]).strip(),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume_lots": round(parse_int(row[volume_i]) / 1000.0, 3),
        }
    return result


def load_tpex_day(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    table = payload["tables"][0]
    fields = [normalize_field_name(x) for x in table.get("fields", [])]

    def idx(name: str) -> int:
        return fields.index(name)

    code_i = idx("代號")
    name_i = idx("名稱")
    open_i = idx("開盤")
    high_i = idx("最高")
    low_i = idx("最低")
    close_i = idx("收盤")
    volume_i = idx("成交股數")

    result: dict[str, dict] = {}
    for row in table.get("data", []):
        if not isinstance(row, list):
            continue
        o = parse_num(row[open_i])
        h = parse_num(row[high_i])
        l = parse_num(row[low_i])
        c = parse_num(row[close_i])
        if None in (o, h, l, c):
            continue
        code = str(row[code_i]).strip()
        result[code] = {
            "market": "tpex",
            "code": code,
            "name": str(row[name_i]).strip(),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume_lots": round(parse_int(row[volume_i]) / 1000.0, 3),
        }
    return result


def build_stock_history(targets: dict[str, str], latest_date: str) -> tuple[list[str], dict[str, list[dict]]]:
    dates = available_dates()
    if latest_date not in dates:
        raise SystemExit(f"latest_date={latest_date} 不在有效共同交易日清單中。")
    end_idx = dates.index(latest_date)
    start_idx = max(0, end_idx - WINDOW + 1)
    window_dates = dates[start_idx : end_idx + 1]
    if len(window_dates) < WINDOW:
        raise SystemExit(f"可用交易日不足 {WINDOW} 天，無法畫圖。")

    histories = {code: [] for code in targets}
    for date_str in window_dates:
        twse_rows = load_twse_day(TWSE_DIR / f"{date_str}.json")
        tpex_rows = load_tpex_day(TPEX_DIR / f"{date_str}.json")
        merged = {**twse_rows, **tpex_rows}
        for code in targets:
            row = merged.get(code)
            if row is None:
                raise SystemExit(f"{code} 在 {date_str} 找不到行情資料。")
            histories[code].append({"date": date_str, **row})
    return window_dates, histories


def moving_average(values: list[float], period: int) -> np.ndarray:
    ma = np.full(len(values), np.nan)
    for i in range(period - 1, len(values)):
        ma[i] = sum(values[i - period + 1 : i + 1]) / period
    return ma


def ensure_safe_name(text: str) -> str:
    return re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", text).strip("_")


def plot_chart(rows: list[dict], out_path: Path) -> None:
    dates = [row["date"] for row in rows]
    opens = [row["open"] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    closes = [row["close"] for row in rows]
    volumes = [row["volume_lots"] for row in rows]
    code = rows[-1]["code"]
    name = rows[-1]["name"]
    market = rows[-1]["market"].upper()

    x = np.arange(len(rows))
    ma5 = moving_average(closes, 5)
    ma10 = moving_average(closes, 10)
    ma20 = moving_average(closes, 20)

    fig = plt.figure(figsize=(12.8, 7.2), dpi=180)
    fig.patch.set_facecolor("white")
    ax1 = fig.add_axes([0.07, 0.24, 0.88, 0.62])
    ax2 = fig.add_axes([0.07, 0.08, 0.88, 0.12], sharex=ax1)

    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        is_up = c >= o
        color = "#d62728" if is_up else "#2ca02c"
        ax1.plot([i, i], [l, h], color=color, linewidth=0.9)
        body_bottom = min(o, c)
        body_height = max(abs(c - o), 0.01)
        ax1.add_patch(
            plt.Rectangle(
                (i - 0.3, body_bottom),
                0.6,
                body_height,
                facecolor=color if is_up else "white",
                edgecolor=color,
                linewidth=0.9,
            )
        )

    ax1.plot(x, ma5, color="#1f77b4", linewidth=1.2, label="MA5")
    ax1.plot(x, ma10, color="#ff7f0e", linewidth=1.2, label="MA10")
    ax1.plot(x, ma20, color="black", linewidth=1.2, linestyle="--", label="MA20")
    ax1.set_xlim(-1, len(rows))
    ax1.set_ylim(min(lows) * 0.97, max(highs) * 1.03)
    ax1.set_ylabel("價格")
    ax1.set_title(f"{code} {name} — {market} 40日K線（{dates[0]}~{dates[-1]}）")
    ax1.grid(True, alpha=0.25)
    ax1.legend(loc="upper left", fontsize=8)
    ax1.set_facecolor("#f9f9f9")
    ax1.text(
        0.985,
        0.96,
        f"MA5={ma5[-1]:.2f}\nMA10={ma10[-1]:.2f}\nMA20={ma20[-1]:.2f}",
        transform=ax1.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        bbox={"boxstyle": "round", "facecolor": "wheat", "alpha": 0.55},
    )

    vol_colors = ["#d62728" if c >= o else "#2ca02c" for o, c in zip(opens, closes)]
    ax2.bar(x, volumes, color=vol_colors, width=0.7, alpha=0.75)
    ax2.set_ylabel("量(張)")
    ax2.set_xlabel("交易日")
    ax2.grid(True, alpha=0.25, axis="y")
    ax2.set_facecolor("#f9f9f9")

    tick_pos = list(range(0, len(rows), 5))
    if tick_pos[-1] != len(rows) - 1:
        tick_pos.append(len(rows) - 1)
    ax2.set_xticks(tick_pos)
    ax2.set_xticklabels([dates[i] for i in tick_pos], rotation=45, fontsize=7)
    plt.setp(ax1.get_xticklabels(), visible=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    img = Image.open(out_path)
    w, h = img.size
    if w > 1280 or h > 960:
        ratio = min(1280 / w, 960 / h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        img.save(out_path, quality=85)


def main() -> None:
    args = parse_args()
    input_path = resolve_input_path(args.latest_date, args.input_json)
    payload = load_analysis(input_path)
    latest_date = str(payload["latest_date"])
    first_tier = payload.get("first_tier_theme")
    if not first_tier or not first_tier.get("members"):
        raise SystemExit("0121 結果沒有 first_tier_theme 可供畫圖。")

    targets = {}
    for member in first_tier["members"]:
        code, name = member.split(" ", 1)
        targets[code] = name

    _, histories = build_stock_history(targets, latest_date)
    out_dir = OUTPUT_DIR / f"kline_0121_first_tier_{latest_date}"

    print(f"第一梯隊：{first_tier['theme_name']} | {len(targets)} 檔")
    print(f"輸出目錄：{out_dir}")
    for code, rows in histories.items():
        safe_name = ensure_safe_name(targets[code])
        out_path = out_dir / f"kline_{code}_{safe_name}_40d.png"
        plot_chart(rows, out_path)
        print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
