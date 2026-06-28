#!/usr/bin/env python3
"""
XQ 股池篩選腳本
用法: python3 xq_screener.py <csv_path>
輸出: 候選股池 JSON + 摘要報告

條件參考自 tw-stock-pool-screener skill + NotebookLM 交易日誌
"""

import csv
import json
import sys
import os
import math
import traceback
import argparse
from datetime import datetime

# ── 路徑設定（相對於本腳本位置）──
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.dirname(_SCRIPT_DIR)  # daily_trade_plan 根目錄

# ── 板塊資金流分類（from sector_flow.py, adapted for XQ CSV） ──
SECTOR_MAP = {
    'semiconductor': {'prefixes': ('23', '24'), 'label': '半導體'},
    'electronics':    {'prefixes': ('25', '30', '33', '34', '35', '36'), 'label': '電子零組件'},
    'computing':      {'prefixes': ('37', '49', '61', '63', '64', '65', '66', '67', '68', '69'), 'label': '資訊通訊'},
    'finance':        {'prefixes': ('28', '58'), 'label': '金融'},
    'shipping':       {'prefixes': ('26',), 'label': '航運'},
    'biotech':        {'prefixes': ('17', '47'), 'label': '生技醫療'},
    'traditional':    {'prefixes': (
        '11','12','13','14','15','16','18','19','20','21','22','27','29','31','32','39',
        '40','41','42','43','44','45','46','48','51','52','53','54','55','56','57','59',
        '60','62','70','71','72','73','74','75','76','77','78','79','80','81','82','83',
        '84','85','86','87','88','89','90','91','92','93','94','95','96','97','98','99'
    ), 'label': '傳產/其他'},
}
SPECIAL_SECTOR_MAP = {
    '3297': '安全監控',
    '5489': '安全監控',
    '5251': '安全監控',
    '3128': '安全監控',
    '0584': '安全監控',
    '584': '安全監控',
    '6560': '安全監控',
    '3356': '安全監控',
    '2390': '安全監控',
    '8072': '安全監控',
    '6419': '安全監控',
}
_PREFIX_TO_SECTOR = {}
for _sname, _info in SECTOR_MAP.items():
    for _p in _info['prefixes']:
        _PREFIX_TO_SECTOR[_p] = _sname

def classify_sector(ticker):
    """根據台股代號前兩碼判斷板塊，回傳 sector key"""
    ticker_str = ''.join(ch for ch in str(ticker).strip() if ch.isdigit())
    if ticker_str in SPECIAL_SECTOR_MAP:
        return SPECIAL_SECTOR_MAP[ticker_str]
    if len(ticker_str) >= 2:
        prefix = ticker_str[:2]
        return _PREFIX_TO_SECTOR.get(prefix, 'traditional')
    return 'traditional'

def compute_sector_flow_from_xq(df):
    """
    用 XQ CSV 的 % 欄位計算各板塊資金流分數。
    df: candidates DataFrame，需有 一週%、一月%、一季% 欄位
    回傳: dict { sector_key: flow_score }
    """
    WEIGHTS = {'一週%': 0.5, '一月%': 0.4, '一季%': 0.1}  # 2026-05-31: 月權重 0.3→0.4（NotebookLM：強化強勢股特徵）
    sector_data = {}
    for _, row in df.iterrows():
        sector = classify_sector(row['代碼'])
        if sector not in sector_data:
            sector_data[sector] = {'sum': 0.0, 'count': 0}
        for col, w in WEIGHTS.items():
            val = float(row.get(col, 0) or 0)
            sector_data[sector]['sum'] += val * w
            sector_data[sector]['count'] += 1
    scores = {}
    for s, d in sector_data.items():
        scores[s] = d['sum'] / d['count'] if d['count'] > 0 else 0.0
    return scores

def allocate_sector_slots(sector_scores, sector_counts, total_candidates):
    """
    根據板塊分數分配名額。
    - 板塊平均動量 < 0% → 剔除（0 名額，資金流出不進場）
    - 動量 > 0 的板塊中，依分數比例分配名額
    - 配額不超過該板塊實際股票數（sector_counts）
    回傳: dict { sector_key: slot_count }
    """
    if not sector_scores:
        return {}
    # 只保留分數 > 0 的板塊（資金正在流入）
    valid = {s: v for s, v in sector_scores.items() if v > 0}
    if len(valid) == 0:
        return {}
    # 依分數比例分配
    sorted_sectors = sorted(valid.items(), key=lambda x: -x[1])
    top_sectors = [s for s, _ in sorted_sectors]
    top_scores = {s: valid[s] for s in top_sectors}
    total_score = sum(top_scores.values())
    if total_score <= 0:
        return {}
    # 依分數比例分配，用 ceiling，但不超過該板塊實際股票數
    allocated = {}
    actual_total = sum(sector_counts.get(s, 0) for s in top_sectors)
    cap = min(total_candidates, actual_total)
    remaining = cap
    for s in top_sectors[:-1]:
        slot = math.ceil(top_scores[s] / total_score * cap)
        slot = max(slot, 1)
        # 不超過該板塊實際股票數
        max_avail = sector_counts.get(s, cap)
        slot = min(slot, max_avail)
        allocated[s] = slot
        remaining -= slot
    # 最後一個板塊拿剩下的，但也不超過實際股票數
    last_max = sector_counts.get(top_sectors[-1], remaining)
    allocated[top_sectors[-1]] = max(min(remaining, last_max), 1)
    return allocated

def sector_label(sector_key):
    return SECTOR_MAP.get(sector_key, {}).get('label', sector_key)


# ── 地端 K 線特徵引擎（Local Feature Engine） ──
def build_stock_kline(stock_id, data_dir='twse', max_days=40):
    """
    從 data/twse/2026/ 或 data/tpex/2026/ 的全市場日行情中，
    抽出某檔股票最近 max_days 個交易日的 K 線資料。

    回傳: list of dict {date, open, high, low, close, volume(張)}
           依日期從新到舊排列，若資料不足 max_days 則回傳有的全部。
    """
    base = os.path.join(_BASE, "data", data_dir, "2026")
    if not os.path.isdir(base):
        return []

    # 所有交易日 JSON 檔，依檔名排序（從舊到新）
    files = sorted([f for f in os.listdir(base) if f.endswith('.json')], reverse=True)

    if data_dir == 'twse':
        code_idx = 0
    else:  # tpex
        code_idx = 0

    stock_id_str = str(stock_id)
    kline_data = []
    collected = 0

    for fname in files:
        if collected >= max_days:
            break
        fpath = os.path.join(base, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                daily_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        if data_dir == 'twse':
            entries = daily_data.get('data', [])
            fields = daily_data.get('fields', [])
            # 動態從 fields 找出開高低收量的 index
            # TWSE 欄位在不同日期格式不同（10欄 vs 16欄）
            field_names = [f.strip() for f in fields]
            try:
                o_idx = field_names.index('開盤價')
                h_idx = field_names.index('最高價')
                l_idx = field_names.index('最低價')
                c_idx = field_names.index('收盤價')
                v_idx = field_names.index('成交股數')
            except ValueError:
                # fallback 到硬編碼
                o_idx, h_idx, l_idx, c_idx, v_idx = 4, 5, 6, 7, 2
        else:
            tables = daily_data.get('tables', [])
            entries = tables[0].get('data', []) if tables else []
            # TPEX 欄位固定
            o_idx, h_idx, l_idx, c_idx, v_idx = 4, 5, 6, 2, 7

        # 找這檔股票
        for row in entries:
            if not isinstance(row, (list, tuple)) or len(row) < 9:
                continue
            row_code = str(row[code_idx]).strip()
            if row_code != stock_id_str:
                continue

            # 解析數值
            try:
                o = float(str(row[o_idx]).replace(',', ''))
                h = float(str(row[h_idx]).replace(',', ''))
                l = float(str(row[l_idx]).replace(',', ''))
                c = float(str(row[c_idx]).replace(',', ''))
                vol_shares = float(str(row[v_idx]).replace(',', ''))
                # 成交量從股轉張
                vol_lots = int(vol_shares / 1000)
            except (ValueError, IndexError):
                continue

            # 日期從檔名取（如 20260525.json → 2026/05/25）
            date_str = fname.replace('.json', '')
            date_fmt = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:8]}"

            kline_data.append({
                'date': date_fmt,
                'open': o,
                'high': h,
                'low': l,
                'close': c,
                'volume': vol_lots,
            })
            collected += 1
            break  # 同一檔案只取一筆

    return kline_data


def calc_sma(data_desc, period):
    """
    計算收盤價的簡單移動平均。
    data_desc: 從新到舊排列的 K 線資料
    回傳 list，最新(第0筆)的 MA=avg(最近 period 根收盤)
    """
    closes = [d['close'] for d in data_desc]
    result = [None] * len(closes)
    for i in range(len(closes)):
        if i + period <= len(closes):
            result[i] = round(sum(closes[i:i+period]) / period, 2)
    return result


