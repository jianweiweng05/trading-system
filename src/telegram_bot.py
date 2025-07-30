import logging
import os
import sys
import asyncio
import psutil
import fcntl
from functools import wraps
from fastapi import FastAPI
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode
import telegram.error

# 导入共享的组件
from config import CONFIG
from system_state import SystemState
from database import get_open_positions, init_db, engine, trades

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
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("halt", halt_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("settings", settings_command))
    
    # 按钮处理
    application.add_handler(MessageHandler(filters.Regex('^📊 系统状态$'), status_command))
    application.add_handler(MessageHandler(filters.Regex('^📈 当前持仓$'), positions_command))
    application.add_handler(MessageHandler(filters.Regex('^📋 操作日志$'), logs_command))
    application.add_handler(MessageHandler(filters.Regex('^⚙️ 设置$'), settings_command))
    application.add_handler(MessageHandler(filters.Regex('^🔁 切换模式$'), toggle_mode_command))
    application.add_handler(MessageHandler(filters.Regex('^🔙 返回主菜单$'), back_command))
    application.add_handler(MessageHandler(filters.Regex('^🔴 紧急暂停$'), halt_command))
    application.add_handler(MessageHandler(filters.Regex('^🟢 恢复运行$'), resume_command))
    
    await application.initialize()
    await application.start()
    
    # ===== 终极实例控制方案 =====
    # 方法1: 使用文件锁确保单实例
    lock_file_path = "/tmp/bot_instance.lock"
    lock_file = open(lock_file_path, "w")
    
    try:
        # 尝试获取文件锁 (非阻塞)
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.critical("检测到另一个Bot实例正在运行。为避免冲突，系统将退出。")
        await application.stop()
        sys.exit(1)
    
    # 方法2: 在数据库中标记运行状态
    try:
        async with engine.connect() as conn:
            # 检查是否有其他实例标记
            stmt = select(trades).where(trades.c.status == 'BOT_RUNNING')
            result = await conn.execute(stmt)
            if result.fetchone():
                logger.critical("数据库检测到另一个Bot实例正在运行")
                await application.stop()
                sys.exit(1)
            
            # 标记当前实例
            stmt = insert(trades).values(
                symbol="BOT_INSTANCE",
                status="BOT_RUNNING",
                trade_type="SYSTEM"
            )
            await conn.execute(stmt)
            await conn.commit()
    except Exception as e:
        logger.error(f"数据库标记失败: {e}")
    
    # 方法3: 进程ID检查
    current_pid = os.getpid()
    logger.info(f"当前进程ID: {current_pid}")
    
    # 检查是否有其他Python进程使用相同token
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if "python" in proc.info['name'].lower() and str(current_pid) != str(proc.info['pid']):
                for arg in proc.info['cmdline']:
                    if CONFIG.telegram_bot_token in arg:
                        logger.critical(f"检测到另一个进程使用相同token: PID {proc.info['pid']}")
                        await application.stop()
                        sys.exit(1)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    # 方法4: 强制清理和重试
    try:
        # 强制删除Webhook
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("已强制删除任何可能存在的Webhook设置")
        
        # 等待确保清理完成
        await asyncio.sleep(3)
    except Exception as e:
        logger.warning(f"清理Webhook时出错: {e}")
    
    # 方法5: 使用长轮询减少冲突
    polling_params = {
        "drop_pending_updates": True,
        "allowed_updates": ["message"],
        "timeout": 60,  # 60秒长轮询
        "poll_interval": 0.5
    }
    
    try:
        logger.info("启动轮询...")
        await application.updater.start_polling(**polling_params)
        logger.info("Telegram Bot已成功启动轮询。")
    except telegram.error.Conflict as e:
        logger.critical(f"Telegram API冲突: {str(e)}")
        logger.critical("请确保只有一个Bot实例运行。系统将退出。")
        await application.stop()
        sys.exit(1)
    except Exception as e:
        logger.error(f"启动轮询时发生未知错误: {e}")
        await application.stop()
        sys.exit(1)
    
    # 返回文件锁对象，在stop_bot中释放
    app_instance.state.bot_lock = lock_file

async def stop_bot(app_instance: FastAPI):
    """
    在FastAPI的生命周期中，安全地关闭Telegram Bot
    """
    logger.info("正在关闭Telegram Bot...")
    
    # 清理数据库标记
    try:
        async with engine.connect() as conn:
            stmt = delete(trades).where(
                (trades.c.symbol == "BOT_INSTANCE") & 
                (trades.c.status == "BOT_RUNNING")
            )
            await conn.execute(stmt)
            await conn.commit()
            logger.info("已清理数据库中的Bot运行标记")
    except Exception as e:
        logger.error(f"清理数据库标记失败: {e}")
    
    # 释放文件锁
    if hasattr(app_instance.state, 'bot_lock'):
        try:
            lock_file = app_instance.state.bot_lock
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
            logger.info("已释放文件锁")
        except Exception as e:
            logger.error(f"释放文件锁失败: {e}")
    
    # 检查是否已创建Telegram应用实例
    if not hasattr(app_instance.state, 'telegram_app'):
        logger.warning("无法关闭Telegram Bot: telegram_app 未初始化")
        return
    
    application = app_instance.state.telegram_app
    
    # 安全地停止轮询和关闭应用
    try:
        if application.updater and application.updater.running:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Telegram Bot已成功关闭。")
    except Exception as e:
        logger.error(f"关闭Telegram Bot时出错: {e}", exc_info=True)
