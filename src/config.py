import logging
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import ClassVar

class DiscordConfig(BaseSettings):
    """Discord机器人配置（完整参数）"""
    token: str = Field(..., env="DISCORD_TOKEN",
        description="从Discord开发者门户获取的Bot Token")
    channel_id: str = Field(..., env="DISCORD_CHANNEL_ID",
        description="交易通知频道ID（需开启开发者模式获取）")
    command_prefix: str = Field("!", env="DISCORD_PREFIX",
        description="Bot命令前缀，默认!")
    
    @validator('token')
    def validate_token(cls, v):
        if not v.startswith('MT'):
            raise ValueError("无效的Discord Token格式")
        return v

class TradingConfig(BaseSettings):
    """交易核心配置（完整参数）""" 
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    tv_webhook_secret: str = Field(..., env="TV_WEBHOOK_SECRET")
    run_mode: str = Field("simulate", env="RUN_MODE")

class StrategyConfig:
    """策略配置（从数据库加载）"""
    leverage: ClassVar[int] = 3
    macro_coefficient: ClassVar[float] = 1.0
    
    async def load_from_db(self):
        from database import get_setting
        self.leverage = int(await get_setting('leverage', self.leverage))

class AppConfig:
    """全局配置聚合（完整功能）"""
    def __init__(self):
        self.discord = DiscordConfig()
        self.trading = TradingConfig()
        self.strategy = StrategyConfig()
        self._setup()

    def _setup(self):
        """初始化日志和验证"""
        self._validate()
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self._add_log_filter()

    def _validate(self):
        """完整配置验证"""
        if not all([
            self.discord.token,
            self.discord.channel_id,
            self.trading.binance_api_key,
            self.trading.tv_webhook_secret
        ]):
            raise ValueError("关键配置缺失")

    def _add_log_filter(self):
        """安全日志过滤（完整实现）"""
        class SecurityFilter(logging.Filter):
            def __init__(self, discord_cfg, trading_cfg):
                self.discord = discord_cfg
                self.trading = trading_cfg
            
            def filter(self, record):
                if hasattr(record, 'msg'):
                    msg = str(record.msg)
                    msg = msg.replace(self.discord.token, '[REDACTED]')
                    msg = msg.replace(self.trading.binance_api_key, '[REDACTED]')
                    record.msg = msg
                return True
        
        logging.getLogger().addFilter(
            SecurityFilter(self.discord, self.trading)
    
    async def initialize(self):
        """异步初始化（完整流程）"""
        await self.strategy.load_from_db()
        logging.info(f"配置加载完成. 模式: {self.trading.run_mode}")

# 全局单例（保持原有调用方式不变）
CONFIG = AppConfig()
