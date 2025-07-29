import os
import logging
from fastapi import FastAPI, Request
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

# 健康检查端点
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

# Telegram 状态检查
@app.get("/telegram-status")
async def telegram_status():
    return {
        "token_set": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "chat_id_set": bool(os.getenv("TELEGRAM_CHAT_ID"))
    }

# 消息测试端点
@app.get("/test-telegram")
async def test_telegram():
    from src.telegram_bot import send_message
    success = await send_message("🚀 测试消息：交易系统运行正常！")
    return {"status": "success" if success else "error"}

# 按钮测试端点（永久修复版）
@app.get("/button-test")
async def button_test():
    from src.telegram_bot import send_message_with_buttons
    buttons = [
        [{"text": "按钮1", "callback_data": "action_1"}],
        [{"text": "按钮2", "callback_data": "action_2"}]
    ]
    success = await send_message_with_buttons("请点击按钮测试:", buttons)
    return {"status": "按钮测试已发送" if success else "发送失败"}

# Telegram回调处理（永久修复版）
@app.post("/telegram-callback")
async def telegram_callback(request: Request):
    try:
        data = await request.json()
        logger.info(f"收到Telegram回调: {data}")
        
        callback_data = data.get("callback_query", {}).get("data")
        
        if callback_data == "action_1":
            return {"status": "操作1执行成功"}
        elif callback_data == "action_2":
            return {"status": "操作2执行成功"}
        
        return {"status": "未知操作"}
    except Exception as e:
        logger.error(f"回调处理失败: {str(e)}")
        return {"status": "error", "detail": str(e)}

# 启动服务器
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
