import time
import logging
from tenacity import retry, stop_after_attempt, wait_fixed

# 导入共享的组件
from database import db_query, get_sim_balance, get_sim_position, log_trade, get_config

logger = logging.getLogger(__name__)

# --- 1. 模拟盘引擎 (Simulated Broker) ---
async def execute_sim_trade(exchange, symbol: str, target_amount: float):
    """
    在数据库中执行模拟交易，更新模拟持仓和余额 (已修复反向开仓逻辑)
    """
    current_pos = await get_sim_position(symbol)
    current_amount = current_pos['amount']
    diff = target_amount - current_amount

    if abs(diff) < 0.00001:
        return

    side = 'buy' if diff > 0 else 'sell'
    try:
        ticker = await exchange.fetch_ticker(symbol)
        price = ticker['last']
        
        # 减仓或平仓部分逻辑
        if current_amount * diff < 0:
            balance = await get_sim_balance()
            pnl = (price - current_pos['entry_price']) * current_amount if current_amount > 0 else (current_pos['entry_price'] - price) * abs(current_amount)
            new_balance = balance + pnl
            await db_query("UPDATE sim_account SET value = ? WHERE key = 'balance'", (new_balance,))
            await db_query("DELETE FROM sim_positions WHERE symbol = ?", (symbol,))
            logger.info(f"[SIM] 模拟平仓: {current_amount:.4f} {symbol} @ ${price}, PNL: ${pnl:.2f}")
            await log_trade("SIM_TRADE", symbol, "CLOSE", "SUCCESS", f"Close at: {price}", "sim")
            current_amount = 0 # 平仓后当前仓位为0

        # 开仓或加仓部分逻辑
        if abs(target_amount) > 0.00001 and diff != 0:
             # 如果是从0开新仓
            if abs(current_amount) < 0.00001:
                await db_query("INSERT INTO sim_positions (symbol, amount, entry_price) VALUES (?, ?, ?)", 
                               (symbol, target_amount, price))
            else: # 如果是加仓
                new_entry_price = (current_pos['entry_price'] * current_amount + price * (target_amount - current_amount)) / target_amount
                await db_query("UPDATE sim_positions SET amount = ?, entry_price = ? WHERE symbol = ?",
                               (target_amount, new_entry_price, symbol))
            
            logger.info(f"[SIM] 模拟开/加仓成功: {side} {abs(diff):.4f} {symbol} @ ${price}")
            await log_trade("SIM_TRADE", symbol, side.upper(), "SUCCESS", f"Target: {target_amount}", "sim")

    except Exception as e:
        logger.error(f"[SIM] 模拟执行失败 for {symbol}: {e}", exc_info=True)
        await log_trade("SIM_TRADE", symbol, side.upper(), "FAILED", str(e), "sim")
        
# --- 2. 实盘交易执行器 (Live Broker) ---
@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def get_live_position(exchange, symbol: str, all_positions=None):
    # 此处省略...
    pass

async def execute_live_trade(exchange, symbol: str, target_amount: float, all_positions=None):
    # 此处省略...
    pass

# --- 3. 仓位总管 (Position Manager) ---
async def position_manager(exchange, symbol: str, target_amount: float, all_positions=None):
    """
    根据系统运行模式，决定调用模拟交易员还是实盘交易员。
    """
    run_mode = await get_config('run_mode', 'live')
    logger.info(f"仓位管理器启动: 模式={run_mode.upper()}, 目标={target_amount:.4f} {symbol}")

    try:
        if run_mode == 'sim':
            await execute_sim_trade(exchange, symbol, target_amount)
        elif run_mode == 'live':
            await execute_live_trade(exchange, symbol, target_amount, all_positions)
        else:
            logger.error(f"未知的运行模式: {run_mode}")
    except Exception as e:
        logger.error(f"仓位管理器执行失败: {e}")