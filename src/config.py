# 文件: src/config.py (最终升级版)

import os
import logging
import asyncio
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import Optional

# 注意：我们需要异步地从数据库加载，所以 get_setting 需要在这里导入
# 但为了避免循环导入，我们只在函数内部导入它
# from database import get_setting

# 加载环境变量
load_dotenv()

class SystemConfig(BaseSettings):
    """
    配置模型 - 包含从环境变量加载的静态配置和从数据库加载的动态配置
    """
    # --- 1. 从环境变量加载的静态配置 ---
    binance_api_key: str = Field(..., env="BINANCE_API_KEY")
    binance_api_secret: str = Field(..., env="BINANCE_API_SECRET")
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    admin_chat_id: str = Field(..., env="ADMIN_CHAT_ID") # 已修正为 ADMIN_CHAT_ID
    deepseek_api_key: str = Field(..., env="DEEPSEEK_API_KEY")
    
    tv_webhook_secret: Optional[str] = Field(None, env="TV_WEBHOOK_SECRET")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    
    # --- 2. 将由数据库管理的动态配置 (提供安全的默认值) ---
    run_mode: str = "simulate"  # 默认值
    macro_coefficient: float = 1.0
    resonance_coefficient: float = 1.0
    
    # --- 3. 固定/计算得出的配置 ---
    base_leverage: int = 3  # 固定值
    
    @property
    def db_path(self) -> str:
        # 在Render平台使用持久化存储
        if "RENDER" in os.environ:
            base_path = "/var/data"
        else:
            # 本地运行时，存在项目根目录的 data 文件夹下
            base_path = os.path.join(os.getcwd(), "data")
        
        os.makedirs(base_path, exist_ok=True)
        return os.path.join(base_path, "trading_system_v7.db")
    
    # --- 异步加载方法 ---
    async def load_dynamic_settings(self):
        """从数据库加载或初始化动态设置，覆盖默认值"""
        # 延迟导入以避免循环依赖
        from database import get_setting

        self.run_mode = await get_setting('run_mode', self.run_mode)
        self.macro_coefficient = float(await get_setting('macro_coefficient', str(self.macro_coefficient)))
        self.resonance_coefficient = float(await get_setting('resonance_coefficient', str(self.resonance_coefficient)))
        logging.getLogger("Config").info(f"动态配置已从数据库加载。当前模式: {self.run_mode.upper()}")
        
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# --- 全局配置实例 ---
CONFIG: Optional[SystemConfig] = None

# --- 修改后的异步初始化函数 ---
async def init_config() -> SystemConfig:
    """
    异步初始化配置，先从 env 加载，再从 db 加载/覆盖
    """
    global CONFIG
    try:
        # 1. 先从环境变量加载静态配置
        config = SystemConfig()
        
        # 2. 设置日志 (使用静态配置中的 log_level)
        log_level = config.log_level.upper()
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 3. 再从数据库加载动态配置
        await config.load_dynamic_settings()
        
        CONFIG = config
        logging.getLogger("Config").info(f"✅ 配置加载成功。模式: {CONFIG.run_mode}, 杠杆: {CONFIG.base_leverage}x")
        return CONFIG
    except Exception as e:
        logging.critical(f"❌ 配置初始化失败: {str(e)}", exc_info=True)
        raise RuntimeError("关键配置错误，系统终止") from e
