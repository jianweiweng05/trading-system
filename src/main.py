import logging
import time
from typing import Dict, Optional  # 【修改】添加 Optional
from sqlalchemy import text
from contextlib import asynccontextmanager  # 【修改】添加缺失的导入
from src.config import CONFIG  # 【修改】添加缺失的导入

logger = logging.getLogger(__name__)

async def init_tv_status_table():
    """初始化TV状态表"""
    try:
        from src.database import db_pool
        async with db_pool.get_simple_session() as conn:
            await conn.execute(text('''
                CREATE TABLE IF NOT EXISTS tv_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol VARCHAR(10) NOT NULL UNIQUE,
                    status VARCHAR(20) NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            await conn.commit()
    except Exception as e:
        logger.error(f"初始化TV状态表失败: {e}")
        raise  # 【修改】修复缩进

async def load_tv_status() -> Dict[str, str]:
    """从数据库加载TV状态"""
    status = {'btc': CONFIG.default_btc_status, 'eth': CONFIG.default_eth_status}
    try:
        from src.database import db_pool
        async with db_pool.get_simple_session() as conn:  # 【修改】统一使用 async with
            result = await conn.execute(text('SELECT symbol, status FROM tv_status'))
            rows = await result.fetchall()
            for row in rows:
                status[row['symbol']] = row['status']
    except Exception as e:
        logger.error(f"加载TV状态失败: {e}")
    return status

async def save_tv_status(symbol: str, status: str):
    """保存TV状态到数据库"""
    try:
        from src.database import db_pool
        async with db_pool.get_simple_session() as conn:  # 【修改】统一使用 async with
            await conn.execute(text('''
                INSERT OR REPLACE INTO tv_status (symbol, status, timestamp)
                VALUES (?, ?, ?)
            '''), (symbol, status, time.time()))
            await conn.commit()
    except Exception as e:
        logger.error(f"保存TV状态失败: {e}")
        raise RuntimeError("保存TV状态失败") from e  # 【修改】保持异常链

# --- 【修改】安全启动任务包装函数，扩大异常捕获范围 ---
async def safe_start_task(task_func, name: str) -> Optional[asyncio.Task]:
    """安全启动任务的包装函数"""
    try:
        task = asyncio.create_task(task_func())
        logger.info(f"✅ {name} 启动任务已创建")
        return task
    except Exception as e: # 捕获所有可能的异常
        logger.error(f"❌ {name} 启动任务失败: {e}", exc_info=True)
        return None

# --- 【修改】生命周期管理，增强资源清理的健壮性 ---
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
        
        # 5. 初始化 AI 分析器
        app.state.macro_analyzer = MacroAnalyzer(api_key=CONFIG.deepseek_api_key)
        logger.info("✅ 宏观分析器已初始化")
        
        # 6. 初始化交易引擎
        if CONFIG.trading_engine:
            trading_engine = TradingEngine(
                exchange=app.state.exchange,
                alert_system=app.state.alert_system
            )
            app.state.trading_engine = trading_engine
            logger.info("✅ 交易引擎已启动")
        
        # 7. 启动黑天鹅雷达
        background_tasks['radar'] = await safe_start_task(
            start_black_swan_radar,
            "黑天鹅雷达"
        )
      
        # 8. 启动 Discord Bot (作为后台任务)
        if CONFIG.discord_token:
            # 【修改】使用 lambda 将 app 对象传递给 run_discord_bot
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
        
        # 为每个关闭操作添加独立的 try-except 块
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

# --- 路由定义 (保持不变) ---
@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "status": "running",
        "version": app.version,
        "mode": CONFIG.run_mode
    }

# --- 【修改】健康检查端点，改进健康检查逻辑 ---
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
            # 实际的健康检查：尝试获取服务器时间
            await app_state.exchange.fetch_time()
            checks["exchange"] = True
        except Exception:
            checks["exchange"] = False
            
    if hasattr(app_state, 'alert_system') and app_state.alert_system:
        # 实际的健康检查：检查其内部状态
        checks["alert_system"] = app_state.alert_system.is_running
    
    if hasattr(app_state, 'trading_engine') and app_state.trading_engine:
        # 改进的健康检查：假设如果交易所健康，交易引擎也大概率是健康的
        # 未来可以为 TradingEngine 添加自己的 is_healthy() 方法
        checks["trading_engine"] = checks["exchange"]

    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "timestamp": time.time(),
        "components": checks
    }

# --- Webhook 和 TV 状态路由 (保持不变) ---
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

# --- 主函数 (保持不变) ---
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
