import logging
import os
import sys
import asyncio
from functools import wraps
from fastapi import FastAPI
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode
import telegram.error

# 导入共享的组件
from config import CONFIG
from system_state import SystemState
from database import get_open_positions

logger = logging.getLogger(__name__)

# ... 其他代码保持不变 ...

async def start_bot(app_instance: FastAPI):
    """
    在FastAPI的生命周期中，安全地启动Telegram Bot
    """
    logger.info("正在启动Telegram Bot...")
    
    # 检查是否已创建Telegram应用实例
    if not hasattr(app_instance.state, 'telegram_app'):
        logger.error("无法启动Telegram Bot: telegram_app 未初始化")
        return
    
    application = app_instance.state.telegram_app
    
    # 修复回调函数参数不匹配问题
    SystemState.set_alert_callback(lambda old, new, app: state_change_alert(old, new, application))
    
    # 主命令
    application.add_handler(CommandHandler("start", start_command))
    # ... 其他处理器保持不变 ...
    
    await application.initialize()
    await application.start()
    
    # ===== Render 专用修复方案 =====
    # 方法1: 使用进程ID作为唯一标识
    pid = os.getpid()
    logger.info(f"当前进程ID: {pid}")
    
    # 方法2: 增加启动延迟 (Render环境专用)
    logger.info("等待5秒，确保之前的实例完全关闭...")
    await asyncio.sleep(5)
    
    # 方法3: 强制删除Webhook (即使不使用)
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("已强制删除任何可能存在的Webhook设置")
    except Exception as e:
        logger.warning(f"删除Webhook时出错: {e}")
    
    # 方法4: 使用更可靠的轮询参数
    polling_params = {
        "drop_pending_updates": True,
        "allowed_updates": ["message", "callback_query"],
        "timeout": 30
    }
    
    # 方法5: 带重试机制的轮询启动
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"尝试启动轮询 (第 {attempt} 次)...")
            await application.updater.start_polling(**polling_params)
            logger.info("Telegram Bot已成功启动轮询。")
            break
        except telegram.error.Conflict as e:
            logger.warning(f"Telegram API冲突 (尝试 {attempt}/{max_retries}): {str(e)}")
            if attempt < max_retries:
                # 指数退避策略
                delay = 2 ** attempt
                logger.info(f"等待 {delay} 秒后重试...")
                await asyncio.sleep(delay)
            else:
                logger.critical("达到最大重试次数，系统将退出。")
                await application.stop()
                sys.exit(1)
        except Exception as e:
            logger.error(f"启动轮询时发生未知错误: {e}")
            await application.stop()
            sys.exit(1)
