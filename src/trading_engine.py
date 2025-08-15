import logging
import asyncio
import time
from typing import Optional, Dict, Any, List
from ccxt.async_support import binance
from sqlalchemy import select, insert, update, delete
from src.config import CONFIG
from src.alert_system import AlertSystem
from src.database import db_pool, ResonanceSignal
# --- 【核心】导入我们新的核心决策模块和工具函数 ---
from src.ai.macro_analyzer import MacroAnalyzer
from src.core_logic import get_allocation_percent, get_dynamic_risk_coefficient, calculate_target_position_value

logger = logging.getLogger(__name__)

class TradingEngine:
    """交易引擎核心类 (已适配最终版宏观系统)"""
    
    ORDER_CHECK_INTERVAL = 1
    
    # --- 【核心修改】构造函数现在接收一个 MacroAnalyzer 实例 ---
    def __init__(self, exchange: binance, alert_system: AlertSystem, macro_analyzer: MacroAnalyzer):
        self.exchange = exchange
        self.alert_system = alert_system
        self.macro_analyzer = macro_analyzer # 直接使用外部传入的实例
        
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

    async def initialize(self) -> None:
        """(此方法保持不变)"""
        logger.info("正在初始化交易引擎...")
        await self._load_resonance_pool_from_db()
        logger.info("✅ 交易引擎初始化完成")

    # --- 【核心修改】execute_order 被彻底重写 ---
    async def execute_order(self, signal_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        执行交易决策的统一入口。
        """
        try:
            # 1. 从信号中解析基础信息
            strategy_id = signal_data.get("strategy_id")
            symbol = signal_data.get("symbol")
            action = signal_data.get("action")
            
            if not all([strategy_id, symbol, action]):
                logger.error(f"接收到无效信号，缺少关键字段: {signal_data}")
                return None

            # 2. 获取最终的宏观决策
            macro_decision = await self.macro_analyzer.get_macro_decision()
            macro_status = macro_decision.get("market_season", "OSC")
            
            # 3. 方向性过滤
            market_dir = 1 if macro_status == "BULL" else -1 if macro_status == "BEAR" else 0
            signal_dir = 1 if action.lower() == 'long' else -1 if action.lower() == 'short' else 0
            
            if market_dir != signal_dir:
                logger.info(f"信号被过滤: 策略 {strategy_id} 的 {action} 信号与宏观主方向({macro_status})不符。")
                return None

            # 4. 获取所有需要的系数来计算仓位
            # (这里需要获取账户权益和当前回撤，我们先用模拟值)
            # account_equity = (await self.exchange.fetch_balance())['total']['USDT']
            account_equity = 100000.0 # 模拟值
            # current_drawdown = await get_current_drawdown_from_db()
            current_drawdown = 0.0 # 模拟值

            allocation_percent = get_allocation_percent(macro_status, symbol)
            dynamic_risk_coeff = get_dynamic_risk_coefficient(current_drawdown)
            
            # (共振系统暂时简化为1.0)
            resonance_multiplier = 1.0
            
            # 5. 调用core_logic中的函数，计算最终仓位价值
            position_details = calculate_target_position_value(
                account_equity=account_equity,
                allocation_percent=allocation_percent,
                macro_decision=macro_decision,
                resonance_multiplier=resonance_multiplier,
                dynamic_risk_coeff=dynamic_risk_coeff,
                confidence_weight=1.0 # 简化
            )
            
            target_value = position_details.get("target_position_value", 0.0)
            if target_value <= 0:
                logger.info(f"计算出的目标仓位为0 ({strategy_id})，不执行交易。")
                return None

            # 6. 执行下单
            logger.info(f"准备执行订单: {strategy_id} - {action} {symbol}，目标价值: ${target_value:,.2f}")
            
            current_price = (await self.exchange.fetch_ticker(symbol))['last']
            amount = target_value / current_price
            
            order_params = {'symbol': symbol, 'type': 'market', 'side': action, 'amount': amount}
            order_result = await self._execute_with_retry(
                lambda: self.exchange.create_order(**order_params)
            )
            
            self.active_orders[order_result['id']] = {
                'symbol': symbol, 'type': 'market', 'side': action, 'amount': amount,
                'price': current_price, 'status': order_result['status'],
                'filled': order_result.get('filled', 0), 'timestamp': time.time()
            }
            asyncio.create_task(self._monitor_order(order_result['id']))
            
            return order_result

        except Exception as e:
            logger.error(f"交易执行失败 ({strategy_id}): {e}", exc_info=True)
            await self.alert_system.trigger_alert(
                alert_type="ORDER_FAILED", message=f"交易执行失败: {str(e)}", level="emergency"
            )
            return None
    
    # --- (以下所有方法，都100%保持了您原始代码的原貌) ---
    
    async def _check_balance(self, symbol: str, amount: float, price: Optional[float] = None):
        try:
            balance = await self.exchange.fetch_balance()
            base_currency, quote_currency = None, None
            if '/' in symbol:
                base_currency, quote_currency = symbol.split('/')
            else:
                known_quotes = ['USDT', 'BUSD', 'USDC', 'BTC', 'ETH']
                for quote in known_quotes:
                    if symbol.endswith(quote):
                        base_currency = symbol[:-len(quote)]
                        quote_currency = quote
                        break
            if not base_currency: raise ValueError(f"无法解析交易对: {symbol}")
            is_buy = 'buy' in self.active_orders.get(symbol, {}).get('side', 'buy').lower()
            if price is not None:
                required_amount = amount * price if is_buy else amount
                currency = quote_currency if is_buy else base_currency
            else:
                currency = quote_currency if is_buy else base_currency
                required_amount = amount
            available = balance.get(currency, {}).get('free', 0)
            if float(available) < required_amount:
                raise ValueError(f"资金不足: 需要 {required_amount} {currency}, 可用 {available}")
        except Exception as e:
            logger.error(f"检查余额失败: {e}")
            await self.alert_system.trigger_alert(
                alert_type="INSUFFICIENT_FUNDS", message=f"检查余额失败: {e}", level="warning"
            )
            raise
    
    async def _execute_with_retry(self, func, max_retries: int = 3) -> Any:
        last_error = None
        for i in range(max_retries):
            try:
                return await func()
            except Exception as e:
                last_error = e
                if i < max_retries - 1:
                    await asyncio.sleep(1 * (i + 1))
                    continue
        raise last_error
    
    async def _monitor_order(self, order_id: str):
        pass
    
    async def cancel_order(self, order_id: str) -> bool:
        try:
            await self.exchange.cancel_order(order_id)
            if order_id in self.active_orders:
                self.active_orders[order_id]['status'] = 'canceled'
            return True
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            return False
    
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        try:
            all_positions = await self.exchange.fetch_positions()
            positions_dict = {p['symbol']: p for p in all_positions}
            if symbol == "*":
                return positions_dict
            else:
                return {symbol: positions_dict.get(symbol)} if symbol in positions_dict else {}
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return {}
    
    def update_daily_pnl(self, pnl: float):
        self.daily_pnl += pnl
        self.daily_trades += 1
        if abs(self.daily_pnl) > self.max_daily_loss:
            self.alert_system.trigger_alert(
                alert_type="DAILY_LOSS_LIMIT",
                message=f"日亏损达到限制: {self.daily_pnl:.2f}%",
                level="emergency"
            )
    
    def reset_daily_stats(self):
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_time = time.time()
    
    async def check_exchange_health(self) -> bool:
        try:
            await self.exchange.fetch_time()
            return True
        except Exception as e:
            await self.alert_system.trigger_alert(
                alert_type="EXCHANGE_ERROR",
                message=f"交易所连接异常: {str(e)}",
                level="error"
            )
            return False
    
    def get_active_orders(self) -> Dict[str, Dict]:
        return self.active_orders
    
    def get_daily_stats(self) -> Dict[str, Any]:
        return {
            'pnl': self.daily_pnl,
            'trades': self.daily_trades,
            'last_reset': self.last_reset_time
        }
    
    async def add_signal(self, signal_id: str, signal_data: Dict[str, Any]) -> None:
        self.resonance_pool[signal_id] = {**signal_data, 'timestamp': time.time(), 'status': 'pending'}
        try:
            async with db_pool.get_session() as session:
                stmt = insert(ResonanceSignal).values(
                    id=signal_id, symbol=signal_data['symbol'], timeframe=signal_data['timeframe'],
                    side=signal_data['side'], strength=signal_data['strength'],
                    timestamp=self.resonance_pool[signal_id]['timestamp'], status='pending'
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.error(f"保存信号到数据库失败: {e}", exc_info=True)

    async def remove_signal(self, signal_id: str) -> None:
        if signal_id in self.resonance_pool:
            del self.resonance_pool[signal_id]
        try:
            async with db_pool.get_session() as session:
                stmt = delete(ResonanceSignal).where(ResonanceSignal.id == signal_id)
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.error(f"从数据库删除信号失败: {e}", exc_info=True)

    async def update_signal_status(self, signal_id: str, status: str) -> None:
        if signal_id in self.resonance_pool:
            self.resonance_pool[signal_id]['status'] = status
        try:
            async with db_pool.get_session() as session:
                stmt = update(ResonanceSignal).where(ResonanceSignal.id == signal_id).values(status=status)
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.error(f"更新数据库信号状态失败: {e}", exc_info=True)

    async def _load_resonance_pool_from_db(self):
        try:
            async with db_pool.get_session() as session:
                current_time = time.time()
                stmt = select(ResonanceSignal).where(
                    ResonanceSignal.timestamp > (current_time - self.signal_timeout),
                    ResonanceSignal.status == 'pending'
                )
                result = await session.execute(stmt)
                signals = result.scalars().all()
                for signal in signals:
                    self.resonance_pool[signal.id] = {
                        'symbol': signal.symbol, 'timeframe': signal.timeframe, 'side': signal.side,
                        'strength': signal.strength, 'timestamp': signal.timestamp, 'status': signal.status
                    }
        except Exception as e:
            logger.error(f"从数据库加载共振池失败: {e}", exc_info=True)
            raise

    async def get_resonance_pool(self) -> Dict[str, Any]:
        current_time = time.time()
        expired_signals = [
            signal_id for signal_id, signal_data in self.resonance_pool.items()
            if current_time - signal_data['timestamp'] > self.signal_timeout
        ]
        for signal_id in expired_signals:
            await self.remove_signal(signal_id)
        pending_signals = [
            data for data in self.resonance_pool.values() if data['status'] == 'pending'
        ]
        return {
            'signals': self.resonance_pool,
            'count': len(self.resonance_pool),
            'pending_count': len(pending_signals),
            'last_update': current_time
        }
