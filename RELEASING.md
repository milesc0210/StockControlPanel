# RELEASING StockControlPanel (EXE-first)

這份文件是 StockControlPanel 目前的 **GitHub / EXE 發佈主流程**。

目標：

- GitHub Repo 保存原始碼與打包流程
- 一般使用者從 **GitHub Releases** 下載 EXE 包
- 後續更新以 **可攜式 EXE 版本** 為主

---

## 一、發佈原則

### 對使用者
請下載：

- GitHub Releases 的 `StockControlPanel-portable-exe.zip`

不要把：

- `Code > Download ZIP`

當成最終可執行版本。

### 對維護者
Repo 主要負責：

- 原始碼管理
- 打包腳本管理
- 文件管理
- 新版 EXE 資產發佈

---

## 二、每次更新標準流程

1. 修改功能或修 bug
2. 本機驗證
3. 重新打包 EXE
4. 重新產生發佈 ZIP
5. 更新 README / RELEASING.md（如果流程有變）
6. commit / push 到 GitHub `main`
7. 建立新 tag / release
8. 上傳新的 EXE ZIP 到 GitHub Releases

---

## 三、本機驗證

### 語法檢查

```bash
python -m py_compile app.py stock_control_panel_boot.py build_portable_exe.py scripts/*.py
```

### source 模式檢查

```bash
python app.py
```

至少確認：

- `/api/functions` 正常
- `/api/update_status` 正常
- 至少一個選股功能能執行

---

## 四、建置 EXE

先安裝 PyInstaller：

```bash
python -m pip install pyinstaller
```

建置：

```bash
python build_portable_exe.py
```

輸出資料夾：

```text
Release/PortableEXE/dist/StockControlPanel/
```

主執行檔：

```text
Release/PortableEXE/dist/StockControlPanel/StockControlPanel.exe
```

---

## 五、產生發佈 ZIP

建議把整個 `dist/StockControlPanel/` 壓成：

```text
Release/PortableEXE/StockControlPanel-portable-exe.zip
```

原因：

- 目前使用 PyInstaller `--onedir`
- 不能只發一個裸 `.exe`
- 必須連同整個 bundle 一起交付

---

## 六、GitHub Repo 應保留的內容

應提交：

- `app.py`
- `stock_control_panel_boot.py`
- `build_portable_exe.py`
- `scripts/`
- `static/`
- `templates/`
- `data/`（若專案策略仍保留資料）
- `README.md`
- `RELEASING.md`
- `.env.example`
- `.gitignore`

---

## 七、GitHub Repo 不應提交的內容

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
- `__pycache__/`
- `*.pyc`

---

## 八、GitHub Release 說明建議

每次發佈 Release 時，說明建議至少包含：

- 本次修正內容
- 下載方式：請下載 `StockControlPanel-portable-exe.zip`
- 使用方式：解壓縮後雙擊 `StockControlPanel.exe`
- 注意：不要用 `Code > Download ZIP` 當成可執行版

---

## 九、建議 tag 命名

例如：

- `v1.1.0`
- `v1.1.1`
- `v1.2.0`

---

## 十、發布前檢查清單

- [ ] README 已反映 EXE-first 流程
- [ ] RELEASING.md 已反映最新步驟
- [ ] `python -m py_compile ...` 通過
- [ ] `python build_portable_exe.py` 成功
- [ ] `StockControlPanel.exe` 可啟動
- [ ] `/api/functions` 可正常回應
- [ ] `/api/update_status` 顯示 EXE 模式
- [ ] 至少一個真實選股流程可執行
- [ ] 新 ZIP 已產生
- [ ] 已 push 到 GitHub `main`
- [ ] 已上傳 GitHub Releases 資產

---

## 十一、重要原則

從現在開始，StockControlPanel 對外的主要交付物是：

- **Portable EXE Release**

不是：

- 原始碼 ZIP
- 直接 copy Python 專案資料夾

GitHub Repo 是來源；GitHub Releases 才是給使用者下載的成品。
