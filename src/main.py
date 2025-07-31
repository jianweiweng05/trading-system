# 文件: src/main.py (与config.py兼容的最终版)

import logging
import asyncio
import time
import hmac
import hashlib
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from ccxt.async_support import binance
from telegram.ext import ApplicationBuilder

# 导入自定义模块
from config import CONFIG, init_config
from database import init_db
from system_state import SystemState
from telegram_bot import start_bot, stop_bot

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- 全局状态与辅助函数 ---
REQUEST_LOG = {}

def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    """验证TradingView HMAC签名"""
    if not secret:
        logger.warning("TV_WEBHOOK_SECRET未设置，跳过签名验证 (仅限测试)")
        return True
    
    expected = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def rate_limit_check(client_ip: str) -> bool:
    """简单的内存速率限制 (60秒内最多20次)"""
    now = time.time()
    if client_ip not in REQUEST_LOG:
        REQUEST_LOG[client_ip] = []
    
    REQUEST_LOG[client_ip] = [t for t in REQUEST_LOG[client_ip] if now - t < 60]
    
    if len(REQUEST_LOG[client_ip]) >= 20:
        logger.warning(f"IP {client_ip} 请求频率过高")
        return False
    
    REQUEST_LOG[client_ip].append(now)
    return True

async def run_safe_polling(telegram_app):
    """安全运行轮询的包装器"""
    try:
        logger.info("启动Telegram轮询服务...")
        await telegram_app.updater.start_polling(
            drop_pending_updates=True,
            timeout=10,
            read_timeout=5
        )
        logger.info("Telegram轮询服务已启动")
        
        # 永久等待直到被取消
        while True:
            await asyncio.sleep(3600)
            
    except asyncio.CancelledError:
        logger.info("正在停止轮询服务...")
        await telegram_app.updater.stop()
        logger.info("轮询服务已停止")
        raise
    except Exception as e:
        logger.error(f"轮询异常: {str(e)}", exc_info=True)
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    exchange = None
    polling_task = None
    
    try:
        logger.info("系统启动中...")
        
        # 初始化配置和数据库
        await init_config()
        await init_db()
        
        # 初始化交易所连接
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange
        
        # 初始化Telegram Bot
        telegram_app = ApplicationBuilder().token(CONFIG.telegram_bot_token).build()
        app.state.telegram_app = telegram_app
        telegram_app.bot_data.update({
            "exchange": exchange,
            "config": CONFIG,
            "system_state": SystemState,
            "application": telegram_app
        })
        
        # 启动服务
        await start_bot(app)
        polling_task = asyncio.create_task(run_safe_polling(telegram_app))
        app.state.polling_task = polling_task
        await SystemState.set_state("ACTIVE", telegram_app)
        
        logger.info("系统启动完成")
        yield
        
    except Exception as e:
        logger.critical(f"启动失败: {str(e)}", exc_info=True)
        raise
    
    finally:
        logger.info("系统关闭中...")
        
        # 安全关闭所有服务
        if polling_task and not polling_task.done():
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
        
        if hasattr(app.state, 'telegram_app'):
            await stop_bot(app)
        
        if exchange:
            await exchange.close()
            
        logger.info("系统已关闭")

# 创建FastAPI应用
app = FastAPI(
    title="交易机器人系统",
    version="1.0.0",
    lifespan=lifespan,
    debug=CONFIG.log_level == "DEBUG"  # 从CONFIG获取调试模式
)

# --- API端点 ---
@app.get("/")
async def root():
    return {
        "status": "running",
        "version": app.version,
        "mode": CONFIG.run_mode
    }

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "bot_running": hasattr(app.state, 'polling_task') and not app.state.polling_task.done()
    }

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    """处理交易信号"""
    if not verify_signature(
        CONFIG.tv_webhook_secret,
        request.headers.get("X-Tv-Signature", ""),
        await request.body()
    ):
        raise HTTPException(401, "签名验证失败")
    
    if not rate_limit_check(request.client.host):
        raise HTTPException(429, "请求频率过高")
    
    if not await SystemState.is_active():
        state = await SystemState.get_state()
        raise HTTPException(503, f"系统未激活 (当前状态: {state})")

    try:
        data = await request.json()
        logger.info(f"收到信号: {data}")
        return {"status": "processed", "data": data}
    except Exception as e:
        logger.error(f"处理失败: {str(e)}")
        raise HTTPException(400, "信号处理错误")

# 启动服务器
if __name__ == "__main__":
    import uvicorn
    
    # 从CONFIG获取端口配置，如果没有则默认为8000
    port = getattr(CONFIG, "port", 8000)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=CONFIG.log_level == "DEBUG",  # 调试模式下启用热重载
        log_level="info"
    )
