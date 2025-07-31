import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import (
    Table, Column, Integer, String, Float, DateTime, MetaData, insert, select, update, func, Text
)

logger = logging.getLogger(__name__)

# 安全获取数据库路径
def get_db_path():
    """计算数据库路径并确保目录可写"""
    # Render平台使用持久化存储
    if "RENDER" in os.environ:
        base_path = "/var/data"
    else:
        base_path = os.path.join(os.getcwd(), "data")
    
    # 确保目录存在
    os.makedirs(base_path, exist_ok=True)
    
    # 验证目录可写
    if not os.access(base_path, os.W_OK):
        raise PermissionError(f"数据库目录不可写: {base_path}")
    
    return os.path.join(base_path, "trading_system_v7.db")

# 使用独立路径
DATABASE_URL = f"sqlite+aiosqlite:///{get_db_path()}"
logger.info(f"数据库路径: {DATABASE_URL}")

engine = create_async_engine(DATABASE_URL, echo=False)
metadata = MetaData()

# 定义表结构
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
    """异步创建表（带错误处理）"""
    try:
        async with engine.begin() as conn:
            logger.info(f"正在创建数据库表...")
            await conn.run_sync(metadata.create_all)
            logger.info("✅ 数据库表创建完成")
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {str(e)}", exc_info=True)
        raise

async def get_setting(key: str, default_value: str = None) -> str:
    async with engine.connect() as conn:
        stmt = select(settings.c.value).where(settings.c.key == key)
        result = await conn.execute(stmt)
        value = result.scalar_one_or_none()
        
        if value is None and default_value is not None:
            logger.info(f"设置项 '{key}' 不存在，使用默认值 '{default_value}'")
            await set_setting(key, default_value)
            return default_value
            
        return value

async def set_setting(key: str, value: str):
    async with engine.connect() as conn:
        check_stmt = select(settings.c.key).where(settings.c.key == key)
        result = await conn.execute(check_stmt)
        
        if result.scalar_one_or_none():
            update_stmt = update(settings).where(settings.c.key == key).values(value=str(value))
            await conn.execute(update_stmt)
        else:
