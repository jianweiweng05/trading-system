import logging
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

load_dotenv()

# 配置类
class StaticConfig(BaseSettings):
    admin_chat_id: str = Field(..., env="ADMIN_CHAT_ID")
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    deepseek_api_key: str = Field(..., env="DEEPSEEK_API_KEY")
    tv_webhook_secret: Optional[str] = Field(None, env="TV_WEBHOOK_SECRET")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    
    # Discord配置
    discord_token: str = Field(..., env="DISCORD_TOKEN")
    discord_channel_id: str = Field(..., env="DISCORD_CHANNEL_ID")
    discord_prefix: str = Field(default="!")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

class StrategyConfig:
    def __init__(self):
        self.run_mode: str = "simulate"
        self.leverage: int = 3
        self.macro_coefficient: float = 1.0
        self.resonance_coefficient: float = 1.0

    async def load_from_db(self):
        from database import get_setting
        try:
            self.run_mode = await get_setting('run_mode', self.run_mode)
            self.macro_coefficient = float(await get_setting('macro_coefficient', str(self.macro_coefficient)))
            self.resonance_coefficient = float(await get_setting('resonance_coefficient', str(self.resonance_coefficient)))
        except Exception as e:
            logging.warning(f"配置加载失败，使用默认值: {e}")

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

# 全局配置实例
CONFIG: Optional[AppConfig] = None

async def init_config() -> AppConfig:
    global CONFIG
    if CONFIG:
        return CONFIG
        
    try:
        # 加载静态配置
        static_config = StaticConfig()
        
        # 设置日志级别
        logging.basicConfig(
            level=static_config.log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 创建策略配置
        strategy_config = StrategyConfig()
        CONFIG = AppConfig(static_config, strategy_config)
        
        # 从数据库加载配置
        await strategy_config.load_from_db()
        
        # 验证配置是否正确初始化
        if not CONFIG.binance_api_key or not CONFIG.binance_api_secret:
            raise ValueError("关键配置缺失：API密钥未设置")
        
        logging.info(f"配置加载成功 - 模式: {CONFIG.run_mode}")
        return CONFIG
        
    except Exception as e:
        logging.critical(f"配置初始化失败: {e}")
        raise RuntimeError("配置错误") from e
