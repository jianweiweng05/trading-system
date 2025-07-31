# 文件: src/main.py (完整兼容版)

import logging
import asyncio
import hmac
import hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from ccxt.async_support import binance
from telegram.ext import ApplicationBuilder

# 导入模块（保持原有结构）
from config import CONFIG, init_config
from system_state import SystemState
from telegram_bot import start_bot, stop_bot

logger = logging.getLogger(__name__)

# --- 辅助函数 ---
def verify_signature(secret: str, payload: bytes, signature: str) -> bool:
    """安全签名验证"""
    if not secret:
        logger.warning("未配置签名密钥，跳过验证")
        return True
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

# --- 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """严格按顺序初始化的上下文管理器"""
    exchange = None
    
    try:
        # 阶段1: 必须首先初始化配置
        await init_config()
        logger.info(f"✅ 配置加载完成 (模式: {CONFIG.run_mode})")

        # 阶段2: 初始化数据库和交易所
        from database import init_db
        await init_db()
        
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange

        # 阶段3: 启动Telegram Bot
        await start_bot(app)
        
        # 阶段4: 设置系统状态
        await SystemState.set_state("ACTIVE")
        
        logger.info("🚀 系统启动完成")
        yield

    except Exception as e:
        logger.critical(f"启动失败: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("🛑 正在关闭系统...")
        await stop_bot(app)
        if exchange:
            await exchange.close()
        logger.info("✅ 系统已安全关闭")

# --- FastAPI应用 ---
app = FastAPI(
    lifespan=lifespan,
    title="交易系统",
    description="与现有config.py完全兼容的版本"
)

# --- 核心端点 ---
@app.post("/webhook")
async def handle_webhook(request: Request):
    """处理交易信号（保持原有逻辑）"""
    if not verify_signature(
        getattr(CONFIG, 'tv_webhook_secret', ''),
        await request.body(),
        request.headers.get("X-Signature", "")
    ):
        raise HTTPException(403, "签名验证失败")

    if not await SystemState.is_active():
        raise HTTPException(503, "系统未就绪")
    
    return {"status": "processed"}

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "config_loaded": bool(CONFIG),
        "mode": getattr(CONFIG, 'run_mode', 'unknown')
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=getattr(CONFIG, 'port', 8000))
