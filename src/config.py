import logging
import os
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, ClassVar

# Discord专属配置
class DiscordConfig(BaseSettings):
    token: str = Field(..., 
        env="DISCORD_TOKEN",
        description="Discord Bot Token")
    channel_id: str = Field(...,
        env="DISCORD_CHANNEL_ID",
        description="交易通知频道ID")
    command_prefix: str = Field(default="!",
        env="DISCORD_PREFIX",
        description="Bot命令前缀")

# 核心业务配置
class TradingConfig(BaseSettings):
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
    leverage: ClassVar[int] = 3
    macro_coefficient: ClassVar[float] = 1.0
    resonance_coefficient: ClassVar[float] = 1.0

    async def load_from_db(self):
        from database import get_setting
        self.leverage = int(await get_setting('leverage', self.leverage))

# 全局配置聚合
class AppConfig:
    def __init__(self):
        self._discord = DiscordConfig()
        self._trading = TradingConfig()
        self._strategy = StrategyConfig()
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self._setup_log_filter()

    def _setup_log_filter(self):
        class SensitiveFilter(logging.Filter):
            def __init__(self, discord_config, trading_config):
                super().__init__()
                self.discord = discord_config
                self.trading = trading_config
            
            def filter(self, record):
                if hasattr(record, 'msg'):
                    msg = str(record.msg)
                    # Discord敏感信息
                    for field in DiscordConfig.__fields__:
                        msg = msg.replace(getattr(self.discord, field), '[REDACTED]')
                    # 交易敏感信息
                    for field in ['binance_api_key', 'binance_api_secret', 'tv_webhook_secret']:
                        msg = msg.replace(getattr(self.trading, field), '[REDACTED]')
                    record.msg = msg
                return True
                
        logging.getLogger().addFilter(
            SensitiveFilter(self._discord, self._trading)
        )

    async def initialize(self):
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

    def __getattr__(self, name):
        for config in [self._discord, self._trading, self._strategy]:
            if hasattr(config, name):
                return getattr(config, name)
        raise AttributeError(f"未知配置项: {name}")

# 全局单例
CONFIG = AppConfig()
