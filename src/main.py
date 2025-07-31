# 文件: src/main.py (最终修正版)

import logging
import time
import hmac
import hashlib
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from ccxt.async_support import binance
from telegram.ext import ApplicationBuilder

# --- 1. 模块导入 ---
from config import CONFIG, init_config
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
    REQUEST_LOG.setdefault(client_ip, [])
    
    REQUEST_LOG[client_ip] = [t for t in REQUEST_LOG[client_ip] if now - t < 60]
    
    if len(REQUEST_LOG[client_ip]) >= 20:
        logger.warning(f"IP {client_ip} 请求频率过高。")
        return False
    
    REQUEST_LOG[client_ip].append(now)
    return True

# --- 3. 生命周期管理 (Lifespan) - 最终版 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用启动时按正确顺序初始化所有核心模块，关闭时优雅清理
    """
    # --- 启动 ---
    exchange = None
    
    try:
        logger.info("系统正在启动...")
        
        # 步骤 1: 初始化配置 (必须是第一步！)
        await init_config()
        
        # 步骤 2: 初始化数据库
        await init_db()
        
        # 步骤 3: 创建核心对象
        exchange = binance({
            'apiKey': CONFIG.binance_api_key, 'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True, 'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange
        
        telegram_app = ApplicationBuilder().token(CONFIG.telegram_bot_token).build()
        app.state.telegram_app = telegram_app

        # 步骤 4: 将核心对象注入到Telegram Bot的 "公共背包"
        telegram_app.bot_data["exchange"] = exchange
        telegram_app.bot_data["config"] = CONFIG
        telegram_app.bot_data["system_state"] = SystemState
        telegram_app.bot_data["application"] = telegram_app
        
        # 步骤 5: 启动Telegram Bot
        await start_bot(app)

        # 步骤 6: 设置系统初始状态
        await SystemState.set_state("ACTIVE", telegram_app)
        
        logger.info("✅ 系统启动完成。")
        yield
        
    except Exception as e:
        logger.critical(f"❌ 系统启动失败: {str(e)}", exc_info=True)
        # import sys
        # sys.exit(1)
    
    # --- 关闭 (已修正) ---
    logger.info("系统正在关闭...")
    
    # 使用 hasattr 检查属性是否存在，这是更安全的方式
    if hasattr(app.state, 'telegram_app'):
        await stop_bot(app)
    
    if exchange:
        await exchange.close()
    logger.info("系统已成功关闭。")

# --- 4. 创建FastAPI应用实例 ---
app = FastAPI(
    title="自适应共振交易系统",
    version="7.2-Final-Configurable",
    lifespan=lifespan
)

# --- 5. API 端点 (Endpoints) ---
@app.get("/")
def root():
    return {"status": "running", "version": app.version, "mode": CONFIG.run_mode if CONFIG else "initializing"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    """
    接收来自TradingView的Webhook信号 (安全加固版)
    """
    if not verify_signature(CONFIG.tv_webhook_secret, request.headers.get("X-Tv-Signature", ""), await request.body()):
        raise HTTPException(status_code=401, detail="签名验证失败")
    
    if not rate_limit_check(request.client.host):
        raise HTTPException(status_code=429, detail="请求频率过高")
    
    if not await SystemState.is_active():
        current_state = await SystemState.get_state()
        logger.warning(f"信号被拒绝，因为系统状态为: {current_state}")
        raise HTTPException(status_code=503, detail=f"Trading is not active. Current state: {current_state}")

    try:
        signal_data = await request.json()
        logger.info(f"收到有效信号 (模式: {CONFIG.run_mode.upper()})，准备分发给交易引擎: {signal_data}")
        
        return {"status": "processed", "data": signal_data}
    
    except Exception as e:
        logger.error(f"信号处理失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="信号格式错误或处理异常")

# --- 6. 启动服务器 ---
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
