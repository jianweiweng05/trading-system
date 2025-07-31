# 文件: src/telegram_bot.py (严格按您的要求修改)

import logging
from functools import wraps
from fastapi import FastAPI
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

# 导入共享的组件
from config import CONFIG
from system_state import SystemState
from database import get_open_positions, get_setting, set_setting

logger = logging.getLogger(__name__)

# --- 1. 键盘布局 --- 
MAIN_KEYBOARD = [
    ["📊 系统状态", "⚙️ 设置"],
    ["📈 当前持仓", "📋 操作日志"],
]
REPLY_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

# --- 2. 装饰器 ---
def execute_safe(func):
    """安全装饰器，进行权限检查"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not CONFIG:
            logger.warning("配置尚未初始化，命令被推迟")
            await update.message.reply_text("系统正在启动，请稍后再试...")
            return

        if str(update.effective_user.id) != CONFIG.admin_chat_id:
            await update.message.reply_text("❌ 权限不足")
            return
            
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"命令 {func.__name__} 执行失败: {e}", exc_info=True)
            await update.message.reply_text("⚠️ 命令执行时发生内部错误")
    return wrapper

# --- 3. 命令处理器 (完全保持原样) ---
@execute_safe
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **交易机器人指挥中心**\n请使用下方仪表盘操作", reply_markup=REPLY_MARKUP, parse_mode='Markdown')

@execute_safe
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = await SystemState.get_state()
    report = (
        f"📊 **系统状态报告**\n"
        f"--------------------------------\n"
        f"🟢 系统状态: `{state}`\n"
        f"⚙️ 运行模式: `{CONFIG.run_mode.upper()}`\n"
        f"🔱 固定杠杆: `{CONFIG.leverage}x`\n"
        f"🔬 宏观系数: `{CONFIG.macro_coefficient}`\n"
        f"🎛️ 共振系数: `{CONFIG.resonance_coefficient}`"
    )
    await update.message.reply_text(report, parse_mode='Markdown')

@execute_safe
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = (
        f"⚙️ **系统设置中心**\n"
        "--------------------------------\n"
        "你可以使用 `/set` 命令修改以下参数:\n\n"
        f"🔹 `run_mode`\n"
        f"   - 当前值: {CONFIG.run_mode}\n"
        f"   - 说明: 运行模式 (live/simulate)\n\n"
        f"🔹 `macro_coefficient`\n"
        f"   - 当前值: {CONFIG.macro_coefficient}\n"
        f"   - 说明: 宏观市场影响系数\n\n"
        f"🔹 `resonance_coefficient`\n"
        f"   - 当前值: {CONFIG.resonance_coefficient}\n"
        f"   - 说明: 信号共振强度系数\n"
        "--------------------------------\n"
        "修改指令: `/set <参数名> <新值>`\n"
        "示例: `/set macro_coefficient 0.9`"
    )
    await update.message.reply_text(report, parse_mode='Markdown')

@execute_safe
async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        if len(parts) != 3:
            await update.message.reply_text("❌ 格式错误\n用法: `/set <参数名> <新值>`", parse_mode='Markdown')
            return
        
        _, key, value_str = parts
        
        allowed_keys = ['run_mode', 'macro_coefficient', 'resonance_coefficient']
        if key not in allowed_keys:
            await update.message.reply_text(f"❌ 无效参数: {key}", parse_mode='Markdown')
            return

        if key == 'run_mode':
            if value_str.lower() not in ['live', 'simulate']:
                await update.message.reply_text("❌ 运行模式必须是 live 或 simulate")
                return
            new_value = value_str.lower()
        else:
            try:
                new_value = float(value_str)
            except ValueError:
                await update.message.reply_text(f"❌ {key} 必须是数字")
                return

        await set_setting(key, str(new_value))
        setattr(CONFIG, key, new_value)
        
        logger.info(f"系统设置更新: {key} = {new_value}")
        await update.message.reply_text(f"✅ 参数更新成功\n`{key}` = `{new_value}`", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"设置参数失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 设置参数时发生错误")

@execute_safe
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    positions = await get_open_positions()
    if not positions:
        await update.message.reply_text("📭 当前没有持仓")
        return
    report = "📈 **当前持仓**\n" + "\n".join(f"- {p['symbol']} ({p['trade_type']})" for p in positions)
    await update.message.reply_text(report, parse_mode='Markdown')

@execute_safe
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 **最近操作日志**\n此功能暂未实现")

# --- 4. 严格按您的要求修改以下部分 ---
async def initialize_bot(app_instance: FastAPI):
    """仅初始化处理器和依赖注入"""
    logger.info("初始化Telegram处理器...")
    application = app_instance.state.telegram_app
    
    # 添加所有处理器
    handlers = [
        CommandHandler("start", start_command),
        CommandHandler("status", status_command),
        CommandHandler("positions", positions_command),
        CommandHandler("logs", logs_command),
        CommandHandler("settings", settings_command),
        CommandHandler("set", set_command),
        MessageHandler(filters.Regex('^📊 系统状态$'), status_command),
        MessageHandler(filters.Regex('^📈 当前持仓$'), positions_command),
        MessageHandler(filters.Regex('^📋 操作日志$'), logs_command),
        MessageHandler(filters.Regex('^⚙️ 设置$'), settings_command)
    ]
    
    for handler in handlers:
        application.add_handler(handler)
    
    # 仅初始化不启动
    await application.initialize()
    logger.info("✅ Telegram处理器初始化完成")

async def stop_bot_services(app_instance: FastAPI):
    """仅停止核心服务"""
    logger.info("停止Telegram核心服务...")
    application = app_instance.state.telegram_app
    await application.stop()
    await application.shutdown()
    logger.info("✅ Telegram核心服务已停止")

# --- 5. 保留原始导出但标记为过时 ---
async def start_bot(app_instance: FastAPI):
    """[已过时] 请改用initialize_bot"""
    logger.warning("start_bot已过时，将在下个版本移除")
    return await initialize_bot(app_instance)

async def stop_bot(app_instance: FastAPI):
    """[已过时] 请改用stop_bot_services"""
    logger.warning("stop_bot已过时，将在下个版本移除")
    return await stop_bot_services(app_instance)
