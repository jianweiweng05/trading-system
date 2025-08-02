import logging
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings
from typing import ClassVar, Final

class DiscordConfig(BaseSettings):
    model_config = {'env_file': '.env'}
    
    token: str = Field(...,
        description="Discord Bot Token (必须以MT/OT开头)",
        min_length=59, max_length=72)
    channel_id: str = Field(...,
        description="数字格式的频道ID",
        pattern=r'^\d+$')
    command_prefix: str = Field("!",
        description="命令前缀符号")

    @field_validator('token')
    @classmethod
    def validate_token(cls, v):
        if not v.startswith(('MT', 'OT')):
            raise ValueError("无效的Discord Token格式")
        return v

class TradingConfig(BaseSettings):
    model_config = {'env_file': '.env'}
    
    binance_api_key: str = Field(...,
        description="64位字母数字组合",
        min_length=64, max_length=64)
    binance_api_secret: str = Field(...,
        description="大小写敏感的API密钥")
    tv_webhook_secret: str = Field(...,
        description="TradingView签名密钥")
    run_mode: str = Field("simulate",
        description="运行模式: simulate/live")

    @field_validator('binance_api_key')
    @classmethod
    def validate_api_key(cls, v):
        if not v.isalnum():
            raise ValueError("API Key必须为字母数字组合")
        return v

class StrategyConfig:
    leverage: ClassVar[int] = 3
    MACRO_COEFF: Final[float] = 1.0
    
    async def load_from_db(self):
        from database import get_setting
        self.leverage = int(await get_setting('leverage', self.leverage))

class AppConfig:
    def __init__(self):
        self._discord = DiscordConfig()
        self._trading = TradingConfig()
        self._strategy = StrategyConfig()
        self._setup()

    def _setup(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S %Z'
        )
        self._add_log_filter()
        self._validate()

    def _add_log_filter(self):
        class SecurityFilter(logging.Filter):
            def __init__(self, discord_config, trading_config):
                super().__init__()
                self.discord_config = discord_config
                self.trading_config = trading_config
                
            def filter(self, record):
                if hasattr(record, 'msg'):
                    msg = str(record.msg)
                    secrets = {
                        'token': self.discord_config.token,
                        'api_key': self.trading_config.binance_api_key,
                        'webhook': self.trading_config.tv_webhook_secret
                    }
                    for k, v in secrets.items():
                        msg = msg.replace(v, f'[REDACTED_{k.upper()}]')
                    record.msg = msg
                return True
        logging.getLogger().addFilter(SecurityFilter(self._discord, self._trading))

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

    async def initialize(self):
        await self._strategy.load_from_db()
        logging.info("系统配置初始化完成")

    def __getattr__(self, name):
        for config in [self._discord, self._trading, self._strategy]:
            if hasattr(config, name):
                return getattr(config, name)
        raise AttributeError(f"无效配置项: {name}")

CONFIG: AppConfig = AppConfig()
