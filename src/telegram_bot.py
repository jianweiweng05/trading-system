# 文件: src/telegram_bot.py (兼容最终版)

import logging
from functools import wraps
from fastapi import FastAPI
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

# 严格使用CONFIG作为唯一配置源
from config import CONFIG
from system_state import SystemState
from database import get_setting, set_setting, get_open_positions

logger = logging.getLogger(__name__)

# --- 1. 静态界面元素（无需配置）---
MAIN_KEYBOARD = [
    ["📊 系统状态", "⚙️ 设置"],
    ["📈 当前持仓", "📋 操作日志"],
]
REPLY_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

# --- 2. 核心命令处理器 ---
def execute_safe(func):
    """权限检查装饰器（完全依赖CONFIG）"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        # 安全访问CONFIG
        if not CONFIG or not hasattr(CONFIG, 'admin_chat_id'):
            await update.message.reply_text("⚠️ 系统配置加载中...")
            return

        if str(update.effective_user.id) != CONFIG.admin_chat_id:
            await update.message.reply_text("❌ 权限不足")
            return
            
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"命令执行异常: {e}", exc_info=True)
            await update.message.reply_text("⚠️ 操作失败，请查看日志")
    return wrapper

# [所有命令处理器保持原样，仅内部使用CONFIG]
# ... start_command, status_command 等保持不变 ...

# --- 3. 服务管理接口 ---
async def start_bot(app_instance: FastAPI):
    """启动Telegram服务（兼容原有接口）"""
    logger.info(f"启动Telegram Bot (模式: {getattr(CONFIG, 'run_mode', 'UNKNOWN')})")
    application = app_instance.state.telegram_app
    
    # 注册处理器
    handlers = [
        CommandHandler("start", start_command),
        CommandHandler("status", status_command),
        # ... 其他处理器 ...
    ]
    
    for handler in handlers:
        application.add_handler(handler)
    
    # 初始化服务
    await application.initialize()
    await application.start()
    
    # 安全启动轮询
    polling_timeout = getattr(CONFIG, 'polling_timeout', 10)
    await application.updater.start_polling(
        drop_pending_updates=True,
        timeout=polling_timeout
    )
    logger.info("Telegram服务已就绪")

async def stop_bot(app_instance: FastAPI):
    """停止Telegram服务（兼容原有接口）"""
    logger.info("停止Telegram服务...")
    application = app_instance.state.telegram_app
    
    try:
        if hasattr(application, 'updater') and application.updater.running:
            await application.updater.stop()
        
        await application.stop()
        await application.shutdown()
        logger.info("服务已安全停止")
    except Exception as e:
        logger.error(f"停止服务时出错: {e}")
        raise
