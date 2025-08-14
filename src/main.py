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
from src.database import get_setting, db_pool, update_tv_status

# --- 日志配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 安全启动任务包装函数 (无变动) ---
async def safe_start_task(task_func, name: str) -> Optional[asyncio.Task]:
    """安全启动任务的包装函数"""
    try:
        task = asyncio.create_task(task_func())
        logger.info(f"✅ {name} 启动任务已创建")
        return task
    except Exception as e:
        logger.error(f"❌ {name} 启动任务失败: {e}", exc_info=True)
        return None

# --- 生命周期管理 (有修改) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🔄 系统启动中...")
    
    background_tasks = {}
    
    try:
        # 1. 初始化数据库 (无变动)
        from src.database import init_db
        await init_db()
        logger.info("✅ 数据库连接已建立")
        
        # 2. 初始化交易所连接 (无变动)
        exchange = binance({
            'apiKey': CONFIG.binance_api_key,
            'secret': CONFIG.binance_api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
        })
        await exchange.load_markets()
        app.state.exchange = exchange
        logger.info("✅ 交易所连接已建立")
        
        # 3. 初始化核心服务
        if CONFIG.discord_alert_webhook:
            alert_system = AlertSystem(webhook_url=CONFIG.discord_alert_webhook, cooldown_period=CONFIG.alert_cooldown_period)
            await alert_system.start()
            app.state.alert_system = alert_system
            logger.info("✅ 报警系统已启动")
        else:
            logger.warning("⚠️ 未配置Discord webhook，报警系统将不会启动")
            app.state.alert_system = None
        
        # --- 【核心修改】确保 MacroAnalyzer 初始化时加载因子文件 ---
        factor_file_path = getattr(CONFIG, 'factor_history_file', 'factor_history_full.csv')
        macro_analyzer = MacroAnalyzer(api_key=CONFIG.deepseek_api_key, factor_history_path=factor_file_path)
        last_season = await get_setting('market_season')
        if last_season:
            macro_analyzer.last_known_season = last_season
            logger.info(f"✅ 成功从数据库恢复宏观状态: {last_season}")
        app.state.macro_analyzer = macro_analyzer
        logger.info("✅ 宏观分析器已初始化")
        
        if CONFIG.trading_engine:
            # 【核心修改】将已初始化的 macro_analyzer 传递给 TradingEngine
            trading_engine = TradingEngine(
                exchange=app.state.exchange, 
                alert_system=app.state.alert_system,
                macro_analyzer=app.state.macro_analyzer # 注入依赖
            )
            await trading_engine.initialize()
            app.state.trading_engine = trading_engine
            logger.info("✅ 交易引擎已启动")
        
        # 4. 启动后台任务 (无变动)
        background_tasks['radar'] = await safe_start_task(start_black_swan_radar, "黑天鹅雷达")
        if CONFIG.discord_token:
            start_func = lambda: run_discord_bot(app)
            background_tasks['discord_bot'] = await safe_start_task(start_func, "Discord Bot")
        else:
            logger.warning("⚠️ 未配置Discord token，Discord Bot将不会启动")

        # 5. 启动时不再需要单独执行宏观分析，因为它会在第一次交易时被调用
        
        # 6. 设置系统状态 (无变动)
        await SystemState.set_state("ACTIVE")
        logger.info("🚀 系统启动完成")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ 系统启动失败: {e}", exc_info=True)
        await SystemState.set_state("ERROR")
        raise
    finally:
        # ... (finally 块保持不变) ...
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

# --- 路由定义 (有修改) ---
@app.get("/")
async def root() -> Dict[str, Any]:
    return {"status": "running", "version": app.version, "mode": CONFIG.run_mode}

@app.get("/health")
async def health_check(request: Request) -> Dict[str, Any]:
    """(此函数保持不变)"""
    # ...
    pass

# --- 【核心修改】彻底重构 Webhook 逻辑 ---
@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    """
    TradingView Webhook接收端点 (已升级为交易触发器)
    """
    # 1. 基础验证 (与原始代码类似)
    try:
        data = await request.json()
        # 假设您的TV信号现在包含一个简单的密码或密钥
        if 'secret' not in data or data['secret'] != CONFIG.tv_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        # 检查系统状态
        current_state = await SystemState.get_state()
        if current_state != "ACTIVE":
            logger.warning(f"系统未激活，拒绝处理信号 - 当前状态: {current_state}")
            raise HTTPException(503, detail=f"系统未激活 ({current_state})")

        # 2. 检查交易引擎是否存在
        if not hasattr(request.app.state, 'trading_engine') or not request.app.state.trading_engine:
            logger.error("交易引擎未初始化，无法处理信号。")
            raise HTTPException(status_code=503, detail="Trading engine not available")

        # 3. 调用交易引擎执行交易
        logger.info(f"收到有效交易信号，正在转发至交易引擎: {data}")
        
        # 我们假设TV信号的格式为 {'symbol': 'BTCUSDT', 'side': 'long', 'secret': '...'}
        # TradingEngine的execute_order现在需要接收这个信号字典
        order_result = await request.app.state.trading_engine.execute_order(
            symbol=data.get('symbol'),
            side=data.get('side'),
            signal_data=data 
        )
        
        if order_result:
            return {"status": "success", "message": "Order execution process started.", "order": order_result}
        else:
            return {"status": "filtered", "message": "Signal received but filtered by system logic."}

    except Exception as e:
        logger.error(f"TradingView webhook处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

# --- 旧的TV状态路由可以保留或删除，它们不再是核心交易逻辑的一部分 ---
@app.get("/tv-status")
async def get_tv_status():
    """(此函数现在只用于监控，不再影响交易)"""
    # ... (与原始代码相同) ...
    pass

# --- 主函数 (无变 động) ---
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
