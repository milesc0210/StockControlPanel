from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import chip_dashboard


def main() -> int:
    parser = argparse.ArgumentParser(description="補抓指定資料週的全市場 TDCC 集保級距資料")
    parser.add_argument("data_date", help="YYYYMMDD")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    db_path = PROJECT_ROOT / "stock_control_panel.db"
    archive_dir = PROJECT_ROOT / "data" / "tdcc"
    archive_dir.mkdir(parents=True, exist_ok=True)
    output_path = archive_dir / f"tdcc_{args.data_date}.csv"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        chip_dashboard.init_schema(conn)
        codes = [
            str(row[0])
            for row in conn.execute(
                "SELECT code FROM chip_stocks WHERE active=1 AND product_type='stock' ORDER BY code"
            ).fetchall()
        ]
    if not codes:
        codes = [row["code"] for row in chip_dashboard.fetch_stock_master()]

    started = time.perf_counter()
    rows: list[dict[str, object]] = []
    failures: list[str] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as executor:
        futures = {
            executor.submit(chip_dashboard.fetch_tdcc_stock_week, code, args.data_date): code
            for code in codes
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                rows.extend(future.result())
            except Exception as exc:
                failures.append(f"{code}: {exc}")
            completed += 1
            if completed % 100 == 0 or completed == len(codes):
                print(f"進度 {completed}/{len(codes)}，有效列數 {len(rows)}，失敗 {len(failures)}", flush=True)

    if len({str(row.get('證券代號')) for row in rows}) < 500:
        print(f"有效股票不足 500 檔，不寫入正式快照。失敗範例：{failures[:5]}")
        return 1

    fieldnames = ["資料日期", "證券代號", "持股分級", "人數", "股數", "占集保庫存數比例%"]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    imported = chip_dashboard.import_local_tdcc_archives(db_path, archive_dir)
    print(
        f"完成 {args.data_date}：股票 {len({str(row.get('證券代號')) for row in rows})} 檔，"
        f"原始列 {len(rows)}，匯入 {imported}，耗時 {time.perf_counter() - started:.1f} 秒"
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
