import logging
import asyncio
import sys
import time
import hmac
import hashlib
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from ccxt.async_support import binance
from telegram.ext import ApplicationBuilder

from config import CONFIG, init_config
from database import init_db
from system_state import SystemState
from telegram_bot import initialize_bot, stop_bot_services

logger = logging.getLogger(__name__)

# 全局状态与辅助函数
REQUEST_LOG = {}

def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    if not secret:
        logger.warning("TV_WEBHOOK_SECRET未设置，跳过签名验证")
        return True
    
    expected = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def rate_limit_check(client_ip: str) -> bool:
    now = time.time()
    if client_ip not in REQUEST_LOG:
        REQUEST_LOG[client_ip] = []
    
    REQUEST_LOG[client_ip] = [t for t in REQUEST_LOG[client_ip] if now - t < 60]
    
    if len(REQUEST_LOG[client_ip]) >= 20:
        logger.warning(f"IP {client_ip} 请求频率过高")
        return False
    
    REQUEST_LOG[client_ip].append(now)
    return True

# 安全轮询函数
async def run_safe_polling(telegram_app):
    try:
        logger.info("启动Telegram轮询服务...")
        drop_updates = True
        timeout = 10
        if CONFIG:
            drop_updates = getattr(CONFIG, 'drop_pending_updates', True)
            timeout = getattr(CONFIG, 'polling_timeout', 10)
        
        await telegram_app.updater.start_polling(
            drop_pending_updates=drop_updates,
            timeout=timeout
        )
        mode = getattr(CONFIG, 'run_mode', 'UNKNOWN') if CONFIG else 'UNKNOWN'
        logger.info(f"✅ Telegram轮询运行中 (模式: {mode.upper()})")
        
        # 永久等待直到被取消
        while True:
            await asyncio.sleep(3600)
            
    except asyncio.CancelledError:
        logger.info("收到轮询停止指令...")
        await telegram_app.updater.stop()
        logger.info("✅ Telegram轮询已安全停止")
        raise
    except Exception as e:
        logger.error(f"轮询任务异常: {str(e)}", exc_info=True)
        raise

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    exchange = None
    telegram_initialized = False
    
    try:
        logger.info("系统启动中...")
        
        # 步骤1: 初始化配置
        await init_config()
        
        # 步骤2: 初始化数据库
        await init_db()
        
        # 步骤3: 创建交易所实例
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange
        
        # 步骤4: 创建Telegram实例
        telegram_app = ApplicationBuilder().token(CONFIG.telegram_bot_token).build()
        app.state.telegram_app = telegram_app
        
        # 步骤5: 初始化机器人
        await initialize_bot(app)
        telegram_initialized = True
        
        # 步骤6: 设置系统状态
        await SystemState.set_state("ACTIVE", telegram_app)
        
        logger.info("✅ 系统核心启动完成")
        yield
        
        # 阶段2: 启动轮询
        polling_task = asyncio.create_task(run_safe_polling(telegram_app))
        app.state.polling_task = polling_task
        await polling_task
        
    except asyncio.CancelledError:
        logger.info("收到终止信号")
    except Exception as e:
        logger.critical(f"启动失败: {str(e)}", exc_info=True)
    finally:
        logger.info("系统关闭中...")
        
        # 1. 停止轮询任务
        if hasattr(app.state, 'polling_task'):
            app.state.polling_task.cancel()
            try:
                await app.state.polling_task
            except asyncio.CancelledError:
                logger.info("轮询任务已取消")
            except Exception as e:
                logger.error(f"停止轮询时出错: {str(e)}")
        
        # 2. 停止Telegram服务
        if telegram_initialized:
            try:
                await stop_bot_services(app)
            except Exception as e:
                logger.error(f"停止Telegram服务时出错: {str(e)}")
        
        # 3. 关闭交易所连接
        if exchange:
            try:
                await exchange.close()
            except Exception as e:
                logger.error(f"关闭交易所时出错: {str(e)}")
        
        logger.info("✅ 系统已安全关闭")

# 创建FastAPI应用
app = FastAPI(
    title="自适应共振交易系统",
    version="7.2-Final-Configurable",
    lifespan=lifespan,
    debug=getattr(CONFIG, 'log_level', "INFO") == "DEBUG" if CONFIG else False
)

# API端点
@app.get("/")
def root():
    mode = getattr(CONFIG, 'run_mode', 'initializing') if CONFIG else 'initializing'
    return {"status": "running", "version": app.version, "mode": mode}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/startup-check")
async def startup_check():
    """新增的健康检查端点"""
    checks = {
        "config_loaded": bool(CONFIG),
        "db_accessible": False,
        "exchange_ready": False
    }
    
    try:
        # 数据库检查
        from database import engine
        async with engine.connect():
            checks["db_accessible"] = True
        
        # 交易所检查
        if hasattr(app.state, 'exchange'):
            await app.state.exchange.fetch_time()
            checks["exchange_ready"] = True
            
    except Exception as e:
        logger.warning(f"健康检查失败: {str(e)}")
    
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "checks": checks
    }

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    if not CONFIG:
        raise HTTPException(status_code=503, detail="系统配置未初始化")
    
    signature = request.headers.get("X-Tv-Signature", "")
    payload = await request.body()
    if not verify_signature(CONFIG.tv_webhook_secret, signature, payload):
        raise HTTPException(status_code=401, detail="签名验证失败")
    
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit_check(client_ip):
        raise HTTPException(status_code=429, detail="请求频率过高")
    
    if not await SystemState.is_active():
        current_state = await SystemState.get_state()
        logger.warning(f"信号被拒绝，系统状态: {current_state}")
        raise HTTPException(status_code=503, detail=f"交易未激活，当前状态: {current_state}")

    try:
        signal_data = await request.json()
        logger.info(f"收到信号 (模式: {CONFIG.run_mode.upper()}): {signal_data}")
        return {"status": "processed", "data": signal_data}
    except Exception as e:
        logger.error(f"信号处理失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="信号格式错误")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
