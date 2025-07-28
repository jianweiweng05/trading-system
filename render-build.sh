#!/bin/bash
set -e
echo "=== 安装 TA-Lib 的系统编译依赖 ==="
apt-get update -y && apt-get install -y --no-install-recommends libta-lib-dev
echo "=== 系统依赖安装完成 ==="