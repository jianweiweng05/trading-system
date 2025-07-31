import logging
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

load_dotenv()

# 模块级变量
CONFIG: Optional['AppConfig'] = None

class StaticConfig(BaseSettings):
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
    run_mode: str = "simulate"
    leverage: int = 3
    macro_coefficient: float = 1.0
    resonance_coefficient: float = 1.0

    async def load_from_db(self):
        from database import get_setting
        try:
            self.run_mode = await get_setting('run_mode', self.run_mode)
            self.macro_coefficient = float(await get_setting('macro_coefficient', str(self.macro_coefficient)))
            self.resonance_coefficient = float(await get_setting('resonance_coefficient', str(self.resonance_coefficient)))
        except Exception as e:
            logging.warning(f"数据库配置加载失败: {str(e)}，使用默认值")

class AppConfig:
    def __init__(self, static_config: StaticConfig, strategy_config: StrategyConfig):
        self._static = static_config
        self._strategy = strategy_config

    def __getattr__(self, name):
        if hasattr(self._strategy, name):
            return getattr(self._strategy, name)
        if hasattr(self._static, name):
            return getattr(self._static, name)
        raise AttributeError(f"'AppConfig' object has no attribute '{name}'")

async def init_config() -> AppConfig:
    global CONFIG
    if CONFIG:
        return CONFIG
        
    try:
        # 1. 加载静态配置
        static_config = StaticConfig()
        
        # 2. 设置日志级别
        log_level = static_config.log_level.upper()
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 3. 创建策略配置
        strategy_config = StrategyConfig()
        
        # 4. 创建最终配置
        CONFIG = AppConfig(static_config, strategy_config)
        
        # 5. 尝试加载数据库配置
        try:
            await strategy_config.load_from_db()
        except Exception as e:
            logging.warning(f"数据库配置加载失败: {str(e)}，使用默认值")
        
        logging.getLogger("Config").info(f"✅ 配置加载成功。模式: {CONFIG.run_mode}")
        return CONFIG
        
    except Exception as e:
        logging.critical(f"❌ 配置初始化失败: {str(e)}", exc_info=True)
        raise RuntimeError("关键配置错误") from e
