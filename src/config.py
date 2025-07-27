import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 获取当前文件所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据库配置
DATABASE_PATH = os.path.join(BASE_DIR, "trading_system.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH}"

# 其他配置
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE_LEVERAGE = int(os.getenv("BASE_LEVERAGE", "10"))
INITIAL_SIM_BALANCE = float(os.getenv("INITIAL_SIM_BALANCE", "10000.0"))
RUN_MODE = os.getenv("RUN_MODE", "simulate")
DEBUG_MODE = os.getenv("DEBUG_MODE", "False") == "True"
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG_MODE else "INFO")
