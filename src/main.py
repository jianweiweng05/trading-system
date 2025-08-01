import logging
import asyncio
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

# 请求频率限制记录
REQUEST_LOG = {}

def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    if not secret:
        logger.warning("未设置webhook密钥，跳过验证")
        return True
    expected = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def rate_limit_check(client_ip: str) -> bool:
    now = time.time()
    if client_ip not in REQUEST_LOG:
        REQUEST_LOG[client_ip] = []
    
    REQUEST_LOG[client_ip] = [t for t in REQUEST_LOG[client_ip] if now - t < 60]
    
    if len(REQUEST_LOG[client_ip]) >= 20:
        logger.warning(f"IP {client_ip} 请求过于频繁")
        return False
    
    REQUEST_LOG[client_ip].append(now)
    return True

async def run_safe_polling(telegram_app):
    try:
        logger.info("开始轮询...")
        await telegram_app.start_polling()
        logger.info("轮询运行中")
        while True:  # 保持任务持续运行
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("收到停止信号")
        await telegram_app.stop_polling()
    except Exception as e:
        logger.error(f"轮询崩溃: {e}")
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    exchange = None
    telegram_initialized = False
    polling_task = None
    
    try:
        logger.info("系统启动中...")
        
        # 1. 首先初始化数据库
        await init_db()
        
        # 2. 然后初始化配置
        config = await init_config()
        if not config:
            raise RuntimeError("配置初始化失败")
        
        # 3. 初始化交易所
        exchange = binance({
            'apiKey': config.binance_api_key,
            'secret': config.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange
        logger.info("✅ 交易所连接已建立")
        
        # 4. 初始化Telegram
        telegram_app = ApplicationBuilder().token(config.telegram_bot_token).build()
        telegram_app.bot_data['config'] = config
        app.state.telegram_app = telegram_app
        logger.info("✅ Telegram 应用已创建")
        
        await initialize_bot(app)
        telegram_initialized = True
        logger.info("✅ Telegram Bot 已初始化")
        
        # 5. 启动轮询任务（必须在yield之前）
        polling_task = asyncio.create_task(run_safe_polling(telegram_app))
        app.state.polling_task = polling_task
        logger.info("✅ 轮询任务已启动")
        
        # 短暂等待确保任务启动
        await asyncio.sleep(0.1)
        
        # 6. 设置系统状态
        await SystemState.set_state("ACTIVE", telegram_app)
        logger.info("✅ 系统状态已设置为 ACTIVE")
        
        logger.info("系统启动完成")
        yield  # FastAPI服务正式启动
        
    except asyncio.CancelledError:
        logger.info("收到停止信号")
    except Exception as e:
        logger.error(f"启动失败: {e}")
        raise
    finally:
        logger.info("系统关闭中...")
        
        # 停止轮询
        if polling_task:
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                logger.info("轮询任务已正常停止")
            except Exception as e:
                logger.error(f"停止轮询时出错: {e}")
        
        # 停止Telegram服务
        if telegram_initialized:
            try:
                await stop_bot_services(app)
            except Exception as e:
                logger.error(f"停止Telegram服务失败: {e}")
        
        # 关闭交易所连接
        if exchange:
            try:
                await exchange.close()
            except Exception as e:
                logger.error(f"关闭交易所失败: {e}")
        
        logger.info("✅ 系统已安全关闭")

# FastAPI应用
app = FastAPI(
    title="交易系统",
    version="7.2",
    lifespan=lifespan,
    debug=False
)

@app.get("/")
def root():
    return {"status": "running", "version": app.version, "mode": CONFIG.run_mode if CONFIG else "unknown"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/startup-check")
async def startup_check():
    checks = {
        "config_loaded": bool(CONFIG),
        "db_accessible": False,
        "exchange_ready": False,
        "telegram_initialized": hasattr(app.state, 'telegram_app'),
        "telegram_running": False
    }
    
    try:
        from database import engine
        async with engine.connect():
            checks["db_accessible"] = True
        
        if hasattr(app.state, 'exchange'):
            await app.state.exchange.fetch_time()
            checks["exchange_ready"] = True
            
        if hasattr(app.state, 'telegram_app'):
            try:
                checks["telegram_running"] = app.state.telegram_app.updater.running
            except:
                pass
            
    except Exception as e:
        logger.info(f"健康检查失败: {e}")
    
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "checks": checks
    }

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    if not CONFIG:
        raise HTTPException(status_code=503, detail="系统未初始化")
    
    # 验证签名
    signature = request.headers.get("X-Tv-Signature", "")
    payload = await request.body()
    if not verify_signature(CONFIG.tv_webhook_secret, signature, payload):
        raise HTTPException(status_code=401, detail="签名验证失败")
    
    # 检查请求频率
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit_check(client_ip):
        raise HTTPException(status_code=429, detail="请求过于频繁")
    
    # 检查系统状态
    if not await SystemState.is_active():
        current_state = await SystemState.get_state()
        logger.warning(f"信号被拒绝，系统状态: {current_state}")
        raise HTTPException(status_code=503, detail=f"系统未激活: {current_state}")

    try:
        signal_data = await request.json()
        logger.info(f"收到信号: {signal_data}")
        return {"status": "processed"}
    except Exception as e:
        logger.info(f"信号处理失败: {e}")
        raise HTTPException(status_code=400, detail="信号格式错误")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
