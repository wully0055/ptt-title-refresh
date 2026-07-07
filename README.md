# ptt-title-refresh

定時爬取 PTT 看板，當文章標題符合關鍵字時寄 Email 通知。

## 功能

- 依設定的間隔（預設 15 分鐘）爬取指定的 PTT 看板頁面
- 標題含關鍵字（不分大小寫）的新文章會寄信通知
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
```

編輯 `.env` 填入看板網址、關鍵字、Email 與 [Google 應用程式密碼](https://myaccount.google.com/apppasswords)。各欄位說明見 `.env.example`。

## 執行

```bash
venv/bin/python main.py
```

## 測試

```bash
venv/bin/pip install pytest
venv/bin/python -m pytest tests/
```
