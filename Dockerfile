# ===== 构建阶段 =====
FROM python:3.10-slim as builder

# 安装编译依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ===== 生产阶段 =====
FROM python:3.10-slim

# 时区配置
ENV TZ=Asia/Shanghai
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 安全配置
RUN groupadd -r trader && useradd --no-log-init -r -g trader trader \
    && mkdir /app && chown trader:trader /app \
    && chmod -R 750 /app

WORKDIR /app

# 从构建阶段拷贝依赖
COPY --from=builder /root/.local /home/trader/.local
COPY --chown=trader:trader . .

# 环境变量
ENV PATH=/home/trader/.local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONMALLOC=malloc \
    MALLOC_ARENA_MAX=2

USER trader

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["bash", "-c", "trap 'kill -TERM $PID' TERM INT; uvicorn src.main:app --host 0.0.0.0 --port 8000 --no-access-log & PID=$!; wait $PID"]
