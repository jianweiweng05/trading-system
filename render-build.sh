#!/bin/bash
set -e

# 升级pip
pip install --upgrade pip

# 创建并激活虚拟环境
python -m venv venv
source venv/bin/activate

# 安装系统依赖
echo "=== 安装 TA-Lib 的系统编译依赖 ==="
apt-get update -y && apt-get install -y --no-install-recommends build-essential libta-lib-dev

# 使用一种更节约内存的方式安装Python依赖
echo "=== 智能安装 Python 依赖 ==="
pip install --no-cache-dir --prefer-binary -r requirements.txt

echo "=== 构建成功 ==="