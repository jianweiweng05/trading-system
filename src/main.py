import os
import sys
import logging
import asyncio
import traceback
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import ccxt.async_support as ccxt
from datetime import datetime
from typing import Dict, Any, Optional

# 添加当前目录到 Python 路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入自定义模块
from config import (
    TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID, TV_WEBHOOK_SECRET,
    BINANCE_API_KEY, BINANCE_API_SECRET, BASE_LEVERAGE,
    INITIAL_SIM_BALANCE, DATABASE_URL, RUN_MODE, DEBUG_MODE, LOG_LEVEL
)
from core_logic import process_trading_signal
from database import DatabaseManager, Position, Trade, init_db
from broker import position_manager, initialize_broker, get_positions, get_balance
from telegram_bot import start_telegram_bot

# 配置日志
logging.basicConfig(
    level=LOG_LEVEL if LOG_LEVEL else logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(title="Quant Trading System", version="v6.2")

# 定义数据模型
class SignalSchema(BaseModel):
    symbol: str
    direction: str  # 'buy' or 'sell'
    base_amount: float
    strategy_name: str
    btc_trend: Optional[str] = None  # 'up' or 'down'
    eth_trend: Optional[str] = None  # 'up' or 'down'

# 系统状态变量
SYSTEM_HALTED = False

# ================= 系统启动事件 =================
@app.on_event("startup")
async def startup_event():
    """应用启动初始化"""
    print(">>> [Startup] STARTING application initialization...")
    try:
        # 打印系统配置
        print("=" * 40)
        print(">>> [Startup] System Configuration:")
        print(f"Telegram Token: {TELEGRAM_BOT_TOKEN[:6]}...{TELEGRAM_BOT_TOKEN[-5:]}")
        print(f"Admin Chat ID: {ADMIN_CHAT_ID}")
        print(f"TV Webhook Secret: {TV_WEBHOOK_SECRET[:6]}...{TV_WEBHOOK_SECRET[-5:]}")
        print(f"Binance API Key: {BINANCE_API_KEY[:6]}...{BINANCE_API_KEY[-5:]}")
        print(f"Base Leverage: {BASE_LEVERAGE}")
        print(f"Initial Sim Balance: {INITIAL_SIM_BALANCE}")
        print(f"Database URL: {DATABASE_URL[:20]}...")  # 只显示部分数据库URL
        print(f"Run Mode: {RUN_MODE}")
        print(f"Debug Mode: {DEBUG_MODE}")
        print("=" * 40)
        
        # 初始化数据库
        print(">>> [Startup Step 1/5] PREPARING to initialize database...")
        await init_db()
        print(">>> [Startup Step 2/5] SUCCESS: Database initialized.")
        logger.info("数据库初始化完成")
        
        # 初始化交易所
        print(">>> [Startup Step 3/5] PREPARING to create exchange instance...")
        app.state.exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        print(">>> [Startup Step 4/5] SUCCESS: Exchange instance created.")
        logger.info("交易所实例创建完成")
        
        # 初始化交易模块
        print(">>> [Startup Step 5/5] PREPARING to initialize broker...")
        await initialize_broker(app.state.exchange, RUN_MODE)
        print(">>> [Startup] SUCCESS: Broker initialized.")
        logger.info("交易模块初始化完成")
        
        # 启动Telegram机器人
        print(">>> [Startup] PREPARING to start Telegram bot...")
        asyncio.create_task(start_telegram_bot())
        print(">>> [Startup] SUCCESS: Telegram bot task created.")
        logger.info("Telegram机器人已启动")
        
        # 设置运行模式
        app.state.run_mode = RUN_MODE
        
        # 系统启动完成
        print(">>> [Startup] ALL INITIALIZATION COMPLETE! Application should be live.")
        logger.info("系统启动完成")
        
    except Exception as e:
        print(f">>> [Startup FATAL ERROR] An exception occurred during startup: {e}")
        print(">>> [Startup FATAL ERROR] Full traceback:")
        traceback.print_exc()
        logger.error(f"启动失败: {e}", exc_info=True)
        raise

# ================= 健康检查端点 =================
@app.get("/health")
async def health_check():
    """系统健康检查"""
    try:
        # 检查数据库连接
        await DatabaseManager.check_connection()
        
        # 检查交易所连接
        ticker = await app.state.exchange.fetch_ticker("BTC/USDT")
        
        return {
            "status": "ok",
            "version": "v6.2",
            "mode": app.state.run_mode,
            "timestamp": datetime.now().isoformat(),
            "exchange_status": "connected" if ticker else "disconnected",
            "halted": SYSTEM_HALTED
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

# ================= Webhook 信号端点 =================
@app.post("/webhook")
async def webhook_endpoint(request: Request, signal: SignalSchema):
    """接收交易信号"""
    try:
        # 检查系统是否暂停
        if SYSTEM_HALTED:
            logger.warning("系统暂停中，忽略信号")
            return {"status": "error", "message": "System is halted"}
        
        # 验证签名
        signature = request.headers.get("TV-Signature", "")
        if signature != TV_WEBHOOK_SECRET:
            logger.warning("无效签名")
            raise HTTPException(status_code=403, detail="Invalid signature")
        
        # 处理信号
        logger.info(f"接收到交易信号: {signal.symbol} {signal.direction}")
        
        # 调用核心逻辑处理信号
        signal_dict = signal.dict()
        result = await process_trading_signal(
            app.state.exchange, 
            signal_dict, 
            app.state.run_mode
        )
        
        if result['status'] == 'success':
            # 调用仓位管理
            await position_manager(
                app.state.exchange,
                result['symbol'],
                result['target_amount'],
                app.state.run_mode
            )
            return {"status": "success", "target_amount": result['target_amount']}
        else:
            return {"status": "error", "message": result['message']}
            
    except Exception as e:
        logger.error(f"信号处理失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

# ================= 系统状态端点 =================
@app.get("/status")
async def system_status():
    """获取系统状态"""
    try:
        # 获取持仓信息
        positions = await get_positions(app.state.run_mode)
        
        # 获取余额
        balance = await get_balance(app.state.run_mode)
        
        return {
            "status": "running",
            "mode": app.state.run_mode,
            "balance": balance,
            "positions": positions,
            "halted": SYSTEM_HALTED,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        return {"status": "error", "message": str(e)}

# ================= 系统控制端点 =================
@app.post("/control")
async def system_control(action: str):
    """系统控制命令"""
    global SYSTEM_HALTED
    
    try:
        if action == "halt":
            SYSTEM_HALTED = True
            logger.warning("系统已暂停")
            return {"status": "success", "message": "System halted"}
        elif action == "resume":
            SYSTEM_HALTED = False
            logger.warning("系统已恢复")
            return {"status": "success", "message": "System resumed"}
        elif action == "reset_sim":
            await initialize_broker(app.state.exchange, "simulate", reset=True)
            logger.info("模拟账户已重置")
            return {"status": "success", "message": "Simulation reset"}
        else:
            return {"status": "error", "message": "Invalid action"}
    except Exception as e:
        logger.error(f"控制命令失败: {e}")
        return {"status": "error", "message": str(e)}

# ================= 交易历史端点 =================
@app.get("/trades")
async def get_trades(symbol: Optional[str] = None, limit: int = 100):
    """获取交易历史"""
    try:
        trades = await DatabaseManager.get_trades(symbol, limit)
        return {"status": "success", "trades": trades}
    except Exception as e:
        logger.error(f"获取交易历史失败: {e}")
        return {"status": "error", "message": str(e)}

# ================= 错误处理 =================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"全局异常: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"}
    )

# ================= 主程序入口 =================
if __name__ == "__main__":
    import uvicorn
    
    # 打印启动信息
    print("\n" + "=" * 50)
    print(f"Quant Trading System v6.2")
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Running in {'DEBUG' if DEBUG_MODE else 'PRODUCTION'} mode")
    print("=" * 50 + "\n")
    
    # 启动服务器
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        log_level="info" if DEBUG_MODE else "warning",
        reload=DEBUG_MODE
    )