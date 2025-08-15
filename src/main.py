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
# --- 数据库相关的导入 ---
from src.database import get_setting, db_pool, update_tv_status # 保持原有导入

# --- 日志配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 安全启动任务包装函数 (无变动) ---
async def safe_start_task(task_func, name: str) -> Optional[asyncio.Task]:
    """(此函数保持不变)"""
    try:
        task = asyncio.create_task(task_func())
        logger.info(f"✅ {name} 启动任务已创建")
        return task
    except Exception as e:
        logger.error(f"❌ {name} 启动任务失败: {e}", exc_info=True)
        return None

# --- 生命周期管理 (无变动) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """(此函数保持不变)"""
    logger.info("🔄 系统启动中...")
    background_tasks = {}
    try:
        from src.database import init_db
        await init_db()
        logger.info("✅ 数据库连接已建立")
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
        })
        await exchange.load_markets()
        app.state.exchange = exchange
        logger.info("✅ 交易所连接已建立")
        if CONFIG.discord_alert_webhook:
            alert_system = AlertSystem(webhook_url=CONFIG.discord_alert_webhook, cooldown_period=CONFIG.alert_cooldown_period)
            await alert_system.start()
            app.state.alert_system = alert_system
            logger.info("✅ 报警系统已启动")
        else:
            app.state.alert_system = None
        factor_file_path = getattr(CONFIG, 'factor_history_file', 'factor_history_full.csv')
        macro_analyzer = MacroAnalyzer(api_key=CONFIG.deepseek_api_key, factor_history_path=factor_file_path)
        last_season = await get_setting('market_season')
        if last_season:
            macro_analyzer.last_known_season = last_season
        app.state.macro_analyzer = macro_analyzer
        logger.info("✅ 宏观分析器已初始化")
        if CONFIG.trading_engine:
            trading_engine = TradingEngine(
                exchange=app.state.exchange, 
                alert_system=app.state.alert_system,
                macro_analyzer=app.state.macro_analyzer
            )
            await trading_engine.initialize()
            app.state.trading_engine = trading_engine
            logger.info("✅ 交易引擎已启动")
        background_tasks['radar'] = await safe_start_task(start_black_swan_radar, "黑天鹅雷达")
        if CONFIG.discord_token:
            start_func = lambda: run_discord_bot(app)
            background_tasks['discord_bot'] = await safe_start_task(start_func, "Discord Bot")
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
        # ... (关闭逻辑保持不变) ...

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
    """(此路由保持不变)"""
    return {"status": "running", "version": app.version, "mode": CONFIG.run_mode}

@app.get("/health")
async def health_check(request: Request) -> Dict[str, Any]:
    """(此路由保持不变)"""
    # ...
    pass

# --- 【核心新增】用于处理“状态信号”的辅助函数 ---
async def handle_factor_update(data: Dict[str, Any]):
    """处理因子更新信号的逻辑"""
    strategy_id = data.get("strategy_id")
    action = data.get("action", "flat")
    
    # 简单的逻辑映射
    # 在真实系统中，这里会更复杂，需要更新因子历史文件或数据库
    logger.info(f"接收到状态更新信号: {strategy_id} -> {action}")
    # 示例：可以调用一个数据库函数来更新状态
    # await update_factor_status_in_db(strategy_id, action)
    return {"status": "factor update received"}

# --- 【核心修改】彻底重构 Webhook 逻辑 ---
@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    """
    统一的TradingView Webhook接收端点 (已实现“智能接线员”)
    """
    # 1. 基础验证 (签名验证等)
    try:
        # (假设您有签名验证逻辑)
        # ...
        
        data = await request.json()
        strategy_id = data.get("strategy_id")
        
        if not strategy_id:
            raise HTTPException(status_code=400, detail="Missing 'strategy_id' in webhook data")

        # 2. 【核心】智能接线员的“通讯录”
        FACTOR_UPDATE_STRATEGIES = {
            "btc1d", 
            "eth1d多", 
            "eth1d空"
        }

        # 3. 【核心】智能判断和任务分发
        if strategy_id in FACTOR_UPDATE_STRATEGIES:
            # 如果是“状态信号”，转接给“后台数据部门”
            logger.info(f"识别到状态信号: {strategy_id}。")
            response = await handle_factor_update(data)
            return response
            
        else: # 默认所有其他ID都是“行动信号”
            # 就转接给“前线交易部门”
            logger.info(f"识别到行动信号: {strategy_id}。正在转发至交易引擎...")
            
            trading_engine = getattr(request.app.state, 'trading_engine', None)
            if not trading_engine:
                logger.error("交易引擎未初始化，无法处理行动信号。")
                raise HTTPException(status_code=503, detail="Trading engine not available")
            
            # 调用交易引擎
            order_result = await trading_engine.execute_order(data)
            
            if order_result:
                return {"status": "trade processed", "order": order_result}
            else:
                return {"status": "trade filtered"}

    except Exception as e:
        logger.error(f"TradingView webhook处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

# --- 旧的TV状态路由可以保留或删除 ---
@app.get("/tv-status")
async def get_tv_status():
    """(此函数现在只用于监控)"""
    # ... (与原始代码相同) ...
    pass

# --- 主函数 (无变动) ---
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
