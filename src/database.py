# 文件: src/database.py (最终版)

import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import (
    Table, Column, Integer, String, Float, DateTime, MetaData, insert, select, update, func, Text
)

# 导入配置，注意此时 CONFIG 可能还未完全初始化，仅用于获取 db_path
from config import CONFIG

logger = logging.getLogger(__name__)

# --- 1. 数据库引擎与元数据 ---
# 注意：此处的 DATABASE_URL 依赖于 config 模块在 main.py 中被优先初始化
DATABASE_URL = f"sqlite+aiosqlite:///{CONFIG.db_path if CONFIG else os.path.join('/var/data', 'trading_system.db')}"
engine = create_async_engine(DATABASE_URL, echo=False) # 在生产中关闭 echo
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

# 新增 settings 表，用于持久化可变配置
settings = Table(
    'settings', metadata,
    Column('key', String, primary_key=True),
    Column('value', Text)
)

# --- 3. 数据库初始化 ---
async def init_db():
    """异步创建所有定义的表"""
    # 路径创建已在 config.py 的 db_path 属性中完成
    async with engine.begin() as conn:
        logger.info("正在创建/验证数据库表 (trades, settings)...")
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
        # 使用 aiosqlite 的 upsert 功能
        stmt = insert(settings).values(key=key, value=str(value))
        # 在支持 on_conflict_do_update 的方言中，可以实现更原子的 upsert
        # 对于 aiosqlite，我们先查后改/插
        check_stmt = select(settings.c.key).where(settings.c.key == key)
        result = await conn.execute(check_stmt)
        
        if result.scalar_one_or_none():
            update_stmt = update(settings).where(settings.c.key == key).values(value=str(value))
            await conn.execute(update_stmt)
        else:
            await conn.execute(stmt)
        
        await conn.commit()

# --- 5. 交易数据操作函数 (保持不变) ---
# (这里的 log_trade, get_open_positions, close_trade 等函数保持不变)
async def log_trade(symbol: str, quantity: float, entry_price: float, trade_type: str, status: str = "OPEN", strategy_id: str = "default") -> int:
    async with engine.connect() as conn:
        stmt = insert(trades).values(
            symbol=symbol, quantity=quantity, entry_price=entry_price,
            trade_type=trade_type.upper(), status=status.upper(), strategy_id=strategy_id
        )
        result = await conn.execute(stmt)
        await conn.commit()
        return result.inserted_primary_key[0]

async def get_open_positions():
    async with engine.connect() as conn:
        stmt = select(trades).where(trades.c.status == 'OPEN')
        result = await conn.execute(stmt)
        return result.fetchall()

async def close_trade(trade_id: int, exit_price: float) -> bool:
    async with engine.connect() as conn:
        update_stmt = update(trades).where(trades.c.id == trade_id).values(status='CLOSED', exit_price=exit_price)
        result = await conn.execute(update_stmt)
        await conn.commit()
        return result.rowcount > 0
