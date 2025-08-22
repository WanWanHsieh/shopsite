# 1) 建立 deploy.sh
cat > ~/shopsite/deploy.sh <<'SH'
#!/usr/bin/env bash
set -e

cd ~/shopsite

# 如果沒 venv 就建立一個（用 3.11，可依你 Web 設定改）
if [ ! -d .venv ]; then
  python3.11 -m venv .venv
fi
source .venv/bin/activate

# 拉最新程式並覆蓋到遠端 main 版本
git fetch origin main
git reset --hard origin/main

# 若有新套件會安裝，沒有則很快結束
pip install -r requirements.txt

echo "✅ 代碼已同步。請到 PythonAnywhere 的 Web 頁按 Reload。"
SH

# 2) 給執行權限
chmod +x ~/shopsite/deploy.sh
