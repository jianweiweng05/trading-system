import unittest
import asyncio
import sys
import os
import logging
import tempfile
import aiosqlite
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 添加上级目录到系统路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# 使用绝对导入
import src.database

class TestDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        """每个测试前的设置"""
        # 使用临时数据库文件
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        logger.info(f"使用临时数据库: {self.temp_db}")
        
        # 修改配置使用临时数据库
        src.database.DATABASE_PATH = self.temp_db
        src.database.DATABASE_URL = f"sqlite+aiosqlite:///{self.temp_db}"
        
        logger.info("=" * 50)
        logger.info("初始化测试数据库...")
        await src.database.init_db()
        self.db = await src.database.DatabaseManager.initialize()
        logger.info("数据库初始化完成")
        
        # 确保数据库文件存在
        self.assertTrue(os.path.exists(self.temp_db), "数据库文件不存在")
        logger.info(f"数据库文件大小: {os.path.getsize(self.temp_db)} 字节")
    
    async def asyncTearDown(self):
        """每个测试后的清理"""
        # 删除临时数据库文件
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)
            logger.info(f"已删除临时数据库: {self.temp_db}")
    
    async def test_table_creation(self):
        """验证表是否创建成功"""
        # 给数据库一点时间完成初始化
        await asyncio.sleep(0.1)
        
        async with aiosqlite.connect(self.temp_db) as db:
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = await cursor.fetchall()
            table_names = [table[0] for table in tables]
            logger.info(f"数据库包含的表: {', '.join(table_names)}")
            
            self.assertIn('positions', table_names, "positions 表不存在")
            self.assertIn('trades', table_names, "trades 表不存在")
            self.assertIn('config', table_names, "config 表不存在")
    
    async def test_add_position(self):
        """测试添加持仓记录"""
        logger.info("测试添加持仓记录...")
        position = src.database.Position(
            symbol="BTC/USDT",
            amount=0.1,
            entry_price=50000.0,
            leverage=10,
            direction="long"
        )
        await self.db.add_position(position)
        
        # 给数据库一点时间完成写入
        await asyncio.sleep(0.1)
        
        # 查询持仓
        positions = await src.database.DatabaseManager.get_positions("simulate")
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].symbol, "BTC/USDT")
        logger.info("持仓记录测试通过")
    
    async def test_add_trade(self):
        """测试添加交易记录"""
        logger.info("测试添加交易记录...")
        trade = src.database.Trade(
            symbol="ETH/USDT",
            order_id="TEST-123",
            direction="buy",
            amount=1.5,
            price=3000.0,
            fee=0.75
        )
        await self.db.add_trade(trade)
        
        # 给数据库一点时间完成写入
        await asyncio.sleep(0.1)
        
        # 查询交易
        trades = await src.database.DatabaseManager.get_trades("ETH/USDT")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].price, 3000.0)
        logger.info("交易记录测试通过")
    
    async def test_backup_database(self):
        """测试数据库备份"""
        logger.info("测试数据库备份...")
        
        # 添加一些数据
        position = src.database.Position(
            symbol="BTC/USDT",
            amount=0.1,
            entry_price=50000.0,
            leverage=10,
            direction="long"
        )
        await self.db.add_position(position)
        
        trade = src.database.Trade(
            symbol="ETH/USDT",
            order_id="TEST-123",
            direction="buy",
            amount=1.5,
            price=3000.0,
            fee=0.75
        )
        await self.db.add_trade(trade)
        
        # 给数据库一点时间完成写入
        await asyncio.sleep(0.1)
        
        # 创建临时备份文件
        backup_path = tempfile.NamedTemporaryFile(suffix=".backup.db", delete=False).name
        
        # 执行备份
        logger.info(f"执行备份到: {backup_path}")
        result = await src.database.DatabaseManager.backup(backup_path)
        self.assertTrue(result, "备份操作应返回True")
        
        # 验证备份文件存在
        self.assertTrue(os.path.exists(backup_path), "备份文件应存在")
        backup_size = os.path.getsize(backup_path)
        logger.info(f"备份文件创建成功: {backup_size} 字节")
        self.assertGreater(backup_size, 0, "备份文件大小应大于0字节")
        
        # 验证备份文件内容
        async with aiosqlite.connect(backup_path) as db:
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = await cursor.fetchall()
            table_names = [table[0] for table in tables]
            logger.info(f"备份数据库包含的表: {', '.join(table_names)}")
            self.assertIn('positions', table_names)
            self.assertIn('trades', table_names)
            
            # 验证数据
            cursor = await db.execute("SELECT COUNT(*) FROM positions")
            count = await cursor.fetchone()
            self.assertEqual(count[0], 1, "备份文件中应有1条持仓记录")
            
            cursor = await db.execute("SELECT COUNT(*) FROM trades")
            count = await cursor.fetchone()
            self.assertEqual(count[0], 1, "备份文件中应有1条交易记录")
        
        # 清理
        if os.path.exists(backup_path):
            os.remove(backup_path)
            logger.info("已清理备份文件")
        
        logger.info("数据库备份测试通过")

if __name__ == "__main__":
    unittest.main()
