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
@app.get("/test-telegram")
async def test_telegram():
    from src.telegram_bot import send_message  # 确保路径正确
    await send_message("🔥 测试消息：交易系统运行正常！")
    return {"status": "测试消息已发送"}

# 添加的Telegram测试路由
@app.get("/test-telegram")
async def test_telegram():
    from src.telegram_bot import send_message
    success = await send_message("🚀 测试消息：交易系统运行正常！")
    return {"status": "success" if success else "error"}

@app.get("/telegram-status")
async def telegram_status():
    return {
        "token_set": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "chat_id_set": bool(os.getenv("TELEGRAM_CHAT_ID"))
    }

@app.get("/last-log")
async def get_last_log():
    import logging
    from io import StringIO
    
    # 捕获最近日志
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    logger = logging.getLogger()
    logger.addHandler(handler)
    
    # 触发日志记录
    from src.telegram_bot import send_message
    await send_message("测试日志端点消息")
    
    # 获取日志内容
    logger.removeHandler(handler)
    return {"log": log_stream.getvalue()}

@app.get("/check-telegram-env")
async def check_telegram_env():
    return {
        "TELEGRAM_BOT_TOKEN_exists": "TELEGRAM_BOT_TOKEN" in os.environ,
        "TELEGRAM_CHAT_ID_exists": "TELEGRAM_CHAT_ID" in os.environ
    }

# Telegram测试端点
@app.get("/ultimate-test")
async def ultimate_test():
    from src.telegram_bot import send_message
    success = await send_message("🚀 *终极测试成功！*")
    return {"status": "success" if success else "error"}

@app.get("/telegram-debug")
async def telegram_debug():
    return {
        "token_set": "TELEGRAM_BOT_TOKEN" in os.environ,
        "chat_id_set": "TELEGRAM_CHAT_ID" in os.environ
    }
from fastapi import Request

@app.get("/button-test")
async def button_test():
    from src.telegram_bot import send_message
    buttons = [
        ["按钮1", "action_1"],
        ["按钮2", "action_2"]
    ]
    await send_message("请点击按钮测试:", buttons)
    return {"status": "按钮测试已发送"}

@app.post("/telegram-callback")
async def telegram_callback(request: Request):
    data = await request.json()
    logger.info(f"收到按钮回调: {data}")
    
    callback_data = data.get("callback_query", {}).get("data")
    
    if callback_data == "action_1":
        return {"status": "操作1执行成功"}
    elif callback_data == "action_2":
        return {"status": "操作2执行成功"}
    
    return {"status": "未知操作"}

from fastapi import Request

@app.post("/telegram-callback")
async def telegram_callback(request: Request):
    return {"status": "回调永久修复成功！"}

