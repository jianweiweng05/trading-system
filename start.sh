#!/bin/bash

echo "=== 启动应用 ==="
python -m uvicorn src.main:app --host 0.0.0.0 --port $PORT
