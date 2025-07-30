import os
import logging
from dotenv import load_dotenv
from pydantic import BaseSettings, Field, validator
from typing import Optional

# 加载环境变量
load_dotenv()

class SystemConfig(BaseSettings):
    """
    使用Pydantic进行结构化、自验证的配置管理
    """
    # 必填参数
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    admin_chat_id: str = Field(..., env="CHAT_ID")
    
    # 可选参数
    tv_webhook_secret: Optional[str] = Field(None, env="TV_WEBHOOK_SECRET")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    run_mode: str = Field("live", env="RUN_MODE")
    base_leverage: int = Field(3, env="BASE_LEVERAGE")
    
    # 自动计算的路径属性 (修复权限问题)
    @property
    def db_path(self) -> str:
        # 在Render平台使用项目目录下的data文件夹
        if "RENDER" in os.environ:
            base_path = os.path.join(os.getcwd(), "data")
        else:
            base_path = "."
        
        # 确保目录存在
        os.makedirs(base_path, exist_ok=True)
        db_file = os.path.join(base_path, "trading_system_v7.db")
        return db_file
    
    # 参数验证器
    @validator("run_mode")
    def validate_run_mode(cls, v):
        if v.lower() not in ["live", "simulate"]:
            raise ValueError(f"无效的运行模式: {v}. 必须是 'live' 或 'simulate'")
        return v.lower()
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# 初始化配置函数
def init_config() -> SystemConfig:
    try:
        config = SystemConfig()
        
        # 设置日志级别
        log_level = config.log_level.upper()
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        logging.getLogger("Config").info(f"配置加载成功. 模式: {config.run_mode}, 杠杆: {config.base_leverage}x")
        return config
    except Exception as e:
        logging.critical(f"配置初始化失败: {str(e)}")
        raise RuntimeError("关键配置错误，系统终止") from e

# 创建全局唯一的配置实例
CONFIG = init_config()
