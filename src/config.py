# 文件: src/config.py (最终版)

import logging
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

# 加载 .env 文件 (主要用于本地开发)
load_dotenv()

# --- 模块级变量 ---
# 将 CONFIG 声明为全局变量，稍后由异步的 init_config 函数填充
CONFIG: Optional['AppConfig'] = None

# --- 配置模型 ---
class StaticConfig(BaseSettings):
    """
    从环境变量加载的、固定不变的敏感配置
    """
    admin_chat_id: str = Field(..., env="ADMIN_CHAT_ID")
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    deepseek_api_key: str = Field(..., env="DEEPSEEK_API_KEY")
    
    tv_webhook_secret: Optional[str] = Field(None, env="TV_WEBHOOK_SECRET")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

class StrategyConfig:
    """
    从数据库加载的、可通过Telegram动态修改的策略配置
    """
    # 这些是代码中定义的、安全的默认值
    run_mode: str = "simulate"
    leverage: int = 3  # 固定值，不从数据库读取
    macro_coefficient: float = 1.0
    resonance_coefficient: float = 1.0

    async def load_from_db(self):
        """
        异步地从数据库加载或使用默认值初始化配置项
        """
        # 延迟导入以避免在模块加载时产生循环依赖
        from database import get_setting

        self.run_mode = await get_setting('run_mode', self.run_mode)
        self.macro_coefficient = float(await get_setting('macro_coefficient', str(self.macro_coefficient)))
        self.resonance_coefficient = float(await get_setting('resonance_coefficient', str(self.resonance_coefficient)))
        logging.getLogger("Config").info(f"动态策略配置已从数据库加载/初始化。当前模式: {self.run_mode.upper()}")

class AppConfig:
    """
    合并后的最终配置对象，为程序提供统一的访问接口
    """
    def __init__(self, static_config: StaticConfig, strategy_config: StrategyConfig):
        self._static = static_config
        self._strategy = strategy_config

    def __getattr__(self, name):
        """
        提供透明的属性访问，优先从策略配置中获取，再从静态配置中获取
        """
        # 优先从 _strategy 配置中获取
        if hasattr(self._strategy, name):
            return getattr(self._strategy, name)
        # 否则从 _static 配置中获取
        if hasattr(self._static, name):
            return getattr(self._static, name)
        raise AttributeError(f"'AppConfig' object has no attribute '{name}'")

    @property
    def db_path(self) -> str:
        """
        计算数据库路径，确保数据持久化
        """
        # 在Render平台使用持久化存储
        if "RENDER" in os.environ:
            base_path = "/var/data"
        else:
            # 本地运行时，存在项目根目录的 data 文件夹下
            base_path = os.path.join(os.getcwd(), "data")
        
        # 确保目录存在
        os.makedirs(base_path, exist_ok=True)
        return os.path.join(base_path, "trading_system_v7.db")

# --- 初始化函数 ---
async def init_config() -> AppConfig:
    """
    异步初始化并返回全局配置对象
    """
    global CONFIG
    if CONFIG:
        return CONFIG
        
    try:
        # 1. 先从环境变量加载静态配置
        static_config = StaticConfig()
        
        # 2. 设置日志级别
        log_level = static_config.log_level.upper()
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 3. 创建策略配置实例
        strategy_config = StrategyConfig()
        
        # 4. 创建临时的 AppConfig 以便数据库模块能访问 db_path
        CONFIG = AppConfig(static_config, strategy_config)
        
        # 5. 从数据库加载动态配置 (现在可以安全地访问数据库了)
        await strategy_config.load_from_db()
        
        logging.getLogger("Config").info(f"✅ 配置加载成功。模式: {CONFIG.run_mode}, 杠杆: {CONFIG.leverage}x")
        return CONFIG
        
    except Exception as e:
        logging.critical(f"❌ 配置初始化失败: {str(e)}", exc_info=True)
        raise RuntimeError("关键配置错误，系统终止") from e
