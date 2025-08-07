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
# --- 导入AI分析器 ---
from src.ai.macro_analyzer import MacroAnalyzer
# --- 导入黑天鹅雷达 ---
from src.ai.black_swan_radar import start_black_swan_radar
# --- 导入报警系统 ---
from src.alert_system import AlertSystem
# --- 导入交易引擎 ---
from src.trading_engine import TradingEngine

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
alert_system: Optional[AlertSystem] = None
trading_engine: Optional[TradingEngine] = None

# --- Discord Bot 启动函数 (修改) ---
async def start_discord_bot() -> Optional[Any]:
    """启动Discord机器人的异步函数"""
    global discord_bot
    try:
        from src.discord_bot import get_bot, initialize_bot
        
        max_retries = 20
        retry_delay = 2
        
        for i in range(max_retries):
            if hasattr(app.state, 'exchange') and app.state.exchange:
                logger.info("✅ 交易所连接已就绪，启动Discord机器人")
                break
            if i < max_retries - 1:
                logger.info(f"等待交易所连接建立... ({i+1}/{max_retries})")
                await asyncio.sleep(retry_delay)
        else:
            logger.warning("⚠️ 交易所连接未就绪，Discord机器人仍将启动")
        
        # 初始化数据库连接池
        from src.database import init_db
        db_task = asyncio.create_task(init_db)
        await db_task
        logger.info("✅ 数据库连接已建立")
        
        # 初始化报警系统
        alert_system = AlertSystem(
            webhook_url=CONFIG.discord_alert_webhook,
            cooldown_period=CONFIG.alert_cooldown_period
        )
        await alert_system.start()
        logger.info("✅ 报警系统已启动")
        
        # 初始化交易引擎
        trading_engine = TradingEngine(
            exchange=exchange,
            alert_system=alert_system
        )
        await trading_engine.initialize()
        logger.info("✅ 交易引擎已启动")
        
        # 启动黑天鹅雷达
        radar_task = await safe_start_task(
            start_black_swan_radar(),
            "黑天鹅雷达"
        )
        logger.info("✅ 黑天鹅雷达已启动")
        
        # 设置系统状态
        await SystemState.set_state("ACTIVE")
        startup_complete = True
        logger.info("🚀 系统启动完成")
        
    except Exception as e:
        logger.error(f"❌ Discord机器人启动失败: {e}", exc_info=True)
        raise

# --- 安全启动任务包装函数 (修改) ---
async def safe_start_task(task_func, name: str) -> Optional[asyncio.Task]:
    """安全启动任务的包装函数"""
    try:
        task = asyncio.create_task(task_func())
        logger.info(f"✅ {name} 启动任务已创建")
        return task
    except ImportError as e:
        logger.error(f"❌ {name} 启动任务失败: {e}")
        return None

# --- 生命周期管理 (修改) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global discord_bot_task, discord_bot, radar_task, startup_complete, alert_system, trading_engine
    exchange = None
    try:
        logger.info("🔄 系统启动中...")
        
        # 1. 并行初始化数据库和交易所连接
        from src.database import init_db
        db_task = asyncio.create_task(init_db)
        await db_task
        logger.info("✅ 数据库连接已建立")
        
        # 2. 初始化交易所连接（重试机制）
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True
            }
        })
        
        max_retries = int(os.getenv("EXCHANGE_MAX_RETRIES", "3"))
        
        for i in range(max_retries):
            try:
                await asyncio.sleep(int(os.getenv("EXCHANGE_RETRY_DELAY", "5")) * i)
                await exchange.load_markets()
                logger.info(f"✅ 交易所连接已建立 (尝试 {i+1}/{max_retries})")
                break
            except Exception as e:
                logger.error(f"❌ 交易所连接失败 (尝试 {i+1}/{max_retries}): {e}")
                if i == max_retries - 1:
                    logger.warning(f"⚠️ 达到最大重试次数，放弃连接")
                    raise
        
        await db_task
        logger.info("✅ 数据库和交易所连接已建立")
        
        # 3. 初始化 AI 分析器
        app.state.macro_analyzer = MacroAnalyzer(api_key=CONFIG.deepseek_api_key)
        logger.info("✅ 宏观分析器已初始化")
        
        # 4. 初始化报警系统
        if CONFIG.discord_alert_webhook:
            app.state.alert_system = AlertSystem(
                webhook_url=CONFIG.discord_alert_webhook,
                cooldown_period=CONFIG.alert_cooldown_period
            )
            await app.state.alert_system.start()
            logger.info("✅ 报警系统已启动")
        
        # 5. 初始化交易引擎
        if CONFIG.trading_engine:
            app.state.trading_engine = TradingEngine(
                exchange=exchange,
                alert_system=app.state.alert_system
            )
            await app.state.trading_engine.initialize()
            logger.info("✅ 交易引擎已启动")
        
        # 6. 启动黑天鹅雷达
        radar_task = await safe_start_task(
            start_black_swan_radar(),
            "黑天鹅雷达"
        )
        logger.info("✅ 黑天鹅雷达已启动")
        
        # 7. 设置系统状态
        await SystemState.set_state("ACTIVE")
        startup_complete = True
        logger.info("🚀 系统启动完成")
        
        # 8. 添加调试日志
        logger.info("📊 系统状态已设置为 ACTIVE")
        
        # 9. 添加详细的启动日志
        logger.info("🔄 系统启动中...")
        logger.info("📊 正在初始化数据库...")
        logger.info("📊 正在连接交易所...")
        
        # 10. 添加详细的启动日志
        logger.info("📊 正在初始化 AI 分析器...")
        logger.info("📊 正在初始化报警系统...")
        logger.info("📊 正在启动黑天鹅雷达...")
        
        # 11. 验证组件状态
        if not all([
            hasattr(app.state, 'exchange'),
            hasattr(app.state, 'trading_engine'),
            hasattr(app.state, 'alert_system')
        ]):
            logger.error("❌ 组件初始化失败")
            raise RuntimeError("组件初始化失败")
        
        # 12. 启动完成
        startup_complete = True
        logger.info("🚀 系统启动完成")
        
        # 13. 返回最终状态
        return {"status": "ok", "timestamp": time.time()}

