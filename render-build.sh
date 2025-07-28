#!/bin/bash
set -e

echo "=== 安装系统依赖 ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -o Acquire::Check-Valid-Until=false -o Acquire::Check-Date=false
apt-get install -y build-essential

echo "=== 安装Python依赖 ==="
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt

echo "=== 构建成功 ==="
