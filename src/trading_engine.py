import logging
import asyncio
import time
from typing import Optional, Dict, Any, List
from ccxt.async_support import binance
from sqlalchemy import select, insert, update, delete
from src.config import CONFIG
from src.alert_system import AlertSystem
from src.database import db_pool, ResonanceSignal
# --- 【新增】导入我们新的核心决策模块 ---
from src.ai.macro_analyzer import MacroAnalyzer
from src.core_logic import ( # 假设您的core_logic.py现在包含了这些
    calculate_target_position_value, 
    get_allocation_percent,
    get_dynamic_risk_coefficient
)


logger = logging.getLogger(__name__)

class TradingEngine:
    """交易引擎核心类"""
    
    ORDER_CHECK_INTERVAL = 1
    
    def __init__(self, exchange: binance, alert_system: AlertSystem):
        self.exchange = exchange
        self.alert_system = alert_system
        self.active_orders: Dict[str, Dict] = {}
        self.order_timeout = CONFIG.alert_order_timeout
        self.slippage_threshold = CONFIG.alert_slippage_threshold
        self.min_partial_fill = CONFIG.alert_min_partial_fill
        self.max_daily_loss = CONFIG.alert_max_daily_loss
        self.api_retry_count = CONFIG.alert_api_retry_count
        
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_time = time.time()
        
        self.resonance_pool: Dict[str, Dict] = {}
        self.signal_timeout = CONFIG.macro_cache_timeout
        
        # --- 【核心修改】实例化新的宏观分析器 ---
        # 假设因子文件路径在配置中
        factor_file_path = getattr(CONFIG, 'factor_history_file', 'factor_history_full.csv')
        self.macro_analyzer = MacroAnalyzer(CONFIG.deepseek_api_key, factor_file_path)

    async def initialize(self) -> None:
        """
        异步初始化交易引擎。
        """
        logger.info("正在初始化交易引擎...")
        await self._load_resonance_pool_from_db()
        logger.info("✅ 交易引擎初始化完成")

    async def _check_balance(self, symbol: str, amount: float, price: Optional[float] = None):
        """检查账户余额"""
        try:
            balance = await self.exchange.fetch_balance()
            if price:
                required = amount * price
            else:
                ticker = await self.exchange.fetch_ticker(symbol)
                required = amount * ticker['last']
            
            if symbol in balance['total']:
                available = balance['total'][symbol]
                if available >= required:
                    return True
            return False
        except Exception as e:
            logger.error(f"检查余额失败: {str(e)}")
            return False

    async def _execute_with_retry(self, func, max_retries: int = 3) -> Any:
        """带重试的执行函数"""
        for i in range(max_retries):
            try:
                return await func()
            except Exception as e:
                if i == max_retries - 1:
                    raise
                logger.warning(f"执行失败，准备重试 ({i + 1}/{max_retries}): {str(e)}")
                await asyncio.sleep(2 ** i)

    async def _monitor_order(self, order_id: str):
        """监控订单状态"""
        while True:
            try:
                order = await self.exchange.fetch_order(order_id)
                if order['status'] == 'closed':
                    return order
                elif order['status'] == 'canceled':
                    return None
                await asyncio.sleep(self.ORDER_CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"监控订单失败: {str(e)}")
                await asyncio.sleep(self.ORDER_CHECK_INTERVAL)

    async def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        try:
            await self.exchange.cancel_order(order_id)
            return True
        except Exception as e:
            logger.error(f"取消订单失败: {str(e)}")
            return False

    async def get_position(self, symbol: str) -> Dict[str, Any]:
        """获取持仓信息"""
        try:
            return await self.exchange.fetch_position(symbol)
        except Exception as e:
            logger.error(f"获取持仓信息失败: {str(e)}")
            return {}

    def update_daily_pnl(self, pnl: float):
        """更新每日盈亏"""
        self.daily_pnl += pnl
        self.daily_trades += 1

    def reset_daily_stats(self):
        """重置每日统计"""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_time = time.time()

    async def check_exchange_health(self) -> bool:
        """检查交易所连接状态"""
        try:
            await self.exchange.fetch_status()
            return True
        except Exception as e:
            logger.error(f"交易所连接检查失败: {str(e)}")
            return False

    def get_active_orders(self) -> Dict[str, Dict]:
        """获取活跃订单"""
        return self.active_orders

    def get_daily_stats(self) -> Dict[str, Any]:
        """获取每日统计"""
        return {
            'daily_pnl': self.daily_pnl,
            'daily_trades': self.daily_trades,
            'last_reset_time': self.last_reset_time
        }

    async def add_signal(self, signal_id: str, signal_data: Dict[str, Any]) -> None:
        """添加信号到共振池"""
        self.resonance_pool[signal_id] = signal_data
        async with db_pool.acquire() as conn:
            await conn.execute(
                insert(ResonanceSignal).values(
                    signal_id=signal_id,
                    signal_data=signal_data
                )
            )

    async def remove_signal(self, signal_id: str) -> None:
        """从共振池移除信号"""
        if signal_id in self.resonance_pool:
            del self.resonance_pool[signal_id]
            async with db_pool.acquire() as conn:
                await conn.execute(
                    delete(ResonanceSignal).where(
                        ResonanceSignal.signal_id == signal_id
                    )
                )

    def get_resonance_pool(self) -> Dict[str, Any]:
        """获取共振池状态"""
        return self.resonance_pool

    async def update_signal_status(self, signal_id: str, status: str) -> None:
        """更新信号状态"""
        if signal_id in self.resonance_pool:
            self.resonance_pool[signal_id]['status'] = status
            async with db_pool.acquire() as conn:
                await conn.execute(
                    update(ResonanceSignal).where(
                        ResonanceSignal.signal_id == signal_id
                    ).values(
                        status=status
                    )
                )

    async def _load_resonance_pool_from_db(self):
        """从数据库加载共振池"""
        try:
            async with db_pool.acquire() as conn:
                result = await conn.execute(select(ResonanceSignal))
                for row in result:
                    self.resonance_pool[row.signal_id] = row.signal_data
        except Exception as e:
            logger.error(f"从数据库加载共振池失败: {str(e)}")

    # --- 【核心修改】execute_order 被彻底重构，以整合新的决策逻辑 ---
    async def execute_order(self, symbol: str, side: str, 
                          signal_data: Dict[str, Any] 
                         ) -> Optional[Dict[str, Any]]:
        """
        执行交易决策的统一入口。
        """
        try:
            # 1. 获取最终的宏观决策
            macro_decision = await self.macro_analyzer.get_macro_decision()
            macro_status = macro_decision.get("market_season", "OSC")
            
            # 2. 方向性过滤
            market_dir = 1 if macro_status == "BULL" else -1 if macro_status == "BEAR" else 0
            signal_dir = 1 if side.lower() == 'long' else -1 if side.lower() == 'short' else 0
            
            if market_dir != signal_dir:
                logger.info(f"信号被过滤: 信号方向({side})与宏观主方向({macro_status})不符。")
                return None

            # 3. 获取所有需要的系数来计算仓位
            account_balance = await self.exchange.fetch_balance()
            account_equity = account_balance['total']['USDT']
            
            # 获取当前回撤（简化处理，实际应该从数据库获取）
            current_drawdown = 0.0

            allocation_percent = get_allocation_percent(macro_status, symbol)
            dynamic_risk_coeff = get_dynamic_risk_coefficient(current_drawdown)
            
            # 4. 计算最终仓位价值
            position_details = calculate_target_position_value(
                account_equity=account_equity,
                symbol=symbol,
                macro_decision=macro_decision,
                dynamic_risk_coeff=dynamic_risk_coeff
            )
            
            target_value = position_details["target_position_value"]
            if target_value <= 0:
                logger.info("计算出的目标仓位为0，不执行交易。")
                return None

            # 5. 执行下单
            current_price = await self.exchange.fetch_ticker(symbol)['last']
            amount = target_value / current_price
            
            # 检查余额
            if not await self._check_balance(symbol, amount, current_price):
                logger.warning(f"余额不足，无法执行订单: {symbol} {amount}")
                return None
            
            order_params = {'symbol': symbol, 'type': 'market', 'side': side, 'amount': amount}
            order_result = await self._execute_with_retry(
                lambda: self.exchange.create_order(**order_params)
            )
            
            if order_result:
                self.active_orders[order_result['id']] = order_result
                # 更新每日统计
                self.update_daily_pnl(0)  # 实际应该计算实际盈亏
                # 启动订单监控
                asyncio.create_task(self._monitor_order(order_result['id']))
            
            return order_result

        except Exception as e:
            await self.alert_system.trigger_alert(
                alert_type="ORDER_FAILED", message=f"交易执行失败: {str(e)}", level="emergency"
            )
            return None
