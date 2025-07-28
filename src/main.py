import os
import logging
from fastapi import FastAPI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

# 创建应用实例
app = FastAPI(debug=os.getenv("DEBUG_MODE", "False").lower() == "true")

# 打印环境配置
logger.info(f"运行模式: {os.getenv('RUN_MODE', 'live')}")
logger.info(f"基础杠杆率: {os.getenv('BASE_LEVERAGE', '10')}")
logger.info(f"数据库URL: {os.getenv('DATABASE_URL')}")

# 正确的健康检查端点
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "服务运行正常"}

@app.get("/")
def root():
    return {
        "status": "running",
        "mode": os.getenv("RUN_MODE"),
        "leverage": os.getenv("BASE_LEVERAGE"),
        "health_check": "/health"
    }

# 您的交易路由和逻辑...
