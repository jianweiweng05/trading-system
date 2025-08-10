# --- 请用这段新代码，替换你文件顶部所有的 import 语句 ---

import logging
import asyncio
import time
import os
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
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
# --- 导入 Discord Bot 启动器 ---
from src.discord_bot import start_discord_bot as run_discord_bot, stop_bot_services
# --- 导入数据库函数 ---
from src.database import get_setting, db_pool # 【修改】将 db_pool 也导入

# --- 日志配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- TV状态数据库操作 ---
# --- 请用这段新代码，替换你现有的 init_tv_status_table, load_tv_status, save_tv_status 这三个函数 ---

# --- TV状态数据库操作 ---
async def init_tv_status_table() -> None:
    """初始化TV状态表"""
    try:
        # 【修改】使用正确的 async with 语法
        async with db_pool.get_session() as session:
            async with session.begin():
                await session.execute(text('''
                    CREATE TABLE IF NOT EXISTS tv_status (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol VARCHAR(10) NOT NULL UNIQUE,
                        status VARCHAR(20) NOT NULL,
                        timestamp REAL NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                '''))
    except Exception as e:
        logger.error(f"初始化TV状态表失败: {e}")
        raise

async def load_tv_status() -> Dict[str, str]:
    """从数据库加载TV状态"""
    status = {'btc': CONFIG.default_btc_status, 'eth': CONFIG.default_eth_status}
    try:
        # 【修改】使用正确的 async with 语法
        async with db_pool.get_session() as session:
            cursor = await session.execute(text('SELECT symbol, status FROM tv_status'))
            rows = cursor.fetchall() # fetchall 不是异步的
            for row in rows:
                # SQLAlchemy 2.0+ row 是一个 Row 对象，可以通过索引或名称访问
                status[row[0]] = row[1]
    except Exception as e:
        logger.error(f"加载TV状态失败: {e}")
    return status

async def save_tv_status(symbol: str, status: str) -> None:
    """保存TV状态到数据库"""
    try:
        # 【修改】使用正确的 async with 语法
        async with db_pool.get_session() as session:
            async with session.begin():
                await session.execute(text('''
                    INSERT OR REPLACE INTO tv_status (symbol, status, timestamp)
                    VALUES (:symbol, :status, :timestamp)
                '''), {"symbol": symbol, "status": status, "timestamp": time.time()})
    except Exception as e:
        logger.error(f"保存TV状态失败: {e}")
        raise
async def load_tv_status() -> Dict[str, str]:
    """从数据库加载TV状态"""
    status = {'btc': CONFIG.default_btc_status, 'eth': CONFIG.default_eth_status}
    try:
        async with db_pool.get_session() as session:
            cursor = await session.execute(text('SELECT symbol, status FROM tv_status'))
            rows = cursor.fetchall()
            for row in rows:
                status[row[0]] = row[1]
    except Exception as e:
        logger.error(f"加载TV状态失败: {e}")
    return status

async def save_tv_status(symbol: str, status: str) -> None:
    """保存TV状态到数据库"""
    try:
        async with db_pool.get_session() as session:
            async with session.begin():
                await session.execute(text('''
                    INSERT OR REPLACE INTO tv_status (symbol, status, timestamp)
                    VALUES (:symbol, :status, :timestamp)
                '''), {"symbol": symbol, "status": status, "timestamp": time.time()})
    except Exception as e:
        logger.error(f"保存TV状态失败: {e}")
        raise

# --- 安全启动任务包装函数 ---
async def safe_start_task(task_func, name: str) -> Optional[asyncio.Task]:
    """安全启动任务的包装函数"""
    try:
        task = asyncio.create_task(task_func())
        logger.info(f"✅ {name} 启动任务已创建")
        return task
    except Exception as e:
        logger.error(f"❌ {name} 启动任务失败: {e}", exc_info=True)
        return None

