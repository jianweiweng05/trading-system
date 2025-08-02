# ===== 构建阶段 =====
FROM python:3.10-slim as builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip==23.3.2 wheel

WORKDIR /app

COPY requirements.txt .
RUN pip install --user \
    cython==3.0.0 \
    numpy==1.24.4 && \
    pip install --user --no-cache-dir -r requirements.txt

# ===== 生产阶段 =====
FROM python:3.10-slim

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone

RUN groupadd -r trader && useradd --no-log-init -r -g trader trader && \
    mkdir /app && chown trader:trader /app && \
    chmod -R 750 /app

WORKDIR /app

COPY --from=builder /root/.local /home/trader/.local
COPY --chown=trader:trader . .

ENV PATH=/home/trader/.local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONMALLOC=malloc \
    MALLOC_ARENA_MAX=2

USER trader

HEALTHCHECK --interval=30s --timeout=3s \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port 8000 --no-access-log --workers $(nproc) --limit-max-requests 10000"]
