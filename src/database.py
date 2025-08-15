import logging
import os
from typing import Optional, List, AsyncGenerator
from functools import wraps
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, MetaData, 
    select, insert, update, delete, func, Text, text
)

logger = logging.getLogger(__name__)

def get_db_paths() -> str:
    """获取安全的数据库路径"""
    if "RENDER" in os.environ:
        base_path = "/opt/render/project/persistent"
        logger.info(f"检测到Render环境，使用disk挂载路径: {base_path}")
    else:
        base_path = os.path.join(os.getcwd(), "data")
        logger.info(f"本地环境，使用项目目录: {base_path}")
    
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
    return create_async_engine(database_url, echo=False)

DATABASE_URL = f"sqlite+aiosqlite:///{get_db_paths()}"
logger.info(f"数据库路径: {DATABASE_URL}")

engine = create_engine_with_pool(DATABASE_URL)
metadata = MetaData()

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

class ResonanceSignal(Base):
    __tablename__ = 'resonance_signals'
    id = Column(String, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False)
    side = Column(String, nullable=False)
    strength = Column(Float, nullable=False)
    timestamp = Column(Float, nullable=False, index=True)
    status = Column(String, nullable=False, default='pending', index=True)
    created_at = Column(DateTime, default=func.now())

class TVStatus(Base):
    __tablename__ = 'tv_status'
    symbol = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
from contextlib import asynccontextmanager

class DatabaseConnectionPool:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.session_factory = sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        提供一个可以直接与 async with 使用的、安全的数据库会话。
        它会自动处理事务的提交、回滚和关闭。
        """
        session: AsyncSession = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    # 添加 acquire 方法以支持原有的使用方式
    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[AsyncSession, None]:
        """
        为了兼容原有代码而添加的 acquire 方法，内部调用 get_session
        """
        async with self.get_session() as session:
            yield session

db_pool = DatabaseConnectionPool(engine)

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
                # 回滚已在 get_session 中处理
                logger.error(f"事务执行失败: {str(e)}", exc_info=True)
                raise
    return wrapper

async def init_db() -> None:
    """初始化数据库"""
    try:
        logger.info("正在创建数据库表...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ 数据库表创建完成")
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {str(e)}", exc_info=True)
        raise

async def check_database_health() -> bool:
    """检查数据库连接状态"""
    try:
        async with db_pool.get_session() as session:
            await session.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"数据库健康检查失败: {str(e)}", exc_info=True)
        return False

async def get_setting(key: str, default_value: Optional[str] = None) -> Optional[str]:
    """获取设置项"""
    try:
        async with db_pool.get_session() as session:
            result = await session.execute(select(Setting).where(Setting.key == key))
            setting = result.scalar_one_or_none()
            
            if setting is None and default_value is not None:
                await session.execute(insert(Setting).values(key=key, value=str(default_value)))
                await session.commit()
                return default_value
                
            return setting.value if setting else None
    except Exception as e:
        logger.warning(f"获取配置项 '{key}' 失败: {str(e)}，返回默认值")
        return default_value

async def set_setting(key: str, value: str) -> None:
    """设置设置项"""
    try:
        async with db_pool.get_session() as session:
            stmt = update(Setting).where(Setting.key == key).values(value=str(value))
            result = await session.execute(stmt)
            
            if result.rowcount == 0:
                await session.execute(insert(Setting).values(key=key, value=str(value)))
            
            await session.commit()
            logger.info(f"设置项 '{key}' 已更新为: {value}")
    except Exception as e:
        logger.error(f"设置配置项 '{key}' 失败: {str(e)}", exc_info=True)
        raise

@with_transaction
async def get_open_positions(session: AsyncSession) -> List[Trade]:
    """获取所有未平仓仓位"""
    result = await session.execute(select(Trade).where(Trade.status == 'OPEN'))
    return result.scalars().all()

async def log_trade(symbol: str, quantity: float, entry_price: float, 
                   trade_type: str, status: str = "OPEN", strategy_id: str = "default") -> int:
    """记录交易"""
    try:
        async with db_pool.get_session() as session:
            new_trade = Trade(
                symbol=symbol, quantity=quantity, entry_price=entry_price,
                trade_type=trade_type.upper(), status=status.upper(), strategy_id=strategy_id
            )
            session.add(new_trade)
            await session.commit()
            await session.refresh(new_trade)
            logger.info(f"记录交易: {symbol} {trade_type} {quantity} @ {entry_price} (ID: {new_trade.id})")
            return new_trade.id
    except Exception as e:
        logger.error(f"记录交易失败: {str(e)}", exc_info=True)
        raise

async def close_trade(trade_id: int, exit_price: float) -> bool:
    """平仓"""
    try:
        async with db_pool.get_session() as session:
            stmt = update(Trade).where(Trade.id == trade_id).values(
                status='CLOSED', exit_price=exit_price, updated_at=func.now()
            )
            result = await session.execute(stmt)
            await session.commit()
            
            if result.rowcount > 0:
                logger.info(f"交易 {trade_id} 已平仓 @ {exit_price}")
                return True
            return False
    except Exception as e:
        logger.error(f"平仓失败: {str(e)}", exc_info=True)
        raise

async def get_trade_history(symbol: Optional[str] = None, limit: Optional[int] = 10) -> List[Trade]:
    """获取交易历史"""
    try:
        async with db_pool.get_session() as session:
            stmt = select(Trade).order_by(Trade.created_at.desc())
            if symbol:
                stmt = stmt.where(Trade.symbol == symbol)
            if limit:
                stmt = stmt.limit(limit)
            
            result = await session.execute(stmt)
            return result.scalars().all()
    except Exception as e:
        logger.error(f"获取交易历史失败: {str(e)}", exc_info=True)
        return []

async def get_position_by_symbol(symbol: str) -> Optional[Trade]:
    """根据交易对获取持仓"""
    try:
        async with db_pool.get_session() as session:
            stmt = select(Trade).where(Trade.symbol == symbol, Trade.status == 'OPEN')
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"获取持仓失败: {str(e)}", exc_info=True)
        return None

async def update_tv_status(symbol: str, status: str) -> None:
    """
    更新或插入一个交易对的TV信号状态。
    这是处理 Webhook 的逻辑应该调用的函数。
    """
    try:
        async with db_pool.get_session() as session:
            # 尝试更新现有记录
            stmt = update(TVStatus).where(TVStatus.symbol == symbol).values(status=status)
            result = await session.execute(stmt)
            
            # 如果没有记录被更新，说明是新符号，则插入
            if result.rowcount == 0:
                await session.execute(insert(TVStatus).values(symbol=symbol, status=status))
            
            await session.commit()
            logger.info(f"TV 状态已更新: {symbol} -> {status}")
    except Exception as e:
        logger.error(f"更新 TV 状态失败: {symbol} -> {status}, 错误: {e}", exc_info=True)
        raise
