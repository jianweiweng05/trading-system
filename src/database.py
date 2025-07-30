# 文件: src/database.py (请完整复制)

import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import (
    Table, Column, Integer, String, Float, DateTime, MetaData, insert, select, update, func, Text
)

# 导入全局配置
from config import CONFIG

logger = logging.getLogger(__name__)

# --- 1. 数据库引擎与元数据 ---
DATABASE_URL = f"sqlite+aiosqlite:///{CONFIG.db_path}"
engine = create_async_engine(DATABASE_URL, echo=CONFIG.log_level == "DEBUG")
metadata = MetaData()

# --- 2. 定义所有数据表 ---
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

# 新增 settings 表
settings = Table(
    'settings', metadata,
    Column('key', String, primary_key=True),
    Column('value', Text)
)

# --- 3. 数据库初始化与健康检查 ---
async def init_db():
    """异步创建所有定义的表"""
    db_dir = os.path.dirname(CONFIG.db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    async with engine.begin() as conn:
        logger.info("正在创建/验证数据库表...")
        await conn.run_sync(metadata.create_all)
        logger.info("数据库表创建/验证完成。")

# --- 4. 设置项操作函数 (新增) ---
async def get_setting(key: str, default_value: str = None) -> str:
    """获取设置项的值，如果不存在则使用默认值并存入数据库"""
    async with engine.connect() as conn:
        stmt = select(settings.c.value).where(settings.c.key == key)
        result = await conn.execute(stmt)
        value = result.scalar_one_or_none()
        
        if value is None and default_value is not None:
            logger.info(f"设置项 '{key}' 不存在，使用默认值 '{default_value}' 进行初始化。")
            await set_setting(key, default_value)
            return default_value
            
        return value

async def set_setting(key: str, value: str):
    """创建或更新一个设置项"""
    async with engine.connect() as conn:
        # 尝试更新，如果不存在则插入
        stmt = select(settings).where(settings.c.key == key)
        result = await conn.execute(stmt)
        
        if result.first():
            update_stmt = update(settings).where(settings.c.key == key).values(value=str(value))
            await conn.execute(update_stmt)
        else:
            insert_stmt = insert(settings).values(key=key, value=str(value))
            await conn.execute(insert_stmt)
        await conn.commit()

# --- 5. 交易数据操作函数 (保持不变) ---
async def get_open_positions():
    """获取所有当前状态为 'OPEN' 的持仓。"""
    async with engine.connect() as conn:
        stmt = select(trades).where(trades.c.status == 'OPEN')
        result = await conn.execute(stmt)
        return result.fetchall()

# (其他 log_trade, close_trade 等函数保持不变)
