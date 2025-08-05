import logging
import asyncio
import time
import hmac
import hashlib
import os
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from ccxt.async_support import binance
import uvicorn

# --- 导入配置 ---
from src.config import CONFIG
# --- 导入系统状态模块 ---
from src.system_state import SystemState

# --- 日志配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 全局变量 ---
REQUEST_LOG: Dict[str, list] = {}
discord_bot_task: Optional[asyncio.Task] = None
discord_bot: Optional[Any] = None
radar_task: Optional[asyncio.Task] = None
startup_complete: bool = False

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
async def start_discord_bot() -> Optional[Any]:
    """启动Discord机器人的异步函数"""
    global discord_bot
    try:
        from src.discord_bot import get_bot, initialize_bot
        
        # 获取Discord机器人实例
        discord_bot = get_bot()
        
        # 等待交易所连接建立
        max_retries = 20
        retry_delay = 2
        
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
        logger.error(f"Discord机器人启动失败: {e}", exc_info=True)
        raise

# --- 安全启动任务包装函数 ---
async def safe_start_task(task_func, name: str) -> Optional[asyncio.Task]:
    """安全启动任务的包装函数"""
    try:
        task = asyncio.create_task(task_func())
        logger.info(f"✅ {name}启动任务已创建")
        return task
    except ImportError as e:
        logger.error(f"{name}模块导入失败: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"{name}启动失败: {e}", exc_info=True)
        return None

# --- 系统状态检查函数 ---
async def check_system_status() -> Dict[str, Any]:
    """检查系统整体状态"""
    status = {
        "state": "unknown",
        "components": {},
        "last_update": time.time()
    }
    
    try:
        current_state = await SystemState.get_state()
        status["state"] = current_state
        status["components"]["system_state"] = True
    except Exception as e:
        logger.error(f"系统状态检查失败: {e}", exc_info=True)
        status["components"]["system_state"] = False
    
    return status

# --- 优雅关闭处理函数 ---
async def graceful_shutdown():
    """优雅关闭所有服务"""
    logger.info("开始优雅关闭...")
    
    # 取消所有任务
    tasks = [discord_bot_task, radar_task]
    for task in tasks:
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"任务关闭超时")
            except asyncio.CancelledError:
                logger.info(f"任务已取消")
    
    # 关闭Discord Bot
    if discord_bot and discord_bot.is_ready():
        try:
            from src.discord_bot import stop_bot_services
            await asyncio.wait_for(stop_bot_services(discord_bot), timeout=5.0)
            logger.info("✅ Discord 服务已停止")
        except asyncio.TimeoutError:
            logger.warning("Discord服务关闭超时")
    
    # 关闭交易所连接
    if hasattr(app.state, 'exchange'):
        try:
            await asyncio.wait_for(app.state.exchange.close(), timeout=5.0)
            logger.info("✅ 交易所连接已关闭")
        except asyncio.TimeoutError:
            logger.warning("交易所连接关闭超时")
    
    logger.info("✅ 系统安全关闭")

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
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True
            }
        })
        
        # 添加重试机制
        max_retries = int(os.getenv("EXCHANGE_MAX_RETRIES", "3"))
        for i in range(max_retries):
            try:
                await asyncio.sleep(int(os.getenv("EXCHANGE_RETRY_DELAY", "5")) * i)
                await exchange.load_markets()
                logger.info("✅ 交易所连接已建立")
                break
            except Exception as e:
                if i == max_retries - 1:
                    logger.error(f"❌ 交易所连接失败: {e}", exc_info=True)
                    raise
                logger.warning(f"交易所连接重试 {i + 1}/{max_retries}")
        
        # 等待数据库初始化完成
        await db_task
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
        
        # 使用安全启动函数启动黑天鹅雷达
        radar_task = await safe_start_task(
            lambda: start_radar(),
            "黑天鹅雷达"
        )
        
        # 3. 立即设置系统状态，不等待其他任务
        await SystemState.set_state("ACTIVE", discord_bot)
        startup_complete = True
        logger.info("🚀 系统启动完成 (状态: ACTIVE)")
        
        yield
        
    except Exception as e:
        logger.critical(f"启动失败: {e}", exc_info=True)
        try:
            await SystemState.set_state("ERROR")
        except Exception as state_error:
            logger.error(f"设置错误状态失败: {state_error}", exc_info=True)
        raise
    finally:
        logger.info("🛑 系统关闭中...")
        try:
            await SystemState.set_state("SHUTDOWN")
        except Exception as state_error:
            logger.error(f"设置关闭状态失败: {state_error}", exc_info=True)
        
        await graceful_shutdown()

