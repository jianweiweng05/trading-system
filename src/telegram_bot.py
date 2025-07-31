import logging
from functools import wraps
from typing import Optional, Dict, Any
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, Application
from telegram.error import TelegramError

from config import CONFIG
from system_state import SystemState
from database import get_open_positions, get_setting, set_setting

logger = logging.getLogger(__name__)

MAIN_KEYBOARD = [
    ["📊 系统状态", "⚙️ 设置"],
    ["📈 当前持仓", "📋 操作日志"],
    ["🔴 紧急暂停", "🟢 恢复运行"]
]
REPLY_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

def execute_safe(func):
    """
    安全执行装饰器，处理权限检查和错误处理
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            # 权限检查
            if not update.effective_user:
                await update.message.reply_text("❌ 无法获取用户信息。")
                return

            user_id = str(update.effective_user.id)
            if user_id != CONFIG.admin_chat_id:
                await update.message.reply_text("❌ 权限不足。")
                return

            # 状态检查
            current_state = await SystemState.get_state()
            allowed_in_any_state = {
                status_command.__name__,
                resume_command.__name__,
                halt_command.__name__,
                logs_command.__name__
            }
            
            if current_state != "ACTIVE" and func.__name__ not in allowed_in_any_state:
                await update.message.reply_text(f"❌ 命令被阻止，因为当前系统状态为: {current_state}")
                return
                
            return await func(update, context, *args, **kwargs)
            
        except TelegramError as e:
            logger.warning(f"Telegram错误: {e}")
            await update.message.reply_text("⚠️ 消息发送失败，请稍后重试。")
        except Exception as e:
            logger.error(f"命令 {func.__name__} 执行失败: {e}", exc_info=True)
            await update.message.reply_text("⚠️ 命令执行时发生内部错误，请查看日志。")
            
    return wrapper

@execute_safe
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """启动命令处理器"""
    await update.message.reply_text(
        "🚀 **交易机器人指挥中心**\n请使用下方仪表盘操作。", 
        reply_markup=REPLY_MARKUP, 
        parse_mode='Markdown'
    )

@execute_safe
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """系统状态命令处理器"""
    try:
        exchange = context.bot_data.get('exchange')
        config = context.bot_data.get('config')
        
        if not exchange or not config:
            await update.message.reply_text("❌ 系统未完全初始化，请稍后再试。")
            return
        
        state = await SystemState.get_state()
        
        # 获取交易所状态
        exchange_status = "❌ 连接异常"
        try:
            await exchange.fetch_time()
            exchange_status = "✅ 连接正常"
        except Exception as e:
            logger.warning(f"交易所连接检查失败: {e}")
            exchange_status = f"❌ 错误: {type(e).__name__}"
        
        # 获取持仓信息
        positions = await get_open_positions()
        positions_summary = "无持仓" if not positions else f"{len(positions)}个持仓"
        
        # 构建状态报告
        report = (
            f"📊 **系统状态报告 (v7.2)**\n"
            f"🟢 **状态**: {state} | ⚙️ **模式**: {config.run_mode.upper()}\n"
            "--------------------------------\n"
            f"🌍 **战略层**: 中性\n"
            "--------------------------------\n"
            f"📈 **持仓/浮盈**: 🟢 $0.00\n"
            f"{positions_summary}\n"
            "--------------------------------\n"
            f"🌐 **交易所**: {exchange_status}"
        )
        
        await update.message.reply_text(report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"状态命令执行失败: {str(e)}", exc_info=True)
        await update.message.reply_text("⚠️ 获取状态失败，请查看日志。")

@execute_safe
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """持仓查询命令处理器"""
    try:
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
    """日志查询命令处理器"""
    try:
        # TODO: 实现实际的日志查询功能
        await update.message.reply_text(
            "📋 **最近操作日志**:\n"
            "1. 系统启动完成\n"
            "2. 数据库初始化成功\n"
            "3. Telegram Bot 已连接",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"日志命令执行失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 获取日志失败，请查看日志。")

@execute_safe
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置命令处理器"""
    try:
        settings_keyboard = [
            ["🔁 切换模式", "📈 设置杠杆"],
            ["🔙 返回主菜单"]
        ]
        settings_markup = ReplyKeyboardMarkup(settings_keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚙️ **系统设置**\n"
            f"当前模式: {CONFIG.run_mode.upper()}\n"
            f"当前杠杆: {CONFIG.leverage}x",
            reply_markup=settings_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"设置命令执行失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 显示设置失败，请查看日志。")

