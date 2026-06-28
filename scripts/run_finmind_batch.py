#!/usr/bin/env python3
"""
FinMind 批次分析腳本（給 177 檔分3批跑）
用法：python3 run_finmind_batch.py <batch_number>
例：python3 run_finmind_batch.py 1
"""
import json, sys, os, time
from market_feature_extractor import MarketFeatureExtractor

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH_DIR = os.path.join(_BASE, "data", "finmind_batches")
OUTPUT_DIR = os.path.join(_BASE, "data", "finmind_results")
PAUSE_BETWEEN_BATCH = 60  # 每批跑完後停60秒（讓API配額散開）

def load_batch(batch_num):
    path = f"{BATCH_DIR}/batch{batch_num}.json"
    with open(path) as f:
        data = json.load(f)
    return data

def save_batch_results(batch_num, results):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = f"{OUTPUT_DIR}/batch{batch_num}_results.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'batch': batch_num, 'stocks': results}, f, ensure_ascii=False, indent=2)
    print(f"\n💾 結果已儲存: {out_path}")

def run_batch(batch_num):
    print(f"\n{'='*50}")
    print(f"🚀 開始跑 Batch {batch_num}")
    print(f"{'='*50}")
    
    data = load_batch(batch_num)
    stocks = data['stocks']  # dict keyed by code
    stock_codes = list(stocks.keys())
    
    print(f"📦 本批共 {len(stock_codes)} 檔")
    
    ext = MarketFeatureExtractor(volume_threshold=0.5)
    windows = {'window_5': 5, 'window_10': 10, 'window_20': 20}
    
    results = {}
    success = fail = 0
    
    for i, code in enumerate(stock_codes, 1):
        info = stocks[code]
        name = info.get('name', code)
        
        print(f"  [{i}/{len(stock_codes)}] {code} {name}...", end=" ", flush=True)
        
        try:
            structure = {}
            for w_key, w_val in windows.items():
                ext.window = w_val
                if ext.load_from_api(code, days=180, source='finmind'):
                    result = ext.analyze()
                    if 'error' not in result:
                        structure[w_key] = {
                            'supports': [x['price'] for x in result['key_levels']['supports']],
                            'resistances': [x['price'] for x in result['key_levels']['resistances']],
                            'rr': result['risk_reward'].get('ratio', 0) if result.get('risk_reward') else 0,
                            'patterns': [p['type'] for p in result['detected_patterns']],
                            'volume_signals': [{'type': v['type'], 'note': v['note']}
                                                for v in result.get('volume_signals', [])]
                        }
                    else:
                        structure[w_key] = None
                else:
                    structure[w_key] = None
            
            has_data = any(v for v in structure.values() if v)
            results[code] = {
                'code': code,
                'name': name,
                'structure': structure if has_data else None,
                'xq_data': info  # 原始XQ數據
            }
            
            if has_data:
                print("✅")
                success += 1
            else:
                print("⚠️ (no structure)")
                fail += 1
                
        except Exception as e:
            print(f"❌ ERROR: {e}")
            results[code] = {
                'code': code,
                'name': name,
                'structure': None,
                'xq_data': info,
                'error': str(e)
            }
            fail += 1
        
        # 每檔跑完休息一下，避免API瞬間爆量
        time.sleep(0.5)
    
    print(f"\n📊 Batch {batch_num} 完成：✅ {success}  ⚠️ {fail}  ❌ {fail}")
    save_batch_results(batch_num, results)
    
    # 最後休息（等下一批）
    print(f"\n😴 睡 {PAUSE_BETWEEN_BATCH} 秒後結束（手動跑下一批）")
    time.sleep(PAUSE_BETWEEN_BATCH)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("用法: python3 run_finmind_batch.py <batch_number>")
        print("例: python3 run_finmind_batch.py 1")
        sys.exit(1)
    
    batch_num = int(sys.argv[1])
    if batch_num not in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]:
        print("batch_number 只能是 1~12")
        sys.exit(1)
    
    run_batch(batch_num)