def write_kline_json(stock_id, name, kline, ma5, ma10, ma20, data_dir):
    """將 K 線資料及 MA 寫入 JSON 檔案"""
    out_dir = os.path.join(_BASE, "data", data_dir, "Kline")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{stock_id}_40d.json")

    # 將 MA 資訊附加到每根 K 線
    data_with_ma = []
    for i, d in enumerate(kline):
        entry = dict(d)
        if ma5[i] is not None:
            entry['MA5'] = ma5[i]
        if ma10[i] is not None:
            entry['MA10'] = ma10[i]
        if ma20[i] is not None:
            entry['MA20'] = ma20[i]
        data_with_ma.append(entry)

    date_range = f"{kline[-1]['date'].replace('/', '')}~{kline[0]['date'].replace('/', '')}" if len(kline) >= 2 else ""

    output = {
        'meta': {
            'stock_id': stock_id,
            'name': name,
            'source': f"{data_dir.upper()} daily ({data_dir}/2026/)",
            'period': f"~{len(kline)} trading days",
            'date_range': date_range,
            'count': len(kline),
            'format_note': "AI-readable OHLC data. date(YYYY/MM/DD), open/high/low/close(float), volume(int, 張). Bullish=close>open, Bearish=close<open."
        },
        'data': data_with_ma
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return out_path


def local_feature_engine(pool_entries, candidates, today_str, kicked_log):
    """
    地端 K 線特徵引擎：
    - 對每檔候選股，從 data/twse/ 或 data/tpex/ 組最近 40 根日K
    - 算 MA5/MA10/MA20
    - 存 K 線 JSON 到對應 Kline/ 資料夾
    - 剔除「data 最新收盤價 < MA20」的股票
    - 回傳 (過濾後的 pool_entries, 更新的 kicked_log)

    需傳入 candidates（含 XQ 完整資料）和 today_str。
    """
    # 建立 candidates lookup：code -> cand
    cand_lookup = {}
    for c in candidates:
        code = str(c.get('代碼', ''))
        cand_lookup[code] = c

    # 擷取最新交易日（data 最新檔案日期）
    # 從 TWSE 目錄找最新檔案
    twse_base = os.path.join(_BASE, "data", "twse", "2026")
    tpex_base = os.path.join(_BASE, "data", "tpex", "2026")

    kline_kicked = []
    kept_entries = []
    total = len(pool_entries)
    success_count = 0
    fail_count = 0

    for entry in pool_entries:
        code = str(entry['code'])
        name = entry.get('name', '')
        cand = cand_lookup.get(code)

        # 判斷上市還是上櫃：先查 TWSE 目錄最新日有沒有這檔，沒有再去 TPEX
        data_dir = 'twse'
        base_dir = twse_base
        if not os.path.isdir(base_dir):
            data_dir = 'tpex'
            base_dir = tpex_base
        else:
            # 看最新交易日檔案中該股票是否存在於 TWSE
            twse_latest = sorted([f for f in os.listdir(twse_base) if f.endswith('.json')], reverse=True)
            found_in_twse = False
            if twse_latest:
                try:
                    with open(os.path.join(twse_base, twse_latest[0]), 'r', encoding='utf-8') as f:
                        twse_data = json.load(f)
                    for row in twse_data.get('data', []):
                        if isinstance(row, (list, tuple)) and len(row) >= 1 and str(row[0]).strip() == code:
                            found_in_twse = True
                            break
                except (json.JSONDecodeError, IOError):
                    pass
            if not found_in_twse:
                data_dir = 'tpex'
                base_dir = tpex_base
        if not os.path.isdir(base_dir):
            print(f"   ⚠️ [{code}] {name} — data 目錄不存在: {base_dir}")
            kept_entries.append(entry)  # 無法判斷就不踢
            continue

        # 抓最近 40 根日K
        kline = build_stock_kline(code, data_dir=data_dir, max_days=40)
        if not kline:
            print(f"   ⚠️ [{code}] {name} — 無歷史資料，保留")
            kept_entries.append(entry)
            fail_count += 1
            continue

        # K 線是從新到舊排列，直接算 SMA（最新筆 MA=最近 period 根收盤均值）
        ma5 = calc_sma(kline, 5)
        ma10 = calc_sma(kline, 10)
        ma20 = calc_sma(kline, 20)

        # 存 K 線 JSON
        try:
            kline_path = write_kline_json(code, name, kline, ma5, ma10, ma20, data_dir)
        except Exception as e:
            print(f"   ⚠️ [{code}] {name} — 寫入 K 線 JSON 失敗: {e}")

        # 取最新收盤價（kline[0] 是最新）
        latest_close = kline[0]['close']
        ma5_val = ma5[0]
        ma20_val = ma20[0]

        # 判斷剔除條件 1：現價 < MA20
        if ma20_val is not None and latest_close < ma20_val:
            reason = f'below_ma20: 收盤價={latest_close} < MA20={ma20_val}'
            kline_kicked.append({
                'code': code,
                'name': name,
                'kicked_date': today_str,
                'days_in_pool': entry.get('days', 1),
                'reason': reason
            })
            kicked_log.append({
                'code': code,
                'name': name,
                'kicked_date': today_str,
                'days_in_pool': entry.get('days', 1),
                'reason': reason
            })
            print(f"   ❌ [{code}] {name} — {reason}")
            continue  # 已剔除，跳到下一檔
        
        # 判斷剔除條件 2：MA5 < MA20（死亡交叉，2026-05-26 老闆指令）
        if ma5_val is not None and ma20_val is not None and ma5_val < ma20_val:
            reason = f'death_cross: MA5={ma5_val} < MA20={ma20_val}'
            kline_kicked.append({
                'code': code,
                'name': name,
                'kicked_date': today_str,
                'days_in_pool': entry.get('days', 1),
                'reason': reason
            })
            kicked_log.append({
                'code': code,
                'name': name,
                'kicked_date': today_str,
                'days_in_pool': entry.get('days', 1),
                'reason': reason
            })
            print(f"   ❌ [{code}] {name} — {reason}")
            continue  # 已剔除，跳到下一檔
        
        kept_entries.append(entry)
        success_count += 1
        if ma20_val is not None:
            print(f"   ✅ [{code}] {name} — 收盤價={latest_close}, MA5={ma5_val}, MA20={ma20_val}, 通過")

    print(f"\n📊 地端 K 線特徵引擎：{total} 檔 → 保留 {len(kept_entries)} / 剔除 {len(kline_kicked)}")
    return kept_entries, kicked_log


import pandas as pd

# ── MarketFeatureExtractor（嵌入版，減少 import 依賴） ──
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from market_feature_extractor import MarketFeatureExtractor
    HAS_FEATURE_EXTRACTOR = True
except ImportError:
    HAS_FEATURE_EXTRACTOR = False

# ── 參數設定（可調） ──

# Pass 1: 技術面
MIN_AMPLITUDE = 2.0      # 最小振幅%
MAX_AMPLITUDE = 10.0     # 最大振幅%（參考 NotebookLM：振幅>10%若獲利需全數鎖利，放寬至此範圍）
MIN_CHANGE = 0.0         # 最小漲幅%（不含下跌）
MAX_CHANGE = 7.0         # 最大漲幅%
MIN_DROP = -8.0          # 單日跌幅上限（排除暴跌股，如 NotebookLM 提及的華電網）
MIN_VOLUME = 500         # 最低成交量（張）
MIN_5D_AVG_VOL = 300     # 五日均量最低
MIN_VOL_RATIO = 0.8      # 量比門檻（2026-05-31 上修：0.5→0.8，NotebookLM 本週經驗：量比太低缺乏動能確認）
EXTREME_UP_VOL_RATIO = 2.0  # 極端單邊大漲日後的量比門檻（全市場>90%收紅時隔日需 vol_ratio>2.0）
HIGH_VOL_RATIO_THRESHOLD = 3.0  # 量比>3 需搭配週漲幅檢驗（量增價漲 vs 量增價平）

# Pass 2: 法人籌碼
MIN_FOREIGN = 0           # 外資買超 > 0
MIN_INVESTMENT = 0        # 投信買超 > 0
#  通過條件: (外援>0 OR 投信>0) AND 法人合計>0

# Pass 3: 歷史表現
MAX_1W = 20.0             # 一週漲幅上限（排除短期已噴出）
MAX_1M = 35.0             # 一月漲幅上限
MAX_CHANGE_RATE = 15.0    # 換手率上限（超過的可能過熱）

# RSI 超買降部位門檻（新增，參考 NotebookLM：RSI6>75 首批部位降至25%）
RSI6_OVERBOUGHT = 75.0
RSI6_EXTREME = 80.0      # RSI6>80 則不入場

# 環境濾網（2026-05-31 新增，NotebookLM 本週 M 頭氾濫教訓）
MHEAD_KICK_THRESHOLD = 0.50   # 全市場 M 頭踢除比例 >50% → 隔日禁用新買入
EXTREME_UP_DAY_THRESHOLD = 0.90  # 全市場 >90% 類股收紅 → 視為極端單邊日

# 排除條件
EXCLUDE_INDUSTRIES = ['ETF', 'ETN']  # 排除 ETF/ETN


# ── 環境濾網函數（2026-05-31 新增，NotebookLM M 頭氾濫教訓） ──

def detect_extreme_up_day(all_rows):
    """
    偵測全市場是否為極端單邊大漲日。
    條件：全市場 >90% 的股票收紅（漲幅% > 0）。
    回傳: (is_extreme: bool, up_ratio: float)
    """
    if not all_rows:
        return False, 0.0
    up_count = sum(1 for r in all_rows if parse_float(r.get('漲幅%')) > 0)
    ratio = up_count / len(all_rows)
    return ratio >= EXTREME_UP_DAY_THRESHOLD, ratio


def check_high_vol_price_divergence(row):
    """
    量比 > 3 時檢查「量增價漲」vs「量增價平」。
    量增價平（振幅<1.5% 且漲幅<1%）= 警訊，應減碼。
    回傳: ('healthy', None) 或 ('divergent', detail_str)
    """
    vol_ratio = parse_float(row.get('量比'))
    if vol_ratio <= HIGH_VOL_RATIO_THRESHOLD:
        return 'healthy', None
    amp = parse_float(row.get('振幅%'))
    change = parse_float(row.get('漲幅%'))
    if amp < 1.5 and change < 1.0:
        return 'divergent', f'量比{vol_ratio:.1f}但振幅{amp:.1f}%/漲幅{change:.1f}%（量增價平）'
    return 'healthy', None


def parse_float(val, default=0.0):
    """安全轉浮點數，處理 '--' 'N/A' 等"""
    if val is None:
        return default
    val = str(val).strip()
    if val in ('--', 'N/A', '', '-', '+'):
        return default
    # 處理百分比符號
    val = val.replace('%', '')
    # 處理 + 開頭
    if val.startswith('+'):
        val = val[1:]
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def parse_int(val, default=0):
    """安全轉整數"""
    if val is None:
        return default
    val = str(val).strip()
    if val in ('--', 'N/A', '', '-'):
        return default
    # 處理千分位逗號
    val = val.replace(',', '')
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def should_skip_stock(code, name, industry):
    """排除 ETF、權證、期貨等"""
    code = str(code).strip()
    name = str(name).strip()
    industry = str(industry).strip()
    
    # 排除 ETF/ETN
    if 'ETF' in industry or 'ETN' in industry:
        return True
    
    # 排除期貨/選擇權相關
    if industry in ('上市其他-期貨', '上櫃其他-期貨'):
        return True
    
    # 排除權證（代碼通常 03xxxx 或 04xxxx 但普通股不需要特別過濾）
    # 排除特別股（代碼帶 - 的）
    if '-' in code:
        return True
    
    return False


def pass1_technical(row):
    """Pass 1: 技術面單日過濾"""
    name = row.get('商品', '')
    code = row.get('代碼', '')
    industry = row.get('產業', '')
    
    if should_skip_stock(code, name, industry):
        return False, None
    
    change_pct = parse_float(row.get('漲幅%'))
    amp = parse_float(row.get('振幅%'))
    volume = parse_float(row.get('總量'))  # 張
    avg_5d_vol = parse_float(row.get('五日均量'))
    vol_ratio = parse_float(row.get('量比'))
    
    # 漲幅範圍
    if change_pct < MIN_CHANGE or change_pct > MAX_CHANGE:
        return False, f"漲幅{change_pct:.1f}%不在範圍"
    
    # 振幅範圍
    if amp < MIN_AMPLITUDE or amp > MAX_AMPLITUDE:
        return False, f"振幅{amp:.1f}%不在範圍"

    # 單日暴跌排除（NotebookLM：跌幅>8%排除，如華電網）
    if change_pct < MIN_DROP:
        return False, f"單日跌幅{change_pct:.1f}%過大"

    # 最低成交量
    if volume < MIN_VOLUME:
        return False, f"成交量{int(volume)}張不足"

    # 五日均量（排除極冷門股）
    if avg_5d_vol < MIN_5D_AVG_VOL:
        return False, f"五日均量{int(avg_5d_vol)}不足"

    # 量比門檻（NotebookLM：新濾網，量能需有基本放大配合）
    if vol_ratio < MIN_VOL_RATIO:
        return False, f"量比{vol_ratio:.2f}不足{MIN_VOL_RATIO}"
    
    return True, None


def pass2_institutional(row):
    """Pass 2: 法人籌碼過濾"""
    foreign = parse_int(row.get('外資買賣超'))
    investment = parse_int(row.get('投信買賣超'))
    dealer = parse_int(row.get('自營商買賣超'))
    total = parse_int(row.get('法人買賣超'))
    
    # 法人合計必須買超
    if total <= 0:
        return False, f"法人合計{total}未買超"
    
    # 外資或投信至少一個買超
    if foreign <= 0 and investment <= 0:
        return False, f"外資{foreign}/投信{investment}均未買超"
    
    return True, {
        '外資買賣超': foreign,
        '投信買賣超': investment,
        '自營商買賣超': dealer,
        '法人合計': total
    }


def pass3_history(row):
    """Pass 3: 歷史表現過濾"""
    change_1w = parse_float(row.get('一週%'))
    change_1m = parse_float(row.get('一月%'))
    turnover = parse_float(row.get('換手率%'))
    
    # 排除一週已漲超過上限的（短線已噴出）
    if change_1w > MAX_1W:
        return False, f"一週漲{change_1w:.1f}%已噴出"
    
    # 排除一月已漲超過上限的
    if change_1m > MAX_1M:
        return False, f"一月漲{change_1m:.1f}%已過熱"
    
    # 排除換手率過高的（籌碼鬆動）
    if turnover > MAX_CHANGE_RATE:
        return False, f"換手率{turnover:.1f}%過高"
    
    return True, {
        '一週%': change_1w,
        '一月%': change_1m,
        '一季%': parse_float(row.get('一季%')),
        '換手率%': turnover
    }


# ── 模式識別（需歷史K線補資料） ──

def check_3red_upper_shadow(code, max_days_ago=10):
    """
    檢查最近 N 個交易日內是否有「連3紅上引線」結構。
    需從 TWSE API 抓逐日K線。
    
    條件:
    1. 連續3個交易日收紅K（收盤 > 開盤）
    2. 連續3個交易日都有上引線（最高 > 收盤）
    3. 第3天的上引線長度明顯（上引線 > 實體 * 0.5）
    
    回傳: (bool, dict) — 是否命中 + 詳細資料
    """
    import urllib.request
    import json as _json
    
    try:
        # 判斷上市/櫃
        prefix = 'otc_' if str(code).startswith('8') or str(code).startswith('6') else 'tse_'
        url = f'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={prefix}{code}.tw&json=1&delay=0'
        
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode('utf-8'))
        
        msg_array = data.get('msgArray', [])
        if not msg_array:
            return False, None
        
        # msgArray[0] 是當日即時資料，沒有歷史K線
        # 這個API只提供當日，無法判斷前幾天
        # 需要用別的方法——先回傳 unavailable
        return False, {'status': 'no_historical_data', 'note': 'TWSE即時API無歷史K線'}
    
    except Exception as e:
        return False, {'status': 'error', 'error': str(e)}


