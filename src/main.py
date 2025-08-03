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
            # 获取所有字段名
            field_names = [
                'binance_api_key',
                'binance_api_secret',
                'discord_token',
                'tv_webhook_secret',
                'discord_channel_id',
                'run_mode'
            ]
            
            # 替换敏感信息
            for field_name in field_names:
                if hasattr(CONFIG, field_name):
                    value = getattr(CONFIG, field_name)
                    if value:
                        msg = msg.replace(value, f"[REDACTED_{field_name.upper()}]")
            
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

# --- 全局变量 ---
REQUEST_LOG = {}

# --- 辅助函数 ---
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

# --- FastAPI 生命周期 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    exchange = None
    try:
        logger.info("🔄 系统启动中...")
        
        # 1. 初始化数据库
        from database import init_db
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
        asyncio.create_task(discord_bot.start(CONFIG.discord_token))
        logger.info("✅ Discord Bot 已启动")
        
        # 4. 设置系统状态
        from system_state import SystemState
        await SystemState.set_state("ACTIVE", discord_bot)
        logger.info("🚀 系统启动完成 (状态: ACTIVE)")
        
        yield  # FastAPI服务正式运行
        
    except Exception as e:
        logger.critical(f"启动失败: {e}", exc_info=True)
        raise
    finally:
        logger.info("🛑 系统关闭中...")
        
        # 停止 Discord 服务
        if discord_bot.is_ready():
            await discord_bot.close()
            logger.info("✅ Discord 服务已停止")
        
        # 关闭交易所连接
        if exchange:
            try:
                await exchange.close()
                logger.info("✅ 交易所连接已关闭")
            except Exception as e:
                logger.error(f"关闭交易所失败: {e}")
        
        logger.info("✅ 系统安全关闭")

# --- FastAPI 应用定义 ---
app = FastAPI(
    title="量化交易系统",
    version="7.2",
    lifespan=lifespan,
    debug=False
)

# --- FastAPI 路由 ---
@app.get("/")
async def root():
    """根端点"""
    return {
        "status": "running",
        "version": app.version,
        "mode": CONFIG.run_mode
    }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok"}

@app.get("/startup-check")
async def startup_check():
    """深度健康检查"""
    checks = {
        "config_loaded": hasattr(CONFIG, 'discord_token'),
        "db_accessible": False,
        "exchange_ready": False,
        "discord_ready": discord_bot.is_ready() if discord_bot else False
    }
    
    try:
        # 数据库检查
        from database import engine
        async with engine.connect():
            checks["db_accessible"] = True
        
        # 交易所检查
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
    """交易信号Webhook"""
    if not hasattr(CONFIG, 'tv_webhook_secret'):
        raise HTTPException(503, detail="系统未初始化")
    
    # 签名验证
    signature = request.headers.get("X-Tv-Signature", "")
    payload = await request.body()
    if not verify_signature(CONFIG.tv_webhook_secret, signature, payload):
        raise HTTPException(401, detail="签名验证失败")
    
    # 频率限制
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit_check(client_ip):
        raise HTTPException(429, detail="请求过于频繁")
    
    # 系统状态检查
    from system_state import SystemState
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

# --- 导出配置 ---
__all__ = ['app']

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000))
    )
