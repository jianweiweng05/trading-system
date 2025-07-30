import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import (
    Table, Column, Integer, String, Float, DateTime, MetaData, insert, select, update, func, delete
)

# 导入全局配置
from config import CONFIG

logger = logging.getLogger(__name__)

# --- 1. 数据库引擎与元数据 ---
# 使用 CONFIG.db_path 获取数据库路径
DATABASE_URL = f"sqlite+aiosqlite:///{CONFIG.db_path}"
engine = create_async_engine(DATABASE_URL, echo=CONFIG.log_level == "DEBUG")
metadata = MetaData()

# --- 2. 定义所有数据表 (SQLAlchemy Schema) ---
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

# --- 3. 数据库初始化与健康检查 ---
async def init_db():
    """异步创建所有定义的表"""
    # 确保数据库目录存在
    db_dir = os.path.dirname(CONFIG.db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    async with engine.begin() as conn:
        logger.info("正在创建/验证数据库表...")
        await conn.run_sync(metadata.create_all)
        logger.info("数据库表创建/验证完成。")

async def db_health_check() -> bool:
    """检查数据库连接是否正常"""
    try:
        async with engine.connect() as conn:
            await conn.execute(select(1))
        return True
    except Exception as e:
        logger.error(f"数据库健康检查失败: {e}")
        return False

# --- 4. 交易数据操作函数 ---
async def log_trade(symbol: str, quantity: float, entry_price: float, trade_type: str, status: str = "OPEN", strategy_id: str = "default") -> int:
    """记录一笔新的交易到数据库，并返回交易ID。"""
    async with engine.connect() as conn:
        try:
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
            logger.info(f"交易记录已存入数据库, ID: {trade_id}")
            return trade_id
        except Exception as e:
            logger.error(f"记录交易失败: {e}", exc_info=True)
            await conn.rollback()
            return -1

async def get_open_positions():
    """获取所有当前状态为 'OPEN' 的持仓。"""
    async with engine.connect() as conn:
        stmt = select(trades).where(trades.c.status == 'OPEN')
        result = await conn.execute(stmt)
        return result.fetchall()

async def close_trade(trade_id: int, exit_price: float) -> bool:
    """平仓一笔交易，更新状态和退出价格，并返回操作状态。"""
    async with engine.connect() as conn:
        try:
            async with conn.begin(): # 开始事务
                # 检查交易是否存在且是OPEN状态
                check_stmt = select(trades).where(
                    (trades.c.id == trade_id) & 
                    (trades.c.status == 'OPEN')
                )
                result = await conn.execute(check_stmt)
                if not result.fetchone():
                    logger.warning(f"交易 {trade_id} 不存在或已被平仓，无需操作。")
                    return False
                
                # 更新交易状态和退出价格
                update_stmt = (
                    update(trades)
                    .where(trades.c.id == trade_id)
                    .values(status='CLOSED', exit_price=exit_price)
                )
                await conn.execute(update_stmt)
                
                logger.info(f"交易 {trade_id} 已在数据库中标记为平仓, 价格: ${exit_price}")
                return True
                
        except Exception as e:
            logger.error(f"数据库平仓操作失败: {e}", exc_info=True)
            return False

# --- 5. Bot 实例管理功能 ---
async def delete_bot_marker():
    """删除Bot运行标记"""
    logger.info("正在尝试清理数据库中的Bot运行标记...")
    try:
        async with engine.connect() as conn:
            stmt = delete(trades).where(
                (trades.c.symbol == "BOT_INSTANCE") & 
                (trades.c.status == "BOT_RUNNING")
            )
            result = await conn.execute(stmt)
            await conn.commit()
            if result.rowcount > 0:
                logger.info(f"成功删除了 {result.rowcount} 个旧的Bot运行标记。")
            else:
                logger.info("数据库中没有需要清理的Bot运行标记。")
    except Exception as e:
        logger.error(f"清理数据库中的Bot运行标记时出错: {e}", exc_info=True)