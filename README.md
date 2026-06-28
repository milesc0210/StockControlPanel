# StockControlPanel

StockControlPanel 是一套用於台股資料整理與選股分析的可攜式 Flask 控制台。

它把常用的資料更新、選股流程、K 線檢視與快取邏輯整合在同一個專案裡，方便在本機快速操作與延伸開發。

## 主要功能

- 台股上市 / 上櫃收盤資料更新
- 漲停紅箭選股
- 均線多頭新成形選股
- 標準選股 / 保守選股
- 60 日 K 線圖檢視
- 40 日 K 線縮圖批次載入
- 本機 SQLite / 記憶體快取
- Token 設定 UI

## 技術架構

- Backend: Flask
- Frontend: Vanilla JavaScript + HTML + CSS
- Data store: JSON 檔案 + SQLite
- Runtime: Python 3

## 專案結構

```text
StockControlPanel/
├── app.py
├── README.md
├── requirements.txt
├── .env.example
├── start_mac.sh
├── start_stock_control_panel.bat
├── scripts/
├── static/
├── templates/
├── data/
└── outputs/
```

## 環境需求

- Python 3.10+
- 建議使用虛擬環境

目前 `requirements.txt` 內含最基本依賴：

- Flask
- openpyxl

部分功能若有使用額外資料處理或繪圖套件，請依實際腳本需求補裝。

## 安裝與啟動

### Windows

```bash
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
py -3 app.py
```

### macOS / Linux

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

啟動後開啟：

```text
http://127.0.0.1:8765
```

## Token 設定

可用兩種方式設定：

### 方式 1：UI 設定

啟動後在畫面中輸入：

- `FINMIND_TOKEN`
- `FUGLE_INTRADAY_API_KEY`

### 方式 2：手動編輯 `.env`

```env
FINMIND_TOKEN="your-finmind-token"
FUGLE_INTRADAY_API_KEY="your-fugle-api-key"
```

注意：

- `.env` 屬於個人本機設定，不應提交到 GitHub
- 公開分享時請只保留 `.env.example`

## 功能對應腳本

| 功能 | 腳本 |
|---|---|
| 漲停紅箭 | `scripts/screen_limitup_upperwick.py` |
| 均線多頭新成形 | `scripts/screen_ma_alignment_turning_point.py` |
| 012 快速族群分類 | `scripts/analyze_012_sector_groups.py` |
| 標準選股 | `scripts/pre_breakout_screen.py --relaxed` |
| 保守選股 | `scripts/pre_breakout_screen.py` |
| 上市上櫃資料更新 | `scripts/twse_tpex_fetch.py` / `scripts/fetch_market_data.py` |

## 資料與快取

專案目前使用：

- `data/`：本機市場資料與 K 線資料
- `outputs/`：功能輸出結果
- `stock_control_panel.db`：本機執行紀錄與快取資料庫

近期已加入 K 線相關優化：

- 60 日 K 線圖後端記憶體快取
- 60 日 K 線圖前端記憶體快取
- 40 日批次 K 線載入優化

這可以讓同一支股票重複開啟時大幅加快速度。

## 開發說明

如果你要修改專案，建議先檢查：

- `app.py`
- `static/app.js`
- `templates/index.html`
- `scripts/` 內相關腳本

常用驗證方式：

```bash
python -m py_compile app.py
python app.py
```

## 公開版注意事項

這個 GitHub 公開版已排除：

- `.env`
- `.venv`
- `stock_control_panel.db`
- `Release/`
- Python 快取檔

如果你要重新打包給終端使用者，可以自行從目前原始碼產生 Release 版本。

## Version

- `v1.0.0`：首次公開版，整理專案結構、README、GitHub 上傳與 K 線快取優化。
