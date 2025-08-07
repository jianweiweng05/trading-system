mport logging
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

    # 报警系统配置
    alert_order_timeout: int = Field(default=30, env="ALERT_ORDER_TIMEOUT")  # 订单超时时间（秒）
    alert_slippage_threshold: float = Field(default=0.5, env="ALERT_SLIPPAGE_THRESHOLD")  # 滑点阈值（百分比）
    alert_min_partial_fill: float = Field(default=0.2, env="ALERT_MIN_PARTIAL_FILL")  # 最小部分成交比例
    alert_max_daily_loss: float = Field(default=5.0, env="ALERT_MAX_DAILY_LOSS")  # 最大单日亏损（百分比）
    alert_api_retry_count: int = Field(default=3, env="ALERT_API_RETRY_COUNT")  # API重试次数
    alert_cooldown_period: int = Field(default=300, env="ALERT_COOLDOWN_PERIOD")  # 报警冷却时间（秒）

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

    @validator('alert_order_timeout')
    def validate_alert_order_timeout(cls, v):
        """验证订单超时时间"""
        if not 10 <= v <= 300:
            raise ValueError("订单超时时间必须在10-300秒之间")
        return v

    @validator('alert_slippage_threshold')
    def validate_alert_slippage_threshold(cls, v):
        """验证滑点阈值"""
        if not 0.1 <= v <= 2.0:
            raise ValueError("滑点阈值必须在0.1%-2.0%之间")
        return v

    @validator('alert_min_partial_fill')
    def validate_alert_min_partial_fill(cls, v):
        """验证最小部分成交比例"""
        if not 0.1 <= v <= 0.9:
            raise ValueError("最小部分成交比例必须在10%-90%之间")
        return v

    @validator('alert_max_daily_loss')
    def validate_alert_max_daily_loss(cls, v):
        """验证最大单日亏损"""
        if not 1.0 <= v <= 20.0:
            raise ValueError("最大单日亏损必须在1%-20%之间")
        return v

    @validator('alert_api_retry_count')
    def validate_alert_api_retry_count(cls, v):
        """验证API重试次数"""
        if not 1 <= v <= 10:
            raise ValueError("API重试次数必须在1-10次之间")
        return v

    @validator('alert_cooldown_period')
    def validate_alert_cooldown_period(cls, v):
        """验证报警冷却时间"""
        if not 60 <= v <= 3600:
            raise ValueError("报警冷却时间必须在60-3600秒之间")
        return v

# 创建全局配置实例
CONFIG = Config()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