# --- FastAPI 应用 ---
app = FastAPI(
    title="量化交易系统",
    version="7.2",
    lifespan=lifespan,
    debug=False
)

# --- 路由定义 ---
@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "status": "running",
        "version": app.version,
        "mode": CONFIG.run_mode
    }

@app.get("/health")
async def health_check() -> Dict[str, Any]:
    checks = {
        "status": "unknown",
        "timestamp": time.time(),
        "components": {
            "config": hasattr(CONFIG, 'discord_token'),
            "database": False,
            "exchange": False,
            "discord": False,
            "radar": False
        }
    }
    
    # 检查数据库
    try:
        from src.database import check_database_health
        checks["components"]["database"] = await check_database_health()
    except Exception as e:
        logger.error(f"数据库健康检查失败: {e}", exc_info=True)
    
    # 检查交易所
    if hasattr(app.state, 'exchange'):
        try:
            await app.state.exchange.fetch_time()
            checks["components"]["exchange"] = True
        except Exception as e:
            logger.error(f"交易所健康检查失败: {e}", exc_info=True)
    
    # 检查Discord
    if discord_bot and discord_bot.is_ready():
        checks["components"]["discord"] = True
    
    # 检查雷达
    if radar_task and not radar_task.done():
        checks["components"]["radar"] = True
    
    # 设置整体状态
    checks["status"] = "ok" if all(checks["components"].values()) else "degraded"
    
    return checks

@app.get("/startup-check")
async def startup_check() -> Dict[str, Any]:
    checks = {
        "status": "unknown",
        "components": {
            "config_loaded": hasattr(CONFIG, 'discord_token'),
            "db_accessible": False,
            "exchange_ready": False,
            "discord_ready": False,
            "radar_ready": False
        }
    }
    
    try:
        from src.database import engine
        async with engine.connect():
            checks["components"]["db_accessible"] = True
        if hasattr(app.state, 'exchange'):
            try:
                await app.state.exchange.fetch_time()
                checks["components"]["exchange_ready"] = True
            except Exception as e:
                logger.error(f"交易所就绪检查失败: {e}", exc_info=True)
        if discord_bot and discord_bot.is_ready():
            checks["components"]["discord_ready"] = True
        if radar_task and not radar_task.done():
            checks["components"]["radar_ready"] = True
    except Exception as e:
        logger.error(f"启动检查失败: {e}", exc_info=True)
    
    return {
        "status": "ok" if all(checks["components"].values()) else "degraded",
        "checks": checks
    }

@app.post("/webhook")
async def tradingview_webhook(request: Request) -> Dict[str, Any]:
    if not hasattr(CONFIG, 'tv_webhook_secret'):
        raise HTTPException(503, detail="系统未初始化")
    
    signature = request.headers.get("X-Tv-Signature", "")
    payload = await request.body()
    if not verify_signature(CONFIG.tv_webhook_secret, signature, payload):
        raise HTTPException(401, detail="签名验证失败")
    
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit_check(client_ip):
        raise HTTPException(429, detail="请求过于频繁")
    
    try:
        signal_data = await request.json()
        
        # 记录详细的信号信息
        logger.info(f"收到交易信号 - IP: {client_ip}, 数据: {signal_data}")
        
        # 添加信号验证
        required_fields = ['symbol', 'action', 'price']
        if not all(field in signal_data for field in required_fields):
            raise ValueError("缺少必要的信号字段")
        
        # 检查系统状态
        if not await SystemState.is_active():
            current_state = await SystemState.get_state()
            logger.warning(f"系统未激活，拒绝处理信号 - 当前状态: {current_state}")
            raise HTTPException(503, detail=f"系统未激活 ({current_state})")
        
        # 这里可以添加处理交易信号的逻辑
        # 例如：调用交易函数执行下单操作
        
        return {"status": "processed", "timestamp": time.time()}
        
    except ValueError as e:
        logger.error(f"信号数据验证失败: {e}", exc_info=True)
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        logger.error(f"信号处理失败: {e}", exc_info=True)
        raise HTTPException(500, detail="内部处理错误")

# --- 主函数 ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"启动服务器，端口: {port}")
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        workers=1  # 减少worker数量为1，避免内存溢出
    )
