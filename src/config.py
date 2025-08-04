import logging
from pydantic import Field
from pydantic_settings import BaseSettings

class Config(BaseSettings):
    """基础配置类"""
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    discord_token: str = Field(..., env="DISCORD_TOKEN")
    tv_webhook_secret: str = Field(..., env="TV_WEBHOOK_SECRET")
    discord_channel_id: str = Field(..., env="DISCORD_CHANNEL_ID")
    discord_prefix: str = Field(default="!", env="DISCORD_PREFIX")
    run_mode: str = Field(default="simulate", env="RUN_MODE")
    
    # 新增的UI相关配置项（都有默认值）
    leverage: float = Field(default=5.0, env="LEVERAGE")
    firepower: float = Field(default=0.8, env="FIRESPOWER")
    allocation: str = Field(default="balanced", env="ALLOCATION")

    class Config:
        extra = "forbid"

# 创建全局配置实例
CONFIG = Config()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
