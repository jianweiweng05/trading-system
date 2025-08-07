import logging
import asyncio
import time
from typing import Optional, Dict, Any, List
from ccxt.async_support import binance
from src.config import CONFIG
from src.alert_system import AlertSystem

logger = logging.getLogger(__name__)

class TradingEngine:
    """交易引擎核心类"""
    
    def __init__(self, exchange: binance, alert_system: AlertSystem):
        self.exchange = exchange
        self.alert_system = alert_system
        self.active_orders: Dict[str, Dict] = {}
        self.order_timeout = CONFIG.alert_order_timeout
        self.slippage_threshold = CONFIG.alert_slippage_threshold
        self.min_partial_fill = CONFIG.alert_min_partial_fill
        self.max_daily_loss = CONFIG.alert_max_daily_loss
        self.api_retry_count = CONFIG.alert_api_retry_count
        
        # 统计数据
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_time = time.time()
        
        # 新增：共振池数据
        self.resonance_pool: Dict[str, Dict] = {}
        self.signal_timeout = 300  # 信号超时时间（5分钟）
    
    async def execute_order(self, symbol: str, order_type: str, side: str, 
                          amount: float, price: Optional[float] = None) -> Dict[str, Any]:
        """执行订单"""
        try:
            # 检查资金是否充足
            await self._check_balance(symbol, amount, price)
            
            # 准备订单参数
            order_params = {
                'symbol': symbol,
                'type': order_type,
                'side': side,
                'amount': amount
            }
            
            if price is not None:
                order_params['price'] = price
            
            # 执行订单（带重试机制）
            order_result = await self._execute_with_retry(
                lambda: self.exchange.create_order(**order_params),
                max_retries=self.api_retry_count
            )
            
            # 记录订单
            self.active_orders[order_result['id']] = {
                'symbol': symbol,
                'type': order_type,
                'side': side,
                'amount': amount,
                'price': price,
                'status': order_result['status'],
                'filled': order_result.get('filled', 0),
                'timestamp': time.time()
            }
            
            # 启动订单监控
            asyncio.create_task(self._monitor_order(order_result['id']))
            
            return order_result
            
        except Exception as e:
            # 触发下单失败报警
            await self.alert_system.trigger_alert(
                alert_type="ORDER_FAILED",
                message=f"下单失败: {str(e)}",
                level="emergency"
            )
            raise
    
    async def _check_balance(self, symbol: str, amount: float, price: Optional[float] = None):
        """检查资金是否充足"""
        try:
            # 获取账户余额
            balance = await self.exchange.fetch_balance()
            
            # 确定需要的币种
            base_currency = symbol.split('/')[0]
            quote_currency = symbol.split('/')[1]
            
            # 检查买入/卖出方向
            if price is not None:  # 限价单
                required_amount = amount * price if 'buy' in symbol.lower() else amount
                currency = quote_currency if 'buy' in symbol.lower() else base_currency
            else:  # 市价单
                currency = quote_currency if 'buy' in symbol.lower() else base_currency
                required_amount = amount
            
            # 检查余额
            available = balance.get(currency, {}).get('free', 0)
            if float(available) < required_amount:
                await self.alert_system.trigger_alert(
                    alert_type="INSUFFICIENT_FUNDS",
                    message=f"{currency}余额不足: 需要{required_amount}, 可用{available}",
                    level="warning"
                )
                raise ValueError(f"资金不足: 需要{required_amount}, 可用{available}")
                
        except Exception as e:
            logger.error(f"检查余额失败: {e}")
            raise
    
    async def _execute_with_retry(self, func, max_retries: int = 3) -> Any:
        """带重试机制的执行函数"""
        last_error = None
        for i in range(max_retries):
            try:
                return await func()
            except Exception as e:
                last_error = e
                if i < max_retries - 1:
                    await asyncio.sleep(1 * (i + 1))  # 递增延迟
                    continue
        raise last_error
    
    async def _monitor_order(self, order_id: str):
        """监控订单状态"""
        try:
            start_time = time.time()
            
            while True:
                # 检查订单超时
                if time.time() - start_time > self.order_timeout:
                    await self.alert_system.trigger_alert(
                        alert_type="ORDER_TIMEOUT",
                        message=f"订单 {order_id} 超时未成交",
                        level="warning"
                    )
                    # 尝试取消订单
                    await self.cancel_order(order_id)
                    break
                
                # 获取订单状态
                order = await self.exchange.fetch_order(order_id)
                
                # 检查部分成交
                if order['status'] == 'open' and order.get('filled', 0) > 0:
                    filled_ratio = order['filled'] / order['amount']
                    if filled_ratio < self.min_partial_fill:
                        await self.alert_system.trigger_alert(
                            alert_type="PARTIAL_FILL",
                            message=f"订单 {order_id} 部分成交: {filled_ratio:.1%}",
                            level="warning"
                        )
                
                # 检查滑点
                if order['status'] == 'closed' and order.get('price'):
                    expected_price = self.active_orders[order_id]['price']
                    actual_price = order['price']
                    if expected_price:
                        slippage = abs(actual_price - expected_price) / expected_price
                        if slippage > self.slippage_threshold / 100:
                            await self.alert_system.trigger_alert(
                                alert_type="HIGH_SLIPPAGE",
                                message=f"订单 {order_id} 滑点过大: {slippage:.2%}",
                                level="warning"
                            )
                
                # 更新订单状态
                if order_id in self.active_orders:
                    self.active_orders[order_id].update({
                        'status': order['status'],
                        'filled': order.get('filled', 0)
                    })
                
                # 订单完成则退出监控
                if order['status'] in ['closed', 'canceled', 'expired']:
                    break
                
                await asyncio.sleep(1)  # 每秒检查一次
                
        except Exception as e:
            logger.error(f"监控订单失败: {e}")
            await self.alert_system.trigger_alert(
                alert_type="ORDER_MONITOR_ERROR",
                message=f"监控订单 {order_id} 失败: {str(e)}",
                level="error"
            )
    
    async def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        try:
            result = await self.exchange.cancel_order(order_id)
            if order_id in self.active_orders:
                self.active_orders[order_id]['status'] = 'canceled'
            return True
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            return False
    
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        """获取持仓信息"""
        try:
            positions = await self.exchange.fetch_positions([symbol])
            return positions[0] if positions else {}
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return {}
    
    def update_daily_pnl(self, pnl: float):
        """更新每日盈亏"""
        self.daily_pnl += pnl
        self.daily_trades += 1
        
        # 检查是否超过最大亏损限制
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
    
    # 新增：共振池管理方法
    def add_signal(self, signal_id: str, signal_data: Dict[str, Any]) -> None:
        """添加信号到共振池"""
        self.resonance_pool[signal_id] = {
            **signal_data,
            'timestamp': time.time(),
            'status': 'pending'
        }
        logger.info(f"添加信号到共振池: {signal_id}")
    
    def remove_signal(self, signal_id: str) -> None:
        """从共振池移除信号"""
        if signal_id in self.resonance_pool:
            del self.resonance_pool[signal_id]
            logger.info(f"从共振池移除信号: {signal_id}")
    
    def get_resonance_pool(self) -> Dict[str, Any]:
        """获取共振池状态"""
        current_time = time.time()
        
        # 清理过期信号
        expired_signals = [
            signal_id for signal_id, signal_data in self.resonance_pool.items()
            if current_time - signal_data['timestamp'] > self.signal_timeout
        ]
        
        for signal_id in expired_signals:
            self.remove_signal(signal_id)
        
        # 统计信号状态
        pending_signals = [
            signal_data for signal_data in self.resonance_pool.values()
            if signal_data['status'] == 'pending'
        ]
        
        return {
            'signals': self.resonance_pool,
            'count': len(self.resonance_pool),
            'pending_count': len(pending_signals),
            'last_update': current_time
        }
    
    def update_signal_status(self, signal_id: str, status: str) -> None:
        """更新信号状态"""
        if signal_id in self.resonance_pool:
            self.resonance_pool[signal_id]['status'] = status
            self.resonance_pool[signal_id]['updated_at'] = time.time()
            logger.info(f"更新信号状态: {signal_id} -> {status}")
    
    def clear_expired_signals(self) -> None:
        """清理过期信号"""
        current_time = time.time()
        expired_count = 0
        
        for signal_id in list(self.resonance_pool.keys()):
            if current_time - self.resonance_pool[signal_id]['timestamp'] > self.signal_timeout:
                self.remove_signal(signal_id)
                expired_count += 1
        
        if expired_count > 0:
            logger.info(f"清理了 {expired_count} 个过期信号")
