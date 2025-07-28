#!/bin/bash
set -e

echo "=== 安装系统依赖 ==="
apt-get update
apt-get install -y build-essential

echo "=== 安装Python依赖 ==="
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt

echo "=== 构建成功 ==="
