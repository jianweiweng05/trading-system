#!/bin/bash
set -e

echo "=== 安装 Python 依赖（无系统依赖）==="
pip install --upgrade pip
pip install --no-cache-dir --only-binary=:all: -r requirements.txt

echo "=== 构建成功 ==="
