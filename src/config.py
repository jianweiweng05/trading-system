# config.py 最终安全版本
import logging
from pydantic_settings import BaseSettings
from pydantic import Field, validator

class DiscordConfig(BaseSettings):
    token: str = Field(..., env="DISCORD_TOKEN")
    channel_id: str = Field(..., env="DISCORD_CHANNEL_ID")
    prefix: str = Field("!", env="DISCORD_PREFIX")

class TradingConfig(BaseSettings):
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET") 
    tv_webhook_secret: str = Field(..., env="TV_WEBHOOK_SECRET")
    run_mode: str = Field("simulate", env="RUN_MODE")

class AppConfig:
    def __init__(self):
        self.discord = DiscordConfig()
        self.trading = TradingConfig()
        
        # 安全验证
        self._validate()
        
        # 日志配置
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self._setup_log_filter()

    def _validate(self):
        required = {
            'Discord Token': self.discord.token,
            'Channel ID': self.discord.channel_id,
            'Binance API Key': self.trading.binance_api_key
        }
        if missing := [k for k,v in required.items() if not v]:
            raise ValueError(f"配置缺失: {missing}")

    def _setup_log_filter(self):
        class SecurityFilter(logging.Filter):
            def filter(self, record):
                if hasattr(record, 'msg'):
                    msg = str(record.msg)
                    msg = msg.replace(self.discord.token, '[REDACTED]')
                    msg = msg.replace(self.trading.binance_api_key, '[REDACTED]')
                    record.msg = msg
                return True
        logging.getLogger().addFilter(SecurityFilter())

CONFIG = AppConfig()
