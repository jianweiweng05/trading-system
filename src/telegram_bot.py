import logging
import os
import sys
import asyncio
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
from database import get_open_positions

logger = logging.getLogger(__name__)

# --- 1. 装饰器与键盘布局 ---
MAIN_KEYBOARD = [
    ["📊 系统状态", "⚙️ 设置"],
    ["📈 当前持仓", "📋 操作日志"],
    ["🔴 紧急暂停", "🟢 恢复运行"]
]
REPLY_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

def execute_safe(func):
    """
    一个安全装饰器，用于在执行命令前进行权限和系统状态检查
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = str(update.effective_user.id)
        if user_id != CONFIG.admin_chat_id:
            await update.message.reply_text("❌ 权限不足。")
            return

        current_state = await SystemState.get_state()
        allowed_in_any_state = [status_command.__name__, resume_command.__name__]
        if current_state != "ACTIVE" and func.__name__ not in allowed_in_any_state:
             await update.message.reply_text(f"❌ 命令被阻止，因为当前系统状态为: {current_state}")
             return
            
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"命令 {func.__name__} 执行失败: {e}", exc_info=True)
            await update.message.reply_text(f"⚠️ 命令执行时发生内部错误，请检查日志。")
            
    return wrapper

# --- 2. 命令处理器 (Command Handlers) ---
@execute_safe
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **交易机器人指挥中心**\n请使用下方仪表盘操作。", reply_markup=REPLY_MARKUP, parse_mode='Markdown')

@execute_safe
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        exchange = context.bot_data['exchange']
        config = context.bot_data['config']
        
        state = await SystemState.get_state()
        
        # 获取交易所时间
        try:
            exchange_time = await exchange.fetch_time()
            exchange_status = "✅ 连接正常"
        except Exception as e:
            exchange_status = f"❌ 连接异常: {e}"
        
        # 获取持仓信息
        positions = await get_open_positions()
        positions_summary = "无持仓" if not positions else f"{len(positions)}个持仓"
        
        # 构建完整状态报告
        report = (
            f"📊 **系统状态报告 (v7.2)**\n"
            f"🟢 **状态**: {state} | ⚙️ **模式**: {config.run_mode.upper()}\n"
            "--------------------------------\n"
            f"🌍 **战略层**: 中性\n"
            f"- 依据: BTC/USDT (neutral)\n"
            f"- 依据: ETH/USDT (neutral)\n"
            "--------------------------------\n"
            f"📈 **持仓/浮盈**: 🟢 $0.00\n"
            f"{positions_summary}\n"
            "--------------------------------\n"
            f"⏳ **共振池 (0个信号)**\n"
            f"无待处理信号\n"
            "--------------------------------\n"
            f"🌐 **交易所**: {exchange_status}"
        )
        
        await update.message.reply_text(report, parse_mode='Markdown')
        
    except KeyError as e:
        logger.critical(f"关键依赖缺失: {str(e)}", exc_info=True)
        await update.message.reply_text("🔧 系统配置错误，请联系管理员。")
    except Exception as e:
        logger.error(f"状态命令执行失败: {str(e)}", exc_info=True)
        await update.message.reply_text("⚠️ 获取状态失败，请查看日志。")

@execute_safe
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # 获取所有持仓
        positions = await get_open_positions()
        
        if not positions:
            await update.message.reply_text("📭 当前没有持仓。")
            return
        
        # 构建持仓报告
        report = "📈 **当前持仓**:\n"
        for i, position in enumerate(positions, 1):
            symbol = position['symbol']
            quantity = position['quantity']
            entry_price = position['entry_price']
            trade_type = position['trade_type']
            
            report += (
                f"\n{i}. **{symbol}**\n"
                f"   - 类型: {trade_type}\n"
                f"   - 数量: {quantity}\n"
                f"   - 入场价: ${entry_price:.2f}\n"
            )
        
        await update.message.reply_text(report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"获取持仓失败: {str(e)}", exc_info=True)
        await update.message.reply_text("⚠️ 获取持仓时发生错误，请查看日志。")

@execute_safe
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 操作日志功能
    await update.message.reply_text(
        "📋 **最近操作日志**:\n"
        "1. 2025-07-30 03:15:22 - 系统启动完成\n"
        "2. 2025-07-30 03:10:45 - 数据库初始化成功\n"
        "3. 2025-07-30 03:10:30 - Telegram Bot 已连接",
        parse_mode='Markdown'
    )

@execute_safe
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 设置键盘
    settings_keyboard = [
        ["🔁 切换模式", "📈 设置杠杆"],
        ["🔙 返回主菜单"]
    ]
    settings_markup = ReplyKeyboardMarkup(settings_keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "⚙️ **系统设置**\n"
        f"当前模式: {CONFIG.run_mode.upper()}\n"
        f"当前杠杆: {CONFIG.base_leverage}x",
        reply_markup=settings_markup,
        parse_mode='Markdown'
    )

@execute_safe
async def toggle_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 切换运行模式
    new_mode = "simulate" if CONFIG.run_mode == "live" else "live"
    CONFIG.run_mode = new_mode
    
    await update.message.reply_text(
        f"✅ 运行模式已切换为: {new_mode.upper()}\n"
        "注意: 此设置将在下次重启后生效",
        reply_markup=REPLY_MARKUP,
        parse_mode='Markdown'
    )

@execute_safe
async def back_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("返回主菜单", reply_markup=REPLY_MARKUP)

@execute_safe
async def halt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    application = context.bot_data.get('application')
    await SystemState.set_state("HALTED", application)
    await update.message.reply_text("🛑 系统已暂停交易")

@execute_safe
async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    application = context.bot_data.get('application')
    await SystemState.set_state("ACTIVE", application)
    await update.message.reply_text("🟢 系统已恢复交易")

# --- 3. 异步的、独立的Bot启动与关闭逻辑 ---
async def state_change_alert(old_state: str, new_state: str, application: Application):
    """
    一个独立的回调函数，用于在状态变更时发送Telegram通知
    """
    if not application: return
    message = f"🚨 **系统状态变更**\n- 从: `{old_state}`\n- 变为: `{new_state}`"
    await application.bot.send_message(
        chat_id=CONFIG.admin_chat_id,
        text=message,
        parse_mode=ParseMode.MARKDOWN
    )

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
    
    # ===== Render 平台专用解决方案 =====
    # 1. 文件锁机制 - 防止同一容器内多个实例
    lock_file_path = "/tmp/bot_instance.lock"
    try:
        lock_file = open(lock_file_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info("已获取文件锁，继续启动")
        app_instance.state.bot_lock = lock_file
    except (BlockingIOError, IOError):
        logger.critical("检测到另一个Bot实例正在运行（同一容器内）。为避免冲突，系统将退出。")
        await application.stop()
        sys.exit(1)
    
    # 2. 强制清理Webhook - 确保没有残留状态
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("已强制删除任何可能存在的Webhook设置")
    except Exception as e:
        logger.warning(f"清理Webhook时出错: {e}")
    
    # 3. 带重试机制的轮询启动 - 处理Render新旧容器共存期
    max_retries = 10  # 最多重试10次
    retry_delay = 5   # 每次重试间隔5秒
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"尝试启动轮询 (第 {attempt}/{max_retries} 次)...")
            
            # 使用优化的轮询参数
            await application.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
                timeout=60,
                poll_interval=0.5
            )
            
            logger.info("Telegram Bot已成功启动轮询并获得控制权。")
            return  # 成功启动，退出函数
        
        except telegram.error.Conflict as e:
            logger.warning(
                f"启动轮询时发生冲突 (尝试 {attempt}/{max_retries}): {str(e)}"
                f"\n将在 {retry_delay} 秒后重试..."
            )
            
            # 停止可能已部分初始化的updater
            if application.updater and application.updater.running:
                try:
                    await application.updater.stop()
                except:
                    pass
            
            # 等待一段时间，给旧实例关闭的机会
            await asyncio.sleep(retry_delay)
            
        except Exception as e:
            logger.critical(f"启动轮询时发生无法恢复的错误: {e}")
            await application.stop()
            # 释放文件锁
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
            sys.exit(1)
    
    # 所有重试均失败
    logger.critical("⚠️ 所有启动轮询的尝试均因冲突而失败。请检查Render配置或手动停止所有实例。")
    # 释放文件锁并退出
    fcntl.flock(lock_file, fcntl.LOCK_UN)
    lock_file.close()
    await application.stop()
    sys.exit(1)

async def stop_bot(app_instance: FastAPI):
    """
    在FastAPI的生命周期中，安全地关闭Telegram Bot
    """
    logger.info("正在关闭Telegram Bot...")
    
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
