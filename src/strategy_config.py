import logging
from typing import ClassVar, Final
from src.database import get_setting

logger = logging.getLogger(__name__)

class StrategyConfig:
    """策略配置类"""
    leverage: ClassVar[int] = 3
    MACRO_COEFF: Final[float] = 1.0
    
    @classmethod
    async def load_from_db(cls):
        """从数据库加载配置"""
        try:
            leverage_value = await get_setting('leverage', str(cls.leverage))
            cls.leverage = int(leverage_value)
            logger.info(f"策略配置已更新: leverage={cls.leverage}")
            return True
        except ValueError as e:
            logger.error(f"杠杆系数格式错误: {e}")
            return False
        except Exception as e:
            logger.error(f"加载策略配置失败: {e}")
            return False
    
    @classmethod
    async def save_to_db(cls):
        """保存配置到数据库"""
        try:
            from src.database import set_setting
            await set_setting('leverage', str(cls.leverage))
            logger.info(f"策略配置已保存: leverage={cls.leverage}")
            return True
        except Exception as e:
            logger.error(f"保存策略配置失败: {e}")
            return False
