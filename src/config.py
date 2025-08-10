
import logging
from typing import Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """基础配置类"""
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    discord_token: str = Field(..., env="DISCORD_TOKEN")
    tv_webhook_secret: str = Field(..., env="TV_WEBHOOK_SECRET")
    discord_channel_id: int = Field(..., env="DISCORD_CHANNEL_ID")
    discord_prefix: str = Field(default="!", env="DISCORD_PREFIX")
    run_mode: str = Field(default="simulate", env="RUN_MODE")
    
    deepseek_api_key: str = Field(..., env="DEEPSEEK_API_KEY")
    
    database_url: str = Field(default="sqlite+aiosqlite:///./data/trading_system_v7.db", env="DATABASE_URL")
    
    discord_alert_webhook: Optional[str] = Field(default=None, env="DISCORD_ALERT_WEBHOOK")
    discord_report_webhook: Optional[str] = Field(default=None, env="DISCORD_REPORT_WEBHOOK")

    alert_order_timeout: int = Field(default=30, env="ALERT_ORDER_TIMEOUT")
    alert_slippage_threshold: float = Field(default=0.5, env="ALERT_SLIPPAGE_THRESHOLD")
    alert_min_partial_fill: float = Field(default=0.2, env="ALERT_MIN_PARTIAL_FILL")
    alert_max_daily_loss: float = Field(default=5.0, env="ALERT_MAX_DAILY_LOSS")
    alert_api_retry_count: int = Field(default=3, env="ALERT_API_RETRY_COUNT")
    alert_cooldown_period: int = Field(default=300, env="ALERT_COOLDOWN_PERIOD")

    trading_engine: bool = Field(default=True, env="TRADING_ENGINE")

    default_btc_status: str = Field(default="neutral", env="DEFAULT_BTC_STATUS")
    default_eth_status: str = Field(default="neutral", env="DEFAULT_ETH_STATUS")
    status_update_interval: int = Field(default=3600, env="STATUS_UPDATE_INTERVAL")

    macro_cache_timeout: int = Field(default=300, env="MACRO_CACHE_TIMEOUT")
    db_retry_attempts: int = Field(default=3, env="DB_RETRY_ATTEMPTS")
    db_retry_delay: float = Field(default=1.0, env="DB_RETRY_DELAY")

    class Config:
        extra = "allow"
        env_file = ".env"
        env_file_encoding = "utf-8"

    # --- 【修改】移除了与 firepower 和 allocation 相关的验证器 ---
    
    @validator('alert_order_timeout')
    def validate_alert_order_timeout(cls, v):
        if not 10 <= v <= 300:
            raise ValueError("订单超时时间必须在10-300秒之间")
        return v

    @validator('alert_slippage_threshold')
    def validate_alert_slippage_threshold(cls, v):
        if not 0.1 <= v <= 2.0:
            raise ValueError("滑点阈值必须在0.1%-2.0%之间")
        return v

    @validator('alert_min_partial_fill')
    def validate_alert_min_partial_fill(cls, v):
        if not 0.1 <= v <= 0.9:
            raise ValueError("最小部分成交比例必须在10%-90%之间")
        return v

    @validator('alert_max_daily_loss')
    def validate_alert_max_daily_loss(cls, v):
        if not 1.0 <= v <= 20.0:
            raise ValueError("最大单日亏损必须在1%-20%之间")
        return v

    @validator('alert_api_retry_count')
    def validate_alert_api_retry_count(cls, v):
        if not 1 <= v <= 10:
            raise ValueError("API重试次数必须在1-10次之间")
        return v

    @validator('alert_cooldown_period')
    def validate_alert_cooldown_period(cls, v):
        if not 60 <= v <= 3600:
            raise ValueError("报警冷却时间必须在60-3600秒之间")
        return v

    @validator('default_btc_status', 'default_eth_status')
    def validate_default_status(cls, v):
        allowed_values = {"bullish", "bearish", "neutral"}
        if v not in allowed_values:
            raise ValueError(f"默认状态必须是以下之一: {allowed_values}")
        return v

    @validator('macro_cache_timeout')
    def validate_macro_cache_timeout(cls, v):
        if not 60 <= v <= 3600:
            raise ValueError("宏观状态缓存时间必须在60-3600秒之间")
        return v

    @validator('db_retry_attempts')
    def validate_db_retry_attempts(cls, v):
        if not 1 <= v <= 10:
            raise ValueError("数据库重试次数必须在1-10次之间")
        return v

    @validator('db_retry_delay')
    def validate_db_retry_delay(cls, v):
        if not 0.1 <= v <= 10.0:
            raise ValueError("数据库重试间隔必须在0.1-10秒之间")
        return v

# 创建全局配置实例
CONFIG = Settings()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 添加启动时的调试日志
logger.info("--- [Config Debug] ---")
logger.info(f"DISCORD_ALERT_WEBHOOK loaded as: {CONFIG.discord_alert_webhook}")
logger.info(f"Type of DISCORD_ALERT_WEBHOOK is: {type(CONFIG.discord_alert_webhook)}")
logger.info("--- [End Config Debug] ---")
