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
import uvicorn

# --- 导入配置 ---
from src.config import CONFIG

# --- 日志配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 全局变量 ---
REQUEST_LOG = {}
discord_bot_task = None  # 用于存储Discord机器人任务
discord_bot = None  # 用于存储Discord机器人实例
radar_task = None  # 用于存储黑天鹅雷达任务
startup_complete = False  # 标记系统是否完全启动

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

# --- Discord Bot 启动函数 ---
async def start_discord_bot():
    """启动Discord机器人的异步函数"""
    global discord_bot
    try:
        from src.discord_bot import get_bot, initialize_bot
        
        # 获取Discord机器人实例
        discord_bot = get_bot()
        
        # 等待交易所连接建立
        max_retries = 20  # 增加重试次数
        retry_delay = 2   # 增加重试间隔
        
        for i in range(max_retries):
            if hasattr(app.state, 'exchange') and app.state.exchange:
                logger.info("✅ 交易所连接已就绪，启动Discord机器人")
                break
            if i < max_retries - 1:
                logger.info(f"等待交易所连接建立... ({i + 1}/{max_retries})")
                await asyncio.sleep(retry_delay)
        else:
            logger.warning("⚠️ 交易所连接未就绪，Discord机器人仍将启动")
        
        # 设置机器人数据
        discord_bot.bot_data = {
            'exchange': getattr(app.state, 'exchange', None),
            'config': CONFIG
        }
        
        # 验证交易所连接
        if discord_bot.bot_data['exchange']:
            try:
                await discord_bot.bot_data['exchange'].fetch_time()
                logger.info("✅ 交易所连接验证成功")
            except Exception as e:
                logger.error(f"❌ 交易所连接验证失败: {e}")
                discord_bot.bot_data['exchange'] = None
        
        # 初始化机器人
        await initialize_bot(discord_bot)
        
        # 标记启动完成
        startup_complete = True
        logger.info("🚀 系统启动完成")
        
        return discord_bot
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        raise

# --- 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global discord_bot_task, discord_bot, radar_task, startup_complete
    exchange = None
    try:
        logger.info("🔄 系统启动中...")
        
        # 1. 并行初始化数据库和交易所连接
        from src.database import init_db
        db_task = asyncio.create_task(init_db())
        
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        exchange_task = asyncio.create_task(exchange.load_markets())
        
        # 等待数据库和交易所初始化完成
        await asyncio.gather(db_task, exchange_task)
        logger.info("✅ 数据库和交易所初始化完成")
        
        app.state.exchange = exchange
        
        # 2. 并行启动 Discord Bot 和黑天鹅雷达
        from src.discord_bot import get_bot, initialize_bot
        discord_bot = get_bot()
        discord_bot.bot_data = {
            'exchange': exchange,
            'config': CONFIG
        }
        
        # 创建启动任务但不等待
        discord_bot_task = asyncio.create_task(initialize_bot(discord_bot))
        logger.info("✅ Discord Bot 启动任务已创建")
        
        try:
            from src.black_swan_radar import start_radar
            radar_task = asyncio.create_task(start_radar())
            logger.info("✅ 黑天鹅雷达启动任务已创建")
        except ImportError as e:
            logger.error(f"黑天鹅雷达模块导入失败: {e}")
        except Exception as e:
            logger.error(f"黑天鹅雷达启动失败: {e}")
        
        # 3. 立即设置系统状态，不等待其他任务
        from src.system_state import SystemState
        await SystemState.set_state("ACTIVE", discord_bot)
        startup_complete = True
        logger.info("🚀 系统启动完成 (状态: ACTIVE)")
        
        yield
        
    except Exception as e:
        logger.critical(f"启动失败: {e}", exc_info=True)
        try:
            await SystemState.set_state("ERROR")
        except:
            pass
        raise
    finally:
        logger.info("🛑 系统关闭中...")
        try:
            await SystemState.set_state("SHUTDOWN")
        except:
            pass
        
        tasks = [discord_bot_task, radar_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"✅ 任务已取消")
        
        if discord_bot and discord_bot.is_ready():
            from src.discord_bot import stop_bot_services
            await stop_bot_services(discord_bot)
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
    return {
        "status": "ok",
        "timestamp": time.time()
    }

@app.get("/startup-check")
async def startup_check():
    checks = {
        "config_loaded": hasattr(CONFIG, 'discord_token'),
        "db_accessible": False,
        "exchange_ready": False,
        "discord_ready": False,
        "radar_ready": False
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
        if discord_bot and discord_bot.is_ready():
            checks["discord_ready"] = True
        if radar_task and not radar_task.done():
            checks["radar_ready"] = True
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
        
        # 这里可以添加处理交易信号的逻辑
        # 例如：调用交易函数执行下单操作
        
        return {"status": "processed"}
    except Exception as e:
        logger.error(f"信号处理失败: {e}")
        raise HTTPException(400, detail="无效的JSON数据")

# --- 主函数 ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"启动服务器，端口: {port}")
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
