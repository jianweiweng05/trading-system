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

# --- 优化后的配置类 ---
class Config(BaseSettings):
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    discord_token: str = Field(..., env="DISCORD_TOKEN")
    tv_webhook_secret: str = Field(..., env="TV_WEBHOOK_SECRET")
    discord_channel_id: str = Field(..., env="DISCORD_CHANNEL_ID")
    run_mode: str = Field(default="simulate", env="RUN_MODE")

    class Config:
        extra = "forbid"  # 禁止额外字段

CONFIG = Config()

# --- 增强型安全过滤器 ---
class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, "msg"):
            msg = str(record.msg)
            for field in Config.__fields__.values():
                if (value := getattr(CONFIG, field.name)):
                    msg = msg.replace(value, "[REDACTED]")
            record.msg = msg
        return True

# --- 初始化 ---
logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

intents = discord.Intents.default()
intents.message_content = True
discord_bot = commands.Bot(command_prefix="!", intents=intents)

# --- Discord 事件 ---
@discord_bot.event
async def on_ready():
    channel = discord_bot.get_channel(int(CONFIG.discord_channel_id))
    await channel.send("✅ 交易系统连接成功")
    logger.info(f"Discord Bot 已登录: {discord_bot.user}")

# --- 保持原有功能不变 ---
# ... [原有 verify_signature, rate_limit_check, status 命令等代码完全不变] ...

# --- FastAPI 生命周期 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    exchange = None
    try:
        # ... [原有初始化代码不变，确保包含以下内容] ...
        
        # Discord 启动必须包含
        discord_bot.bot_data = {
            'exchange': exchange,
            'config': CONFIG
        }
        asyncio.create_task(discord_bot.start(CONFIG.discord_token))
        
        # ... [其他代码不变] ...
    finally:
        # ... [原有关闭逻辑，确保包含] ...
        if discord_bot.is_ready():
            await discord_bot.close()

# ... [保持所有原有路由不变] ...

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
