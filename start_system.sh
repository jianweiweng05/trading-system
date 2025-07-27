#!/bin/bash

# ================= 量化交易系统启动脚本 =================
# 版本: v6.2
# 作者: Quant Team
# 最后更新: 2025-07-27
# ====================================================

# 设置环境变量
export PYTHONPATH=$PWD/src
export PYTHONWARNINGS="ignore::DeprecationWarning"

# 打印启动信息
echo "=========================================="
echo "启动量化交易系统 v6.2"
echo "启动时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "虚拟环境不存在，正在创建..."
    python3.10 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "使用现有虚拟环境"
    source venv/bin/activate
fi

# 检查数据库是否存在
if [ ! -f "src/trading_system.db" ]; then
    echo "初始化数据库..."
    python src/init_db.py
fi

# 启动系统
echo "启动交易系统..."
cd src
python main.py

# 系统退出时清理
deactivate
echo "系统已停止"
