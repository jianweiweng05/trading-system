#!/bin/bash
set -e  # 出错时立即停止

echo "=== 安装系统编译依赖 ==="
sudo apt-get update
sudo apt-get install -y build-essential python3-dev

echo "=== 更新 pip 和构建工具 ==="
pip install --upgrade pip setuptools wheel

echo "=== 安装 Python 依赖 ==="
pip install --no-cache-dir -r requirements.txt

echo "=== 构建成功 ==="
