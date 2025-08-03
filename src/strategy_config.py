import logging
from typing import ClassVar, Final
from src.database import get_setting  # 修改导入路径

logger = logging.getLogger(__name__)

class StrategyConfig:
    """策略配置类"""
    leverage: ClassVar[int] = 3
    MACRO_COEFF: Final[float] = 1.0
    
    async def load_from_db(self):
        try:
            self.leverage = int(await get_setting('leverage', str(self.leverage)))
            logger.info(f"策略配置已更新: leverage={self.leverage}")
        except Exception as e:
            logger.error(f"加载策略配置失败: {e}")
