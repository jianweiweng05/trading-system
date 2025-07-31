import logging
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field, ValidationError, field_validator
from typing import Optional, Dict, Any, Callable
from enum import Enum

load_dotenv()

class RunMode(str, Enum):
    SIMULATE = "simulate"
    LIVE = "live"

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

# --- 1. 增强配置验证 ---
class StaticConfig(BaseSettings):
    admin_chat_id: str = Field(..., min_length=1, env="ADMIN_CHAT_ID")
    binance_api_key: str = Field(..., min_length=16, env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., min_length=16, env="BINANCE_API_SECRET")
    telegram_bot_token: str = Field(..., min_length=16, env="TELEGRAM_BOT_TOKEN")
    deepseek_api_key: str = Field(..., min_length=16, env="DEEPSEEK_API_KEY")
    tv_webhook_secret: Optional[str] = Field(None, env="TV_WEBHOOK_SECRET")
    log_level: LogLevel = Field(LogLevel.INFO, env="LOG_LEVEL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
        use_enum_values = True

class StrategyConfig:
    def __init__(self):
        self.run_mode: RunMode = RunMode.SIMULATE
        self.leverage: int = 3
        self.macro_coefficient: float = 1.0
        self.resonance_coefficient: float = 1.0
        self._validate_all()

    def _validate_all(self):
        """验证所有配置项"""
        self._validate_leverage()
        self._validate_coefficients()

    def _validate_leverage(self):
        """验证杠杆倍数"""
        if not (1 <= self.leverage <= 100):
            raise ValueError("杠杆倍数必须在1-100之间")

    def _validate_coefficients(self):
        """验证系数范围"""
        for name, value in [('macro_coefficient', self.macro_coefficient), 
                          ('resonance_coefficient', self.resonance_coefficient)]:
            if not (0.1 <= value <= 10.0):
                raise ValueError(f"{name}必须在0.1到10.0之间")

    def update_leverage(self, value: int):
        """更新杠杆倍数"""
        self.leverage = value
        self._validate_leverage()

    def update_coefficient(self, name: str, value: float):
        """更新系数"""
        if name not in ['macro_coefficient', 'resonance_coefficient']:
            raise AttributeError(f"无效的系数名称: {name}")
        setattr(self, name, value)
        self._validate_coefficients()

# --- 2. 增强错误处理 ---
CONFIG: Optional['AppConfig'] = None

class ConfigError(Exception):
    """基础配置错误"""
    pass

class ConfigValidationError(ConfigError):
    """配置验证错误"""
    pass

class ConfigUpdateError(ConfigError):
    """配置更新错误"""
    pass

class AppConfig:
    def __init__(self, static_config: StaticConfig, strategy_config: StrategyConfig):
        self._static = static_config
        self._strategy = strategy_config
        self._listeners: Dict[str, list] = {}

    def __getattr__(self, name):
        if hasattr(self._strategy, name):
            return getattr(self._strategy, name)
        if hasattr(self._static, name):
            return getattr(self._static, name)
        raise AttributeError(f"'AppConfig' object has no attribute '{name}'")
    
    def add_change_listener(self, key: str, callback: Callable[[str, Any], None]):
        """注册配置变更监听器"""
        if key not in self._listeners:
            self._listeners[key] = []
        self._listeners[key].append(callback)
    
    async def update_setting(self, key: str, value: Any):
        """更新配置并通知监听器"""
        from database import set_setting
        
        try:
            # 更新内存配置
            if hasattr(self._strategy, key):
                if key == 'leverage':
                    self._strategy.update_leverage(int(value))
                elif key in ['macro_coefficient', 'resonance_coefficient']:
                    self._strategy.update_coefficient(key, float(value))
                else:
                    setattr(self._strategy, key, value)
                
                # 持久化到数据库
                await set_setting(key, str(value))
                
                # 通知监听器
                if key in self._listeners:
                    for callback in self._listeners[key]:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(key, value)
                            else:
                                callback(key, value)
                        except Exception as e:
                            logging.error(f"配置变更通知失败: {e}")
            else:
                raise AttributeError(f"不可修改的配置项: {key}")
                
        except (ValueError, TypeError) as e:
            raise ConfigUpdateError(f"配置值无效: {e}")
        except Exception as e:
            raise ConfigUpdateError(f"配置更新失败: {e}")

# --- 3. 增强初始化错误处理 ---
async def init_config() -> AppConfig:
    global CONFIG
    if CONFIG:
        return CONFIG
        
    try:
        # 加载静态配置
        try:
            static_config = StaticConfig()
        except ValidationError as e:
            raise ConfigValidationError(f"配置验证失败: {e.errors()}")

        # 设置日志级别
        logging.basicConfig(
            level=static_config.log_level.value,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 创建策略配置
        strategy_config = StrategyConfig()
        CONFIG = AppConfig(static_config, strategy_config)
        
        # 加载数据库配置
        try:
            from database import get_setting
            run_mode = await get_setting('run_mode', strategy_config.run_mode.value)
            strategy_config.run_mode = RunMode(run_mode)
            
            macro = await get_setting('macro_coefficient', str(strategy_config.macro_coefficient))
            strategy_config.macro_coefficient = float(macro)
            
            resonance = await get_setting('resonance_coefficient', str(strategy_config.resonance_coefficient))
            strategy_config.resonance_coefficient = float(resonance)
            
        except ValueError as e:
            logging.warning(f"配置类型转换错误: {e}，使用默认值")
        except Exception as e:
            logging.warning(f"数据库配置加载失败: {e}，使用默认值")
        
        logging.getLogger("Config").info(
            f"✅ 配置加载成功。模式: {CONFIG.run_mode.value}, "
            f"杠杆: {CONFIG.leverage}x, "
            f"日志级别: {CONFIG.log_level.value}"
        )
        return CONFIG
        
    except ConfigError as e:
        logging.critical(str(e))
        raise
    except Exception as e:
        logging.critical(f"❌ 配置初始化失败: {e}", exc_info=True)
        raise ConfigError("关键配置错误") from e
