# ===== 构建阶段 =====
FROM python:3.10-slim as builder

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev libffi-dev curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

# 升级pip并安装wheel
RUN pip install --upgrade pip==23.3.2 wheel setuptools

# 设置工作目录
WORKDIR /app

# 复制requirements文件并安装依赖
COPY requirements.txt .
RUN pip install --user \
    cython==3.0.0 \
    numpy==1.24.4 && \
    pip install --user --no-cache-dir \
    -r requirements.txt \
    --compile \
    --no-cache-dir

# ===== 生产阶段 =====
FROM python:3.10-slim

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

# 设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone

# 创建非root用户
RUN groupadd -r trader && \
    useradd --no-log-init -r -g trader trader && \
    mkdir -p /app /app/data && \
    chown -R trader:trader /app && \
    chmod -R 750 /app

# 设置工作目录
WORKDIR /app

# 从构建阶段复制安装的依赖
COPY --from=builder /root/.local /home/trader/.local

# 复制应用代码
COPY --chown=trader:trader . .

# 设置环境变量
ENV PATH=/home/trader/.local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONMALLOC=malloc \
    MALLOC_ARENA_MAX=2 \
    PYTHONOPTIMIZE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONASYNCIODEBUG=0 \
    PYTHONFAULTHANDLER=1

# 切换到非root用户
USER trader

# 健康检查 - 增加启动等待时间和重试次数
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 暴露端口
EXPOSE 8000

# 启动命令 - 使用uvicorn运行FastAPI应用
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info", "--workers", "4"]
