# Dockerfile (最终权限修复版)

# 1. 基础镜像
FROM python:3.10.13-slim

# 2. 环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# --- 新增步骤：创建非 root 用户并授予权限 ---
# 创建一个专门用来运行我们应用的用户，这是一个安全最佳实践
RUN useradd --create-home --shell /bin/bash appuser

# 创建持久化数据目录，并把所有权交给我们的新用户
RUN mkdir -p /var/data && chown -R appuser:appuser /var/data

# 切换到这个新创建的用户
USER appuser
# ---------------------------------------------

# 3. 工作目录
WORKDIR /home/appuser/app # 将工作目录设置在新用户的主目录下

# 4. 安装依赖
COPY --chown=appuser:appuser requirements.txt . # 复制文件时也指定所有权
RUN pip install --no-cache-dir -r requirements.txt

# 5. 复制项目代码
COPY --chown=appuser:appuser . .

# 6. 定义启动命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
