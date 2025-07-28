# 使用 cat 命令一次性创建正确的文件
cat > render-build.sh << 'EOL'
#!/bin/bash
set -e

echo "=== 安装 TA-Lib 的系统编译依赖 ==="
apt-get update -y && apt-get install -y --no-install-recommends build-essential libta-lib-dev

echo "=== 安装 Python 依赖 ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 构建成功 ==="
EOL

# 授予文件执行权限
chmod +x render-build.sh