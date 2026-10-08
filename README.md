# 丸藝手作坊 v1（Flask 版）

> ⚠️ **已停止維護**，正式版請見 [wan-design](https://github.com/WanWanHsieh/wan-design)。

手作商品網站的第一版，使用 Python **Flask** + **SQLAlchemy** + Jinja2 模板，資料庫預設為 SQLite。

## 功能

- **前台**：商品分類、款式、商品頁、布料挑選、出清布料
- **後台**：分類 / 款式 / 商品 / 規格 / 布料管理、圖片上傳、網站開關設定

## 執行方式

```bash
pip install -r requirements.txt
python app.py
```

環境變數：`ADMIN_PASSWORD`（後台密碼）、`SECRET_KEY`、`DATABASE_URL`。
請務必自行設定，不要使用程式內的預設值。

`migrate_add_columns.py`：舊資料庫補欄位用的遷移腳本。
