import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import (
    Table, Column, Integer, String, Float, DateTime, MetaData, insert, select, update, func, Text
)
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)

def get_db_paths():
    """获取安全的数据库路径"""
    # 在Render平台使用项目目录下的data文件夹
    if "RENDER" in os.environ:
        base_path = os.path.join(os.getcwd(), "data")
    else:
        base_path = os.path.join(os.getcwd(), "data")
    
    try:
        os.makedirs(base_path, exist_ok=True)
        logger.info(f"数据库目录: {base_path}")
    except Exception as e:
        logger.error(f"创建数据库目录失败: {e}")
        raise
    
    if not os.access(base_path, os.W_OK):
        raise PermissionError(f"数据库目录不可写: {base_path}")
    
    return os.path.join(base_path, "trading_system_v7.db")

# 修复了函数名错误
DATABASE_URL = f"sqlite+aiosqlite:///{get_db_paths()}"  # 使用正确的函数名
logger.info(f"数据库路径: {DATABASE_URL}")

engine = create_async_engine(DATABASE_URL, echo=False)
metadata = MetaData()

trades = Table(
    'trades', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('symbol', String, nullable=False, index=True),
    Column('quantity', Float, nullable=False),
    Column('entry_price', Float, nullable=False),
    Column('exit_price', Float),
    Column('trade_type', String, nullable=False),
    Column('status', String, nullable=False, default='OPEN', index=True),
    Column('strategy_id', String),
    Column('created_at', DateTime, default=func.now()),
    Column('updated_at', DateTime, default=func.now(), onupdate=func.now())
)

settings = Table(
    'settings', metadata,
    Column('key', String, primary_key=True),
    Column('value', Text)
)

async def init_db():
    """初始化数据库"""
    try:
        async with engine.begin() as conn:
            logger.info("正在创建数据库表...")
            await conn.run_sync(metadata.create_all)
            logger.info("✅ 数据库表创建完成")
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {str(e)}", exc_info=True)
        raise

async def get_setting(key: str, default_value: str = None) -> str:
    """获取设置项"""
    try:
        async with engine.connect() as conn:
            stmt = select(settings.c.value).where(settings.c.key == key)
            result = await conn.execute(stmt)
            value = result.scalar_one_or_none()
            
            if value is None and default_value is not None:
                logger.info(f"设置项 '{key}' 不存在，使用默认值 '{default_value}'")
                await set_setting(key, default_value)
                return default_value
                
            return value
    except Exception as e:
        logger.warning(f"获取配置项 '{key}' 失败: {str(e)}，返回默认值")
        return default_value

async def set_setting(key: str, value: str):
    """设置设置项"""
    try:
        async with engine.connect() as conn:
            check_stmt = select(settings.c.key).where(settings.c.key == key)
            result = await conn.execute(check_stmt)
            
            if result.scalar_one_or_none():
                update_stmt = update(settings).where(settings.c.key == key).values(value=str(value))
                await conn.execute(update_stmt)
            else:
                stmt = insert(settings).values(key=key, value=str(value))
                await conn.execute(stmt)
            
            await conn.commit()
            logger.info(f"设置项 '{key}' 已更新为: {value}")
    except Exception as e:
        logger.error(f"设置配置项 '{key}' 失败: {str(e)}")
        raise

async def get_open_positions():
    """获取所有未平仓仓位"""
    try:
        async with engine.connect() as conn:
            stmt = select(trades).where(trades.c.status == 'OPEN')
            result = await conn.execute(stmt)
            positions = result.fetchall()
            logger.info(f"获取到 {len(positions)} 个未平仓位")
            return positions
    except Exception as e:
        logger.error(f"获取持仓失败: {str(e)}")
        return []

async def log_trade(symbol: str, quantity: float, entry_price: float, 
                   trade_type: str, status: str = "OPEN", strategy_id: str = "default") -> int:
    """记录交易"""
    try:
        async with engine.connect() as conn:
            stmt = insert(trades).values(
                symbol=symbol, 
                quantity=quantity, 
                entry_price=entry_price,
                trade_type=trade_type.upper(), 
                status=status.upper(), 
                strategy_id=strategy_id
            )
            result = await conn.execute(stmt)
            await conn.commit()
            trade_id = result.inserted_primary_key[0]
            logger.info(f"记录交易: {symbol} {trade_type} {quantity} @ {entry_price} (ID: {trade_id})")
            return trade_id
    except Exception as e:
        logger.error(f"记录交易失败: {str(e)}")
        raise

async def close_trade(trade_id: int, exit_price: float) -> bool:
    """平仓"""
    try:
        async with engine.connect() as conn:
            update_stmt = update(trades).where(trades.c.id == trade_id).values(
                status='CLOSED', 
                exit_price=exit_price,
                updated_at=func.now()
            )
            result = await conn.execute(update_stmt)
            await conn.commit()
            success = result.rowcount > 0
            if success:
                logger.info(f"交易 {trade_id} 已平仓 @ {exit_price}")
            return success
    except Exception as e:
        logger.error(f"平仓失败: {str(e)}")
        return False

async def get_trade_history(symbol: str = None, limit: int = 10):
    """获取交易历史"""
    try:
        async with engine.connect() as conn:
            if symbol:
                stmt = select(trades).where(trades.c.symbol == symbol).order_by(trades.c.created_at.desc())
            else:
                stmt = select(trades).order_by(trades.c.created_at.desc())
            
            if limit:
                stmt = stmt.limit(limit)
                
            result = await conn.execute(stmt)
            trades = result.fetchall()
            logger.info(f"获取到 {len(trades)} 条交易记录")
            return trades
    except Exception as e:
        logger.error(f"获取交易历史失败: {str(e)}")
        return []

async def get_position_by_symbol(symbol: str):
    """根据交易对获取持仓"""
    try:
        async with engine.connect() as conn:
            stmt = select(trades).where(
                trades.c.symbol == symbol,
                trades.c.status == 'OPEN'
            )
            result = await conn.execute(stmt)
            position = result.fetchone()
            if position:
                logger.info(f"找到 {symbol} 持仓: {position['quantity']} @ {position['entry_price']}")
                return position
            else:
                logger.info(f"未找到 {symbol} 的持仓")
                return None
    except Exception as e:
        logger.error(f"获取持仓失败: {str(e)}")
        return None

# 添加数据库会话管理器
async def get_db_connection():
    """获取数据库连接的上下文管理器"""
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

# 数据库连接池
class DatabaseConnectionPool:
    def __init__(self):
        self.engine = engine
        
    async def execute_query(self, query, params=None):
        """执行查询"""
        try:
            async with self.engine.connect() as conn:
                if params:
                    result = await conn.execute(query, params)
                else:
                    result = await conn.execute(query)
                await conn.commit()
                return result
        except Exception as e:
            logger.error(f"数据库查询失败: {str(e)}")
            raise

# 创建全局连接池实例
db_pool = DatabaseConnectionPool()
