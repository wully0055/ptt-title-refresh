# ptt-title-refresh

定時爬取 PTT 看板，當文章標題符合關鍵字時寄 Email 通知。

## 功能

- 依設定的間隔（預設 15 分鐘）爬取監控清單裡的 PTT 看板頁面
- 支援多組監控項目：每組可以看不同的板、設多個關鍵字（不分大小寫），`mode: "any"` 任一命中、`"all"` 全部命中才通知
- 通知信為 HTML 卡片格式（標題超連結＋看板名稱），附純文字 fallback
- 已通知的文章記錄在 `seen_posts.json`，程式重啟不會重複通知
- 自帶 `over18` cookie，需年齡確認的看板（如八卦板）也能爬

## 安裝

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## 設定

```bash
cp .env.example .env
cp watches.example.json watches.json
```

- `.env`：Email 與 [Google 應用程式密碼](https://myaccount.google.com/apppasswords)、檢查間隔。各欄位說明見 `.env.example`
- `watches.json`：監控清單。每個項目包含 `url`（看板頁面）、`keywords`（關鍵字陣列）、選填的 `mode`（`any`＝任一命中即通知（預設）、`all`＝標題須含全部關鍵字）與 `name`（信件主旨用，預設以關鍵字組成）

## 執行

```bash
venv/bin/python main.py
```

## 測試

```bash
venv/bin/pip install pytest
venv/bin/python -m pytest tests/
```
