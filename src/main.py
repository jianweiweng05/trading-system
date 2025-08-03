import logging
import asyncio
import time
import hmac
import hashlib
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from ccxt.async_support import binance
import discord
from discord.ext import commands
from pydantic import Field
from pydantic_settings import BaseSettings

# --- 导入配置 ---
from src.config import CONFIG

# --- 日志配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Discord Bot ---
intents = discord.Intents.default()
intents.message_content = True
discord_bot = commands.Bot(command_prefix="!", intents=intents)

@discord_bot.event
async def on_ready():
    channel = discord_bot.get_channel(int(CONFIG.discord_channel_id))
    await channel.send("✅ 交易系统连接成功")
    logger.info(f"Discord Bot 已登录: {discord_bot.user}")

# --- 全局变量 ---
REQUEST_LOG = {}

# --- 辅助函数 ---
def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    if not secret:
        return True
    expected = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def rate_limit_check(client_ip: str) -> bool:
    now = time.time()
    if client_ip not in REQUEST_LOG:
        REQUEST_LOG[client_ip] = []
    REQUEST_LOG[client_ip] = [t for t in REQUEST_LOG[client_ip] if now - t < 60]
    if len(REQUEST_LOG[client_ip]) >= 20:
        return False
    REQUEST_LOG[client_ip].append(now)
    return True

# --- 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    exchange = None
    try:
        logger.info("🔄 系统启动中...")
        
        # 1. 初始化数据库
        from src.database import init_db
        await init_db()
        logger.info("✅ 数据库初始化完成")
        
        # 2. 初始化交易所连接
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange
        logger.info("✅ 交易所连接已建立")
        
        # 3. 启动 Discord Bot
        discord_bot.bot_data = {
            'exchange': exchange,
            'config': CONFIG
        }
        
        # 注册 Discord 命令
        from src.discord_bot import status
        discord_bot.add_command(status)
        logger.info("✅ Discord 命令已注册")
        
        asyncio.create_task(discord_bot.start(CONFIG.discord_token))
        logger.info("✅ Discord Bot 已启动")
        
        # 4. 设置系统状态
        from src.system_state import SystemState
        await SystemState.set_state("ACTIVE", discord_bot)
        logger.info("🚀 系统启动完成 (状态: ACTIVE)")
        
        yield
        
    except Exception as e:
        logger.critical(f"启动失败: {e}", exc_info=True)
        raise
    finally:
        logger.info("🛑 系统关闭中...")
        if discord_bot.is_ready():
            await discord_bot.close()
            logger.info("✅ Discord 服务已停止")
        if exchange:
            try:
                await exchange.close()
                logger.info("✅ 交易所连接已关闭")
            except Exception as e:
                logger.error(f"关闭交易所失败: {e}")
        logger.info("✅ 系统安全关闭")

# --- FastAPI 应用 ---
app = FastAPI(
    title="量化交易系统",
    version="7.2",
    lifespan=lifespan,
    debug=False
)

# --- 路由定义 ---
@app.get("/")
async def root():
    return {
        "status": "running",
        "version": app.version,
        "mode": CONFIG.run_mode
    }

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/startup-check")
async def startup_check():
    checks = {
        "config_loaded": hasattr(CONFIG, 'discord_token'),
        "db_accessible": False,
        "exchange_ready": False,
        "discord_ready": discord_bot.is_ready() if discord_bot else False
    }
    
    try:
        from src.database import engine
        async with engine.connect():
            checks["db_accessible"] = True
        if hasattr(app.state, 'exchange'):
            try:
                await app.state.exchange.fetch_time()
                checks["exchange_ready"] = True
            except:
                pass
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
    
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
    
    from src.system_state import SystemState
    if not await SystemState.is_active():
        current_state = await SystemState.get_state()
        raise HTTPException(503, detail=f"系统未激活 ({current_state})")

    try:
        signal_data = await request.json()
        logger.info(f"收到交易信号: {signal_data}")
        return {"status": "processed"}
    except Exception as e:
        logger.error(f"信号处理失败: {e}")
        raise HTTPException(400, detail="无效的JSON数据")

# --- 导出 ---
__all__ = ['app']

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000))
    )
