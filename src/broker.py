import logging
import asyncio
import ccxt.async_support as ccxt
from .config import RUN_MODE, DEBUG_MODE, LOG_LEVEL

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL if LOG_LEVEL else logging.DEBUG if DEBUG_MODE else logging.INFO)

# 定义 Broker 类
class Broker:
    def __init__(self, exchange_id='binance', api_key=None, api_secret=None):
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = None
        self.run_mode = RUN_MODE
        
    async def connect(self):
        """连接交易所"""
        try:
            exchange_class = getattr(ccxt, self.exchange_id)
            self.exchange = exchange_class({
                'apiKey': self.api_key,
                'secret': self.api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future',
                }
            })
            logger.info(f"已连接到 {self.exchange_id}")
            return True
        except Exception as e:
            logger.error(f"连接交易所失败: {e}")
            return False
    
    async def place_order(self, symbol, order_type, side, amount, price=None, params={}):
        """下单"""
        if self.run_mode == 'simulate':
            logger.info(f"[模拟交易] 下单: {symbol} {side} {amount} @ {price if price else '市价'}")
            return {
                'status': 'filled',
                'symbol': symbol,
                'side': side,
                'amount': amount,
                'price': price or 0,
                'fee': 0
            }
        
        try:
            order_params = {
                'symbol': symbol,
                'type': order_type,
                'side': side,
                'amount': amount,
                'params': params
            }
            
            if price:
                order_params['price'] = price
            
            order = await self.exchange.create_order(**order_params)
            logger.info(f"下单成功: {order['id']} {symbol} {side} {amount}")
            return order
        except Exception as e:
            logger.error(f"下单失败: {e}")
            return None
    
    async def close(self):
        """关闭交易所连接"""
        if self.exchange:
            await self.exchange.close()
            logger.info(f"已断开 {self.exchange_id} 连接")
