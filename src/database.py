import logging
import os
from typing import Optional, List, AsyncGenerator
from datetime import datetime
from functools import wraps

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Table, Column, Integer, String, Float, DateTime, MetaData, insert, select, update, func, Text, text
)

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

# 添加数据库连接池配置
def create_engine_with_pool(database_url: str) -> AsyncEngine:
    """创建带连接池的引擎"""
    return create_async_engine(
        database_url,
        echo=False
    )

DATABASE_URL = f"sqlite+aiosqlite:///{get_db_paths()}"
logger.info(f"数据库路径: {DATABASE_URL}")

engine = create_engine_with_pool(DATABASE_URL)
metadata = MetaData()

# 添加数据模型
Base = declarative_base()

class Trade(Base):
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    trade_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default='OPEN', index=True)
    strategy_id = Column(String)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

class Setting(Base):
    __tablename__ = 'settings'
    
    key = Column(String, primary_key=True)
    value = Column(Text)

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

# 添加事务装饰器
def with_transaction(func):
    """事务装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        async with db_pool.get_session() as session:
            try:
                result = await func(session, *args, **kwargs)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
    return wrapper

# 优化数据库连接池
class DatabaseConnectionPool:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.session_factory = sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取数据库会话"""
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

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

# 添加数据库健康检查
async def check_database_health() -> bool:
    """检查数据库连接状态"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"数据库健康检查失败: {str(e)}")
        return False

async def get_setting(key: str, default_value: str = None) -> Optional[str]:
    """获取设置项"""
    try:
        async with db_pool.get_session() as session:
            result = await session.execute(
                select(Setting).where(Setting.key == key)
            )
            setting = result.scalar_one_or_none()
            
            if setting is None and default_value is not None:
                logger.info(f"设置项 '{key}' 不存在，使用默认值 '{default_value}'")
                await set_setting(key, default_value)
                return default_value
                
            return setting.value if setting else None
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

@with_transaction
async def get_open_positions(session: AsyncSession) -> List[Trade]:
    """获取所有未平仓仓位"""
    try:
        result = await session.execute(
            select(Trade).where(Trade.status == 'OPEN')
        )
        positions = result.scalars().all()
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

async def get_db_connection():
    """获取数据库连接的上下文管理器"""
    async with db_pool.get_session() as session:
        yield session

# 创建全局连接池实例
db_pool = DatabaseConnectionPool(engine)
