import os
import logging

# --- 1. 日志配置 ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Config")

# --- 2. 环境变量加载函数 ---
def get_env(key: str, required: bool = True, default=None):
    """安全地从环境中获取变量。"""
    val = os.getenv(key, default)
    if required and not val:
        logger.error(f"FATAL: 缺失必需的环境变量: {key}")
        raise RuntimeError(f"FATAL: Missing required environment var: {key}")
    return val

# --- 3. 加载所有API密钥和秘密 ---
API_KEY = get_env("BINANCE_API_KEY")
API_SECRET = get_env("BINANCE_API_SECRET")
TELEGRAM_TOKEN = get_env("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = get_env("CHAT_ID")
TV_WEBHOOK_SECRET = get_env("TV_WEBHOOK_SECRET", required=False)

# --- 4. 核心系统参数 ---
DB_BASE_PATH = "/var/data/db" if "RENDER" in os.environ else "."
DB_FILE = os.path.join(DB_BASE_PATH, "trading_system_v7.db")
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

RUN_MODE = get_env("RUN_MODE", default="live")
BASE_LEVERAGE = int(get_env("BASE_LEVERAGE", default="3"))

logger.info(f"配置加载成功. 模式: {RUN_MODE}, 杠杆: {BASE_LEVERAGE}x")