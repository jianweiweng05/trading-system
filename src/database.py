# /database.py

import logging
import os
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import (
    Table, Column, Integer, String, Float, DateTime, MetaData, insert, select, update, func, Text
)
# 导入 SQLite 特定的 insert 语句，以支持 UPSERT 操作
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

# --- 日志记录器设置 ---
# 在实际应用中，你可能会在更高层级配置日志记录器
# 为了让这个模块独立可用，我们在这里做一个简单的配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 数据库路径和引擎设置 ---

def get_db_path():
    """安全地获取数据库文件路径并验证目录权限"""
    # 检查是否在 Render.com 环境中运行
    if "RENDER" in os.environ:
        # 在 Render 中，使用 /var/data 目录进行持久化存储
        base_path = "/var/data"
    else:
        # 在本地开发环境中，使用项目根目录下的 'data' 文件夹
        base_path = os.path.join(os.getcwd(), "data")
    
    # 确保数据目录存在，如果不存在则创建
    os.makedirs(base_path, exist_ok=True)
    
    # 验证目录是否可写，如果不可写则抛出异常
    if not os.access(base_path, os.W_OK):
        error_msg = f"数据库目录不可写: {base_path}"
        logger.error(error_msg)
        raise PermissionError(error_msg)
    
    return os.path.join(base_path, "trading_system_v8.db")

try:
    DATABASE_URL = f"sqlite+aiosqlite:///{get_db_path()}"
    logger.info(f"数据库路径设置为: {DATABASE_URL}")
    engine = create_async_engine(DATABASE_URL, echo=False)
except PermissionError as e:
    # 如果路径设置失败，程序无法继续，记录致命错误并退出
    logger.critical(f"无法初始化数据库引擎: {e}")
    engine = None # 将 engine 设置为 None

metadata = MetaData()

# --- 表结构定义 ---

settings = Table(
    'settings', metadata,
    Column('key', String(50), primary_key=True, nullable=False),
    Column('value', Text, nullable=False)
)

trades = Table(
    'trades', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('symbol', String(20), nullable=False, index=True),
    Column('quantity', Float, nullable=False),
    Column('entry_price', Float, nullable=False),
    Column('exit_price', Float, nullable=True),
    Column('trade_type', String(10), nullable=False), # 'BUY' or 'SELL'
    Column('status', String(10), nullable=False, index=True), # 'OPEN' or 'CLOSED'
    Column('strategy_id', String(50), default='default', nullable=False),
    Column('entry_time', DateTime, default=lambda: datetime.now(timezone.utc), nullable=False),
    Column('exit_time', DateTime, nullable=True)
)

# --- 数据库核心功能函数 ---

async def init_db():
    """异步初始化数据库，创建所有定义的表"""
    if not engine:
        logger.error("数据库引擎未初始化，跳过数据库设置。")
        return
        
    try:
        async with engine.begin() as conn:
            logger.info("正在创建/验证数据库表...")
            await conn.run_sync(metadata.create_all)
            logger.info("✅ 数据库表初始化完成")
    except Exception as e:
        logger.warning(f"数据库初始化期间遇到问题: {e}")

async def get_setting(key: str, default_value: str = None) -> str:
    """安全地从数据库获取配置项，如果不存在则设置并返回默认值"""
    if not engine: return default_value
    
    try:
        async with engine.connect() as conn:
            stmt = select(settings.c.value).where(settings.c.key == key)
            result = await conn.execute(stmt)
            value = result.scalar_one_or_none()
            
            if value is None and default_value is not None:
                logger.info(f"配置项 '{key}' 不存在，将使用并设置默认值: {default_value}")
                await set_setting(key, default_value)
                return default_value
                
            return value
    except Exception as e:
        logger.warning(f"获取配置项 '{key}' 失败: {e}. 返回默认值。")
        return default_value

async def set_setting(key: str, value: str):
    """
    安全地更新或插入配置项 (UPSERT)。
    【改进】使用单个原子操作，比先查询后更新/插入更高效。
    """
    if not engine: return

    try:
        async with engine.connect() as conn:
            # 使用 SQLite 的 "INSERT ... ON CONFLICT" 实现 UPSERT
            stmt = sqlite_insert(settings).values(key=key, value=str(value))
            update_stmt = stmt.on_conflict_do_update(
                index_elements=['key'],
                set_=dict(value=str(value))
            )
            await conn.execute(update_stmt)
            await conn.commit()
            logger.info(f"配置项 '{key}' 已成功设置/更新。")
    except Exception as e:
        logger.warning(f"更新配置项 '{key}' 失败: {e}")

# --- 交易数据操作函数 ---

async def get_open_positions():
    """获取所有未平仓的交易"""
    if not engine: return []

    try:
        async with engine.connect() as conn:
            stmt = select(trades).where(trades.c.status == 'OPEN')
            result = await conn.execute(stmt)
            return result.fetchall()
    except Exception as e:
        logger.warning(f"获取未平仓交易失败: {e}")
        return []

async def log_trade(symbol: str, quantity: float, entry_price: float, 
                   trade_type: str, status: str = "OPEN", strategy_id: str = "default") -> int:
    """记录一笔新的交易，并返回其唯一ID"""
    if not engine: return -1

    try:
        async with engine.connect() as conn:
            stmt = insert(trades).values(
                symbol=symbol, 
                quantity=quantity, 
                entry_price=entry_price,
                trade_type=trade_type.upper(), 
                status=status.upper(), 
                strategy_id=strategy_id,
                # entry_time 会自动使用默认值 (当前UTC时间)
            )
            result = await conn.execute(stmt)
            await conn.commit()
            trade_id = result.inserted_primary_key[0]
            logger.info(f"交易记录成功: ID #{trade_id} - {symbol} {trade_type}")
            return trade_id
    except Exception as e:
        logger.warning(f"记录交易日志失败: {e}")
        return -1

async def close_trade(trade_id: int, exit_price: float) -> bool:
    """根据交易ID平仓一笔现有交易"""
    if not engine: return False

    try:
        async with engine.connect() as conn:
            update_stmt = update(trades).where(trades.c.id == trade_id)\
                                        .where(trades.c.status == 'OPEN')\
                                        .values(
                                            status='CLOSED', 
                                            exit_price=exit_price,
                                            exit_time=datetime.now(timezone.utc)
                                        )
            result = await conn.execute(update_stmt)
            await conn.commit()
            
            if result.rowcount > 0:
                logger.info(f"交易 #{trade_id} 已成功平仓。")
                return True
            else:
                logger.warning(f"尝试平仓交易 #{trade_id} 失败，可能已被平仓或ID不存在。")
                return False
    except Exception as e:
        logger.warning(f"平仓交易 #{trade_id} 失败: {e}")
        return False
