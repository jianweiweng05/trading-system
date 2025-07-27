"""
src 包初始化文件
量化交易系统核心包
版本: v6.2
"""

import os
import sys
import logging
from datetime import datetime

# ================= 包级配置 =================
__version__ = "6.2.0"
__author__ = "Quant Team"
__license__ = "Proprietary"

# 设置包级日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 添加当前目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ================= 包级初始化 =================
def initialize_package():
    """初始化量化交易包"""
    logger.info(f"初始化量化交易系统 v{__version__}")
    logger.info(f"初始化时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查环境变量
    required_envs = [
        'TELEGRAM_BOT_TOKEN', 
        'TV_WEBHOOK_SECRET',
        'BINANCE_API_KEY',
        'BINANCE_API_SECRET'
    ]
    
    missing = [var for var in required_envs if var not in os.environ]
    if missing:
        logger.warning(f"缺少环境变量: {', '.join(missing)}")
    
    logger.info("包初始化完成")

# 自动执行初始化
initialize_package()

# ================= 包级工具函数 =================
def get_system_info() -> dict:
    """获取系统信息"""
    return {
        "name": "Quant Trading System",
        "version": __version__,
        "author": __author__,
        "license": __license__,
        "modules": [
            "config", "database", "core_logic", 
            "broker", "telegram_bot", "main"
        ]
    }

# ================= 包级异常 =================
class TradingSystemError(Exception):
    """量化交易系统基础异常"""
    pass

class ConfigurationError(TradingSystemError):
    """配置错误异常"""
    pass

class ExchangeConnectionError(TradingSystemError):
    """交易所连接异常"""
    pass

# ================= 包结束信息 =================
logger.info(f"量化交易包 v{__version__} 加载完成")
