# Dockerfile (最终稳定版 - 兼容 Render 构建环境)

# 阶段一：准备环境和安装依赖
FROM python:3.10.13-slim

# 设置环境变量，这是良好实践
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 在容器内创建工作目录
WORKDIR /app

# 只复制依赖清单文件进来
# 这是最标准的做法，可以最好地利用 Docker 的层缓存
COPY requirements.txt ./

# 在纯净、兼容的 Python 3.10 环境中安装所有依赖
RUN pip install --no-cache-dir -r requirements.txt

# 阶段二：复制应用程序代码
# 把当前目录（构建上下文）下的所有东西都复制到容器的 /app/ 目录里
COPY . .

# 定义容器启动时要执行的命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
