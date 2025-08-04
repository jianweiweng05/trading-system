import logging
from decimal import Decimal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from typing import Literal

class Config(BaseSettings):
    """基础配置类"""
    # API配置
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    discord_token: str = Field(..., env="DISCORD_TOKEN")
    tv_webhook_secret: str = Field(..., env="TV_WEBHOOK_SECRET")
    
    # Discord配置
    discord_channel_id: int = Field(..., env="DISCORD_CHANNEL_ID")
    discord_prefix: str = Field(default="!", env="DISCORD_PREFIX")
    discord_alert_webhook: str = Field(default="", env="DISCORD_ALERT_WEBHOOK")
    discord_report_webhook: str = Field(default="", env="DISCORD_REPORT_WEBHOOK")
    
    # 运行模式
    run_mode: Literal["simulate", "live"] = Field(default="simulate", env="RUN_MODE")
    
    # AI分析相关配置
    deepseek_api_key: str = Field(..., env="DEEPSEEK_API_KEY")
    
    # 交易参数
    leverage: Decimal = Field(default=Decimal("5.0"), env="LEVERAGE")
    firepower: Decimal = Field(default=Decimal("0.8"), env="FIRESPOWER")
    allocation: Literal["conservative", "balanced", "aggressive"] = Field(
        default="balanced", 
        env="ALLOCATION"
    )
    
    # 数据库配置
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/trading_system_v7.db", 
        env="DATABASE_URL"
    )
    database_pool_size: int = Field(default=5, env="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, env="DATABASE_MAX_OVERFLOW")

    class Config:
        extra = "allow"
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "TRADING_"

    @field_validator('leverage')
    def validate_leverage(cls, v):
        if not (1 <= v <= 125):
            raise ValueError("杠杆必须在1-125之间")
        return v

    @field_validator('firepower')
    def validate_firepower(cls, v):
        if not (0 < v <= 1):
            raise ValueError("火力值必须在0-1之间")
        return v

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 验证必要的配置项
        required_fields = [
            'binance_api_key',
            'binance_api_secret',
            'discord_token',
            'tv_webhook_secret',
            'discord_channel_id',
            'deepseek_api_key'
        ]
        
        for field in required_fields:
            if not getattr(self, field):
                raise ValueError(f"{field} 未设置")

def setup_logging():
    """设置日志配置"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('trading.log', encoding='utf-8')
        ]
    )
    return logging.getLogger(__name__)

# 创建全局配置实例
CONFIG = Config()

# 配置日志
logger = setup_logging()