def fetch_recent_daily_kbars(code, days=10):
    """
    從 TWSE 官方日K API 抓最近 N 個交易日的日K線。
    回傳 list of dict: {date, open, high, low, close, volume}
    """
    import urllib.request
    import json as _json
    from datetime import datetime, timedelta
    
    try:
        # TWSE 日K API 需要指定年份
        # 格式: https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20260513&stockNo=3090
        today = datetime.now()
        year_str = today.strftime('%Y')
        stock_code = str(code).zfill(4)
        
        url = f'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={year_str}0513&stockNo={stock_code}'
        
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode('utf-8'))
        
        raw_data = data.get('data', [])
        if not raw_data:
            return []
        
        # TWSE 回傳格式: [日期, 成交股數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 成交筆數]
        kbars = []
        for row in raw_data:
            try:
                date_str = row[0]  # '113/05/13' (民國年)
                # 轉西元年
                parts = date_str.split('/')
                y = int(parts[0]) + 1911
                m = parts[1].zfill(2)
                d = parts[2].zfill(2)
                iso_date = f'{y}-{m}-{d}'
                
                o = float(row[3].replace(',', ''))
                h = float(row[4].replace(',', ''))
                l = float(row[5].replace(',', ''))
                c = float(row[6].replace(',', ''))
                v = int(row[1].replace(',', ''))
                
                kbars.append({
                    'date': iso_date,
                    'open': o, 'high': h, 'low': l, 'close': c, 'volume': v
                })
            except (ValueError, IndexError):
                continue
        
        # 取最近 days 筆（日期倒序）
        kbars.sort(key=lambda x: x['date'])
        return kbars[-days:] if len(kbars) > days else kbars
    
    except Exception as e:
        return []


def check_3red_upper_shadow_advanced(code):
    """
    用 TWSE 日K API 檢查最近的「連3紅上引線」結構。
    
    條件:
    1. 近3~5個交易日中，存在連續3天都收紅K（close > open）
    2. 這3天都有上引線（high > close）
    3. 第3天的上引線/實體比 > 0.5（或有明顯上引）
    
    回傳: (bool, dict)
    """
    kbars = fetch_recent_daily_kbars(code)
    if len(kbars) < 5:
        return False, {'status': 'insufficient_data', 'count': len(kbars)}
    
    # 從最新往前掃，找連續3紅K + 上引線
    matches = []
    for i in range(len(kbars) - 2):
        d1, d2, d3 = kbars[i], kbars[i+1], kbars[i+2]
        
        # 3天都收紅K
        if not (d1['close'] > d1['open'] and d2['close'] > d2['open'] and d3['close'] > d3['open']):
            continue
        
        # 3天都有上引線
        if not (d1['high'] > d1['close'] and d2['high'] > d2['close'] and d3['high'] > d3['close']):
            continue
        
        # 第3天上引線長度 > 實體 * 0.5
        body3 = d3['close'] - d3['open']
        upper_shadow3 = d3['high'] - d3['close']
        if body3 <= 0 or (upper_shadow3 / body3) < 0.5:
            continue
        
        matches.append({
            'start_date': d1['date'],
            'end_date': d3['date'],
            'd1': d1, 'd2': d2, 'd3': d3,
            'upper_shadow_ratio': round(upper_shadow3 / body3, 2)
        })
    
    if matches:
        return True, matches[-1]  # 最新的
    return False, None


def classify_k_shape(open_p, high, low, close):
    """
    判斷單日 K 線形狀。

    台股定義：🔴紅=漲(收>開)、🟢綠=跌(收<開)

    回傳中文標籤:
      紅實體、上引紅、下引紅、上下引紅、長紅棒
      黑實體、上引黑、下引黑、上下引黑、長黑棒
      十字線
    """
    if open_p == 0 or close == 0:
        return '—'

    body = abs(close - open_p)
    upper = max(open_p, close)
    lower = min(open_p, close)
    upper_shadow = high - upper
    lower_shadow = lower - low

    is_red = close > open_p
    change_pct = ((close - open_p) / open_p) * 100

    # 十字線：實體極小（開收幾乎同價）
    avg_price = (high + low + close) / 3
    if body < avg_price * 0.003:
        return '十字線'

    has_upper = upper_shadow > body * 0.3
    has_lower = lower_shadow > body * 0.3

    # 長紅/黑棒：漲跌幅大且實體佔絕大部分
    if is_red:
        if change_pct > 5.0 and not has_upper and not has_lower:
            return '長紅棒'
        if has_upper and has_lower:
            return '上下引紅'
        if has_upper:
            return '上引紅'
        if has_lower:
            return '下引紅'
        return '紅實體'
    else:
        if change_pct < -5.0 and not has_upper and not has_lower:
            return '長黑棒'
        if has_upper and has_lower:
            return '上下引黑'
        if has_upper:
            return '上引黑'
        if has_lower:
            return '下引黑'
        return '黑實體'


def shape_to_emoji(shape):
    """K線形狀轉顯示用emoji"""
    mapping = {
        '長紅棒': '🔴📈',
        '紅實體': '🔴▌',
        '上引紅': '🔴↑',
        '下引紅': '🔴↓',
        '上下引紅': '🔴↕',
        '長黑棒': '🟢📉',
        '黑實體': '🟢▌',
        '上引黑': '🟢↑',
        '下引黑': '🟢↓',
        '上下引黑': '🟢↕',
        '十字線': '⚪＋',
        '—': '—'
    }
    return mapping.get(shape, '❓')


