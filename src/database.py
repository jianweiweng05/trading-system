import os
import aiosqlite
import logging
import asyncio
import shutil

# 配置日志
logger = logging.getLogger(__name__)

# 数据库配置 - 使用绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "trading_system.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH}"

# 定义 Position 和 Trade 类
class Position:
    def __init__(self, symbol, amount, entry_price, leverage, direction, unrealized_pnl=0.0, run_mode='simulate'):
        self.symbol = symbol
        self.amount = amount
        self.entry_price = entry_price
        self.leverage = leverage
        self.direction = direction
        self.unrealized_pnl = unrealized_pnl
        self.run_mode = run_mode

    def __repr__(self):
        return f"Position({self.symbol}, {self.amount}, {self.entry_price})"

class Trade:
    def __init__(self, symbol, order_id, direction, amount, price, fee=0.0, run_mode='simulate', timestamp=None):
        self.symbol = symbol
        self.order_id = order_id
        self.direction = direction
        self.amount = amount
        self.price = price
        self.fee = fee
        self.run_mode = run_mode
        self.timestamp = timestamp

    def __repr__(self):
        return f"Trade({self.symbol}, {self.direction}, {self.amount}, {self.price})"

class DatabaseManager:
    _instance = None
    
    @classmethod
    async def initialize(cls):
        if cls._instance is None:
            cls._instance = DatabaseManager()
            await cls._instance._create_tables()
            logger.info("数据库初始化完成")
        return cls._instance
    
    async def _create_tables(self):
        # 确保数据库目录存在
        db_dir = os.path.dirname(DATABASE_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"创建数据库目录: {db_dir}")
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # 创建持仓表
            await db.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                amount REAL NOT NULL,
                entry_price REAL NOT NULL,
                leverage INTEGER NOT NULL,
                direction TEXT NOT NULL,
                unrealized_pnl REAL DEFAULT 0.0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                run_mode TEXT DEFAULT 'simulate'
            )
            ''')
            
            # 创建交易表
            await db.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                order_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                amount REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL DEFAULT 0.0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                run_mode TEXT DEFAULT 'simulate'
            )
            ''')
            
            # 创建配置表
            await db.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            ''')
            
            # 确保所有表都已提交
            await db.commit()
            logger.info("数据库表创建完成")
            
            # 验证表是否创建成功
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = await cursor.fetchall()
            table_names = [table[0] for table in tables]
            logger.info(f"数据库包含的表: {', '.join(table_names)}")
            
            # 如果缺少表，创建它们
            required_tables = ['positions', 'trades', 'config']
            for table in required_tables:
                if table not in table_names:
                    logger.warning(f"缺少表: {table}，尝试创建...")
                    if table == 'positions':
                        await db.execute('''
                        CREATE TABLE positions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            symbol TEXT NOT NULL,
                            amount REAL NOT NULL,
                            entry_price REAL NOT NULL,
                            leverage INTEGER NOT NULL,
                            direction TEXT NOT NULL,
                            unrealized_pnl REAL DEFAULT 0.0,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            run_mode TEXT DEFAULT 'simulate'
                        )
                        ''')
                    elif table == 'trades':
                        await db.execute('''
                        CREATE TABLE trades (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            symbol TEXT NOT NULL,
                            order_id TEXT NOT NULL,
                            direction TEXT NOT NULL,
                            amount REAL NOT NULL,
                            price REAL NOT NULL,
                            fee REAL DEFAULT 0.0,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            run_mode TEXT DEFAULT 'simulate'
                        )
                        ''')
                    elif table == 'config':
                        await db.execute('''
                        CREATE TABLE config (
                            key TEXT PRIMARY KEY,
                            value TEXT NOT NULL
                        )
                        ''')
                    await db.commit()
                    logger.info(f"已创建表: {table}")
    
    async def add_position(self, position):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute('''
            INSERT INTO positions (
                symbol, amount, entry_price, leverage, direction, unrealized_pnl, run_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                position.symbol,
                position.amount,
                position.entry_price,
                position.leverage,
                position.direction,
                position.unrealized_pnl,
                position.run_mode
            ))
            await db.commit()
            logger.info(f"持仓记录已添加: {position}")
    
    async def add_trade(self, trade):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # 确保表存在
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            table_exists = await cursor.fetchone()
            
            if not table_exists:
                logger.warning("trades表不存在，尝试创建...")
                await db.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    amount REAL NOT NULL,
                    price REAL NOT NULL,
                    fee REAL DEFAULT 0.0,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    run_mode TEXT DEFAULT 'simulate'
                )
                ''')
                await db.commit()
                logger.info("已创建trades表")
            
            await db.execute('''
            INSERT INTO trades (
                symbol, order_id, direction, amount, price, fee, run_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.symbol,
                trade.order_id,
                trade.direction,
                trade.amount,
                trade.price,
                trade.fee,
                trade.run_mode
            ))
            await db.commit()
            logger.info(f"交易记录已添加: {trade}")
    
    @classmethod
    async def get_positions(cls, run_mode: str):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # 确保表存在
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
            table_exists = await cursor.fetchone()
            
            if not table_exists:
                logger.warning("positions表不存在")
                return []
            
            cursor = await db.execute('''
            SELECT id, symbol, amount, entry_price, leverage, direction, unrealized_pnl, run_mode
            FROM positions WHERE run_mode = ?
            ''', (run_mode,))
            rows = await cursor.fetchall()
            
            positions = []
            for row in rows:
                positions.append(Position(
                    symbol=row[1],
                    amount=row[2],
                    entry_price=row[3],
                    leverage=row[4],
                    direction=row[5],
                    unrealized_pnl=row[6],
                    run_mode=row[7]
                ))
            
            logger.info(f"获取到 {len(positions)} 条持仓记录")
            return positions
    
    @classmethod
    async def get_trades(cls, symbol: str = None, limit: int = 100):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # 确保表存在
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            table_exists = await cursor.fetchone()
            
            if not table_exists:
                logger.warning("trades表不存在")
                return []
            
            if symbol:
                cursor = await db.execute('''
                SELECT id, symbol, order_id, direction, amount, price, fee, timestamp, run_mode
                FROM trades WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?
                ''', (symbol, limit))
            else:
                cursor = await db.execute('''
                SELECT id, symbol, order_id, direction, amount, price, fee, timestamp, run_mode
                FROM trades ORDER BY timestamp DESC LIMIT ?
                ''', (limit,))
                
            rows = await cursor.fetchall()
            
            trades = []
            for row in rows:
                trades.append(Trade(
                    symbol=row[1],
                    order_id=row[2],
                    direction=row[3],
                    amount=row[4],
                    price=row[5],
                    fee=row[6],
                    timestamp=row[7],
                    run_mode=row[8]
                ))
            
            logger.info(f"获取到 {len(trades)} 条交易记录")
            return trades

    @classmethod
    async def backup(cls, backup_path: str) -> bool:
        try:
            # 确保备份目录存在
            backup_dir = os.path.dirname(backup_path)
            if backup_dir and not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            
            # 使用文件复制备份
            shutil.copy2(DATABASE_PATH, backup_path)
            
            # 验证备份文件大小
            file_size = os.path.getsize(backup_path)
            if file_size == 0:
                logger.warning(f"备份文件大小为0字节: {backup_path}")
                return False
            
            logger.info(f"数据库已备份到 {backup_path} ({file_size} 字节)")
            return True
        except Exception as e:
            logger.error(f"数据库备份失败: {e}")
            return False

# 数据库初始化函数
async def init_db():
    """初始化数据库"""
    # 确保数据库目录存在
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    # 重置单例实例
    DatabaseManager._instance = None
    
    await DatabaseManager.initialize()
    logger.info("数据库初始化完成")
