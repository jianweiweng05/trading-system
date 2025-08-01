import logging
from datetime import datetime
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from telegram.error import TelegramError

from config import CONFIG
from database import engine

logger = logging.getLogger(__name__)

def execute_safe(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            return None
    return wrapper

async def get_system_stats():
    """获取系统统计信息"""
    try:
        async with engine.connect() as conn:
            return {
                "status": "active",
                "uptime": str(datetime.now()),
                "database": "connected"
            }
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        return {"status": "error", "error": str(e)}

async def format_system_status(stats: dict) -> str:
    """格式化系统状态"""
    return f"""
📊 系统状态
状态: {stats.get('status', 'unknown')}
运行时间: {stats.get('uptime', 'unknown')}
数据库: {stats.get('database', 'unknown')}
"""

async def format_position_info(positions: list) -> str:
    """格式化持仓信息"""
    if not positions:
        return "📊 当前无持仓"
    
    result = "📈 当前持仓:\n\n"
    for pos in positions:
        result += f"交易对: {pos.get('symbol', 'N/A')}\n"
        result += f"数量: {pos.get('contracts', 'N/A')}\n"
        result += f"盈亏: {pos.get('unrealizedPnl', 'N/A')}\n\n"
    return result

MAIN_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("📊 系统状态", callback_data="status")],
    [InlineKeyboardButton("📈 当前持仓", callback_data="positions")]
])

@execute_safe
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """启动命令"""
    await update.message.reply_text(
        "🚀 交易机器人已启动",
        reply_markup=MAIN_KEYBOARD
    )

@execute_safe
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """帮助命令"""
    help_text = """
🤖 可用命令：
/start - 启动机器人
/status - 系统状态
/positions - 当前持仓
/help - 显示帮助
    """
    await update.message.reply_text(help_text)

@execute_safe
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """系统状态命令"""
    stats = await get_system_stats()
    status_text = await format_system_status(stats)
    await update.message.reply_text(status_text, parse_mode="HTML")

@execute_safe
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """持仓查询命令"""
    if not hasattr(context.application, 'state') or not context.application.state.exchange:
        await update.message.reply_text("❌ 交易所未连接")
        return
    
    try:
        positions = await context.application.state.exchange.fetch_positions()
        if not positions:
            await update.message.reply_text("📊 当前无持仓")
            return
        
        position_text = await format_position_info(positions)
        await update.message.reply_text(position_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"获取持仓失败: {e}")
        await update.message.reply_text("❌ 获取持仓失败")

@execute_safe
async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮点击"""
    query = update.callback_query
    logger.info(f"🔥 按钮回调触发: {query.data}")
    
    try:
        await query.answer()
        await asyncio.sleep(0.1)
        await query.edit_message_text("⏳ 正在处理...")
        
        if query.data == "status":
            stats = await get_system_stats()
            status_text = await format_system_status(stats)
            await query.edit_message_text(status_text, parse_mode="HTML")
            
        elif query.data == "positions":
            if not hasattr(context.application, 'state') or not context.application.state.exchange:
                await query.edit_message_text("❌ 交易所未连接")
                return
            
            try:
                positions = await context.application.state.exchange.fetch_positions()
                if not positions:
                    await query.edit_message_text("📊 当前无持仓")
                    return
                
                position_text = await format_position_info(positions)
                await query.edit_message_text(position_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"获取持仓失败: {e}")
                await query.edit_message_text("❌ 获取持仓失败")
                
    except Exception as e:
        logger.error(f"按钮处理异常: {e}")
        await query.answer("操作失败", show_alert=True)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """错误处理"""
    logger.error(f"Update {update} caused error {context.error}")

async def initialize_bot(app_instance):
    """初始化Telegram Bot"""
    logger.info("开始注册处理器...")
    
    # 获取Telegram应用实例
    app = app_instance.state.telegram_app
    
    # 清除可能存在的旧处理器
    app.handlers.clear()
    
    # 定义所有处理器
    handlers = [
        CommandHandler("start", start_command),
        CommandHandler("help", help_command),
        CommandHandler("status", status_command),
        CommandHandler("positions", positions_command),
        CallbackQueryHandler(handle_button_click),
        MessageHandler(filters.ALL, error_handler)
    ]
    
    # 注册所有处理器
    for handler in handlers:
        app.add_handler(handler)
    
    # 添加调试信息
    logger.info(f"✅ 处理器注册完成 (数量: {len(handlers)})")
    for handler in handlers:
        logger.info(f"处理器类型: {type(handler).__name__}")

async def stop_bot_services(app_instance):
    """停止Bot服务"""
    logger.info("正在停止Telegram服务...")
    if hasattr(app_instance.state, 'telegram_app'):
        telegram_app = app_instance.state.telegram_app
        if telegram_app.running:
            await telegram_app.stop()
            await telegram_app.shutdown()
    logger.info("✅ Telegram服务已停止")

async def send_status_change_notification(old_state: str, new_state: str, telegram_app):
    """发送状态变更通知"""
    if not CONFIG.telegram_chat_id:
        return
    
    try:
        message = f"🔄 系统状态变更：{old_state} → {new_state}"
        await telegram_app.bot.send_message(
            chat_id=CONFIG.telegram_chat_id,
            text=message
        )
        logger.info(f"发送状态变更通知: {old_state} -> {new_state}")
    except Exception as e:
        logger.error(f"发送状态通知失败: {e}")