def run_screening(csv_path=None, skip_finmind=False, rows=None):
    """執行完整三層篩選
    
    csv_path: XQ CSV 路徑（相容舊模式）
    rows: 直接傳入 list[dict]（從 local_market_loader 取得）
    """
    if csv_path:
        with open(csv_path, 'r', encoding='big5', errors='replace') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # ── 欄位名稱修正：CSV 的 Big5 編碼欄位名 vs 程式用的中文欄位名 ──
        FIELD_MAP = {
            '¥N½X': '代碼', '°Ó«~': '商品', '²£·~': '產業',
            '¬Q¦¬': '收盤價', '¶}½L': '開盤價', '³Ì°ª': '最高價', '³Ì§C': '最低價',
            'º¦¶^': '漲跌', 'º¦´T%': '漲幅%', '®¶´T%': '振幅%', 'Á`¶q': '總量',
            'ªk¤H¶R½æ¶W': '法人買賣超', '¥~¸ê¶R½æ¶W': '外資買賣超',
            '§ë«H¶R½æ¶W': '投信買賣超', '¦ÛÀç°Ó¶R½æ¶W': '自營商買賣超',
            '¤@¶g%': '一週%', '¤@¤ë%': '一月%', '¤@©u%': '一季%',
            '¤­¤é§¡¶q': '五日均量', '¶q¤ñ': '量比', '´«¤â²v%': '換手率%',
        }
        sample_keys = list(rows[0].keys()) if rows else []
        first_key = sample_keys[0] if sample_keys else ''
        if first_key in FIELD_MAP:
            mapped_rows = []
            for row in rows:
                new_row = {}
                for k, v in row.items():
                    new_key = FIELD_MAP.get(k, k)
                    new_row[new_key] = v
                mapped_rows.append(new_row)
            rows = mapped_rows
            print(f"   🔄 CSV 欄位名已重新對應（latin1 → 中文）")
    else:
        if rows is None:
            print(f"❌ 必須提供 csv_path 或 rows")
            return
    
    print(f"📊 全市場: {len(rows)} 檔")
    
    # ── 環境濾網：極端單邊日偵測 ──
    is_extreme_up, extreme_ratio = detect_extreme_up_day(rows)
    if is_extreme_up:
        print(f"⚠️  極端單邊大漲日偵測：全市場 {extreme_ratio*100:.0f}% 收紅 → 隔日篩選需 vol_ratio>{EXTREME_UP_VOL_RATIO}")
    
    # ── Pass 1 ──
    p1_passed = []
    p1_rejected = {'漲幅': 0, '振幅': 0, '暴跌': 0, '量能': 0, '量比': 0, '排除': 0}
    for row in rows:
        ok, reason = pass1_technical(row)
        if ok:
            p1_passed.append(row)
        else:
            if reason:
                if '漲幅' in reason:
                    p1_rejected['漲幅'] += 1
                elif '振幅' in reason:
                    p1_rejected['振幅'] += 1
                elif '暴跌' in reason or '跌幅' in reason:
                    p1_rejected['暴跌'] += 1
                elif '量比' in reason:
                    p1_rejected['量比'] += 1
                elif '量能' in reason or '均量' in reason:
                    p1_rejected['量能'] += 1
                else:
                    p1_rejected['排除'] += 1
    
    print(f"\n📌 Pass 1（技術面）:")
    print(f"   通過: {len(p1_passed)} 檔")
    print(f"   淘汰: 漲幅{p1_rejected['漲幅']} / 振幅{p1_rejected['振幅']} / 暴跌{p1_rejected['暴跌']} / 量比不足{p1_rejected['量比']} / 量能{p1_rejected['量能']} / 排除{p1_rejected['排除']}")
    
    # ── 量比>3 異常檢查（NotebookLM：量增價平需警惕） ──
    for row in p1_passed:
        status, detail = check_high_vol_price_divergence(row)
        if status == 'divergent':
            name = row.get('商品', '')
            code = row.get('代碼', '')
            print(f"   ⚠️  [{code}] {name} — {detail}（量增價平，建議減碼）")
    
    # ── Pass 2 ──
    p2_passed = []
    p2_details = []
    total_positive_foreign = 0
    total_positive_investment = 0
    total_positive_both = 0
    for row in p1_passed:
        ok, info = pass2_institutional(row)
        if ok:
            p2_passed.append(row)
            p2_details.append(info)
            if info['外資買賣超'] > 0 and info['投信買賣超'] > 0:
                total_positive_both += 1
            elif info['外資買賣超'] > 0:
                total_positive_foreign += 1
            elif info['投信買賣超'] > 0:
                total_positive_investment += 1
    
    print(f"\n📌 Pass 2（法人籌碼）:")
    print(f"   通過: {len(p2_passed)} 檔")
    print(f"   外資+投信都買超: {total_positive_both}")
    print(f"   僅外資買超: {total_positive_foreign}")
    print(f"   僅投信買超: {total_positive_investment}")
    
    # ── Pass 3 ──
    p3_passed = []
    p3_details = []
    p3_rejected_history = 0
    p3_rejected_turnover = 0
    for i, row in enumerate(p2_passed):
        ok, info = pass3_history(row)
        if ok:
            p3_passed.append(row)
            p3_details.append({**p2_details[i], **info})
        else:
            if '噴出' in str(info) or '過熱' in str(info):
                p3_rejected_history += 1
            elif '換手率' in str(info):
                p3_rejected_turnover += 1
    
    print(f"\n📌 Pass 3（歷史表現）:")
    print(f"   通過: {len(p3_passed)} 檔")
    print(f"   淘汰: 短線已噴出{p3_rejected_history} / 換手率過高{p3_rejected_turnover}")
    
    # ── 輸出結果 ──
    print(f"\n{'='*60}")
    print(f"🏆 最終候選股池: {len(p3_passed)} 檔")
    print(f"{'='*60}")
    
    candidates = []
    today_str = datetime.now().strftime('%Y-%m-%d')
    for i, row in enumerate(p3_passed):
        code = row.get('代碼', '')
        name = row.get('商品', '')
        industry = row.get('產業', '')
        open_p = parse_float(row.get('開盤'))
        high = parse_float(row.get('最高'))
        low = parse_float(row.get('最低'))
        close = parse_float(row.get('成交'))
        change = parse_float(row.get('漲幅%'))
        amp = parse_float(row.get('振幅%'))
        vol = parse_float(row.get('總量'))
        vol_ratio = parse_float(row.get('量比'))
        detail = p3_details[i]

        # K 線形狀
        shape = classify_k_shape(open_p, high, low, close)
        shape_icon = shape_to_emoji(shape)
        
        cand = {
            '代碼': code,
            '商品': name,
            '產業': industry,
            '成交': close,
            '漲幅%': change,
            '振幅%': amp,
            '總量': int(vol),
            '量比': vol_ratio,
            '外資': detail.get('外資買賣超', 0),
            '投信': detail.get('投信買賣超', 0),
            '自營商': detail.get('自營商買賣超', 0),
            '法人合計': detail.get('法人合計', 0),
            '一週%': detail.get('一週%', 0),
            '一月%': detail.get('一月%', 0),
            '換手率%': detail.get('換手率%', 0),
            '試撮價': parse_float(row.get('試撮價')),
            '試撮量': parse_int(row.get('試撮量')),
            'shape': shape,  # K線形狀
        }
        
        # 標記
        tags = []
        if detail.get('外資買賣超', 0) > 0 and detail.get('投信買賣超', 0) > 0:
            tags.append('📗 法人合買')
        elif detail.get('外資買賣超', 0) > 0:
            tags.append('🔵 外資主買')
        elif detail.get('投信買賣超', 0) > 0:
            tags.append('🔴 投信主買')
        
        vol_tag = detail.get('一週%', 0)
        if vol_tag < 2 and vol_tag > -2:
            tags.append('📊 橫盤整理')
        elif vol_tag > 5:
            tags.append('⬆️ 短線偏強')
        
        cand['tags'] = tags
        
        candidates.append(cand)
        
        print(f"\n  {i+1}. [{code}] {name}")
        print(f"     產業: {industry} | 成交: {close} | 漲跌: {change:+.1f}% | K線: {shape_icon} {shape}")
        print(f"     振幅: {amp:.1f}% | 總量: {int(vol):,}張 | 量比: {vol_ratio:.2f}")
        print(f"     法人: 外資{detail.get('外資買賣超', 0):+,} / 投信{detail.get('投信買賣超', 0):+,} / 自營{detail.get('自營商買賣超', 0):+,}")
        print(f"     一週: {detail.get('一週%', 0):+.1f}% | 一月: {detail.get('一月%', 0):+.1f}%")
        print(f"     試撮: {parse_float(row.get('試撮價'))} / {parse_int(row.get('試撮量'))}張")
        if tags:
            print(f"     標記: {' '.join(tags)}")
    
    # ── 載入前一天的 pool 以比對剔除 & 繼承 days + snapshots ──
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')

    prev_pool_path = os.path.join(_BASE, 'data', 'stock_pool.json')
    prev_pool = {'pool': [], 'kicked_log': []}
    if os.path.exists(prev_pool_path):
        try:
            with open(prev_pool_path, 'r', encoding='utf-8') as f:
                prev_pool = json.load(f)
        except (json.JSONDecodeError, KeyError):
            prev_pool = {'pool': [], 'kicked_log': []}

    prev_items = prev_pool.get('pool', [])
    prev_days = {}     # code -> days
    prev_names = {}    # code -> name
    prev_snapshots = {}  # code -> [snapshots array]
    prev_added_dates = {}  # code -> added_date
    prev_last_signal_dates = {}  # code -> last_signal_date
    for item in prev_items:
        if 'days' in item:
            prev_days[item['code']] = item['days']
        prev_names[item['code']] = item.get('name', '')
        if 'snapshots' in item:
            prev_snapshots[item['code']] = item['snapshots']
        else:
            prev_snapshots[item['code']] = []
        if 'added_date' in item:
            prev_added_dates[item['code']] = item['added_date']
        if 'last_signal_date' in item:
            prev_last_signal_dates[item['code']] = item['last_signal_date']

    kicked_log = prev_pool.get('kicked_log', [])
    
    # ── 找出本日被剔除的股票 ──
    today_codes = {c['代碼'] for c in candidates}
    kicked_today = []
    for item in prev_items:
        code = item['code']
        if code not in today_codes:
            # 找出被踢的原因（看前一天的數據）—— 先記錄，後續可在 CSV 中追蹤
            kicked_today.append({
                'code': code,
                'name': prev_names.get(code, item.get('name', '')),
                'date': today_str,
                'days_in_pool': prev_days.get(code, 0),
                'reason': '未通過當日篩選'
            })
            kicked_log.append({
                'code': code,
                'name': prev_names.get(code, item.get('name', '')),
                'kicked_date': today_str,
                'days_in_pool': prev_days.get(code, 0),
                'reason': '未通過當日篩選'
            })
    
    if kicked_today:
        print(f"\n📌 本日剔除 {len(kicked_today)} 檔:")
        for k in kicked_today:
            print(f"   ❌ [{k['code']}] {k['name']} (在池 {k['days_in_pool']} 天)")
    
    # ── 輸出 JSON ──
    output_dir = os.path.dirname(os.path.abspath(csv_path)) if csv_path else _BASE
    json_path = os.path.join(output_dir, 'xq_pool_result.json')
    
    result = {
        'date': today_str,
        'source': os.path.basename(csv_path) if csv_path else 'local_market_loader',
        'summary': {
            'total': len(rows),
            'pass1': len(p1_passed),
            'pass2': len(p2_passed),
            'pass3': len(p3_passed),
            'candidates': len(candidates)
        },
        'candidates': candidates
    }
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # ── 更新 stock_pool.json（含 days 繼承 + snapshots + kicked_log） ──
    pool_path = os.path.join(_BASE, 'data', 'stock_pool.json')
    pool_entries = []
    for c in candidates:
        code = c['代碼']
        name = c['商品']
        # days = 日曆天（從 added_date 到今天的實際天數）
        added = prev_added_dates.get(code)
        if added:
            try:
                added_dt = datetime.strptime(added, '%Y-%m-%d')
                days = (today - added_dt).days + 1  # +1 讓今天也算一天
            except:
                days = 1
        else:
            days = 1

        # 繼承時間衰退欄位
        added_date = prev_added_dates.get(code)
        last_signal_date = prev_last_signal_dates.get(code)

        # 新進池的股票：設 added_date = 今天
        if not added_date:
            added_date = today_str

        # 判斷本日是否有"觸發訊號"（更新 last_signal_date）
        # 定義：只要今天通過 Pass 篩選且 Pool 中有該股票，就算持續活躍
        # 更嚴格的定義：有新的結構突破或交易條件觸發，但這裡無法判斷
        # 最保守：只要還在池裡，就算今天活躍，更新 last_signal_date
        last_signal_date = today_str

        # 繼承或初始化 snapshots
        prev_snap = prev_snapshots.get(code, [])
        # 避免重複寫入同一天（如果 CSV 是同一天的同一批資料）
        today_snapshot = {'date': today_str, 'shape': c.get('shape', '—')}
        if not prev_snap or prev_snap[-1]['date'] != today_str:
            prev_snap.append(today_snapshot)

        pool_entries.append({
            'code': code,
            'name': name,
            'days': days,
            'added_date': added_date,
            'last_signal_date': last_signal_date,
            'snapshots': prev_snap
        })
    
    # ── 動能前濾網（規則 4 提前執行，不需要 FinMind） ──
    # 目的：先把動能不足的股票濾掉，減少 FinMind API 消耗
    # 規則：一週% <= 0 或 一月% <= 0 → 踢（資金流出，不進場）
    candidate_momentum = {c['代碼']: (float(c.get('一週%') or 0), float(c.get('一月%') or 0)) for c in candidates}
    momentum_prekicked = []
    before_count = len(pool_entries)
    for entry in pool_entries[:]:
        code = entry['code']
        week_ret, month_ret = candidate_momentum.get(code, (0, 0))
        if month_ret <= 0 or week_ret <= 0:
            reason = f'weak_momentum: 一週={week_ret:+.1f}% / 一月={month_ret:+.1f}%（資金流出，不進場）'
            momentum_prekicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'reason': reason})
            kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': entry.get('days', 1), 'reason': reason})
            pool_entries.remove(entry)
    if momentum_prekicked:
        print(f"\n🔴 動能前濾網：踢除 {len(momentum_prekicked)} 檔（{before_count} → {len(pool_entries)}）")
        for k in momentum_prekicked:
            print(f"   ❌ [{k['code']}] {k['name']} — {k['reason']}")

    # ── 板塊資金流分析（在動能前濾網之後、FinMind 之前） ──
    # 根據板塊動量強度調整候選股配額
    after_sector = len(pool_entries)  # 預設值，防止 pool 為空時未定義
    sector_kicked = []
    before_sector = len(pool_entries)
    if pool_entries:
        # 建立 DataFrame 供 sector 分析使用
        sector_df_rows = []
        for e in pool_entries:
            week = float(candidate_momentum.get(e['code'], (0, 0))[0] or 0)
            month = float(candidate_momentum.get(e['code'], (0, 0))[1] or 0)
            quarter = float(e.get('一季%', 0) or 0)
            sector = classify_sector(e['code'])
            sector_df_rows.append({
                '代碼': e['code'],
                'name': e.get('name', ''),
                'sector': sector,
                '一週%': week,
                '一月%': month,
                '一季%': quarter,
            })
        sector_df = pd.DataFrame(sector_df_rows)

        # 計算各板塊分數
        sector_scores = compute_sector_flow_from_xq(sector_df)

        # 分配配額
        sector_counts = sector_df['sector'].value_counts().to_dict()
        sector_slots = allocate_sector_slots(sector_scores, sector_counts, len(sector_df))

        # 印摘要
        print(f"\n{'='*50}")
        print(f"📊 板塊資金流分析（輪動加權：近週×0.5 + 近月×0.4 + 近季×0.1）")
        print(f"{'='*50}")
        all_sorted = sorted(sector_scores.items(), key=lambda x: -x[1])
        trend_up = []    # 分數 > 0
        trend_down = []  # 分數 ≤ 0
        for s, score in all_sorted:
            label = sector_label(s)
            is_active = s in sector_slots
            slot_count = sector_slots.get(s, 0)
            if is_active:
                print(f"   ✅ {label}: 分數 {score:+.2f}% ↑，保留 {slot_count} 檔")
                trend_up.append(label)
            else:
                print(f"   🚫 {label}: 分數 {score:+.2f}% ↓，資金流出不進場")
                trend_down.append(label)

        # 輪動方向摘要
        if trend_up:
            arrow = " → ".join(trend_up)
            print(f"\n💡 資金輪動方向：{arrow}")
        if trend_down:
            print(f"⚠️  資金流出板塊：{'、'.join(trend_down)}")

        # 依配額篩選（每板塊取一個月%最高的）
        if sector_slots:
            kept_entries = []
            for s, max_slot in sector_slots.items():
                if max_slot <= 0:
                    continue
                # 找 this sector 的 entries
                sector_entries = [e for e in pool_entries
                                   if classify_sector(e['code']) == s]
                # 按一月%排序取 top
                sector_entries.sort(
                    key=lambda e: -float(candidate_momentum.get(e['code'], (0, 0))[1] or 0)
                )
                for e in sector_entries[:max_slot]:
                    kept_entries.append(e)
                # 統計被踢的
                for e in sector_entries[max_slot:]:
                    sector_kicked.append({
                        'code': e['code'],
                        'name': e.get('name', ''),
                        'reason': f'sector_tilt: {label} 板塊配額已滿（{len(sector_entries)}選{max_slot}）'
                    })
            pool_entries = kept_entries

        after_sector = len(pool_entries)
        print(f"板塊過濾後剩餘：{after_sector} 檔（前 {before_sector} → {after_sector}）")
        for k in sector_kicked:
            print(f"   ❌ [{k['code']}] {k['name']} — {k['reason']}")
            kicked_log.append({**k, 'kicked_date': today_str, 'days_in_pool': 0})

        # ── 上引線降溫指標（NotebookLM：本週新洞見）──────────────
        # 若股池中「上引線型」K線佔比 >60%，隔日衝高回落機率高，應降低買入上限
        upper_shadow_shapes = {'上引紅', '上下引紅', '上引黑', '上下引黑'}
        if pool_entries:
            upper_shadow_count = sum(
                1 for e in pool_entries
                if e.get('shape') in upper_shadow_shapes
            )
            upper_shadow_pct = upper_shadow_count / len(pool_entries) * 100
            print(f"\n🔍 上引線降溫指標：上引線型 {upper_shadow_count}/{len(pool_entries)} ({upper_shadow_pct:.0f}%)")
            if upper_shadow_pct > 60:
                print(f"   ⚠️  上引線型>{upper_shadow_pct:.0f}% (>60%)，降低買入上限至50%")
                # 暫時標記，後續配額決策時參考（此地只印出警告，不改 pool_entries）
        else:
            upper_shadow_pct = 0

        # ── 一日遊淘汰指標（NotebookLM：本週新洞見）──────────────
        # 若踢出名單中 days_in_pool=1 的股票佔總數 >25%，代表動能極短
        if kicked_log:
            recent_kicked = [k for k in kicked_log if k.get('kicked_date') == today_str]
            one_day_kicks = [k for k in recent_kicked if k.get('days_in_pool', 99) == 1]
            if recent_kicked:
                one_day_pct = len(one_day_kicks) / len(recent_kicked) * 100
                print(f"\n🔍 一日遊淘汰指標：{len(one_day_kicks)}/{len(recent_kicked)} ({one_day_pct:.0f}%)")
                if one_day_pct > 25:
                    print(f"   ⚠️  一日遊>{one_day_pct:.0f}% (>25%)，隔日不觸發任何新買入")
        else:
            one_day_pct = 0

        # ── Pool 活性門檻（<3 檔僅觀察）────────────────────────
        if after_sector < 3:
            print(f"\n⚠️  篩選結果僅 {after_sector} 檔，觸發「僅觀察、不下單」模式")

    # ── 地端 K 線特徵引擎（在板塊分析後、FinMind 前執行） ──
    print(f"\n{'='*50}")
    print(f"📈 地端 K 線特徵引擎（最近40根日K + MA計算）")
    print(f"{'='*50}")
    pool_entries, kicked_log = local_feature_engine(
        pool_entries, candidates, today_str, kicked_log
    )
    after_kline = len(pool_entries)
    print(f"K 線特徵引擎後剩餘：{after_kline} 檔")
    
    # ── M 頭市場級過濾器（2026-05-31 新增） ──
    # 檢查今天有多少檔因 M 頭被踢除，若 >50% 則代表市場結構轉弱
    # ⚠️ 修正：mhead_kicked 必須也用 today_str 過濾，否則分子是累積值、分母是今日值，比例會爆掉
    kicked_log_today = [k for k in kicked_log if k.get('kicked_date') == today_str]
    mhead_kicked = [k for k in kicked_log_today if 'M頭' in str(k.get('reason', ''))]
    total_kicked_today = len(kicked_log_today)
    if total_kicked_today > 0:
        mhead_ratio = len(mhead_kicked) / total_kicked_today
        if mhead_ratio > MHEAD_KICK_THRESHOLD:
            print(f"\n🔴 M 頭市場級警報：本日 {len(mhead_kicked)}/{total_kicked_today} 檔因 M 頭被踢除 ({mhead_ratio*100:.0f}%)")
            print(f"   ⚠️  市場結構轉弱，隔日應自動禁用新買入")
            # 寫入環境狀態檔供隔日 cron 讀取
            env_state = {
                'date': today_str,
                'mhead_kick_ratio': round(mhead_ratio, 3),
                'total_kicked': total_kicked_today,
                'mhead_kicked': len(mhead_kicked),
                'block_new_buy': True,
                'extreme_up_day': is_extreme_up,
                'extreme_ratio': round(extreme_ratio, 3)
            }
            env_state_path = os.path.join(_BASE, 'data', 'market_env_state.json')
            try:
                with open(env_state_path, 'w', encoding='utf-8') as f:
                    json.dump(env_state, f, ensure_ascii=False, indent=2)
                print(f"   📝 環境狀態已寫入 {env_state_path}")
            except Exception as e:
                print(f"   ⚠️  寫入環境狀態失敗: {e}")
    
    # ── 如果 --skip-finmind，存中間檔然後結束 ──
    if skip_finmind:
        # 存 sector_filtered_pool.json（板塊過濾後的中間結果）
        sector_pool_path = os.path.join(_BASE, 'data', 'sector_filtered_pool.json')
        sector_pool_output = {
            'date': today_str,
            'source': os.path.basename(csv_path) if csv_path else 'local_market_loader',
            'summary': {
                'total': len(rows),
                'pass1': len(p1_passed),
                'pass2': len(p2_passed),
                'pass3': len(p3_passed),
                'candidates': len(candidates),
                'after_momentum': after_sector,  # 動能前濾網後
                'after_sector': after_sector,    # 板塊過濾後（板塊分析已結束）
                'after_kline': after_kline,       # K 線特徵引擎後
            },
            'pool_entries': pool_entries,        # 板塊過濾後的 pool
            'candidates': candidates,             # 原始 candidates（含 XQ 完整資料）
            'kicked_log': kicked_log,
        }
        # 也寫入 xq_pool_result.json 讓其他流程可以讀
        result = {
            'date': today_str,
            'source': os.path.basename(csv_path) if csv_path else 'local_market_loader',
            'summary': {
                'total': len(rows),
                'pass1': len(p1_passed),
                'pass2': len(p2_passed),
                'pass3': len(p3_passed),
                'candidates': len(candidates)
            },
            'candidates': candidates
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        with open(sector_pool_path, 'w', encoding='utf-8') as f:
            json.dump(sector_pool_output, f, ensure_ascii=False, indent=2)
        print(f"\n📁 xq_pool_result.json 已存檔: {json_path}")
        print(f"📁 sector_filtered_pool.json 已存檔: {sector_pool_path}")
        print(f"   ⏸ 板塊分析已完成，等待老闆下達啟動 FinMind 指令")
        print(f"   下次請執行: python3 {sys.argv[0]} --resume")
        return candidates

    # ── 對 pool 每檔執行技術結構分析（三窗格支撐壓力 + 型態） ──
    # 分批處理：每批 20 檔，中間暫停 2 秒，避免 FinMind API rate limit
    if skip_finmind:
        print(f"\n⏭ FinMind 已跳過（--skip-finmind），直接進入第二階段篩選")
        print(f"   板塊過濾後：{len(pool_entries)} 檔")
        pool_for_finmind = []  # 空，不送 FinMind
    elif HAS_FEATURE_EXTRACTOR and pool_entries:
        enriched_count = 0
        fail_count = 0
        batch_size = 20
        pause_between_batch = 2
        print(f"\n🔬 技術結構分析中（{len(pool_entries)} 檔，FinMind API）...")
        for i in range(0, len(pool_entries), batch_size):
            batch = pool_entries[i:i+batch_size]
            for entry in batch:
                code = entry['code']
                try:
                    extractor = MarketFeatureExtractor(volume_threshold=0.5)
                    windows = {'window_5': 5, 'window_10': 10, 'window_20': 20}
                    structure = {}
                    for w_key, w_val in windows.items():
                        extractor.window = w_val
                        if extractor.load_from_api(code, days=365, source='finmind'):
                            result = extractor.analyze()
                            if 'error' not in result:
                                structure[w_key] = {
                                    'supports': [s['price'] for s in result['key_levels']['supports']],
                                    'resistances': [r['price'] for r in result['key_levels']['resistances']],
                                    'rr': result['risk_reward'].get('ratio', 0) if result.get('risk_reward') else 0,
                                    'patterns': [p['type'] for p in result['detected_patterns']],
                                    'volume_signals': [{'type': v['type'], 'note': v['note']}
                                                        for v in result.get('volume_signals', [])]
                                }
                                all_vs = structure[w_key].get('volume_signals', [])
                                if all_vs:
                                    if 'volume_signals' not in entry:
                                        entry['volume_signals'] = []
                                    for vs in all_vs:
                                        if vs not in entry['volume_signals']:
                                            entry['volume_signals'].append(vs)
                            else:
                                structure[w_key] = None
                        else:
                            structure[w_key] = None
                    entry['structure'] = structure if any(v for v in structure.values()) else None
                    enriched_count += 1
                except Exception as e:
                    fail_count += 1
                    entry['structure'] = None
            # 每批處理完畢，印進度並暫停
            done = min(i + batch_size, len(pool_entries))
            print(f"   ...已完成 {done}/{len(pool_entries)} 檔")
            if done < len(pool_entries):
                import time; time.sleep(pause_between_batch)
        print(f"   ✅ 分析完成: {enriched_count} 檔成功{f' / {fail_count} 檔失敗' if fail_count else ''}")

    # ── 第二階段踢出檢查（規則 1→2→3→4，順序不可調） ──
    # 順序邏輯：
    # 規則 1：時間衰退 → 太久沒動就踢
    # 規則 2：長線結構破壞 → 跌破 w20 核心支撐就踢
    # 規則 3：Pattern 否決 → M頭 / W底 不適合順勢波段，出貨訊號直接踢
    # 規則 4：動能過濾 → 一月%<=0 或一週%<=0 代表資金流出，不進
    # 規則 5：RR 區間過濾 → RR 門檻值（0.0 ~ 15），排除高RR陷阱（>15=跌無可跌）和零RR（完全沒空間）
    # 規則 6：雞蛋水餃股 → 現價<10元 且 RR>20 直接踢
    candidate_close = {c['代碼']: c['成交'] for c in candidates}
    candidate_momentum = {c['代碼']: (float(c.get('一週%') or 0), float(c.get('一月%') or 0)) for c in candidates}
    auto_kicked = []
    for entry in pool_entries[:]:
        code = entry['code']
        close = candidate_close.get(code)
        if close is None:
            continue
        week_ret, month_ret = candidate_momentum.get(code, (0, 0))

        # 規則 1：時間衰退
        added_date = entry.get('added_date', today_str)
        last_signal = entry.get('last_signal_date', today_str)
        days_in_pool = entry.get('days', 1)
        if days_in_pool > 10:
            try:
                last_dt = datetime.strptime(last_signal, '%Y-%m-%d')
                days_since_signal = (today - last_dt).days
                if days_since_signal >= 10:
                    reason = 'time_decay: 進池超過10天無觸發訊號'
                    auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    pool_entries.remove(entry)
                    continue
            except (ValueError, TypeError):
                pass

        # 規則 2：長線結構破壞（跌破 w20 核心支撐，2% buffer）
        structure = entry.get('structure') or {}
        w20 = structure.get('window_20') or {}
        w20_supports = w20.get('supports', [])
        if w20_supports:
            w20_core_support = min(w20_supports)
            if close < (w20_core_support * 0.98):
                reason = 'long_term_breakdown: 收盤跌破w20支撐(2% buffer)'
                auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                pool_entries.remove(entry)
                continue

        # 規則 3：Pattern 否決（M頭 = 順勢波段否定，出貨訊號 = 主力倒貨）
        all_patterns = []
        all_vs_types = []
        for wk in ['window_5', 'window_10', 'window_20']:
            w_struct = structure.get(wk) or {}
            all_patterns.extend(w_struct.get('patterns', []))
            all_vs_types.extend([v.get('type', '') for v in w_struct.get('volume_signals', [])])
        for vs in entry.get('volume_signals', []):
            all_vs_types.append(vs.get('type', ''))
        # Pattern 否決：M頭 直接踢
        if 'M頭' in all_patterns:
            reason = 'pattern_veto: M頭型態（上方套牢賣壓過重，不適合順勢波段）'
            auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
            kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
            pool_entries.remove(entry)
            continue
        # 出貨訊號否決：有出貨且無吃貨 → 踢
        has_distribution = '出貨' in all_vs_types
        has_accumulation = '吃貨' in all_vs_types
        if has_distribution and not has_accumulation:
            reason = 'distribution_veto: 有出貨訊號且無吃貨（主力在倒貨）'
            auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
            kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
            pool_entries.remove(entry)
            continue

        # 規則 4：動能過濾（已提前到 FinMind 前執行，此處跳過避免重複）
        # 提前執行位置：動能前濾網區塊（在「─ 對 pool 每檔執行技術結構分析」之前）
        pass

        # 規則 5：RR 區間過濾（門檻值，不是求最大）
        # 前提：需要有 FinMind 結構資料。structure=null 時跳過（不該用 RR=0 踢除）
        if structure:
            w5 = structure.get('window_5') or {}
            rr = float(w5.get('rr', 0) or 0)
            if rr <= 0.0 or rr > 15.0:
                if rr > 15.0:
                    reason = f'high_rr_trap: RR={rr:.1f}>15（跌無可跌，高RR陷阱）'
                elif rr <= 0.0:
                    reason = f'low_rr: RR={rr:.2f}（完全沒空間）'
                auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                pool_entries.remove(entry)
                continue

            # 規則 6：雞蛋水餃股（現價 < 10 元且 RR > 20）
            if close and close < 10 and rr > 20:
                reason = 'junk_stock: 現價<10元且RR>20（雞蛋水餃股，流動性差）'
                auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                pool_entries.remove(entry)
                continue
        # 暫時註解掉，等 FinMind API 恢復後再啟用含位階判斷的版本
        # ── 下面這段啟用後會取代為 `check_distribution_only()` 函數 ──
        # all_entry_vs = set()
        # for wk in ['window_5', 'window_10', 'window_20']:
        #     w = structure.get(wk) or {}
        #     for vs in w.get('volume_signals', []):
        #         all_entry_vs.add(vs.get('type', ''))
        # for vs in entry.get('volume_signals', []):
        #     all_entry_vs.add(vs.get('type', ''))
        # has_distribution = '出貨' in all_entry_vs or 'distribution' in str(all_entry_vs).lower()
        # has_accumulation = '吃貨' in all_entry_vs or 'accumulation' in str(all_entry_vs).lower()
        # if has_distribution and not has_accumulation:
        #     reason = 'distribution_only: 有出貨訊號且無吃貨訊號'
        #     auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
        #     kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
        #     pool_entries.remove(entry)
            continue

    if auto_kicked:
        print(f"\n🔴 自動踢除 {len(auto_kicked)} 檔（第二階段規則）:")
        for k in auto_kicked:
            print(f"   ❌ [{k['code']}] {k['name']} — {k['reason']}")
    else:
        print(f"\n🔴 自動踢除: 0 檔（全部符合保留條件）")

    # ── 依技術結構篩選優先級 ──
    def _rr(entry):
        w5 = (entry.get('structure', {}) or {}).get('window_5', {}) or {}
        return float(w5.get('rr', 0) or 0)
    pool_entries.sort(key=lambda e: -_rr(e))
    pool_output = {
        'date': today_str,
        'source': 'xq_screener.py from XQ EOD CSV (3-pass filter)',
        'total_candidates': len(pool_entries),
        'pool': pool_entries,
        'kicked_log': kicked_log
    }
    
    with open(pool_path, 'w', encoding='utf-8') as f:
        json.dump(pool_output, f, ensure_ascii=False, indent=2)
    
    print(f"\n📁 xq_pool_result.json 已存檔: {json_path}")
    print(f"📁 stock_pool.json 已更新: {len(pool_entries)} 檔 🗑 累積剔除紀錄: {len(kicked_log)} 筆")
    
    # ── 輸出成交量異常統計 ──
    vol_count = {'吃貨': 0, '出貨': 0, '量窒息': 0}
    for e in pool_entries:
        vs_list = e.get('volume_signals', [])
        for vs in vs_list:
            vtype = vs.get('type', '')
            if vtype in vol_count:
                vol_count[vtype] += 1
    if sum(vol_count.values()) > 0:
        vol_summary = ' | '.join(f"{k}: {v}" for k, v in vol_count.items() if v > 0)
        print(f"📊 成交量異常: {vol_summary}")
    
    return candidates


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='XQ 股池篩選')
    parser.add_argument('csv_path', nargs='?', help='XQ CSV 檔案路徑（第一段使用）')
    parser.add_argument('--skip-finmind', action='store_true', help='跳過 FinMind，只跑到板塊過濾（第一段）')
    parser.add_argument('--resume', action='store_true', help='從 sector_filtered_pool.json 接續執行 FinMind（第二段）')
    parser.add_argument('--from-loader', action='store_true', help='使用 local_market_loader.py 取代 XQ CSV')
    parser.add_argument('--date', type=str, default=None, help='指定日期 YYYYMMDD（配合 --from-loader）')
    parser.add_argument('--await-finmind', action='store_true', help='跑完 Pass1 後停下，等老闆說可以送再批次送 FinMind 法人資料')
    parser.add_argument('--send-finmind', action='store_true', help='讀取 finmind_pending.json，分批送 FinMind 法人資料（每批50檔）')
    args = parser.parse_args()

    # ── 獨立模式：分批送 FinMind 法人資料（每批50檔，等老闆確認才送下一批）──
    if args.send_finmind:
        from local_market_loader import LocalMarketLoader
        import json as json_mod

        pending_path = os.path.join(_BASE, 'data', 'finmind_pending.json')
        if not os.path.exists(pending_path):
            print("❌ finmind_pending.json 不存在，請先跑 --await-finmind 產生待送的股票列表")
            sys.exit(1)

        with open(pending_path, 'r', encoding='utf-8') as f:
            pending_data = json_mod.load(f)

        all_codes = pending_data['codes']
        date_str = pending_data.get('date', '20260527')
        total = len(all_codes)

        # 每次只送第一批（50檔）
        batch_size = 50
        batch_codes = all_codes[:batch_size]
        remaining_codes = all_codes[batch_size:]

        loader2 = LocalMarketLoader()
        print(f"📋 FinMind 法人資料：共 {total} 檔，本批送 {len(batch_codes)} 檔（1-{len(batch_codes)}）")

        inst_data = loader2.fetch_institutional(batch_codes, date_str)

        # 疊加到 finmind_results.json
        result_path = os.path.join(_BASE, 'data', 'finmind_results.json')
        existing = {}
        if os.path.exists(result_path):
            with open(result_path, 'r', encoding='utf-8') as f:
                existing = json_mod.load(f)

        existing.update(inst_data)
        with open(result_path, 'w', encoding='utf-8') as f:
            json_mod.dump(existing, f, ensure_ascii=False, indent=2)

        # 更新 finmind_pending.json（移除已送的）
        if remaining_codes:
            pending_data['codes'] = remaining_codes
            pending_data['remaining'] = len(remaining_codes)
            with open(pending_path, 'w', encoding='utf-8') as f:
                json_mod.dump(pending_data, f, ensure_ascii=False, indent=2)
            print(f"✅ 本批 {len(batch_codes)} 檔已寫入 finmind_results.json（累計 {len(existing)} 檔）")
            print(f"   ⏸ 還有 {len(remaining_codes)} 檔待送，下批請說「可以送 FinMind」")
        else:
            os.remove(pending_path)
            print(f"✅ 最後一批 {len(batch_codes)} 檔已完成，finmind_pending.json 已刪除")
            print(f"✅ 全部 {len(existing)} 檔已寫入 finmind_results.json")

        sys.exit(0)

    if args.from_loader:
        # ── 從本地 JSON 載入（不含法人，Pass1 後再查） ──
        from local_market_loader import LocalMarketLoader
        loader = LocalMarketLoader()
        rows = loader.load(date_str=args.date, skip_finmind=True)

        # 手動跑 Pass1 取得通過的股票（減少 FinMind/結構分析量）
        p1_passed = []
        for row in rows:
            ok, reason = pass1_technical(row)
            if ok:
                p1_passed.append(row)
        print(f"\n📌 Pass 1（技術面，loader 先行）: {len(p1_passed)} 檔通過")

