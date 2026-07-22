# StockControlPanel

StockControlPanel 是一套以 **Windows 可攜式 EXE 發佈** 為主的台股資料整理與選股分析工具。

目前產品定位已調整為：

- 使用者端以 **EXE 版本** 為主
- GitHub Repo 主要用途是：
  - 保存原始碼
  - 維護打包流程
  - 發佈新的 EXE 版本
- 一般使用者 **不需要安裝 Python**
- 一般使用者應從 **GitHub Releases 下載 EXE 發佈包**，不是直接下載原始碼 ZIP

---

## 主要發佈方式

### 給使用者
請下載 **GitHub Releases** 內的可攜式 EXE 壓縮包：

- 解壓縮
- 雙擊 `StockControlPanel.exe`
- 程式會自動在背景啟動本機服務
- 預設瀏覽器會自動開啟介面

### 給開發/維護者
GitHub Repo 保留原始碼與打包腳本，用來：

- 修改功能
- 測試
- 重新打包 EXE
- 上傳新的 Release 資產

---

## 目前版本的重點

這個專案現在主打的是：

- 別台 Windows 電腦不用安裝 Python
- 雙擊即可啟動
- 保留目前瀏覽器 UI
- 使用 PyInstaller 產生可攜式 EXE 發佈包

---

## 主要功能

- 台股上市 / 上櫃收盤資料更新
- 漲停紅箭選股
- 均線多頭新成形選股
- 標準選股 / 保守選股
- 今日漲停 / 族群分析
- 60 日 K 線圖檢視
- 40 日 K 線縮圖批次載入
- 本機 SQLite / 記憶體快取
- Token 設定 UI
- 回測功能
- 每個選股功能頁面的 **Serenity 深度分析**：將目前候選股交給 Hermes，進行供應鏈瓶頸、證據強度與風險研究

---

## 專案結構

```text
StockControlPanel/
├── app.py                          # Flask 主程式
├── stock_control_panel_boot.py     # EXE 啟動入口
├── build_portable_exe.py           # 可攜式 EXE 打包腳本
├── README.md
├── RELEASING.md                    # GitHub / EXE 發佈流程
├── requirements.txt
├── .env.example
├── scripts/                        # 選股 / 抓資料 / 回測腳本
├── static/                         # 前端 JS / CSS
├── templates/                      # HTML 模板
├── data/                           # 本機市場資料
├── outputs/                        # 執行輸出
└── Release/
    └── PortableEXE/                # 本機建置出的 EXE 發佈產物（不建議直接進 repo）
```

---

## 使用者下載與啟動方式

## 1. 正確下載方式

請優先使用：

- **GitHub Releases 的 EXE 壓縮包**

不要把 GitHub Repo 頁面的：

- `Code > Download ZIP`

當成最終使用者版本。

原因是：

- Repo ZIP 是原始碼
- 原始碼模式仍偏向開發/維護用途
- 使用者正確入口應該是已打包完成的 EXE 發佈包

---

## 2. 啟動方式

解壓縮後，進入資料夾並雙擊：

- `StockControlPanel.exe`

程式會：

1. 在背景啟動本機服務
2. 自動開啟瀏覽器
3. 載入 `http://127.0.0.1:8765`

---

## 3. 發佈形態說明

本專案目前採用的是：

- **Portable EXE onedir bundle**

也就是：

- 不是只有單一裸 `.exe`
- 而是整個 EXE 資料夾一起發佈

建議分享方式：

- 分享整個 `dist/StockControlPanel/` 資料夾
- 或將其壓成 ZIP 後分享

---

## EXE 打包方式

先安裝 PyInstaller：

```bash
python -m pip install pyinstaller
```

執行打包：

```bash
python build_portable_exe.py
```

輸出位置：

```text
Release/PortableEXE/dist/StockControlPanel/
```

主要執行檔：

```text
Release/PortableEXE/dist/StockControlPanel/StockControlPanel.exe
```

建議對外發佈：

```text
Release/PortableEXE/StockControlPanel-portable-exe.zip
```

---

## EXE 模式的設計說明

### 1. `stock_control_panel_boot.py`
這是 EXE 版入口，負責：

- 預設模式：啟動後端並自動開瀏覽器
- `--server`：只啟動 Flask server
- `--run-script <script>`：執行內部腳本

### 2. `app.py` 已支援 frozen 模式
在 EXE 模式下，程式不依賴外部 `python` 指令，會改用 EXE 自己來執行內部腳本。

