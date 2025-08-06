import logging
import os
from typing import Optional, List, AsyncGenerator, Union
from datetime import datetime
from functools import wraps

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, MetaData, insert, select, update, func, Text, text
)

logger = logging.getLogger(__name__)

def get_db_paths() -> str:
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

def create_engine_with_pool(database_url: str) -> AsyncEngine:
    """创建带连接池的引擎"""
    return create_async_engine(
        database_url,
        echo=False
    )

DATABASE_URL = f"sqlite+aiosqlite:///{get_db_paths()}"
logger.info(f"数据库路径: {DATABASE_URL}")

# 异步引擎用于业务操作
engine = create_engine_with_pool(DATABASE_URL)
metadata = MetaData()

# 创建 Base 类时绑定 metadata
Base = declarative_base(metadata=metadata)

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

def with_transaction(func):
    """事务装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        async with db_pool.get_session() as session:
            try:
                result = await func(session, *args, **kwargs)
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                logger.error(f"事务执行失败: {str(e)}", exc_info=True)
                raise
    return wrapper

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
            except Exception as e:
                await session.rollback()
                logger.error(f"数据库会话错误: {str(e)}", exc_info=True)
                raise
            finally:
                await session.close()

async def init_db() -> None:
    """初始化数据库"""
    try:
        logger.info("正在创建数据库表...")
        # 使用同步方式创建表，避免异步引擎的 MetaData 绑定问题
        from sqlalchemy import create_engine
        sync_engine = create_engine(DATABASE_URL.replace("aiosqlite", "sqlite"))
        Base.metadata.create_all(sync_engine)
        logger.info("✅ 数据库表创建完成")
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {str(e)}", exc_info=True)
        raise

async def check_database_health() -> bool:
    """检查数据库连接状态"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"数据库健康检查失败: {str(e)}", exc_info=True)
        return False

async def get_setting(key: str, default_value: Optional[str] = None) -> Optional[str]:
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

async def set_setting(key: str, value: str) -> None:
    """设置设置项"""
    try:
        async with engine.connect() as conn:
            # 使用 ORM 模型进行查询和更新
            from . import Setting
            check_stmt = select(Setting).where(Setting.key == key)
            result = await conn.execute(check_stmt)
            
            if result.scalar_one_or_none():
                update_stmt = update(Setting).where(Setting.key == key).values(value=str(value))
                await conn.execute(update_stmt)
            else:
                new_setting = Setting(key=key, value=str(value))
                session = AsyncSession(conn)
                session.add(new_setting)
                await session.commit()
            
            logger.info(f"设置项 '{key}' 已更新为: {value}")
    except Exception as e:
        logger.error(f"设置配置项 '{key}' 失败: {str(e)}", exc_info=True)
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
        logger.error(f"获取持仓失败: {str(e)}", exc_info=True)
        return []

async def log_trade(symbol: str, quantity: float, entry_price: float, 
                   trade_type: str, status: str = "OPEN", strategy_id: str = "default") -> int:
    """记录交易"""
    try:
        async with engine.connect() as conn:
            # 使用 ORM 模型创建新记录
            new_trade = Trade(
                symbol=symbol,
                quantity=quantity,
                entry_price=entry_price,
                trade_type=trade_type.upper(),
                status=status.upper(),
                strategy_id=strategy_id
            )
            session = AsyncSession(conn)
            session.add(new_trade)
            await session.commit()
            logger.info(f"记录交易: {symbol} {trade_type} {quantity} @ {entry_price} (ID: {new_trade.id})")
            return new_trade.id
    except Exception as e:
        logger.error(f"记录交易失败: {str(e)}", exc_info=True)
        raise

async def close_trade(trade_id: int, exit_price: float) -> bool:
    """平仓"""
    try:
        async with engine.connect() as conn:
            # 使用 ORM 模型进行更新
            update_stmt = update(Trade).where(Trade.id == trade_id).values(
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
        logger.error(f"平仓失败: {str(e)}", exc_info=True)
        return False

async def get_trade_history(symbol: Optional[str] = None, limit: Optional[int] = 10) -> List[Trade]:
    """获取交易历史"""
    try:
        async with engine.connect() as conn:
            if symbol:
                stmt = select(Trade).where(Trade.symbol == symbol).order_by(Trade.created_at.desc())
            else:
                stmt = select(Trade).order_by(Trade.created_at.desc())
            
            if limit:
                stmt = stmt.limit(limit)
                
            result = await conn.execute(stmt)
            trades = result.scalars().all()
            logger.info(f"获取到 {len(trades)} 条交易记录")
            return trades
    except Exception as e:
        logger.error(f"获取交易历史失败: {str(e)}", exc_info=True)
        return []

async def get_position_by_symbol(symbol: str) -> Optional[Trade]:
    """根据交易对获取持仓"""
    try:
        async with engine.connect() as conn:
            stmt = select(Trade).where(
                Trade.symbol == symbol,
                Trade.status == 'OPEN'
            )
            result = await conn.execute(stmt)
            position = result.scalar_one_or_none()
            if position:
                logger.info(f"找到 {symbol} 持仓: {position.quantity} @ {position.entry_price}")
                return position
            else:
                logger.info(f"未找到 {symbol} 的持仓")
                return None
    except Exception as e:
        logger.error(f"获取持仓失败: {str(e)}", exc_info=True)
        return None

async def get_db_connection() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库连接的上下文管理器"""
    async with db_pool.get_session() as session:
        yield session

# 创建全局连接池实例
db_pool = DatabaseConnectionPool(engine)
