import logging
import asyncio
import time
import hmac
import hashlib
import os
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from ccxt.async_support import binance
import discord
from discord.ext import commands
from pydantic import BaseSettings

# --- 配置类 ---
class Config(BaseSettings):
    binance_api_key: str
    binance_api_secret: str
    discord_token: str
    tv_webhook_secret: str
    discord_channel_id: str
    run_mode: str = 'simulate'

    class Config:
        env_file = '.env'

CONFIG = Config()

# --- 日志配置 ---
class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, 'msg'):
            record.msg = re.sub(
                r'(api[_-]?key|secret|token)=[\w-]+', 
                '[REDACTED]', 
                str(record.msg)
        return True

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- Discord Bot ---
intents = discord.Intents.default()
intents.message_content = True
discord_bot = commands.Bot(command_prefix="!", intents=intents)

# --- 系统核心 ---
REQUEST_LOG = {}
app = FastAPI(title="量化交易系统", version="7.2")

# --- 辅助函数 ---
def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    if not secret:
        logger.warning("未设置webhook密钥")
        return True
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def rate_limit_check(client_ip: str) -> bool:
    now = time.time()
    REQUEST_LOG[client_ip] = [t for t in REQUEST_LOG.get(client_ip, []) if now - t < 60]
    if len(REQUEST_LOG[client_ip]) >= 20:
        logger.warning(f"限流触发: {client_ip}")
        return False
    REQUEST_LOG[client_ip].append(now)
    return True

# --- Discord命令 ---
@discord_bot.command()
async def status(ctx):
    embed = discord.Embed(title="系统状态")
    embed.add_field(name="模式", value=CONFIG.run_mode.upper())
    await ctx.send(embed=embed)

# --- 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    exchange = None
    try:
        logger.info("系统启动中...")
        
        # 初始化交易所
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange

        # 启动Discord Bot
        discord_bot.bot_data = {'exchange': exchange}
        asyncio.create_task(discord_bot.start(CONFIG.discord_token))
        
        logger.info("系统启动完成")
        yield

    except Exception as e:
        logger.critical(f"启动失败: {e}")
        raise
    finally:
        if exchange: 
            await exchange.close()
        if discord_bot.is_ready():
            await discord_bot.close()

# --- 错误处理 ---
@app.exception_handler(Exception)
async def global_error_handler(_, exc):
    logger.error(f"系统异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "内部服务器错误"}
    )

# --- API路由 ---
@app.get("/")
async def root():
    return {"status": "running", "mode": CONFIG.run_mode}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    if not verify_signature(
        CONFIG.tv_webhook_secret,
        request.headers.get("X-Tv-Signature", ""),
        await request.body()
    ):
        raise HTTPException(401, detail="签名验证失败")

    if not rate_limit_check(request.client.host or "unknown"):
        raise HTTPException(429, detail="请求过于频繁")

    try:
        data = await request.json()
        logger.info(f"收到信号: {data['symbol']}")
        return {"status": "processed"}
    except Exception as e:
        logger.warning(f"信号处理失败: {e}")
        raise HTTPException(400, detail="无效数据")

# --- 启动 ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
