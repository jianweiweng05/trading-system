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
    async def load_from_db(cls, max_retries: int = 3) -> bool:
        """
        从数据库加载配置（仅增加错误处理）
        
        Returns:
            bool: 加载是否成功
        """
        for attempt in range(max_retries):
            try:
                async with cls._lock:
                    cls._leverage = int(await get_setting('leverage', str(cls._leverage)))
                    logger.info(f"策略配置加载成功 | 杠杆: {cls._leverage}x")
                    return True
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"加载配置失败(最终尝试): {e}", exc_info=True)
                    return False
                logger.warning(f"加载配置失败(重试 {attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(1)

    @classmethod
    async def save_to_db(cls) -> bool:
        """
        保存配置到数据库（仅增加错误处理）
        
        Returns:
            bool: 保存是否成功
        """
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
        """
        获取当前杠杆（线程安全）
        
        Returns:
            int: 当前杠杆值
        """
        return cls._leverage

    @classmethod
    async def set_leverage(cls, value: int) -> None:
        """
        设置杠杆（基础校验）
        
        Args:
            value: 新的杠杆值，范围1-10
            
        Raises:
            ValueError: 当杠杆值不在1-10范围内时
        """
        if not isinstance(value, int):
            raise TypeError(f"杠杆值必须是整数，得到: {type(value)}")
        if not 1 <= value <= 10:
            raise ValueError(f"杠杆值必须1-10，得到: {value}")
        async with cls._lock:
            old_value = cls._leverage
            cls._leverage = value
            logger.info(f"杠杆值已更新: {old_value} -> {value}")  # 增加变更日志