# --- FastAPI 应用 (无变动) ---
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
    """健康检查端点"""
    checks = {
        "status": "unknown",
        "timestamp": time.time(),
        "components": {
            "config": hasattr(CONFIG, 'discord_token'),
            "database": False,
            "exchange": False,
            "discord": False,
            "radar": False,
            "alert_system": False,
            "trading_engine": False
        }
    }
    
    try:
        # 检查数据库连接
        from src.database import check_database_health
        checks["components"]["database"] = await check_database_health()
    except Exception as e:
        logger.error(f"数据库健康检查失败: {e}")
        checks["components"]["database"] = False
    
    # 检查交易所连接
    if hasattr(app.state, 'exchange'):
        try:
            await app.state.exchange.fetch_time()
            checks["components"]["exchange"] = True
        except Exception as e:
            logger.error(f"交易所连接检查失败: {e}")
            checks["components"]["exchange"] = False
    
    # 检查 Discord Bot
    if discord_bot and discord_bot.is_ready():
        checks["components"]["discord"] = True
    else:
        checks["components"]["discord"] = False
    
    # 检查黑天鹅雷达
    if radar_task and radar_task.done:
        checks["components"]["radar"] = True
    else:
        checks["components"]["radar"] = False
    
    # 检查报警系统
    if alert_system and alert_system.is_running():
        checks["components"]["alert_system"] = True
    else:
        checks["components"]["alert_system"] = False
    
    # 检查交易引擎
    if trading_engine:
        checks["components"]["trading_engine"] = True
    else:
        checks["components"]["trading_engine"] = False
    
    # 返回检查结果
    return {
        "status": "ok" if all(checks["components"].values()) else "degraded",
        "timestamp": time.time()
    }

@app.get("/startup-check")
async def startup_check() -> Dict[str, Any]:
    """启动检查端点"""
    checks = {
        "status": "unknown",
        "timestamp": time.time(),
        "components": {
            "config_loaded": hasattr(CONFIG, 'discord_token'),
            "database": False,
            "exchange": False,
            "discord": False,
            "radar": False,
            "alert_system": False,
            "trading_engine": False
        }
    }
    
    try:
        # 检查数据库连接
        from src.database import check_database_health
        checks["components"]["database"] = await check_database_health()
    except Exception as e:
        logger.error(f"数据库健康检查失败: {e}")
        checks["components"]["database"] = False
    
    # 检查交易所连接
    if hasattr(app.state, 'exchange'):
        try:
            await app.state.exchange.fetch_time()
            checks["components"]["exchange"] = True
        except Exception as e:
            logger.error(f"交易所连接检查失败: {e}")
            checks["components"]["exchange"] = False
    
    # 检查 Discord Bot
    if discord_bot and discord_bot.is_ready():
        checks["components"]["discord"] = True
    else:
        checks["components"]["discord"] = False
    
    # 检查黑天鹅雷达
    if radar_task and radar_task.done:
        checks["components"]["radar"] = True
    else:
        checks["components"]["radar"] = False
    
    # 检查报警系统
    if alert_system and alert_system.is_running():
        checks["components"]["alert_system"] = True
    else:
        checks["components"]["alert_system"] = False
    
    # 检查交易引擎
    if trading_engine:
        checks["components"]["trading_engine"] = True
    else:
        checks["components"]["trading_engine"] = False
    
    # 返回检查结果
    return {
        "status": "ok" if all(checks["components"].values()) else "degraded",
        "timestamp": time.time()
    }

