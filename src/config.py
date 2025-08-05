import logging
from typing import Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings

class Config(BaseSettings):
    """基础配置类"""
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    discord_token: str = Field(..., env="DISCORD_TOKEN")
    tv_webhook_secret: str = Field(..., env="TV_WEBHOOK_SECRET")
    discord_channel_id: int = Field(..., env="DISCORD_CHANNEL_ID")
    discord_prefix: str = Field(default="!", env="DISCORD_PREFIX")
    run_mode: str = Field(default="simulate", env="RUN_MODE")
    
    # AI分析相关配置
    deepseek_api_key: str = Field(..., env="DEEPSEEK_API_KEY")
    
    # 新增的UI相关配置项（都有默认值）
    leverage: float = Field(default=5.0, env="LEVERAGE")
    firepower: float = Field(default=0.8, env="FIRESPOWER")
    allocation: str = Field(default="balanced", env="ALLOCATION")
    
    # 数据库配置
    database_url: str = Field(default="sqlite+aiosqlite:///./data/trading_system_v7.db", env="DATABASE_URL")
    
    # Discord Webhook配置
    discord_alert_webhook: Optional[str] = Field(default="", env="DISCORD_ALERT_WEBHOOK")
    discord_report_webhook: Optional[str] = Field(default="", env="DISCORD_REPORT_WEBHOOK")

    class Config:
        # 允许额外的字段，这样可以在不修改代码的情况下添加新的配置
        extra = "allow"
        # 从环境变量加载配置
        env_file = ".env"
        env_file_encoding = "utf-8"

    @validator('binance_api_key', 'binance_api_secret', 'discord_token', 
               'tv_webhook_secret', 'deepseek_api_key')
    def validate_required_fields(cls, v):
        """验证必填字段"""
        if not v:
            raise ValueError("此字段为必填项")
        return v

    @validator('leverage')
    def validate_leverage(cls, v):
        """验证杠杆值范围"""
        if not 1 <= v <= 10:
            raise ValueError("杠杆值必须在1-10之间")
        return v

    @validator('firepower')
    def validate_firepower(cls, v):
        """验证火力值范围"""
        if not 0 < v <= 1:
            raise ValueError("火力值必须在0-1之间")
        return v

    @validator('allocation')
    def validate_allocation(cls, v):
        """验证分配模式"""
        allowed_values = {"conservative", "balanced", "aggressive"}
        if v not in allowed_values:
            raise ValueError(f"分配模式必须是以下之一: {allowed_values}")
        return v

# 创建全局配置实例
CONFIG = Config()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