### 3. EXE 版已停用程式內自動更新
目前 EXE 版的 `一鍵更新` 不再走原本 source/git/zip 自動更新邏輯。

EXE 版的更新方式是：

- 直接下載新版 EXE 發佈包
- 用新版覆蓋舊版

---

## 原始碼模式（僅維護 / 打包用途）

如果你是維護者，平常重點是：

- 修改原始碼
- 驗證功能
- 重新打包 EXE

原始碼直接 `python app.py` 啟動只保留給維護與除錯使用，不再作為正式交付模式。

### 維護測試啟動

```bash
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
py -3 app.py
```

啟動後網址：

```text
http://127.0.0.1:8765
```

---

## Serenity 深度分析

五個選股功能頁面都會顯示 `Serenity 深度分析` 按鈕：

- 漲停紅箭
- 今日漲停
- 均線多頭新成形
- 標準選股
- 保守選股

選股完成後，按鈕會將目前最多 30 檔候選股、族群、等級與排序分數交給 Hermes，使用 `serenity-skill` 研究供應鏈瓶頸、公開證據、題材關聯與主要風險。分析結果會直接顯示在頁面下方。

StockControlPanel 的其他功能不依賴 Hermes；只有使用這個按鈕時，執行電腦需要：

1. 已安裝並登入 Hermes Agent。
2. 已安裝且啟用 `serenity-skill`。
3. `hermes` 指令可以從 Windows PATH 執行。
4. 分析期間保持 StockControlPanel 開啟；深度研究通常需要數分鐘。

這項功能只提供研究輔助，不會自動下單，也不提供保證獲利或直接買賣指令。

---

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

---

## 功能對應腳本

| 功能 | 腳本 |
|---|---|
| 漲停紅箭 | `scripts/screen_limitup_upperwick.py` |
| 今日漲停 | `scripts/screen_today_limitup.py` |
| 今日漲停族群分析 | `scripts/analyze_today_limitup_sector_groups.py` |
| 均線多頭新成形 | `scripts/screen_ma_alignment_turning_point.py` |
| 012 快速族群分類 | `scripts/analyze_012_sector_groups.py` |
| 標準選股 | `scripts/pre_breakout_screen.py --relaxed` |
| 保守選股 | `scripts/pre_breakout_screen.py` |
| 回測 | `scripts/pre_breakout_backtest.py` |
| 上市上櫃資料更新 | `scripts/twse_tpex_fetch.py` / `scripts/fetch_market_data.py` |

---

## 資料與快取

專案目前使用：

- `data/`：本機市場資料與 K 線資料
- `outputs/`：功能輸出結果
- `stock_control_panel.db`：本機執行紀錄與快取資料庫

這些屬於執行期資料，不建議當成 GitHub Release 的主要說明重點；對使用者來說，重點是直接下載 EXE 包即可。

---

## GitHub Repo 原則

目前 GitHub Repo 的定位：

- 原始碼倉庫
- EXE 打包來源
- Release 發佈來源

### Repo 應該保留

- 原始碼
- 打包腳本
- 說明文件
- `.env.example`

### Repo 不應該直接當最終成品下載方式

終端使用者請走：

- **GitHub Releases 資產**

不是：

- `Code > Download ZIP`

---

## GitHub 應排除的本機/建置產物

不建議提交：

- `.env`
- `.venv/`
- `stock_control_panel.db`
- `logs/`
- `outputs/`
- `Release/PortableEXE/build/`
- `Release/PortableEXE/dist/`
- `Release/PortableEXE/spec/`
- `Release/PortableEXE/*.zip`
- Python cache

---

## 維護流程

每次更新建議流程：

1. 修改程式
2. 驗證功能
3. 重新打包 EXE
4. 產生新的 ZIP 發佈包
5. 更新 README / 發佈說明（若有需要）
6. 推到 GitHub main
7. 在 GitHub Releases 上傳新的 EXE ZIP

更完整流程請看：

- `RELEASING.md`

---

## 驗證指令

### 語法檢查

```bash
python -m py_compile app.py stock_control_panel_boot.py build_portable_exe.py scripts/*.py
```

### 本機 source 模式啟動

```bash
python app.py
```

### 建置 EXE

```bash
python build_portable_exe.py
```

---

## Version

- `v1.0.0`：首次公開版
- `v1.1.x`：逐步轉向可攜式 EXE 為主的發佈模式
- `vNext`：以 EXE 版為主要使用者交付形式
