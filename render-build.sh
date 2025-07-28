#!/bin/bash
set -e
pip install --upgrade pip
python -m venv venv
source venv/bin/activate
echo "=== 安装 TA-Lib 系统依赖 ==="
apt-get update -y && apt-get install -y --no-install-recommends build-essential libta-lib-dev
echo "=== 智能安装 Python 依赖 (强制使用二进制包) ==="
pip install --no-cache-dir --only-binary ":all:" -r requirements.txt
echo "=== 构建成功！ ==="
