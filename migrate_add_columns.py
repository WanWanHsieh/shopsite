# 安全補欄位：若找不到 products 表，會提示先啟動 app.py 建表
import sqlite3, sys

db = "shop.db"
con = sqlite3.connect(db)
cur = con.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
exists = cur.fetchone() is not None

if not exists:
    print("偵測不到 'products' 資料表。請先執行 `python app.py` 讓程式自動建表後，再來跑遷移。")
    con.close()
    sys.exit(0)

cur.execute("PRAGMA table_info(products)")
cols = [r[1] for r in cur.fetchall()]

if "category_id" not in cols:
    cur.execute("ALTER TABLE products ADD COLUMN category_id INTEGER")
    print("已新增欄位: products.category_id")

if "style_id" not in cols:
    cur.execute("ALTER TABLE products ADD COLUMN style_id INTEGER")
    print("已新增欄位: products.style_id")

con.commit()
con.close()
print("Migration 完成")
