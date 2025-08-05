import logging
from typing import ClassVar, Final
import asyncio
from src.database import get_setting, set_setting

logger = logging.getLogger(__name__)

class StrategyConfig:
    """策略配置类（最小改进版）"""
    _leverage: ClassVar[int] = 3  # 改用受保护变量
    MACRO_COEFF: Final[float] = 1.0
    _lock = asyncio.Lock()  # 增加简单线程锁

    @classmethod
    async def load_from_db(cls):
        """从数据库加载配置（仅增加错误处理）"""
        try:
            async with cls._lock:
                cls._leverage = int(await get_setting('leverage', str(cls._leverage)))
                logger.info(f"策略配置加载成功 | 杠杆: {cls._leverage}x")
                return True
        except Exception as e:
            logger.error(f"加载配置失败: {e}", exc_info=True)
            return False

    @classmethod
    async def save_to_db(cls):
        """保存配置到数据库（仅增加错误处理）"""
        try:
            async with cls._lock:
                await set_setting('leverage', str(cls._leverage))
                logger.info(f"配置已保存 | 杠杆: {cls._leverage}x")
                return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}", exc_info=True)
            return False

    @classmethod
    def get_leverage(cls) -> int:
        """获取当前杠杆（线程安全）"""
        return cls._leverage

    @classmethod
    async def set_leverage(cls, value: int):
        """设置杠杆（基础校验）"""
        if not 1 <= value <= 10:
            raise ValueError("杠杆值必须1-10")
        async with cls._lock:
            cls._leverage = value
