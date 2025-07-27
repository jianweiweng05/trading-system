#!/bin/bash
set -e

echo "=== 更新包索引 ==="
pip install --upgrade pip

echo "=== 安装 Python 依赖 ==="
pip install --no-cache-dir -r requirements.txt

echo "=== 清理缓存 ==="
rm -rf /tmp/pip* ~/.cache/pip

echo "=== 构建成功 ==="