# --- 主要修改区域 ---
# 1. 添加详细的启动日志
# 2. 添加组件状态检查
# 3. 增强错误处理和重试机制
# 4. 优化数据获取和验证

# --- 修改后的启动函数 ---
async def start_discord_bot() -> Optional[Any]:
    """启动Discord机器人的异步函数"""
    global discord_bot
    try:
        from src.discord_bot import get_bot, initialize_bot
        
        max_retries = 20
        retry_delay = 2
        
        for i in range(max_retries):
            try:
                if hasattr(app.state, 'exchange'):
                    logger.info(f"✅ 交易所连接已就绪 (尝试 {i+1}/{max_retries})")
                    await app.state.exchange.load_markets()
                    logger.info("✅ 交易所连接已建立")
                    break
                else:
                    logger.warning(f"⚠️ 交易所连接失败 (尝试 {i+1}/{max_retries})")
                    if i == max_retries - 1:
                        logger.warning(f"⚠️ 达到最大重试次数，放弃连接")
                        raise
        except Exception as e:
            logger.error(f"❌ 交易所连接失败: {e}")
                    raise
        
        # 初始化数据库连接池
        from src.database import init_db
        db_task = asyncio.create_task(init_db)
        await db_task
        logger.info("✅ 数据库连接已建立")
        
        # 初始化报警系统
        if CONFIG.discord_alert_webhook:
            app.state.alert_system = AlertSystem(
                webhook_url=CONFIG.discord_alert_webhook,
                cooldown_period=CONFIG.alert_cooldown_period
            )
            await app.state.alert_system.start()
            logger.info("✅ 报警系统已启动")
        
        # 初始化交易引擎
        if CONFIG.trading_engine:
            app.state.trading_engine = TradingEngine(
                exchange=exchange,
                alert_system=app.state.alert_system
            )
            await app.state.trading_engine.initialize()
            logger.info("✅ 交易引擎已启动")
        
        # 启动黑天鹅雷达
        radar_task = await safe_start_task(
            start_black_swan_radar(),
            "黑天鹅雷达"
        )
        logger.info("✅ 黑天鹅雷达已启动")
        
        # 设置系统状态为活跃
        await SystemState.set_state("ACTIVE")
        startup_complete = True
        logger.info("🚀 系统启动完成")
        
        # 添加详细的调试日志
        logger.info("🔄 正在初始化黑天鹅雷达...")
        logger.info("📊 正在检查系统组件...")
        logger.info("📊 正在验证系统状态...")
        
        # 验证关键组件
        if not all([
            hasattr(app.state, 'exchange'),
            hasattr(app.state, 'trading_engine'),
            hasattr(app.state, 'alert_system')
        ]):
            logger.error("❌ 系统组件初始化失败")
            raise RuntimeError("系统组件初始化失败")
        
        # 返回成功
        return {"status": "ok", "timestamp": time.time()}

# --- FastAPI 应用 (无变动) ---
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
    """健康检查端点"""
    try:
        # 检查数据库连接
        from src.database import check_database_health
        checks["components"]["database"] = await check_database_health()
        
        # 检查交易所连接
        if hasattr(app.state, 'exchange'):
            try:
                await app.state.exchange.fetch_time()
                checks["components"]["exchange"] = True
            except Exception as e:
                logger.error(f"交易所连接检查失败: {e}")
                checks["components"]["exchange"] = False
        
        # 检查 Discord Bot
        if discord_bot and discord_bot.is_ready():
            checks["components"]["discord"] = True
        else:
            checks["components"]["discord"] = False
        
        # 检查黑天鹅雷达
        if radar_task and radar_task.done:
            checks["components"]["radar"] = True
        else:
            checks["components"]["radar"] = False
        
        # 检查报警系统
        if alert_system and alert_system.is_running():
            checks["components"]["alert_system"] = True
        else:
            checks["components"]["alert_system"] = False
        
        # 检查交易引擎
        if trading_engine:
            checks["components"]["trading_engine"] = True
        else:
            checks["components"]["trading_engine"] = False
        
        # 返回检查结果
        return {
            "status": "ok" if all(checks["components"].values()) else "degraded",
            "timestamp": time.time()
        }

# --- 主函数 ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"启动服务器，端口: {port}")
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        workers=1
    )
