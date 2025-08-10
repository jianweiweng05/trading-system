
import logging
import asyncio
import time
from typing import Optional, Dict, Any, List
from ccxt.async_support import binance
from sqlalchemy import select, insert, update, delete # 【修改】从 sqlalchemy 直接导入
from src.config import CONFIG
from src.alert_system import AlertSystem
# 【修改】只从我们自己的 database 模块导入我们自己定义的东西
from src.database import db_pool, ResonanceSignal
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
        
        self._macro_status: Optional[Dict[str, Any]] = None
        self._last_macro_update: float = 0

    # --- 【修改】为新增的 initialize 函数添加注解和文档 ---
    async def initialize(self) -> None:
        """
        异步初始化交易引擎。
        主要负责从数据库加载持久化的状态，例如共振池。
        """
        logger.info("正在初始化交易引擎...")
        await self._load_resonance_pool_from_db()
        logger.info("✅ 交易引擎初始化完成")

    async def execute_order(self, symbol: str, order_type: str, side: str, 
                          amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        # ... (此函数保持不变) ...
        try:
            await self._check_balance(symbol, amount, price)
            order_params = {'symbol': symbol, 'type': order_type, 'side': side, 'amount': amount}
            if price is not None:
                order_params['price'] = price
            order_result = await self._execute_with_retry(
                lambda: self.exchange.create_order(**order_params),
                max_retries=self.api_retry_count
            )
            self.active_orders[order_result['id']] = {
                'symbol': symbol, 'type': order_type, 'side': side, 'amount': amount,
                'price': price, 'status': order_result['status'],
                'filled': order_result.get('filled', 0), 'timestamp': time.time()
            }
            asyncio.create_task(self._monitor_order(order_result['id']))
            return order_result
        except Exception as e:
            await self.alert_system.trigger_alert(
                alert_type="ORDER_FAILED", message=f"下单失败: {str(e)}", level="emergency"
            )
            raise
    
    async def _check_balance(self, symbol: str, amount: float, price: Optional[float] = None):
        # ... (此函数保持不变) ...
        try:
            balance = await self.exchange.fetch_balance()
            # 这是一个简化的货币对解析，未来可以优化
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
        # ... (此函数保持不变) ...
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
        # ... (此函数保持不变) ...
        pass
    
    async def cancel_order(self, order_id: str) -> bool:
        # ... (此函数保持不变) ...
        try:
            await self.exchange.cancel_order(order_id)
            if order_id in self.active_orders:
                self.active_orders[order_id]['status'] = 'canceled'
            return True
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            return False
    
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        # ... (此函数保持不变) ...
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
    
    # --- 【修改】恢复了每日统计相关函数的原始逻辑 ---
    def update_daily_pnl(self, pnl: float):
        """更新每日盈亏"""
        self.daily_pnl += pnl
        self.daily_trades += 1
        if abs(self.daily_pnl) > self.max_daily_loss:
            self.alert_system.trigger_alert(
                alert_type="DAILY_LOSS_LIMIT",
                message=f"日亏损达到限制: {self.daily_pnl:.2f}%",
                level="emergency"
            )
    
    def reset_daily_stats(self):
        """重置每日统计数据"""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_time = time.time()
    
    async def check_exchange_health(self) -> bool:
        """检查交易所连接状态"""
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
        """获取所有活动订单"""
        return self.active_orders
    
    def get_daily_stats(self) -> Dict[str, Any]:
        """获取每日统计数据"""
        return {
            'pnl': self.daily_pnl,
            'trades': self.daily_trades,
            'last_reset': self.last_reset_time
        }
    
    async def add_signal(self, signal_id: str, signal_data: Dict[str, Any]) -> None:
        # ... (此函数保持不变) ...
        self.resonance_pool[signal_id] = {**signal_data, 'timestamp': time.time(), 'status': 'pending'}
        logger.info(f"添加信号到内存共振池: {signal_id}")
        try:
            async with db_pool.get_session() as session:
                stmt = insert(ResonanceSignal).values(
                    id=signal_id, symbol=signal_data['symbol'], timeframe=signal_data['timeframe'],
                    side=signal_data['side'], strength=signal_data['strength'],
                    timestamp=self.resonance_pool[signal_id]['timestamp'], status='pending'
                )
                await session.execute(stmt)
                await session.commit()
            logger.info(f"信号已保存到数据库: {signal_id}")
        except Exception as e:
            logger.error(f"保存信号到数据库失败: {e}", exc_info=True)

    async def remove_signal(self, signal_id: str) -> None:
        # ... (此函数保持不变) ...
        if signal_id in self.resonance_pool:
            del self.resonance_pool[signal_id]
            logger.info(f"从内存共振池移除信号: {signal_id}")
        try:
            async with db_pool.get_session() as session:
                stmt = delete(ResonanceSignal).where(ResonanceSignal.id == signal_id)
                await session.execute(stmt)
                await session.commit()
            logger.info(f"从数据库删除信号: {signal_id}")
        except Exception as e:
            logger.error(f"从数据库删除信号失败: {e}", exc_info=True)

    # --- 【修改】恢复了 get_resonance_pool 的原始逻辑 ---
    def get_resonance_pool(self) -> Dict[str, Any]:
        """获取共振池状态"""
        current_time = time.time()
        expired_signals = [
            signal_id for signal_id, signal_data in self.resonance_pool.items()
            if current_time - signal_data['timestamp'] > self.signal_timeout
        ]
        for signal_id in expired_signals:
            # 这里可以调用 remove_signal，但为了避免异步问题，直接操作内存
            if signal_id in self.resonance_pool:
                del self.resonance_pool[signal_id]
                logger.info(f"从内存共振池移除过期信号: {signal_id}")
        
        pending_signals = [
            data for data in self.resonance_pool.values() if data['status'] == 'pending'
        ]
        logger.info(f"共振池状态: 信号总数={len(self.resonance_pool)}, 待处理={len(pending_signals)}")
        return {
            'signals': self.resonance_pool,
            'count': len(self.resonance_pool),
            'pending_count': len(pending_signals),
            'last_update': current_time
        }

    async def update_signal_status(self, signal_id: str, status: str) -> None:
        # ... (此函数保持不变) ...
        if signal_id in self.resonance_pool:
            self.resonance_pool[signal_id]['status'] = status
            self.resonance_pool[signal_id]['updated_at'] = time.time()
            logger.info(f"更新内存信号状态: {signal_id} -> {status}")
        try:
            async with db_pool.get_session() as session:
                stmt = update(ResonanceSignal).where(ResonanceSignal.id == signal_id).values(status=status)
                await session.execute(stmt)
                await session.commit()
            logger.info(f"更新数据库信号状态: {signal_id} -> {status}")
        except Exception as e:
            logger.error(f"更新数据库信号状态失败: {e}", exc_info=True)

    # --- 【修改】加固了 _load_resonance_pool_from_db 的异常处理 ---
    async def _load_resonance_pool_from_db(self):
        """从数据库加载未过期的信号来预热共振池"""
        logger.info("从数据库加载共振池...")
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
                logger.info(f"✅ 成功从数据库加载 {len(signals)} 个信号到共振池")
        except Exception as e:
            logger.error(f"从数据库加载共振池失败: {e}", exc_info=True)
            raise # 重新抛出异常，使应用启动失败

    # --- 【修改】恢复了宏观状态相关函数的原始逻辑 ---
    def get_macro_status(self) -> Dict[str, Any]:
        """获取宏观状态信息"""
        current_time = time.time()
        if (not self._macro_status or 
            current_time - self._last_macro_update > CONFIG.macro_cache_timeout):
            logger.info("宏观状态缓存过期，返回默认值")
            self._macro_status = {
                'trend': '未知', 'btc1d': '未知', 'eth1d': '未知',
                'confidence': 0, 'last_update': current_time
            }
            self._last_macro_update = current_time
        return self._macro_status.copy()
    
    def update_macro_status(self, trend: str, btc1d: str, eth1d: str, confidence: float = 0) -> None:
        """更新宏观状态信息"""
        self._macro_status = {
            'trend': trend, 'btc1d': btc1d, 'eth1d': eth1d,
            'confidence': confidence, 'last_update': time.time()
        }
        self._last_macro_update = time.time()
        logger.info(f"更新宏观状态: {trend}, BTC1d: {btc1d}, ETH1d: {eth1d}")
