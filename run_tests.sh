#!/bin/bash

# 加载环境变量
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo "已加载环境变量"
else
    echo "警告: 未找到 .env 文件"
fi

# 运行测试
echo "开始运行测试..."
python -m unittest discover -s src/tests -p "test_*.py" -v

# 清理临时文件
find src/tests -name "*.db" -delete
echo "已清理临时数据库文件"

