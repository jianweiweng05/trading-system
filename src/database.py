import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import (
    Table, Column, Integer, String, Float, DateTime, MetaData, insert, select, update, func, Text
)

logger = logging.getLogger(__name__)

def get_db_path():
    """获取安全的数据库路径"""
    # 统一使用项目目录下的data文件夹
    base_path = os.path.join(os.getcwd(), "data")
    
    try:
        os.makedirs(base_path, exist_ok=True)
        logger.info(f"数据库目录: {base_path}")
    except Exception as e:
        logger.error(f"创建数据库目录失败: {e}")
        raise
    
    # 检查目录权限
    if not os.access(base_path, os.W_OK):
        raise PermissionError(f"数据库目录不可写: {base_path}")
    
    db_path = os.path.join(base_path, "trading_system_v7.db")
    logger.info(f"数据库路径: {db_path}")
    return db_path

DATABASE_URL = f"sqlite+aiosqlite:///{get_db_path()}"
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
    try:
        async with engine.begin() as conn:
            logger.info("正在创建数据库表...")
            await conn.run_sync(metadata.create_all)
            logger.info("✅ 数据库表创建完成")
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {str(e)}", exc_info=True)
        raise

async def get_setting(key: str, default_value: str = None) -> str:
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
    except Exception as e:
        logger.error(f"设置配置项 '{key}' 失败: {str(e)}")
        raise

async def get_open_positions():
    try:
        async with engine.connect() as conn:
            stmt = select(trades).where(trades.c.status == 'OPEN')
            result = await conn.execute(stmt)
            return result.fetchall()
    except Exception as e:
        logger.error(f"获取持仓失败: {str(e)}")
        return []

async def log_trade(symbol: str, quantity: float, entry_price: float, 
                   trade_type: str, status: str = "OPEN", strategy_id: str = "default") -> int:
    try:
        async with engine.connect() as conn:
            stmt = insert(trades).values(
                symbol=symbol, quantity=quantity, entry_price=entry_price,
                trade_type=trade_type.upper(), status=status.upper(), strategy_id=strategy_id
            )
            result = await conn.execute(stmt)
            await conn.commit()
            return result.inserted_primary_key[0]
    except Exception as e:
        logger.error(f"记录交易失败: {str(e)}")
        raise

async def close_trade(trade_id: int, exit_price: float) -> bool:
    try:
        async with engine.connect() as conn:
            update_stmt = update(trades).where(trades.c.id == trade_id).values(status='CLOSED', exit_price=exit_price)
            result = await conn.execute(update_stmt)
            await conn.commit()
            return result.rowcount > 0
    except Exception as e:
        logger.error(f"关闭交易失败: {str(e)}")
        return False