# --- 【修改】生命周期管理，增加状态恢复逻辑 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器。
    负责在应用启动时初始化所有服务，在关闭时优雅地释放资源。
    """
    logger.info("🔄 系统启动中...")
    
    background_tasks = {}
    
    try:
        # 1. 初始化数据库连接
        from src.database import init_db
        await init_db()
        logger.info("✅ 数据库连接已建立")
        
        # 2. 初始化TV状态表
        await init_tv_status_table()
        logger.info("✅ TV状态表已初始化")
        
        # 3. 初始化交易所连接
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
        })
        await exchange.load_markets()
        app.state.exchange = exchange
        logger.info("✅ 交易所连接已建立")
        
        # 4. 初始化报警系统
        if CONFIG.discord_alert_webhook:
            alert_system = AlertSystem(
                webhook_url=CONFIG.discord_alert_webhook,
                cooldown_period=CONFIG.alert_cooldown_period
            )
            await alert_system.start()
            app.state.alert_system = alert_system
            logger.info("✅ 报警系统已启动")
        else:
            logger.warning("⚠️ 未配置Discord webhook，报警系统将不会启动")
            app.state.alert_system = None
        
        # 5. 初始化 AI 分析器并恢复状态
        macro_analyzer = MacroAnalyzer(api_key=CONFIG.deepseek_api_key)
        last_season = await get_setting('market_season')
        if last_season:
            macro_analyzer.last_known_season = last_season
            logger.info(f"✅ 成功从数据库恢复宏观状态: {last_season}")
        app.state.macro_analyzer = macro_analyzer
        logger.info("✅ 宏观分析器已初始化")
        
        # 6. 初始化交易引擎并恢复状态
        if CONFIG.trading_engine:
            trading_engine = TradingEngine(
                exchange=app.state.exchange,
                alert_system=app.state.alert_system
            )
            await trading_engine.initialize() # 调用 initialize 来恢复共振池
            app.state.trading_engine = trading_engine
            logger.info("✅ 交易引擎已启动")
        
        # 7. 启动黑天鹅雷达
        background_tasks['radar'] = await safe_start_task(
            start_black_swan_radar,
            "黑天鹅雷达"
        )
        
        # 8. 启动 Discord Bot
        if CONFIG.discord_token:
            start_func = lambda: run_discord_bot(app)
            background_tasks['discord_bot'] = await safe_start_task(
                start_func,
                "Discord Bot"
            )
        else:
            logger.warning("⚠️ 未配置Discord token，Discord Bot将不会启动")

        # 9. 设置系统状态
        await SystemState.set_state("ACTIVE")
        logger.info("🚀 系统启动完成")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ 系统启动失败: {e}", exc_info=True)
        await SystemState.set_state("ERROR")
        raise
    finally:
        logger.info("🛑 系统关闭中...")
        await SystemState.set_state("SHUTDOWN")
        
        for name, task in background_tasks.items():
            try:
                if task and not task.done():
                    task.cancel()
                    await task
            except asyncio.CancelledError:
                logger.info(f"✅ {name} 任务已取消")
            except Exception as e:
                logger.error(f"❌ 关闭 {name} 任务时出错: {e}", exc_info=True)

        try:
            if 'discord_bot' in background_tasks:
                await stop_bot_services()
        except Exception as e:
            logger.error(f"❌ 关闭 Discord Bot 服务时出错: {e}", exc_info=True)

        try:
            if hasattr(app.state, 'alert_system') and app.state.alert_system:
                await app.state.alert_system.stop()
        except Exception as e:
            logger.error(f"❌ 关闭报警系统时出错: {e}", exc_info=True)
        
        try:
            if hasattr(app.state, 'exchange'):
                await app.state.exchange.close()
        except Exception as e:
            logger.error(f"❌ 关闭交易所连接时出错: {e}", exc_info=True)
        
        logger.info("✅ 所有服务已关闭")

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
async def health_check(request: Request) -> Dict[str, Any]:
    """健康检查端点"""
    app_state = request.app.state
    checks = {
        "database": False,
        "exchange": False,
        "alert_system": False,
        "trading_engine": False
    }
    
    try:
        from src.database import check_database_health
        checks["database"] = await check_database_health()
    except Exception:
        checks["database"] = False
    
    if hasattr(app_state, 'exchange'):
        try:
            await app_state.exchange.fetch_time()
            checks["exchange"] = True
        except Exception:
            checks["exchange"] = False
            
    if hasattr(app_state, 'alert_system') and app_state.alert_system:
        checks["alert_system"] = app_state.alert_system.is_running
    
    if hasattr(app_state, 'trading_engine') and app_state.trading_engine:
        checks["trading_engine"] = checks["exchange"]

    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "timestamp": time.time(),
        "components": checks
    }

@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    """TradingView Webhook接收端点"""
    try:
        data = await request.json()
        if 'secret' not in data or data['secret'] != CONFIG.tv_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        symbol = data.get('symbol', '').lower()
        action = data.get('action', '').lower()
        
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
