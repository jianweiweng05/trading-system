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
    
    # AI分析相关配置
    deepseek_api_key: str = Field(..., env="DEEPSEEK_API_KEY")
    
    # 新增的UI相关配置项（都有默认值）
    leverage: float = Field(default=5.0, env="LEVERAGE")
    firepower: float = Field(default=0.8, env="FIRESPOWER")
    allocation: str = Field(default="balanced", env="ALLOCATION")

    class Config:
        # 允许额外的字段，这样可以在不修改代码的情况下添加新的配置
        extra = "allow"
        # 从环境变量加载配置
        env_file = ".env"
        env_file_encoding = "utf-8"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 验证必要的配置项
        if not self.binance_api_key or not self.binance_api_secret:
            raise ValueError("币安API密钥未设置")
        if not self.discord_token:
            raise ValueError("Discord令牌未设置")
        if not self.tv_webhook_secret:
            raise ValueError("TradingView Webhook密钥未设置")
        if not self.discord_channel_id:
            raise ValueError("Discord频道ID未设置")
        if not self.deepseek_api_key:
            raise ValueError("DeepSeek API密钥未设置")

# 创建全局配置实例
CONFIG = Config()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
