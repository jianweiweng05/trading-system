import logging
import sys
import time
import hmac
import hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
import ccxt.async_support as ccxt
from telegram.ext import ApplicationBuilder

# --- 1. 安全导入 (只从我们自己的模块导入) ---
from config import CONFIG
from database import init_db
from system_state import SystemState
from telegram_bot import start_bot, stop_bot

logger = logging.getLogger(__name__)

# --- 2. 全局状态与辅助函数 ---
REQUEST_LOG = {}

def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    """验证TradingView HMAC签名"""
    if not secret:
        logger.warning("TV_WEBHOOK_SECRET未设置，跳过签名验证 (仅限测试)。")
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
        logger.warning(f"IP {client_ip} 请求频率过高。")
        return False
    
    REQUEST_LOG[client_ip].append(now)
    return True

# --- 3. 生命周期管理 (Lifespan) - FastAPI 0.110.0+ 适配 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用启动时初始化所有核心对象并注入依赖，关闭时执行清理
    """
    # 启动
    try:
        logger.info("系统正在启动...")
        
        # 1. 创建核心对象
        app.state.exchange = ccxt.async_support.binance({
            'apiKey': CONFIG.binance_api_key, 'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True, 'options': {'defaultType': 'future'}
        })
        app.state.telegram_app = ApplicationBuilder().token(CONFIG.telegram_bot_token).build()

        # 2. 将核心对象注入到Telegram Bot的 "公共背包"
        app.state.telegram_app.bot_data["exchange"] = app.state.exchange
        app.state.telegram_app.bot_data["config"] = CONFIG
        app.state.telegram_app.bot_data["system_state"] = SystemState
        app.state.telegram_app.bot_data["application"] = app.state.telegram_app

        # 3. 初始化数据库
        await init_db()
        
        # 4. 启动Telegram Bot
        await start_bot(app)

        # 5. 设置初始状态
        await SystemState.set_state("ACTIVE", app.state.telegram_app)
        
        logger.info("系统启动完成。")
        yield
    except Exception as e:
        logger.critical(f"系统启动失败: {str(e)}", exc_info=True)
        # sys.exit(1) # 在生产环境中可以取消注释
    
    # 关闭
    logger.info("系统正在关闭...")
    await stop_bot(app)
    await app.state.exchange.close()

# --- 4. 创建FastAPI应用实例 ---
app = FastAPI(
    title="自适应共振交易系统",
    version="7.2-Final",
    lifespan=lifespan,
    debug=CONFIG.log_level == "DEBUG"
)

# --- 5. API 端点 (Endpoints) ---
@app.get("/")
def root():
    return {"status": "running", "version": app.version, "mode": CONFIG.run_mode}

@app.get("/health")
async def health_check():
    # 可以在这里增加数据库和交易所连接检查
    return {"status": "ok"}

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    """
    接收来自TradingView的Webhook信号 (安全加固版)
    """
    # 1. 安全验证
    signature = request.headers.get("X-Tv-Signature", "")
    payload = await request.body()
    
    if not verify_signature(CONFIG.tv_webhook_secret, signature, payload):
        raise HTTPException(status_code=401, detail="签名验证失败")
    
    if not rate_limit_check(request.client.host):
        raise HTTPException(status_code=429, detail="请求频率过高")
    
    # 2. 检查系统状态
    if not await SystemState.is_active():
        current_state = await SystemState.get_state()
        logger.warning(f"信号被拒绝，因为系统状态为: {current_state}")
        raise HTTPException(status_code=503, detail=f"Trading is not active. Current state: {current_state}")

    # 3. 数据处理与分发 (未来)
    try:
        signal_data = await request.json()
        logger.info(f"收到有效信号，准备分发给交易引擎: {signal_data}")
        # result = await process_signal(signal_data, request.app.state.exchange)
        
        return {"status": "processed", "data": signal_data}
    
    except Exception as e:
        logger.error(f"信号处理失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="信号格式错误或处理异常")