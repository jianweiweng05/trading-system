import logging
import os
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import Optional

# Discord专属配置
class DiscordConfig(BaseSettings):
    model_config = {'env_file': '.env'}
    
    token: str = Field(..., 
        env="DISCORD_TOKEN",
        description="Discord Bot Token (从开发者门户获取)")
    channel_id: str = Field(...,
        env="DISCORD_CHANNEL_ID",
        description="交易通知频道ID (需开启开发者模式获取)")
    command_prefix: str = Field(default="!",
        env="DISCORD_PREFIX",
        description="Bot命令前缀")

# 核心业务配置
class TradingConfig(BaseSettings):
    model_config = {'env_file': '.env'}
    
    binance_api_key: str = Field(...,
        env="BINANCE_API_KEY",
        description="币安API Key")
    binance_api_secret: str = Field(...,
        env="BINANCE_API_SECRET",
        description="币安API Secret")
    tv_webhook_secret: str = Field(...,
        env="TV_WEBHOOK_SECRET",
        description="TradingView签名密钥")
    run_mode: str = Field(default="simulate",
        env="RUN_MODE",
        description="运行模式: simulate/live")

# 策略配置（从数据库加载）
class StrategyConfig:
    def __init__(self):
        self.leverage: int = 3
        self.macro_coefficient: float = 1.0
        self.resonance_coefficient: float = 1.0

    async def load_from_db(self):
        from database import get_setting
        self.leverage = int(await get_setting('leverage', self.leverage))
        # 其他策略参数...

# 全局配置聚合
class AppConfig:
    def __init__(self):
        self._discord = DiscordConfig()
        self._trading = TradingConfig()
        self._strategy = StrategyConfig()
        
        # 初始化日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self._setup_log_filter()

    def _setup_log_filter(self):
        class SensitiveFilter(logging.Filter):
            def __init__(self, configs):
                super().__init__()
                self.configs = configs
                
            def filter(self, record):
                if hasattr(record, 'msg'):
                    msg = str(record.msg)
                    for config in self.configs:
                        for field in config.__fields__:
                            value = getattr(config, field)
                            if value:
                                msg = msg.replace(value, '[REDACTED]')
                    record.msg = msg
                return True
        logging.getLogger().addFilter(SensitiveFilter([self._discord, self._trading]))

    async def initialize(self):
        """异步初始化方法"""
        await self._strategy.load_from_db()
        self._validate()
        logging.info(f"配置加载完成. 模式: {self._trading.run_mode}")

    def _validate(self):
        required_configs = {
            'Discord Token': self._discord.token,
            'Discord Channel ID': self._discord.channel_id,
            'Binance API Key': self._trading.binance_api_key,
            'Binance API Secret': self._trading.binance_api_secret,
            'Webhook Secret': self._trading.tv_webhook_secret
        }
        
        missing = [name for name, value in required_configs.items() if not value]
        if missing:
            raise ValueError(f"关键配置缺失: {', '.join(missing)}")

    # 属性访问代理
    def __getattr__(self, name):
        for config in [self._discord, self._trading, self._strategy]:
            if hasattr(config, name):
                return getattr(config, name)
        raise AttributeError(f"未知配置项: {name}")

# 全局单例
CONFIG = AppConfig()
