import logging
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

# --- 1. 装饰器与键盘布局 (已恢复“设置”按钮) ---
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
        allowed_in_any_state = [status_command.__name__, resume_command.__name__, start_command.__name__, settings_command.__name__, back_command.__name__]
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
        
        try:
            await exchange.fetch_time()
            exchange_status = "✅ 连接正常"
        except Exception as e:
            exchange_status = f"❌ 连接异常: {e}"
        
        positions = await get_open_positions()
        positions_summary = "无持仓" if not positions else f"{len(positions)}个持仓"
        
        report = (
            f"📊 **系统状态报告 (v7.2)**\n"
            f"🟢 **状态**: {state} | ⚙️ **模式**: {config.run_mode.upper()}\n"
            "--------------------------------\n"
            f"📈 **持仓**: {positions_summary}\n"
            "--------------------------------\n"
            f"🌐 **交易所**: {exchange_status}"
        )
        
        await update.message.reply_text(report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"状态命令执行失败: {str(e)}", exc_info=True)
        await update.message.reply_text("⚠️ 获取状态失败，请查看日志。")

@execute_safe
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        positions = await get_open_positions()
        
        if not positions:
            await update.message.reply_text("📭 当前没有持仓。")
            return
        
        report = "📈 **当前持仓**:\n"
        for i, position in enumerate(positions, 1):
            report += (
                f"\n{i}. **{position['symbol']}** | 类型: {position['trade_type']}\n"
                f"   - 数量: {position['quantity']} | 入场价: ${position['entry_price']:.4f}\n"
            )
        
        await update.message.reply_text(report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"获取持仓失败: {str(e)}", exc_info=True)
        await update.message.reply_text("⚠️ 获取持仓时发生错误，请查看日志。")

@execute_safe
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 **最近操作日志**:\n暂未实现日志数据库查询。")

@execute_safe
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings_keyboard = [["🔙 返回主菜单"]]
    settings_markup = ReplyKeyboardMarkup(settings_keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "⚙️ **系统设置**\n此功能正在开发中。",
        reply_markup=settings_markup
    )

@execute_safe
async def back_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("返回主菜单", reply_markup=REPLY_MARKUP)

@execute_safe
async def halt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    application = context.bot_data.get('application')
    await SystemState.set_state("HALTED", application)
    await update.message.reply_text("🛑 系统已暂停接收新信号。")

@execute_safe
async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    application = context.bot_data.get('application')
    await SystemState.set_state("ACTIVE", application)
    await update.message.reply_text("🟢 系统已恢复，准备接收新信号。")

# --- 3. 异步的、独立的Bot启动与关闭逻辑 ---
async def state_change_alert(old_state: str, new_state: str, application: Application):
    if not application: return
    message = f"🚨 **系统状态变更**\n- 从: `{old_state}`\n- 变为: `{new_state}`"
    try:
        await application.bot.send_message(
            chat_id=CONFIG.admin_chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"发送状态变更通知失败: {e}")

async def start_bot(app_instance: FastAPI):
    """
    在FastAPI的生命周期中，安全地启动Telegram Bot (最终修复版)
    """
    logger.info("正在启动Telegram Bot...")
    
    if not hasattr(app_instance.state, 'telegram_app'):
        logger.error("无法启动Telegram Bot: telegram_app 未初始化")
        return
    
    application = app_instance.state.telegram_app
    
    SystemState.set_alert_callback(lambda old, new, app: state_change_alert(old, new, application))
    
    # 添加所有命令和消息处理器
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("halt", halt_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(MessageHandler(filters.Regex('^📊 系统状态$'), status_command))
    application.add_handler(MessageHandler(filters.Regex('^📈 当前持仓$'), positions_command))
    application.add_handler(MessageHandler(filters.Regex('^📋 操作日志$'), logs_command))
    application.add_handler(MessageHandler(filters.Regex('^⚙️ 设置$'), settings_command))
    application.add_handler(MessageHandler(filters.Regex('^🔙 返回主菜单$'), back_command))
    application.add_handler(MessageHandler(filters.Regex('^🔴 紧急暂停$'), halt_command))
    application.add_handler(MessageHandler(filters.Regex('^🟢 恢复运行$'), resume_command))
    
    # 使用 asyncio.create_task 在后台以非阻塞方式运行轮询 (修复交互问题)
    asyncio.create_task(application.run_polling(drop_pending_updates=True))
    
    logger.info("Telegram Bot 的轮询任务已在后台创建并运行。")

async def stop_bot(app_instance: FastAPI):
    """
    在FastAPI的生命周期中，安全地关闭Telegram Bot (最终版)
    """
    logger.info("正在关闭Telegram Bot...")
    
    if not hasattr(app_instance.state, 'telegram_app'):
        logger.warning("无法关闭Telegram Bot: telegram_app 未初始化")
        return
    
    application = app_instance.state.telegram_app
    
    if application.updater and application.updater.running:
      await application.updater.stop()
    await application.shutdown()
    
    logger.info("Telegram Bot已成功关闭。")
