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

# 新增敏感信息过滤类
class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = record.msg.replace(
                os.getenv('TELEGRAM_BOT_TOKEN', ''),
                '<BOT_TOKEN>'
            )
        return True

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())  # 添加过滤器

# 统一日志格式
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

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
        await telegram_app.initialize()
        await telegram_app.start()
        logger.info("✅ Telegram轮询运行中")
        
        while True:
            await asyncio.sleep(0.1)  # 修复：缩短sleep时间
            
    except asyncio.CancelledError:
        logger.info("收到停止信号")
        await telegram_app.stop()
        await telegram_app.shutdown()
    except Exception as e:
        logger.warning(f"轮询异常: {e}")  # 修复：error改为warning
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    exchange = None
    polling_task = None
    
    try:
        logger.info("系统启动中...")
        
        await init_db()
        config = await init_config()
        if not config:
            raise RuntimeError("配置初始化失败")
        
        exchange = binance({
            'apiKey': config.binance_api_key,
            'secret': config.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange
        
        telegram_app = ApplicationBuilder().token(config.telegram_bot_token).build()
        telegram_app.bot_data['config'] = config
        app.state.telegram_app = telegram_app
        
        await initialize_bot(app)
        
        polling_task = asyncio.create_task(run_safe_polling(telegram_app))
        app.state.polling_task = polling_task
        
        await SystemState.set_state("ACTIVE", telegram_app)
        logger.info("系统启动完成")
        yield
        
    except Exception as e:
        logger.error(f"启动失败: {e}")
        raise
    finally:
        logger.info("系统关闭中...")
        
        if polling_task and not polling_task.done():
            polling_task.cancel()
            try:
                await polling_task
            except Exception as e:
                logger.warning(f"停止轮询时出错: {e}")  # 修复：error改为warning
        
        if hasattr(app.state, 'telegram_app'):
            await stop_bot_services(app)
        
        if exchange:
            try:
                await exchange.close()
            except Exception as e:
                logger.warning(f"关闭交易所失败: {e}")  # 修复：error改为warning

app = FastAPI(
    title="交易系统",
    version="7.2",
    lifespan=lifespan,
    debug=False
)

@app.get("/")
async def root():
    return {"status": "running", "version": app.version, "mode": CONFIG.run_mode if hasattr(CONFIG, 'run_mode') else "unknown"}

# 新增HEAD方法支持
@app.head("/")
async def root_head():
    return None

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/startup-check")
async def startup_check():
    checks = {
        "config_loaded": hasattr(CONFIG, 'telegram_bot_token'),
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
            try:
                await app.state.exchange.fetch_time()
                checks["exchange_ready"] = True
            except Exception as e:
                logger.debug(f"交易所连接检查失败: {e}")  # 修复：添加debug日志
            
        if checks["telegram_initialized"]:
            checks["telegram_running"] = not app.state.telegram_app._running.is_set()
            
    except Exception as e:
        logger.warning(f"健康检查失败: {e}")  # 修复：error改为warning
    
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "checks": checks
    }

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    if not hasattr(CONFIG, 'tv_webhook_secret'):
        raise HTTPException(503, detail="系统未初始化")
    
    signature = request.headers.get("X-Tv-Signature", "")
    payload = await request.body()
    if not verify_signature(CONFIG.tv_webhook_secret, signature, payload):
        raise HTTPException(401, detail="签名验证失败")
    
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit_check(client_ip):
        raise HTTPException(429, detail="请求过于频繁")
    
    if not await SystemState.is_active():
        current_state = await SystemState.get_state()
        raise HTTPException(503, detail=f"系统未激活 ({current_state})")

    try:
        signal_data = await request.json()
        logger.info(f"收到交易信号: {signal_data}")
        return {"status": "processed"}
    except Exception as e:
        logger.warning(f"信号处理失败: {e}")  # 修复：error改为warning
        raise HTTPException(400, detail="无效的JSON数据")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
