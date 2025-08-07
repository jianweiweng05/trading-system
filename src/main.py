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

# --- TV状态数据库操作 ---
async def init_tv_status_table():
    """初始化TV状态表"""
    try:
        from src.database import get_db_connection
        conn = await get_db_connection().__anext__()
        try:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tv_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol VARCHAR(10) NOT NULL UNIQUE,
                    status VARCHAR(20) NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.commit()
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"初始化TV状态表失败: {e}")
        raise

async def load_tv_status() -> Dict[str, str]:
    """从数据库加载TV状态"""
    status = {'btc': CONFIG.default_btc_status, 'eth': CONFIG.default_eth_status}
    try:
        from src.database import get_db_connection
        conn = await get_db_connection().__anext__()
        try:
            cursor = await conn.execute('SELECT symbol, status FROM tv_status')
            rows = await cursor.fetchall()
            for row in rows:
                status[row['symbol']] = row['status']
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"加载TV状态失败: {e}")
    return status

async def save_tv_status(symbol: str, status: str):
    """保存TV状态到数据库"""
    try:
        from src.database import get_db_connection
        conn = await get_db_connection().__anext__()
        try:
            await conn.execute('''
                INSERT OR REPLACE INTO tv_status (symbol, status, timestamp)
                VALUES (?, ?, ?)
            ''', (symbol, status, time.time()))
            await conn.commit()
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"保存TV状态失败: {e}")

# --- Discord Bot 启动函数 ---
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
        db_task = asyncio.create_task(init_db())
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
                exchange=app.state.exchange,
                alert_system=app.state.alert_system
            )
            logger.info("✅ 交易引擎已启动")
        
        # 启动黑天鹅雷达
        radar_task = await safe_start_task(
            start_black_swan_radar,
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
    except Exception as e:
        logger.error(f"❌ Discord机器人启动失败: {e}", exc_info=True)
        raise

# --- 安全启动任务包装函数 ---
async def safe_start_task(task_func, name: str) -> Optional[asyncio.Task]:
    """安全启动任务的包装函数"""
    try:
        task = asyncio.create_task(task_func())
        logger.info(f"✅ {name} 启动任务已创建")
        return task
    except ImportError as e:
        logger.error(f"❌ {name} 启动任务失败: {e}")
        return None

# --- 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global discord_bot_task, discord_bot, radar_task, startup_complete, alert_system, trading_engine
    exchange = None
    try:
        logger.info("🔄 系统启动中...")
        
        # 1. 初始化数据库连接
        from src.database import init_db
        db_task = asyncio.create_task(init_db())
        await db_task
        logger.info("✅ 数据库连接已建立")
        
        # 2. 初始化TV状态表
        await init_tv_status_table()
        logger.info("✅ TV状态表已初始化")
        
        # 3. 初始化交易所连接（重试机制）
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
        
        # 4. 初始化报警系统
        if CONFIG.discord_alert_webhook:
            app.state.alert_system = AlertSystem(
                webhook_url=CONFIG.discord_alert_webhook,
                cooldown_period=CONFIG.alert_cooldown_period
            )
            await app.state.alert_system.start()
            alert_system = app.state.alert_system
            logger.info("✅ 报警系统已启动")
        else:
            logger.warning("⚠️ 未配置Discord webhook，报警系统将不会启动")
            app.state.alert_system = None
        
        # 5. 初始化 AI 分析器
        app.state.macro_analyzer = MacroAnalyzer(api_key=CONFIG.deepseek_api_key)
        logger.info("✅ 宏观分析器已初始化")
        
        # 6. 初始化交易引擎
        if CONFIG.trading_engine:
            app.state.trading_engine = TradingEngine(
                exchange=exchange,
                alert_system=app.state.alert_system
            )
            trading_engine = app.state.trading_engine
            logger.info("✅ 交易引擎已启动")
        
        # 7. 启动黑天鹅雷达
        radar_task = await safe_start_task(
            start_black_swan_radar,
            "黑天鹅雷达"
        )
        logger.info("✅ 黑天鹅雷达已启动")
        
        # 8. 设置系统状态
        await SystemState.set_state("ACTIVE")
        startup_complete = True
        logger.info("🚀 系统启动完成")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ 系统启动失败: {e}", exc_info=True)
        await SystemState.set_state("ERROR")
        raise
    finally:
        logger.info("🛑 系统关闭中...")
        try:
            await SystemState.set_state("SHUTDOWN")
        except Exception as state_error:
            logger.error(f"设置关闭状态失败: {state_error}", exc_info=True)
        
        # 关闭所有组件
        if radar_task and not radar_task.done():
            radar_task.cancel()
            try:
                await radar_task
            except asyncio.CancelledError:
                pass
        
        if alert_system:
            try:
                await alert_system.stop()
            except Exception as e:
                logger.error(f"关闭报警系统失败: {e}")
        
        if trading_engine:
            trading_engine = None
            logger.info("✅ 交易引擎已关闭")
        
        if hasattr(app.state, 'exchange'):
            try:
                await app.state.exchange.close()
            except Exception as e:
                logger.error(f"关闭交易所连接失败: {e}")

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
    if radar_task and not radar_task.done():
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
    if radar_task and not radar_task.done():
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

@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    """TradingView Webhook接收端点"""
    try:
        # 获取请求体
        data = await request.json()
        
        # 验证webhook密钥
        if 'secret' not in data or data['secret'] != CONFIG.tv_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        # 解析警报数据
        symbol = data.get('symbol', '').lower()
        action = data.get('action', '').lower()
        
        # 更新状态
        if symbol in ['btc', 'eth'] and action in ['buy', 'sell', 'neutral']:
            await save_tv_status(symbol, action)
            logger.info(f"更新 {symbol} 状态为: {action}")
            
            return {"status": "success", "message": f"Updated {symbol} status to {action}"}
        else:
            raise HTTPException(status_code=400, detail="Invalid symbol or action")
            
    except Exception as e:
        logger.error(f"TradingView webhook处理失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/tv-status")
async def get_tv_status():
    """获取TradingView状态"""
    try:
        status = await load_tv_status()
        return {
            "btc": status['btc'],
            "eth": status['eth'],
            "last_update": time.time()
        }
    except Exception as e:
        logger.error(f"获取TV状态失败: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

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
