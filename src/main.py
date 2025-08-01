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
from pydantic_settings import BaseSettings

# --- 配置类（使用pydantic-settings）---
class Config(BaseSettings):
    binance_api_key: str
    binance_api_secret: str
    discord_token: str
    tv_webhook_secret: str
    discord_channel_id: str
    run_mode: str = "simulate"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

CONFIG = Config()

# --- 日志配置 ---
class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, "msg"):
            sensitive_keys = [
                CONFIG.binance_api_key,
                CONFIG.binance_api_secret,
                CONFIG.discord_token,
                CONFIG.tv_webhook_secret
            ]
            msg = str(record.msg)
            for key in filter(None, sensitive_keys):
                msg = msg.replace(key, "[REDACTED]")
            record.msg = msg
        return True

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --- Discord Bot 初始化 ---
intents = discord.Intents.default()
intents.message_content = True
discord_bot = commands.Bot(command_prefix="!", intents=intents)

# --- 核心功能 ---
REQUEST_LOG = {}

def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    if not secret:
        logger.warning("Webhook secret not configured")
        return True
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def rate_limit_check(client_ip: str) -> bool:
    now = time.time()
    REQUEST_LOG[client_ip] = [t for t in REQUEST_LOG.get(client_ip, []) if now - t < 60]
    if len(REQUEST_LOG[client_ip]) >= 20:
        logger.warning(f"Rate limit triggered for {client_ip}")
        return False
    REQUEST_LOG[client_ip].append(now)
    return True

# --- Discord 命令 ---
@discord_bot.command()
async def status(ctx):
    """系统状态查询"""
    embed = discord.Embed(title="📊 系统状态")
    embed.add_field(name="运行模式", value=CONFIG.run_mode.upper())
    await ctx.send(embed=embed)

# --- FastAPI 应用 ---
app = FastAPI(
    title="Quant Trading System",
    version="7.2",
    lifespan=lifespan
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    exchange = None
    try:
        logger.info("Initializing system...")
        
        # 初始化交易所连接
        exchange = binance({
            "apiKey": CONFIG.binance_api_key,
            "secret": CONFIG.binance_api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"}
        })
        app.state.exchange = exchange

        # 启动 Discord Bot
        discord_bot.bot_data = {"exchange": exchange}
        asyncio.create_task(discord_bot.start(CONFIG.discord_token))
        
        logger.info("System initialized")
        yield

    except Exception as e:
        logger.critical(f"Initialization failed: {e}")
        raise
    finally:
        if exchange:
            await exchange.close()
        if discord_bot.is_ready():
            await discord_bot.close()

@app.exception_handler(Exception)
async def global_error_handler(_, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"}
    )

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

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    # 签名验证
    signature = request.headers.get("X-Tv-Signature", "")
    if not verify_signature(CONFIG.tv_webhook_secret, signature, await request.body()):
        raise HTTPException(401, detail="Signature verification failed")

    # 频率限制
    client_ip = request.client.host or "unknown"
    if not rate_limit_check(client_ip):
        raise HTTPException(429, detail="Rate limit exceeded")

    try:
        data = await request.json()
        logger.info(f"Received signal: {data.get('symbol')}")
        return {"status": "processed"}
    except Exception as e:
        logger.warning(f"Signal processing failed: {e}")
        raise HTTPException(400, detail="Invalid data")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_config=None
    )
