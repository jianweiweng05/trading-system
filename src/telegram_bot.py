import logging
from functools import wraps
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    Application
)

from config import CONFIG
from system_state import SystemState
from database import get_open_positions, get_setting, set_setting

logger = logging.getLogger(__name__)

# 键盘布局
MAIN_KEYBOARD = [
    ["📊 系统状态", "⚙️ 设置"],
    ["📈 当前持仓", "📋 操作日志"],
    ["🔴 紧急暂停", "🟢 恢复运行"]
]
REPLY_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

# 通用装饰器：权限检查和错误处理
def execute_safe(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            # 检查权限
            if not update.effective_user or str(update.effective_user.id) != CONFIG.admin_chat_id:
                await update.message.reply_text("❌ 权限不足")
                return

            # 检查系统状态
            current_state = await SystemState.get_state()
            if current_state != "ACTIVE" and func.__name__ not in ['status_command', 'resume_command', 'halt_command']:
                await update.message.reply_text(f"❌ 系统当前状态: {current_state}")
                return
                
            return await func(update, context, *args, **kwargs)
            
        except Exception as e:
            logger.error(f"命令执行失败: {e}", exc_info=True)
            await update.message.reply_text("⚠️ 出错了，请查看日志")
    return wrapper

# 基础命令
@execute_safe
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"收到启动命令，用户ID: {update.effective_user.id}")
    await update.message.reply_text("🚀 交易机器人已启动", reply_markup=REPLY_MARKUP)

@execute_safe
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        state = await SystemState.get_state()
        positions = await get_open_positions()
        exchange = context.bot_data.get('exchange')
        
        # 检查交易所连接
        exchange_status = "❌ 未连接"
        if exchange:
            try:
                await exchange.fetch_time()
                exchange_status = "✅ 正常"
            except Exception as e:
                logger.warning(f"交易所连接检查失败: {e}")

        report = (
            f"📊 系统状态\n"
            f"状态: {state}\n"
            f"模式: {CONFIG.run_mode.upper()}\n"
            f"持仓: {len(positions)}个\n"
            f"交易所: {exchange_status}"
        )
        await update.message.reply_text(report)
    except Exception as e:
        logger.error(f"获取状态失败: {e}", exc_info=True)
        await update.message.reply_text("❌ 获取状态失败")

@execute_safe
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        positions = await get_open_positions()
        if not positions:
            await update.message.reply_text("📭 当前无持仓")
            return

        report = "📈 当前持仓:\n"
        for p in positions:
            report += f"\n{p['symbol']} - {p['trade_type']}\n"
            report += f"数量: {p['quantity']}\n"
            report += f"入场价: ${p['entry_price']:.2f}\n"
        await update.message.reply_text(report)
    except Exception as e:
        logger.error(f"获取持仓失败: {e}", exc_info=True)
        await update.message.reply_text("❌ 获取持仓失败")

@execute_safe
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 最近日志:\n1. 系统启动\n2. 数据库连接\n3. Bot就绪")

@execute_safe
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🔁 切换模式", "📈 设置杠杆"], ["🔙 返回"]]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        f"⚙️ 设置\n模式: {CONFIG.run_mode.upper()}\n杠杆: {CONFIG.leverage}x",
        reply_markup=markup
    )

@execute_safe
async def toggle_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_mode = "simulate" if CONFIG.run_mode == "live" else "live"
    await set_setting('run_mode', new_mode)
    CONFIG.run_mode = new_mode
    await update.message.reply_text(f"✅ 已切换到: {new_mode.upper()}", reply_markup=REPLY_MARKUP)

@execute_safe
async def back_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("返回主菜单", reply_markup=REPLY_MARKUP)

@execute_safe
async def halt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    application = context.bot_data.get('application')
    if not application:
        logger.error("无法获取application实例")
        return
        
    await SystemState.set_state("HALTED", application)
    await update.message.reply_text("🛑 交易已暂停")

@execute_safe
async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    application = context.bot_data.get('application')
    if not application:
        logger.error("无法获取application实例")
        return
        
    await SystemState.set_state("ACTIVE", application)
    await update.message.reply_text("🟢 交易已恢复")

# 状态变更通知
async def state_change_alert(old_state: str, new_state: str, application: Application):
    try:
        if not application or not hasattr(application, 'bot_data'):
            logger.warning("Application 实例异常")
            return
            
        config = application.bot_data.get('config')
        if not config or not hasattr(config, 'admin_chat_id'):
            logger.warning("配置缺失，跳过通知")
            return
            
        logger.info(f"发送状态变更通知: {old_state} -> {new_state}")
        await application.bot.send_message(
            chat_id=config.admin_chat_id,
            text=f"⚠️ 状态变更: {old_state} -> {new_state}"
        )
    except Exception as e:
        logger.error(f"发送通知失败: {e}", exc_info=True)

# Bot初始化
async def initialize_bot(app_instance):
    """初始化并注册所有处理器"""
    try:
        if not hasattr(app_instance.state, 'telegram_app'):
            logger.error("telegram_app 未初始化")
            return

        app = app_instance.state.telegram_app
        logger.info("开始注册处理器...")
        
        # 注入必要引用
        app.bot_data['application'] = app
        SystemState.set_alert_callback(state_change_alert)

        # 命令处理器
        command_handlers = [
            CommandHandler("start", start_command),
            CommandHandler("status", status_command),
            CommandHandler("positions", positions_command),
            CommandHandler("logs", logs_command),
            CommandHandler("halt", halt_command),
            CommandHandler("resume", resume_command),
            CommandHandler("settings", settings_command)
        ]

        # 消息处理器
        message_handlers = [
            MessageHandler(filters.Regex('^📊 系统状态$'), status_command),
            MessageHandler(filters.Regex('^📈 当前持仓$'), positions_command),
            MessageHandler(filters.Regex('^📋 操作日志$'), logs_command),
            MessageHandler(filters.Regex('^⚙️ 设置$'), settings_command),
            MessageHandler(filters.Regex('^🔁 切换模式$'), toggle_mode_command),
            MessageHandler(filters.Regex('^🔙 返回$'), back_command),
            MessageHandler(filters.Regex('^🔴 紧急暂停$'), halt_command),
            MessageHandler(filters.Regex('^🟢 恢复运行$'), resume_command)
        ]

        # 批量注册
        for handler in command_handlers + message_handlers:
            app.add_handler(handler)

        logger.info("✅ 处理器注册完成")
    except Exception as e:
        logger.error(f"初始化失败: {e}", exc_info=True)
        raise

# Bot停止
async def stop_bot_services(app_instance):
    """安全停止Bot服务"""
    try:
        if not hasattr(app_instance.state, 'telegram_app'):
            return

        app = app_instance.state.telegram_app
        logger.info("开始停止Bot服务...")
        
        await app.stop()
        await app.shutdown()
        
        logger.info("✅ Bot服务已停止")
    except Exception as e:
        logger.error(f"停止服务失败: {e}", exc_info=True)
        raise