@execute_safe
async def toggle_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """模式切换命令处理器"""
    try:
        new_mode = "simulate" if CONFIG.run_mode == "live" else "live"
        await set_setting('run_mode', new_mode)
        CONFIG.run_mode = new_mode
        
        await update.message.reply_text(
            f"✅ 运行模式已切换为: {new_mode.upper()}",
            reply_markup=REPLY_MARKUP,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"切换模式失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 切换模式失败，请查看日志。")

@execute_safe
async def back_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回命令处理器"""
    try:
        await update.message.reply_text("返回主菜单", reply_markup=REPLY_MARKUP)
    except Exception as e:
        logger.error(f"返回命令执行失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 返回失败，请重试。")

@execute_safe
async def halt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """暂停命令处理器"""
    try:
        application = context.bot_data.get('application')
        await SystemState.set_state("HALTED", application)
        await update.message.reply_text("🛑 系统已暂停交易")
    except Exception as e:
        logger.error(f"暂停系统失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 暂停系统失败，请查看日志。")

@execute_safe
async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """恢复命令处理器"""
    try:
        application = context.bot_data.get('application')
        await SystemState.set_state("ACTIVE", application)
        await update.message.reply_text("🟢 系统已恢复交易")
    except Exception as e:
        logger.error(f"恢复系统失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 恢复系统失败，请查看日志。")

async def state_change_alert(old_state: str, new_state: str, application: Application):
    """状态变更通知处理器"""
    try:
        message = f"🚨 **系统状态变更**\n- 从: `{old_state}`\n- 变为: `{new_state}`"
        await application.bot.send_message(
            chat_id=CONFIG.admin_chat_id,
            text=message,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"发送状态变更通知失败: {e}")

async def initialize_bot(app_instance):
    """初始化Telegram Bot"""
    logger.info("初始化Telegram Bot处理器...")
    
    try:
        if not hasattr(app_instance.state, 'telegram_app'):
            logger.error("telegram_app 未初始化")
            return
        
        application = app_instance.state.telegram_app
        
        # 设置状态变更回调
        SystemState.set_alert_callback(state_change_alert)
        
        # 注册所有命令处理器
        handlers = [
            CommandHandler("start", start_command),
            CommandHandler("status", status_command),
            CommandHandler("positions", positions_command),
            CommandHandler("logs", logs_command),
            CommandHandler("halt", halt_command),
            CommandHandler("resume", resume_command),
            CommandHandler("settings", settings_command),
            MessageHandler(filters.Regex('^📊 系统状态$'), status_command),
            MessageHandler(filters.Regex('^📈 当前持仓$'), positions_command),
            MessageHandler(filters.Regex('^📋 操作日志$'), logs_command),
            MessageHandler(filters.Regex('^⚙️ 设置$'), settings_command),
            MessageHandler(filters.Regex('^🔁 切换模式$'), toggle_mode_command),
            MessageHandler(filters.Regex('^🔙 返回主菜单$'), back_command),
            MessageHandler(filters.Regex('^🔴 紧急暂停$'), halt_command),
            MessageHandler(filters.Regex('^🟢 恢复运行$'), resume_command)
        ]
        
        # 添加所有处理器
        for handler in handlers:
            application.add_handler(handler)
        
        # 初始化并启动应用
        await application.initialize()
        await application.start()
        logger.info("✅ Telegram Bot处理器初始化完成")
        
    except Exception as e:
        logger.error(f"初始化Telegram Bot失败: {e}", exc_info=True)
        raise

async def stop_bot_services(app_instance):
    """停止Telegram Bot服务"""
    logger.info("停止Telegram核心服务...")
    
    try:
        if hasattr(app_instance.state, 'telegram_app'):
            application = app_instance.state.telegram_app
            await application.stop()
            await application.shutdown()
            logger.info("✅ Telegram核心服务已停止")
    except Exception as e:
        logger.error(f"停止Telegram服务时出错: {e}", exc_info=True)
        raise
