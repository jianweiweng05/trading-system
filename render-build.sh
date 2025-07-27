#!/bin/bash
set -e

echo "=== 安装 Python 依赖（使用预编译包）==="
pip install --upgrade pip
pip install --no-cache-dir --only-binary=:all: -r requirements.txt

echo "=== 构建成功 ==="
