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

# ==== 修改点1：配置类（原CONFIG全局变量替换）====
class Config(BaseSettings):
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    discord_token: str = os.getenv("DISCORD_TOKEN", "")
    tv_webhook_secret: str = os.getenv("TV_WEBHOOK_SECRET", "")
    discord_channel_id: str = os.getenv("DISCORD_CHANNEL_ID", "")
    run_mode: str = os.getenv("RUN_MODE", "simulate")

CONFIG = Config()

# ==== 修改点2：安全过滤器 ====
class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, "msg"):
            msg = str(record.msg)
            for var in ["BINANCE_API_KEY", "BINANCE_API_SECRET", "DISCORD_TOKEN", "TV_WEBHOOK_SECRET"]:
                if (value := os.getenv(var)):
                    msg = msg.replace(value, "[REDACTED]")
            record.msg = msg
        return True

# ==== 以下为原有代码（完全未改动）====
logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

intents = discord.Intents.default()
intents.message_content = True
discord_bot = commands.Bot(command_prefix="!", intents=intents)

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

@discord_bot.command()
async def status(ctx):
    """查看系统状态"""
    stats = {
        "status": "ACTIVE",
        "mode": CONFIG.run_mode,
        "exchange": "Connected" if ctx.bot.bot_data.get('exchange') else "Disconnected"
    }
    embed = discord.Embed(title="📊 系统状态", color=0x00ff00)
    embed.add_field(name="运行模式", value=stats['mode'].upper())
    embed.add_field(name="交易所", value=stats['exchange'])
    await ctx.send(embed=embed)

app = FastAPI(
    title="量化交易系统",
    version="7.2",
    lifespan=lifespan,
    debug=False
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    exchange = None
    try:
        logger.info("🔄 系统启动中...")
        
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange
        logger.info("✅ 交易所连接已建立")
        
        discord_bot.bot_data = {
            'config': CONFIG,
            'exchange': exchange,
            'app': app
        }
        asyncio.create_task(discord_bot.start(CONFIG.discord_token))
        logger.info("✅ Discord Bot已启动")
        
        await SystemState.set_state("ACTIVE", discord_bot)
        logger.info("🚀 系统启动完成 (状态: ACTIVE)")
        
        yield
        
    except Exception as e:
        logger.critical(f"启动失败: {e}", exc_info=True)
        raise
    finally:
        logger.info("🛑 系统关闭中...")
        
        if exchange:
            try:
                await exchange.close()
                logger.info("✅ 交易所连接已关闭")
            except Exception as e:
                logger.error(f"关闭交易所失败: {e}")
        
        if discord_bot.is_ready():
            await discord_bot.close()
            logger.info("✅ Discord Bot已关闭")
        
        logger.info("✅ 系统安全关闭")

@app.get("/")
async def root():
    return {
        "status": "running",
        "version": app.version,
        "mode": CONFIG.run_mode if hasattr(CONFIG, 'run_mode') else "unknown"
    }

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/startup-check")
async def startup_check():
    checks = {
        "config_loaded": all([
            CONFIG.binance_api_key,
            CONFIG.binance_api_secret,
            CONFIG.discord_token,
            CONFIG.tv_webhook_secret
        ]),
        "db_accessible": False,
        "exchange_ready": False,
        "discord_ready": discord_bot.is_ready() if discord_bot else False
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
                logger.debug(f"交易所连接检查失败: {e}")
                
    except Exception as e:
        logger.warning(f"健康检查失败: {e}")
    
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "checks": checks
    }

@app.post("/webhook")
async def tradingview_webhook(request: Request):
    if not CONFIG.tv_webhook_secret:
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
        
        if discord_bot.is_ready():
            channel = discord_bot.get_channel(int(CONFIG.discord_channel_id))
            await channel.send(f"📢 收到交易信号: {signal_data.get('symbol', '未知')}")
            
        return {"status": "processed"}
    except Exception as e:
        logger.warning(f"信号处理失败: {e}")
        raise HTTPException(400, detail="无效的JSON数据")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_config=None
    )
