import logging
from functools import wraps
from fastapi import FastAPI  # 添加这行导入
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

# 导入共享的组件
from config import CONFIG
from system_state import SystemState

logger = logging.getLogger(__name__)

# --- 1. 装饰器与键盘布局 ---
MAIN_KEYBOARD = [
    ["📊 系统状态"],
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
        
        report = f"🚀 **系统状态**\n• **模式**: `{config.run_mode.upper()}`\n• **状态**: `{state}`\n"
        
        try:
            await exchange.fetch_time()
            report += "• **交易所**: ✅ `连接正常`\n"
        except Exception as e:
            report += f"• **交易所**: ❌ `连接异常`: {e}\n"
            
        await update.message.reply_text(report, parse_mode='Markdown')
        
    except KeyError as e:
        logger.critical(f"关键依赖缺失: {str(e)}", exc_info=True)
        await update.message.reply_text("🔧 系统配置错误，请联系管理员。")
    except Exception as e:
        logger.error(f"状态命令执行失败: {str(e)}", exc_info=True)
        await update.message.reply_text("⚠️ 获取状态失败，请查看日志。")

@execute_safe
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("正在查询持仓...", reply_markup=REPLY_MARKUP)

@execute_safe
async def halt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    application = context.bot_data.get('application')
    await SystemState.set_state("HALTED", application)

@execute_safe
async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    application = context.bot_data.get('application')
    await SystemState.set_state("ACTIVE", application)

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
    
    application = app_instance.state.telegram_app
    
    SystemState.set_alert_callback(lambda old, new: state_change_alert(old, new, application))
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("halt", halt_command))
    application.add_handler(CommandHandler("resume", resume_command))
    
    application.add_handler(MessageHandler(filters.Regex('^📊 系统状态$'), status_command))
    application.add_handler(MessageHandler(filters.Regex('^📈 当前持仓$'), positions_command))
    application.add_handler(MessageHandler(filters.Regex('^🔴 紧急暂停$'), halt_command))
    application.add_handler(MessageHandler(filters.Regex('^🟢 恢复运行$'), resume_command))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    logger.info("Telegram Bot已成功启动轮询。")

async def stop_bot(app_instance: FastAPI):
    """
    在FastAPI的生命周期中，安全地关闭Telegram Bot
    """
    logger.info("正在关闭Telegram Bot...")
    application = app_instance.state.telegram_app
    if application.updater and application.updater.running:
        await application.updater.stop()
    await application.stop()
    await application.shutdown()
    logger.info("Telegram Bot已成功关闭。")
