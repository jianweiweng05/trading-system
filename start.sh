#!/bin/bash

echo "=== 安装应用依赖 ==="
pip install --no-cache-dir -r requirements.txt

echo "=== 启动应用 ==="
python -m uvicorn src.main:app --host 0.0.0.0 --port $PORT
