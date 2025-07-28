#!/bin/bash
set -e

# 1. 升级 pip
pip install --upgrade pip

# 2. 创建一个名为 venv 的虚拟环境
python -m venv venv

# 3. 激活这个虚拟环境
source venv/bin/activate

# 4. 在虚拟环境中安装 TA-Lib 的系统依赖
echo "=== 安装 TA-Lib 的系统编译依赖 ==="
apt-get update -y && apt-get install -y --no-install-recommends build-essential libta-lib-dev

# 5. 在虚拟环境中安装所有 Python 依赖
echo "=== 安装 Python 依赖 ==="
pip install -r requirements.txt

echo "=== 构建成功 ==="