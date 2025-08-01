import logging
import asyncio
import time
import hmac
import hashlib
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from ccxt.async_support import binance
import discord
from discord.ext import commands

from config import CONFIG, init_config
from database import init_db
from system_state import SystemState

logger = logging.getLogger(__name__)

# 初始化Discord Bot
intents = discord.Intents.default()
intents.message_content = True
discord_bot = commands.Bot(command_prefix="!", intents=intents)

# 请求频率限制记录
REQUEST_LOG = {}

def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    """验证Webhook签名"""
    if not secret:
        logger.warning("未设置webhook密钥，跳过验证")
        return True
    expected = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def rate_limit_check(client_ip: str) -> bool:
    """请求频率限制检查"""
    now = time.time()
    if client_ip not in REQUEST_LOG:
        REQUEST_LOG[client_ip] = []
    
    REQUEST_LOG[client_ip] = [t for t in REQUEST_LOG[client_ip] if now - t < 60]
    
    if len(REQUEST_LOG[client_ip]) >= 20:
        logger.warning(f"IP {client_ip} 请求过于频繁")
        return False
    
    REQUEST_LOG[client_ip].append(now)
    return True

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI生命周期管理"""
    exchange = None
    
    try:
        logger.info("🔄 系统启动中...")
        
        # 1. 初始化数据库
        await init_db()
        logger.info("✅ 数据库初始化完成")
        
        # 2. 加载配置
        config = await init_config()
        if not config:
            raise RuntimeError("配置初始化失败")
        logger.info(f"✅ 配置加载完成 (模式: {config.run_mode})")
        
        # 3. 初始化交易所连接
        exchange = binance({
            'apiKey': config.binance_api_key,
            'secret': config.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        app.state.exchange = exchange
        logger.info("✅ 交易所连接已建立")
        
        # 4. 启动Discord Bot
        discord_bot.bot_data = {
            'config': config,
            'exchange': exchange,
            'app': app
        }
        asyncio.create_task(discord_bot.start(config.discord_token))
        logger.info("✅ Discord Bot已启动")
        
        # 5. 设置系统状态
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

# Discord命令
@discord_bot.command()
async def status(ctx):
    """查看系统状态"""
    stats = {
        "status": "ACTIVE",
        "mode": ctx.bot.bot_data['config'].run_mode,
        "exchange": "Connected" if ctx.bot.bot_data.get('exchange') else "Disconnected"
    }
    embed = discord.Embed(title="📊 系统状态", color=0x00ff00)
    embed.add_field(name="运行模式", value=stats['mode'].upper())
    embed.add_field(name="交易所", value=stats['exchange'])
    await ctx.send(embed=embed)

# FastAPI应用
app = FastAPI(
    title="量化交易系统",
    version="7.2",
    lifespan=lifespan,
    debug=False
)

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
        "config_loaded": hasattr(CONFIG, 'discord_token'),
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
        
        # 通过Discord发送通知
        if discord_bot.is_ready():
            channel = discord_bot.get_channel(int(CONFIG.discord_channel_id))
            await channel.send(f"📢 收到交易信号: {signal_data['symbol']}")
            
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
