# ===== 构建阶段 =====
FROM python:3.10-slim as builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev libffi-dev curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip==23.3.2 wheel setuptools

WORKDIR /app

COPY requirements.txt .
RUN pip install --user \
    cython==3.0.0 \
    numpy==1.24.4 && \
    pip install --user --no-cache-dir -r requirements.txt

# ===== 生产阶段 =====
FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone

RUN groupadd -r trader && \
    useradd --no-log-init -r -g trader trader && \
    mkdir -p /app /app/data && \
    chown -R trader:trader /app && \
    chmod -R 750 /app

WORKDIR /app

COPY --from=builder /root/.local /home/trader/.local
COPY --chown=trader:trader . .

ENV PATH=/home/trader/.local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONMALLOC=malloc \
    MALLOC_ARENA_MAX=2 \
    PYTHONOPTIMIZE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONASYNCIODEBUG=0 \
    PYTHONFAULTHANDLER=1

USER trader

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info", "--workers", "4"]
