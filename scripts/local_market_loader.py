#!/usr/bin/env python3
"""
local_market_loader.py — 取代 XQ CSV 的本地市場資料載入器

功能：
1. 從 data/twse/ 和 data/tpex/ 的每日全市場 JSON 讀取行情資料
2. 從歷史 JSON 計算衍生指標（振幅%、均量、量比、週月季%、換手率%）
3. 從 FinMind 公開 API 取得法人買賣超
4. 輸出格式與 XQ CSV DictReader 相容，xq_screener.py 可直接取代

使用方式：
    from local_market_loader import LocalMarketLoader
    loader = LocalMarketLoader()
    rows = loader.load(date_str='20260527')  # 回傳 list[dict]
    rows = loader.load()                     # 預設用 today
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from portable_runtime import DATA_DIR, get_env, load_dotenv

load_dotenv()

# MarketFeatureExtractor（技術結構分析用）
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_feature_extractor import MarketFeatureExtractor

# ── 路徑設定 ──
DATA_BASE = str(DATA_DIR)
TWSE_DIR = os.path.join(DATA_BASE, "twse", "2026")
TPEX_DIR = os.path.join(DATA_BASE, "tpex", "2026")

# ── 欄位索引（固定） ──

# TWSE MI_INDEX fields:
# [證券代號, 證券名稱, 成交股數, 成交筆數, 成交金額, 開盤價, 最高價, 最低價, 收盤價,
#  漲跌(+/-), 漲跌價差, 最後揭示買價, 最後揭示買量, 最後揭示賣價, 最後揭示賣量, 本益比]
TWSE = {
    'code': 0, 'name': 1, 'shares': 2, 'deals': 3, 'amount': 4,
    'open': 5, 'high': 6, 'low': 7, 'close': 8,
    'change_sign': 9, 'change_val': 10,
}

# TPEX fields:
# [代號, 名稱, 收盤, 漲跌, 開盤, 最高, 最低, 成交股數, 成交金額, 成交筆數,
#  最後買價, 最後買量, 最後賣價, 最後賣量, 發行股數, 次日漲停價, 次日跌停價]
TPEX = {
    'code': 0, 'name': 1, 'close': 2, 'change': 3,
    'open': 4, 'high': 5, 'low': 6,
    'shares': 7, 'amount': 8, 'deals': 9,
    'issued_shares': 14,
}

# ── 衍生指標計算參數 ──
TRADING_DAYS_1W = 5     # 一週交易日數
TRADING_DAYS_1M = 21    # 一月交易日數
TRADING_DAYS_1Q = 63    # 一季交易日數
TRADING_DAYS_MAX = 63   # 最大回溯日數（for 一季%）


def parse_num(val, default=0.0):
    """安全轉浮點數，處理逗號、空值、'--'"""
    if val is None:
        return default
    s = str(val).strip().replace(',', '').replace(' ', '')
    if not s or s in ('--', 'N/A', '-', '+', ''):
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def parse_int_safe(val, default=0):
    return int(parse_num(val, default))


def is_etf(code: str, name: str) -> bool:
    """判斷是否為 ETF/ETN/期貨等應排除標的"""
    code = str(code).strip()
    name = str(name).strip()
    # 特別股（含 - 的）
    if '-' in code:
        return True
    # ETF/ETN 名稱關鍵字
    etf_keywords = ['ETF', 'ETN', '期貨', '權證', '牛證', '熊證']
    for kw in etf_keywords:
        if kw in name or kw in code:
            return True
    # 台股代碼以 0 開頭 = ETF/ETN/特別股（0050, 006208, 00878 等）
    if code.startswith('0'):
        return True
    return False


class LocalMarketLoader:
    """本地市場資料載入器"""

    def __init__(self):
        self._hist_cache = {}       # {date_str: {code: {close, volume}}}
        self._today_hist = {}        # 今天已解析的歷史行情（代號→行情dict）
        self._tpex_issued = {}       # {code: 發行股數}
        self._date_list = []         # 排序後的交易日列表（舊→新）

    # ── 公開介面 ──

    def load(self, date_str: Optional[str] = None, skip_finmind: bool = False,
             batch_callback=None) -> list:
        """
        載入指定日期的全市場資料，回傳 list[dict]（與 XQ CSV DictReader 相容）。

        date_str: YYYYMMDD 格式，預設用今日
        skip_finmind: 跳過法人資料查詢（只回傳行情+衍生指標）
        batch_callback: FinMind 每批完成的回呼 fn(batch_num, total_batches)
        """
        if date_str is None:
            date_str = datetime.now().strftime('%Y%m%d')

        # Step 1: 載入當日行情
        rows = self._load_raw_rows(date_str)
        print(f"   📊 全市場行情: {len(rows)} 檔")

        # Step 2: 載入歷史資料（計算衍生指標用）
        self._ensure_historical(date_str)

        # Step 3: 計算衍生指標
        self._compute_derived(rows, date_str)

        # Step 4: 排除 ETF/特別股
        before = len(rows)
        rows = [r for r in rows if not is_etf(r.get('代碼', ''), r.get('商品', ''))]
        print(f"   🚫 排除 ETF/特別股: {before - len(rows)} 檔（剩 {len(rows)}）")

        # Step 5: 法人買賣超
        if not skip_finmind:
            self._fetch_institutional(rows, date_str, batch_callback)
        else:
            print(f"   ⏭ 跳過法人資料（skip_finmind=True）")

        return rows

    # ── Step 1: 載入當日行情 ──

    def _load_raw_rows(self, date_str: str) -> list:
        """讀取 TWSE + TPEX JSON，回傳基本行情 rows"""
        rows = []

        # 上市
        twse_path = os.path.join(TWSE_DIR, f"{date_str}.json")
        if os.path.exists(twse_path):
            try:
                with open(twse_path, 'r', encoding='utf-8') as f:
                    twse_data = json.load(f)
                twse_rows = twse_data.get('data', [])
                for entry in twse_rows:
                    if not isinstance(entry, (list, tuple)) or len(entry) < 11:
                        continue
                    code = str(entry[TWSE['code']]).strip()
                    name = str(entry[TWSE['name']]).strip()
                    row = {
                        '代碼': code,
                        '商品': name,
                        '產業': '上市',
                        '開盤': parse_num(entry[TWSE['open']]),
                        '最高': parse_num(entry[TWSE['high']]),
                        '最低': parse_num(entry[TWSE['low']]),
                        '收盤價': parse_num(entry[TWSE['close']]),
                        '成交': parse_num(entry[TWSE['close']]),  # 相容舊欄位名
                        '總量': parse_int_safe(parse_num(entry[TWSE['shares']]) / 1000),  # 股→張
                        '成交股數': parse_int_safe(entry[TWSE['shares']]),
                        '漲跌價差': parse_num(entry[TWSE['change_val']]),
                        'market': 'twse',
                    }
                    # 漲跌幅需要計算（從歷史資料取得昨日收盤）
                    rows.append(row)
                print(f"   ✅ TWSE 上市: {len(twse_rows)} 檔")
            except (json.JSONDecodeError, IOError) as e:
                print(f"   ❌ TWSE 讀取失敗: {e}")
        else:
            print(f"   ⚠️ TWSE 檔案不存在: {twse_path}")

        # 上櫃
        tpex_path = os.path.join(TPEX_DIR, f"{date_str}.json")
        if os.path.exists(tpex_path):
            try:
                with open(tpex_path, 'r', encoding='utf-8') as f:
                    tpex_data = json.load(f)
                tables = tpex_data.get('tables', [])
                if tables:
                    tpex_entries = tables[0].get('data', [])
                    for entry in tpex_entries:
                        if not isinstance(entry, (list, tuple)) or len(entry) < 15:
                            continue
                        code = str(entry[TPEX['code']]).strip()
                        name = str(entry[TPEX['name']]).strip()
                        shares = parse_num(entry[TPEX['shares']])
                        row = {
                            '代碼': code,
                            '商品': name,
                            '產業': '上櫃',
                            '開盤': parse_num(entry[TPEX['open']]),
                            '最高': parse_num(entry[TPEX['high']]),
                            '最低': parse_num(entry[TPEX['low']]),
                            '收盤價': parse_num(entry[TPEX['close']]),
                            '成交': parse_num(entry[TPEX['close']]),
                            '總量': parse_int_safe(shares / 1000),  # 股→張
                            '成交股數': parse_int_safe(shares),
                            '漲跌': entry[TPEX['change']],
                            'market': 'tpex',
                            '發行股數': parse_int_safe(entry[TPEX['issued_shares']]),
                        }
                        # 記錄發行股數供換手率計算
                        self._tpex_issued[code] = parse_int_safe(entry[TPEX['issued_shares']])
                        rows.append(row)
                    print(f"   ✅ TPEX 上櫃: {len(tpex_entries)} 檔")
            except (json.JSONDecodeError, IOError) as e:
                print(f"   ❌ TPEX 讀取失敗: {e}")
        else:
            print(f"   ⚠️ TPEX 檔案不存在: {tpex_path}")

        return rows

    # ── Step 2: 載入歷史資料 ──

    def _ensure_historical(self, today_str: str):
        """載入歷史交易日行情，建立 {date: {code: {close, volume}}} 索引"""
        if self._hist_cache:
            return  # 已快取

        # 找出所有交易日 JSON
        all_files = set()
        for d in [TWSE_DIR, TPEX_DIR]:
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.endswith('.json') and f != f"{today_str}.json":
                        all_files.add(f.replace('.json', ''))

        # 排序（舊→新）
        date_list = sorted(all_files)
        # 只保留最近 TRADING_DAYS_MAX 個交易日（+ 昨天用於振幅/漲幅分母）
        date_list = date_list[-(TRADING_DAYS_MAX + 5):]
        self._date_list = date_list

        # 載入每個交易日的收盤價和成交量
        for d in date_list:
            daily_map = {}
            # 從 TWSE 取
            twse_path = os.path.join(TWSE_DIR, f"{d}.json")
            if os.path.exists(twse_path):
                try:
                    with open(twse_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for entry in data.get('data', []):
                        if not isinstance(entry, (list, tuple)) or len(entry) < 11:
                            continue
                        code = str(entry[TWSE['code']]).strip()
                        o = parse_num(entry[TWSE['open']])
                        h = parse_num(entry[TWSE['high']])
                        l = parse_num(entry[TWSE['low']])
                        c = parse_num(entry[TWSE['close']])
                        vol = parse_int_safe(parse_num(entry[TWSE['shares']]) / 1000)
                        if c > 0:
                            daily_map[code] = {'open': o, 'high': h, 'low': l, 'close': c, 'volume': vol}
                except Exception:
                    pass

            # 從 TPEX 補
            tpex_path = os.path.join(TPEX_DIR, f"{d}.json")
            if os.path.exists(tpex_path):
                try:
                    with open(tpex_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    tables = data.get('tables', [])
                    if tables:
                        for entry in tables[0].get('data', []):
                            if not isinstance(entry, (list, tuple)) or len(entry) < 8:
                                continue
                            code = str(entry[TPEX['code']]).strip()
                            o = parse_num(entry[TPEX['open']])
                            h = parse_num(entry[TPEX['high']])
                            l = parse_num(entry[TPEX['low']])
                            c = parse_num(entry[TPEX['close']])
                            vol = parse_int_safe(parse_num(entry[TPEX['shares']]) / 1000)
                            if c > 0:
                                daily_map[code] = {'open': o, 'high': h, 'low': l, 'close': c, 'volume': vol}
                except Exception:
                    pass

            self._hist_cache[d] = daily_map

        print(f"   📚 歷史交易日: {len(self._date_list)} 天（{self._date_list[0]} ~ {self._date_list[-1]}）")

    # ── Step 3: 計算衍生指標 ──

    def _lookup_hist(self, code: str, date_str: str) -> dict:
        """查詢某股票在某日期的歷史行情"""
        daily = self._hist_cache.get(date_str, {})
        return daily.get(code, {})

    def _compute_derived(self, rows: list, today_str: str):
        """為每檔股票計算衍生指標"""
        # 找出昨天日期
        if not self._date_list:
            return
        yesterday = self._date_list[-1] if self._date_list else today_str

        count = 0
        for row in rows:
            code = row['代碼']
            close = row['收盤價']

            if close <= 0:
                continue

            # 昨日收盤（用於振幅%/漲跌幅分母）
            prev_close = parse_num(self._lookup_hist(code, yesterday).get('close', 0))

            # ── 漲跌幅% ──
            if prev_close > 0:
                change_pct = (close - prev_close) / prev_close * 100
                row['漲幅%'] = round(change_pct, 2)
            else:
                row['漲幅%'] = 0.0

            # ── 振幅% ──
            high = row['最高']
            low = row['最低']
            if prev_close > 0 and high > 0 and low > 0:
                amp = (high - low) / prev_close * 100
                row['振幅%'] = round(amp, 2)
            else:
                row['振幅%'] = 0.0

            # ── 五日均量 & 量比 ──
            volumes = []
            # 今天的量
            today_vol = row['總量']
            # 往前找最近 5 個交易日的成交量
            for d in reversed(self._date_list[-5:]):
                hist = self._lookup_hist(code, d)
                v = hist.get('volume', 0)
                if v > 0:
                    volumes.append(v)
            if volumes:
                avg_5d = sum(volumes) / len(volumes)
            else:
                avg_5d = today_vol
            row['五日均量'] = round(avg_5d, 0)
            row['量比'] = round(today_vol / avg_5d, 2) if avg_5d > 0 else 0.0

            # ── 一週%/一月%/一季% ──
            # 從歷史資料往前找對應天數的收盤
            dates_for_lookback = self._date_list
            for n_days, col_name in [(TRADING_DAYS_1W, '一週%'),
                                      (TRADING_DAYS_1M, '一月%'),
                                      (TRADING_DAYS_1Q, '一季%')]:
                target_idx = len(dates_for_lookback) - n_days
                if target_idx >= 0:
                    target_date = dates_for_lookback[target_idx]
                    target_close = parse_num(self._lookup_hist(code, target_date).get('close', 0))
                    if target_close > 0:
                        ret = (close - target_close) / target_close * 100
                        row[col_name] = round(ret, 2)
                    else:
                        # fallback: 用最早的可用資料
                        fallback_close = 0
                        for d in dates_for_lookback[:target_idx+1]:
                            fc = parse_num(self._lookup_hist(code, d).get('close', 0))
                            if fc > 0:
                                fallback_close = fc
                                break
                        if fallback_close > 0:
                            ret = (close - fallback_close) / fallback_close * 100
                            row[col_name] = round(ret, 2)
                        else:
                            row[col_name] = 0.0
                else:
                    row[col_name] = 0.0

            # ── 換手率% ──
            # 上市：用 TWSE 成交股數 / 發行股數（TWSE 無發行股數，略過）
            # 上櫃：用 TPEX 發行股數
            if row.get('market') == 'tpex':
                issued = self._tpex_issued.get(code, 0)
                if issued > 0:
                    # 換手率% = 當日成交股數 / 發行股數 × 100
                    turnover = row['成交股數'] / issued * 100
                    row['換手率%'] = round(turnover, 2)
                else:
                    row['換手率%'] = 0.0
            else:
                # TWSE 無發行股數，換手率設 0（Pass3 換手率檢查看 0）
                row['換手率%'] = 0.0

            count += 1

        print(f"   📐 衍生指標計算: {count} 檔完成")

    # ── Step 5: 法人買賣超 ──

    def fetch_institutional(self, codes: list, date_str: str, batch_callback=None) -> dict:
        """
        從 FinMind 查指定股票代碼的法人買賣超。
        
        分批策略：每批 50 檔，批間 pause 30 秒，避開 rate limit。
        
        codes: 股票代碼列表
        date_str: YYYYMMDD 格式
        回傳: {code: {'外資買賣超': int, '投信買賣超': int, '自營商買賣超': int, '法人買賣超': int}}
        """
        FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
        FINMIND_TOKEN = get_env('FINMIND_TOKEN')
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        total = len(codes)
        if total == 0:
            return {}

        results = {}
        success = 0
        fail = 0
        BATCH_SIZE = 50       # 每批 50 檔
        PAUSE_BETWEEN = 30    # 批間 pause 30 秒
        PER_STOCK_DELAY = 0.1  # 每檔間隔 0.1s

        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"   🔬 FinMind 法人資料查詢: {total} 檔（{total_batches} 批，每批 {BATCH_SIZE} 檔，批間 {PAUSE_BETWEEN}s）...")

        for batch_idx in range(0, total, BATCH_SIZE):
            batch_num = batch_idx // BATCH_SIZE + 1
            batch_codes = codes[batch_idx:batch_idx + BATCH_SIZE]

            for code in batch_codes:
                try:
                    params = {
                        'dataset': 'TaiwanStockInstitutionalInvestorsBuySell',
                        'data_id': code,
                        'start_date': date_fmt,
                        'end_date': date_fmt,
                        'token': FINMIND_TOKEN,
                    }
                    r = requests.get(FINMIND_URL, params=params, timeout=10)
                    data = r.json()

                    if data.get('status') != 200 or not data.get('data'):
                        fail += 1
                        results[code] = {'外資買賣超': 0, '投信買賣超': 0, '自營商買賣超': 0, '法人買賣超': 0}
                        continue

                    inst_data = {}
                    for item in data['data']:
                        name = item['name']
                        buy = item['buy']
                        sell = item['sell']
                        inst_data[name] = buy - sell

                    foreign = inst_data.get('Foreign_Investor', 0)
                    investment = inst_data.get('Investment_Trust', 0)
                    dealer_self = inst_data.get('Dealer_self', 0)
                    dealer_hedging = inst_data.get('Dealer_Hedging', 0)
                    dealer = dealer_self + dealer_hedging
                    total_inst = foreign + investment + dealer

                    results[code] = {
                        '外資買賣超': foreign,
                        '投信買賣超': investment,
                        '自營商買賣超': dealer,
                        '法人買賣超': total_inst,
                    }
                    success += 1
                except Exception as e:
                    fail += 1
                    results[code] = {'外資買賣超': 0, '投信買賣超': 0, '自營商買賣超': 0, '法人買賣超': 0}

                time.sleep(PER_STOCK_DELAY)

            done = min(batch_idx + BATCH_SIZE, total)
            print(f"     批次 {batch_num}/{total_batches}: {done}/{total} 檔（成功 {success} / 失敗 {fail}）")
            if batch_callback:
                batch_callback(batch_num, total_batches)

            # 批間 pause 30 秒（最後一批不用等）
            if done < total:
                print(f"     等待 {PAUSE_BETWEEN} 秒後繼續下一批...")
                time.sleep(PAUSE_BETWEEN)

        print(f"   ✅ FinMind 法人資料: {success} 檔成功 / {fail} 檔失敗")
        return results


    # ── Step 5: 法人買賣超（舊版，保留相容） ──

    def _fetch_institutional(self, rows: list, date_str: str, batch_callback=None):
        """從 FinMind 查法人買賣超（直接寫入 rows）"""
        codes = [r['代碼'] for r in rows]
        results = self.fetch_institutional(codes, date_str, batch_callback)
        for row in rows:
            code = row['代碼']
            inst = results.get(code, {'外資買賣超': 0, '投信買賣超': 0, '自營商買賣超': 0, '法人買賣超': 0})
            row.update(inst)

    # ── 技術結構分析（0 API，用本地歷史 JSON）──

    def compute_technical_structure(self, code: str, windows: list = None, current_price: float = None) -> dict:
        """
        從本地歷史 JSON 計算技術結構（支撐/壓力/RR/型態）。
        0 API 消耗，完全取代 FinMind MarketFeatureExtractor。

        code: 股票代碼
        windows: 分析窗口列表，預設 [5, 10, 20]
        current_price: 當前股價（若無則取歷史最後一日收盤）
        回傳: {window_5: {supports, resistances, rr, patterns}, ...}
        """
        if windows is None:
            windows = [5, 10, 20]

        # 從歷史 cache 建立 OHLCV DataFrame
        rows = []
        for date_str in sorted(self._date_list):
            hist = self._hist_cache.get(date_str, {}).get(code, {})
            if hist and hist.get('close', 0) > 0:
                rows.append({
                    'date': date_str,
                    'open': hist.get('open', hist['close']),
                    'high': hist.get('high', hist['close']),
                    'low': hist.get('low', hist['close']),
                    'close': hist['close'],
                    'volume': hist.get('volume', 0),
                })

        if len(rows) < 20:
            return {}

        # 從今天的行情補開高低（如果有）
        # 如果只有收盤價，分析效果有限
        # 嘗試從原始 JSON 取得更精準的 OHLC
        try:
            # 檢查 twse/tpex 原始 JSON 是否有這檔的開高低
            today_str = self._date_list[-1] if self._date_list else None
            if today_str:
                twse_path = os.path.join(TWSE_DIR, f"{today_str}.json")
                if os.path.exists(twse_path):
                    with open(twse_path, 'r', encoding='utf-8') as f:
                        twse_data = json.load(f)
                    for entry in twse_data.get('data', []):
                        if str(entry[TWSE['code']]).strip() == code:
                            rows[-1]['open'] = parse_num(entry[TWSE['open']])
                            rows[-1]['high'] = parse_num(entry[TWSE['high']])
                            rows[-1]['low'] = parse_num(entry[TWSE['low']])
                            rows[-1]['close'] = parse_num(entry[TWSE['close']])
                            break

                tpex_path = os.path.join(TPEX_DIR, f"{today_str}.json")
                if os.path.exists(tpex_path):
                    with open(tpex_path, 'r', encoding='utf-8') as f:
                        tpex_data = json.load(f)
                    tables = tpex_data.get('tables', [])
                    if tables:
                        for entry in tables[0].get('data', []):
                            if str(entry[TPEX['code']]).strip() == code:
                                rows[-1]['open'] = parse_num(entry[TPEX['open']])
                                rows[-1]['high'] = parse_num(entry[TPEX['high']])
                                rows[-1]['low'] = parse_num(entry[TPEX['low']])
                                rows[-1]['close'] = parse_num(entry[TPEX['close']])
                                break
        except Exception:
            pass

        # 確保有足夠的歷史資料
        if len(rows) < 20:
            return {}

        df = pd.DataFrame(rows)

        structure = {}
        for w in windows:
            try:
                # 每個 window 只看相對應的歷史長度，讓支撐壓力更貼近現價
                # W5 看近 25 天、W10 看近 40 天、W20 看近 60 天（全部）
                lookback_map = {5: 25, 10: 40, 20: min(60, len(df))}
                lookback = lookback_map.get(w, min(w * 4, len(df)))
                window_df = df.tail(lookback).reset_index(drop=True)

                extractor = MarketFeatureExtractor(window=w, volume_threshold=0)
                if not extractor.load_from_dataframe(window_df):
                    structure[f'window_{w}'] = None
                    continue

                result = extractor.analyze(current_price=current_price)
                if 'error' in result:
                    structure[f'window_{w}'] = None
                    continue

                # 取得原始結構
                supports = [s['price'] for s in result['key_levels']['supports']]
                resistances = [r['price'] for r in result['key_levels']['resistances']]
                rr = result['risk_reward'].get('ratio', 0) if result.get('risk_reward') else 0

                # RR=0 代表找不到明確的支撐壓力（如股價創近期新高）
                # 不捏造價格，設為 None 讓踢除規則跳過
                if rr == 0:
                    rr = None

                structure[f'window_{w}'] = {
                    'supports': supports,
                    'resistances': resistances,
                    'rr': rr,  # None = 無法評估，跳過 RR 門檻
                    'patterns': [p['type'] for p in result['detected_patterns']],
                    'volume_signals': [{'type': v['type'], 'note': v['note']}
                                        for v in result.get('volume_signals', [])],
                }
            except Exception:
                structure[f'window_{w}'] = None

        return structure if any(v for v in structure.values()) else None


# ── 命令列入口 ──
if __name__ == '__main__':
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    skip_finmind = '--skip-finmind' in sys.argv

    print(f"{'='*50}")
    print(f"📊 LocalMarketLoader — 取代 XQ CSV")
    print(f"{'='*50}")
    print(f"   日期: {date_str or '今天'}")
    print(f"   FinMind: {'跳過' if skip_finmind else '啟用'}")
    print()

    loader = LocalMarketLoader()
    rows = loader.load(date_str=date_str, skip_finmind=skip_finmind)

    print(f"\n{'='*50}")
    print(f"🏁 完成: {len(rows)} 檔")
    print(f"{'='*50}")

    # 顯示前 3 筆樣本
    print(f"\n📝 樣本（前 3 筆）:")
    for row in rows[:3]:
        print(f"   [{row['代碼']}] {row['商品']} | "
              f"收: {row['收盤價']} | 漲跌: {row.get('漲幅%', 0):+.1f}% | "
              f"量: {row['總量']:,}張 | 量比: {row.get('量比', 0):.2f} | "
              f"外資: {row.get('外資買賣超', 0):+,}")

    # 儲存為 JSON 供 debug
    out_path = os.path.join(os.path.dirname(__file__), 'local_market_sample.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(rows[:5], f, ensure_ascii=False, indent=2)
    print(f"\n📁 前5筆已儲存: {out_path}")
