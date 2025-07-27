import unittest
import asyncio
import numpy as np
import sys
import os
import tempfile

# 添加上级目录到系统路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# 使用绝对导入
import src.core_logic
import src.config

class MockExchange:
    async def fetch_ohlcv(self, symbol, timeframe, limit):
        # 生成模拟数据
        np.random.seed(42)
        prices = np.cumprod(1 + np.random.randn(100) * 0.01) * 50000
        timestamps = [i * 3600000 for i in range(100)]
        
        ohlc_data = []
        for ts, p in zip(timestamps, prices):
            open_p = p
            high_p = p + abs(np.random.randn() * 100)
            low_p = p - abs(np.random.randn() * 100)
            close_p = p + np.random.randn() * 50
            volume = 1000 + abs(np.random.randn() * 500)
            ohlc_data.append([ts, open_p, high_p, low_p, close_p, volume])
            
        return ohlc_data

class TestCoreLogic(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 使用临时数据库文件
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        
        # 修改配置使用临时数据库
        src.config.DATABASE_PATH = self.temp_db
        src.config.DATABASE_URL = f"sqlite+aiosqlite:///{self.temp_db}"
    
    async def asyncTearDown(self):
        # 删除临时数据库文件
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)
    
    async def test_signal_processing(self):
        """测试信号处理逻辑"""
        # 创建模拟信号
        test_signal = {
            'symbol': 'BTC/USDT',
            'direction': 'buy',
            'base_amount': 0.1,
            'strategy_name': 'GoldenCross',
            'btc_trend': 'up',
            'eth_trend': 'up'
        }
        
        # 处理信号
        exchange = MockExchange()
        result = await src.core_logic.process_trading_signal(exchange, test_signal, 'simulate')
        
        # 验证结果
        self.assertEqual(result['status'], 'success')
        self.assertGreater(result['target_amount'], 0)
        self.assertEqual(result['symbol'], 'BTC/USDT')
        self.assertEqual(result['strategy_status'], 'bullish')
        self.assertEqual(result['signal_identity'], 'trend_following')

if __name__ == "__main__":
    unittest.main()