# 對 Pass1 通過的股票查法人資料
        if p1_passed and args.await_finmind:
            # 等老闆確認後再送：把待查名單寫入 finmind_pending.json，停住
            import json as json_mod
            pending_path = os.path.join(_BASE, 'data', 'finmind_pending.json')
            pending_data = {'codes': [r['代碼'] for r in p1_passed], 'date': args.date or '20260527'}
            with open(pending_path, 'w', encoding='utf-8') as f:
                json_mod.dump(pending_data, f, ensure_ascii=False, indent=2)
            print(f"\n⏸ Awaiting FinMind 授權：已寫入 {pending_path}（{len(p1_passed)} 檔）")
            print(f"   確認要送時，請說「可以送 FinMind」")
            print(f"   指令：python3 xq_screener.py --send-finmind")
            sys.exit(0)
        elif p1_passed and not args.skip_finmind:
            p1_codes = [r['代碼'] for r in p1_passed]
            inst_data = loader.fetch_institutional(p1_codes, args.date or '20260527')
            for row in rows:
                code = row['代碼']
                if code in inst_data:
                    row.update(inst_data[code])
                else:
                    row.update({'外援買賣超': 0, '投信買賣超': 0, '自營商買賣超': 0, '法人買賣超': 0})
        elif args.skip_finmind:
            # 純技術篩選模式：給 Pass1 通過的股票一個最小法人值，
            # 讓它們能通過 Pass2 門檻，後續全憑結構分析決定去留
            for row in rows:
                code = row['代碼']
                if code in {r['代碼'] for r in p1_passed}:
                    row.update({'外資買賣超': 1, '投信買賣超': 0, '自營商買賣超': 0, '法人買賣超': 1})
                else:
                    row.update({'外資買賣超': 0, '投信買賣超': 0, '自營商買賣超': 0, '法人買賣超': 0})

        # 跑 run_screening 的基礎篩選（Pass1~Pass3 + 動能 + 板塊 + K線，跳過 FinMind）
        run_screening(rows=rows, skip_finmind=True)

        # ── 本地技術結構分析（0 API，純本地執行）──
        sector_pool_path = os.path.join(_BASE, 'data', 'sector_filtered_pool.json')
        if os.path.exists(sector_pool_path):
            with open(sector_pool_path, 'r', encoding='utf-8') as f:
                sector_data = json.load(f)
            pool_entries = sector_data.get('pool_entries', [])
            kicked_log = sector_data.get('kicked_log', [])
            candidates = sector_data.get('candidates', [])
            today_str = sector_data.get('date', datetime.now().strftime('%Y-%m-%d'))

        print(f"\n{'='*50}")
        print(f"🔬 本地技術結構分析（{len(pool_entries)} 檔，0 API）")
        print(f"{'='*50}")

        date_str = args.date or datetime.now().strftime('%Y%m%d')
        candidate_close = {c['代碼']: c['成交'] for c in candidates}
        candidate_momentum = {c['代碼']: (float(c.get('一週%') or 0), float(c.get('一月%') or 0)) for c in candidates}
        struct_success = 0
        struct_fail = 0

        for entry in pool_entries:
            code = entry['code']
            close_price = candidate_close.get(code)
            try:
                structure = loader.compute_technical_structure(code, current_price=close_price)
                if structure:
                    entry['structure'] = structure
                    entry['volume_signals'] = []
                    for wk in ['window_5', 'window_10', 'window_20']:
                        ws = structure.get(wk) or {}
                        for vs in ws.get('volume_signals', []):
                            if vs not in entry['volume_signals']:
                                entry['volume_signals'].append(vs)
                    struct_success += 1
                else:
                    entry['structure'] = None
                    struct_fail += 1
            except Exception:
                entry['structure'] = None
                struct_fail += 1

        print(f"   ✅ 結構分析: {struct_success} 檔成功 / {struct_fail} 檔失敗")

        # ── 第二階段踢出檢查（規則 1→2→3→4→5→6）──
        today = datetime.now()
        auto_kicked = []
        for entry in pool_entries[:]:
            code = entry['code']
            close = candidate_close.get(code)
            if close is None:
                continue
            week_ret, month_ret = candidate_momentum.get(code, (0, 0))
            added_date = entry.get('added_date', today_str)
            last_signal = entry.get('last_signal_date', today_str)
            days_in_pool = entry.get('days', 1)

            # 規則 1：時間衰退
            if days_in_pool > 10:
                try:
                    last_dt = datetime.strptime(last_signal, '%Y-%m-%d')
                    days_since_signal = (today - last_dt).days
                    if days_since_signal >= 10:
                        reason = 'time_decay: 進池超過10天無觸發訊號'
                        auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                        kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                        pool_entries.remove(entry)
                        continue
                except (ValueError, TypeError):
                    pass

            # 規則 2：長線結構破壞
            structure = entry.get('structure') or {}
            w20 = structure.get('window_20') or {}
            w20_supports = w20.get('supports', [])
            if w20_supports:
                w20_core_support = min(w20_supports)
                if close < (w20_core_support * 0.98):
                    reason = 'long_term_breakdown: 收盤跌破w20支撐(2% buffer)'
                    auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    pool_entries.remove(entry)
                    continue

            # 規則 3：Pattern 否決
            all_patterns = []
            all_vs_types = []
            for wk in ['window_5', 'window_10', 'window_20']:
                w_struct = structure.get(wk) or {}
                all_patterns.extend(w_struct.get('patterns', []))
                all_vs_types.extend([v.get('type', '') for v in w_struct.get('volume_signals', [])])
            for vs in entry.get('volume_signals', []):
                all_vs_types.append(vs.get('type', ''))
            if 'M頭' in all_patterns:
                reason = 'pattern_veto: M頭型態（上方套牢賣壓過重）'
                auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                pool_entries.remove(entry)
                continue
            has_distribution = '出貨' in all_vs_types
            has_accumulation = '吃貨' in all_vs_types
            if has_distribution and not has_accumulation:
                reason = 'distribution_veto: 有出貨訊號且無吃貨'
                auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                pool_entries.remove(entry)
                continue

            # 規則 5：RR 區間過濾
            if structure:
                w5 = structure.get('window_5') or {}
                rr = float(w5.get('rr', 0) or 0)
                if rr <= 0.0 or rr > 15.0:
                    if rr > 15.0:
                        reason = f'high_rr_trap: RR={rr:.1f}>15'
                    elif rr <= 0.0:
                        reason = f'low_rr: RR={rr:.2f}'
                    auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    pool_entries.remove(entry)
                    continue
                # 規則 6：雞蛋水餃股
                if close and close < 10 and rr > 20:
                    reason = 'junk_stock: 現價<10元且RR>20'
                    auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    pool_entries.remove(entry)
                    continue

        if auto_kicked:
            print(f"\n🔴 自動踢除 {len(auto_kicked)} 檔（第二階段規則）:")
            for k in auto_kicked:
                print(f"   ❌ [{k['code']}] {k['name']} — {k['reason']}")
        else:
            print(f"\n🔴 自動踢除: 0 檔（全部符合保留條件）")

        # ── 依 RR 排序 ──
        def _rr(entry):
            w5 = (entry.get('structure', {}) or {}).get('window_5', {}) or {}
            return float(w5.get('rr', 0) or 0)
        pool_entries.sort(key=lambda e: -_rr(e))

        # ── 寫入 stock_pool.json ──
        pool_output = {
            'date': today_str,
            'source': 'local_market_loader (結構分析: 本地68天歷史)',
            'total_candidates': len(pool_entries),
            'pool': pool_entries,
            'kicked_log': kicked_log
        }
        pool_path = os.path.join(_BASE, 'data', 'stock_pool.json')
        with open(pool_path, 'w', encoding='utf-8') as f:
            json.dump(pool_output, f, ensure_ascii=False, indent=2)

        print(f"\n📁 stock_pool.json 已更新: {len(pool_entries)} 檔 🗑 累積剔除紀錄: {len(kicked_log)} 筆")
        print("✅ 完整流程完成（0 API 結構分析）")

    elif args.resume:
        # ── 第二段：從中間檔 resume ──
        sector_pool_path = os.path.join(_BASE, 'data', 'sector_filtered_pool.json')
        if not os.path.exists(sector_pool_path):
            print(f"❌ 找不到中間檔: {sector_pool_path}")
            print(f"   請先執行 python3 xq_screener.py <csv_path> --skip-finmind 完成板塊分析")
            sys.exit(1)
        with open(sector_pool_path, 'r', encoding='utf-8') as f:
            sector_data = json.load(f)
        
        pool_entries = sector_data.get('pool_entries', [])
        kicked_log = sector_data.get('kicked_log', [])
        candidates = sector_data.get('candidates', [])
        today_str = sector_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        print(f"📂 從中間檔 resume: {sector_pool_path}")
        print(f"   📅 資料日期: {today_str}")
        print(f"   📊 板塊過濾後: {len(pool_entries)} 檔")
        print(f"   🗑  累積剔除: {len(kicked_log)} 筆")
        
        # 重建 candidate_momentum 和 candidate_close
        candidate_momentum = {c['代碼']: (float(c.get('一週%') or 0), float(c.get('一月%') or 0)) for c in candidates}
        candidate_close = {c['代碼']: c['成交'] for c in candidates}
        
        # ── 繼續 FinMind 結構分析 ──
        skip_finmind = False
        HAS_FEATURE_EXTRACTOR = True
        import time
        
        if HAS_FEATURE_EXTRACTOR and pool_entries:
            enriched_count = 0
            fail_count = 0
            batch_size = 20
            pause_between_batch = 2
            print(f"\n🔬 技術結構分析中（{len(pool_entries)} 檔，FinMind API）...")
            for i in range(0, len(pool_entries), batch_size):
                batch = pool_entries[i:i+batch_size]
                for entry in batch:
                    code = entry['code']
                    try:
                        extractor = MarketFeatureExtractor(volume_threshold=0.5)
                        windows = {'window_5': 5, 'window_10': 10, 'window_20': 20}
                        structure = {}
                        for w_key, w_val in windows.items():
                            extractor.window = w_val
                            if extractor.load_from_api(code, days=365, source='finmind'):
                                result = extractor.analyze()
                                if 'error' not in result:
                                    structure[w_key] = {
                                        'supports': [s['price'] for s in result['key_levels']['supports']],
                                        'resistances': [r['price'] for r in result['key_levels']['resistances']],
                                        'rr': result['risk_reward'].get('ratio', 0) if result.get('risk_reward') else 0,
                                        'patterns': [p['type'] for p in result['detected_patterns']],
                                        'volume_signals': [{'type': v['type'], 'note': v['note']}
                                                            for v in result.get('volume_signals', [])]
                                    }
                                    all_vs = structure[w_key].get('volume_signals', [])
                                    if all_vs:
                                        if 'volume_signals' not in entry:
                                            entry['volume_signals'] = []
                                        for vs in all_vs:
                                            if vs not in entry['volume_signals']:
                                                entry['volume_signals'].append(vs)
                                else:
                                    structure[w_key] = None
                            else:
                                structure[w_key] = None
                        entry['structure'] = structure if any(v for v in structure.values()) else None
                        enriched_count += 1
                    except Exception as e:
                        fail_count += 1
                        entry['structure'] = None
                done = min(i + batch_size, len(pool_entries))
                print(f"   ...已完成 {done}/{len(pool_entries)} 檔")
                if done < len(pool_entries):
                    time.sleep(pause_between_batch)
            print(f"   ✅ 分析完成: {enriched_count} 檔成功{f' / {fail_count} 檔失敗' if fail_count else ''}")
        
        # ── 第二階段踢出檢查 ──
        today = datetime.now()
        auto_kicked = []
        for entry in pool_entries[:]:
            code = entry['code']
            close = candidate_close.get(code)
            if close is None:
                continue
            week_ret, month_ret = candidate_momentum.get(code, (0, 0))
            
            # 規則 1：時間衰退
            added_date = entry.get('added_date', today_str)
            last_signal = entry.get('last_signal_date', today_str)
            days_in_pool = entry.get('days', 1)
            if days_in_pool > 10:
                try:
                    last_dt = datetime.strptime(last_signal, '%Y-%m-%d')
                    days_since_signal = (today - last_dt).days
                    if days_since_signal >= 10:
                        reason = 'time_decay: 進池超過10天無觸發訊號'
                        auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                        kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                        pool_entries.remove(entry)
                        continue
                except (ValueError, TypeError):
                    pass
            
            # 規則 2：長線結構破壞
            structure = entry.get('structure') or {}
            w20 = structure.get('window_20') or {}
            w20_supports = w20.get('supports', [])
            if w20_supports:
                w20_core_support = min(w20_supports)
                if close < (w20_core_support * 0.98):
                    reason = 'long_term_breakdown: 收盤跌破w20支撐(2% buffer)'
                    auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    pool_entries.remove(entry)
                    continue
            
            # 規則 3：Pattern 否決
            all_patterns = []
            all_vs_types = []
            for wk in ['window_5', 'window_10', 'window_20']:
                w_struct = structure.get(wk) or {}
                all_patterns.extend(w_struct.get('patterns', []))
                all_vs_types.extend([v.get('type', '') for v in w_struct.get('volume_signals', [])])
            for vs in entry.get('volume_signals', []):
                all_vs_types.append(vs.get('type', ''))
            if 'M頭' in all_patterns:
                reason = 'pattern_veto: M頭型態（上方套牢賣壓過重）'
                auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                pool_entries.remove(entry)
                continue
            has_distribution = '出貨' in all_vs_types
            has_accumulation = '吃貨' in all_vs_types
            if has_distribution and not has_accumulation:
                reason = 'distribution_veto: 有出貨訊號且無吃貨'
                auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                pool_entries.remove(entry)
                continue
            
            # 規則 5：RR 區間過濾（RR=None 跳過，代表無法評估）
            if structure:
                w5 = structure.get('window_5') or {}
                rr = w5.get('rr')
                if rr is not None and (rr <= 0.0 or rr > 15.0):
                    if rr and rr > 15.0:
                        reason = f'high_rr_trap: RR={rr:.1f}>15'
                    else:
                        reason = f'low_rr: RR={rr}<0.0'
                    auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    pool_entries.remove(entry)
                    continue
                # 規則 6：雞蛋水餃股
                if close and close < 10 and rr is not None and rr > 20:
                    reason = 'junk_stock: 現價<10元且RR>20'
                    auto_kicked.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    kicked_log.append({'code': code, 'name': entry.get('name',''), 'kicked_date': today_str, 'days_in_pool': days_in_pool, 'reason': reason})
                    pool_entries.remove(entry)
                    continue
        
        if auto_kicked:
            print(f"\n🔴 自動踢除 {len(auto_kicked)} 檔（第二階段規則）:")
            for k in auto_kicked:
                print(f"   ❌ [{k['code']}] {k['name']} — {k['reason']}")
        else:
            print(f"\n🔴 自動踢除: 0 檔（全部符合保留條件）")
        
        # ── 依 RR 排序 ──
        def _rr(entry):
            w5 = (entry.get('structure', {}) or {}).get('window_5', {}) or {}
            return float(w5.get('rr', 0) or 0)
        pool_entries.sort(key=lambda e: -_rr(e))
        
        # ── 寫入 stock_pool.json ──
        pool_output = {
            'date': today_str,
            'source': 'xq_screener.py (resumed from sector_filtered_pool.json)',
            'total_candidates': len(pool_entries),
            'pool': pool_entries,
            'kicked_log': kicked_log
        }
        pool_path = os.path.join(_BASE, 'data', 'stock_pool.json')
        with open(pool_path, 'w', encoding='utf-8') as f:
            json.dump(pool_output, f, ensure_ascii=False, indent=2)
        
        print(f"\n📁 stock_pool.json 已更新: {len(pool_entries)} 檔 🗑 累積剔除紀錄: {len(kicked_log)} 筆")
        print("✅ 第二階段完成，請檢視 stock_pool.json")
    
    else:
        # ── 第一段：正常流程 ──
        if not args.csv_path:
            print(f"❌ 請指定 CSV 檔案路徑，或使用 --resume 從中間檔接續")
            parser.print_help()
            sys.exit(1)
        if not os.path.exists(args.csv_path):
            print(f"❌ 找不到檔案: {args.csv_path}")
            sys.exit(1)
        run_screening(args.csv_path, skip_finmind=args.skip_finmind)
