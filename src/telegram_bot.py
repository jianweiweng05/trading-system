# 文件: src/telegram_bot.py (最终版)

import logging
import asyncio
from functools import wraps
from fastapi import FastAPI
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode

# 导入共享的组件
from config import CONFIG
from system_state import SystemState
# 注意：我们现在需要从 database 导入 setting 函数
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
        if str(update.effective_user.id) != CONFIG.admin_chat_id:
            await update.message.reply_text("❌ 权限不足。")
            return
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"命令 {func.__name__} 执行失败: {e}", exc_info=True)
            await update.message.reply_text(f"⚠️ 命令执行时发生内部错误，请检查日志。")
    return wrapper

# --- 3. 命令处理器 (已升级) ---
@execute_safe
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **交易机器人指挥中心**\n请使用下方仪表盘操作。", reply_markup=REPLY_MARKUP, parse_mode='Markdown')

@execute_safe
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统当前的核心状态信息"""
    state = await SystemState.get_state()
    report = (
        f"📊 **系统状态报告**\n"
        f"--------------------------------\n"
        f"🟢 **系统状态**: `{state}`\n"
        f"⚙️ **运行模式**: `{CONFIG.run_mode.upper()}`\n"
        f"🔱 **固定杠杆**: `{CONFIG.leverage}x`\n"
        f"🔬 **宏观系数**: `{CONFIG.macro_coefficient}`\n"
        f"🎛️ **共振系数**: `{CONFIG.resonance_coefficient}`"
    )
    await update.message.reply_text(report, parse_mode='Markdown')

@execute_safe
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示所有可配置的参数及修改方法"""
    report = (
        f"⚙️ **系统设置中心**\n"
        "--------------------------------\n"
        "你可以使用 `/set` 命令修改以下参数:\n\n"
        f"🔹 `run_mode`\n"
        f"   - **当前值**: {CONFIG.run_mode}\n"
        f"   - **说明**: 运行模式 (live/simulate)\n\n"
        f"🔹 `macro_coefficient`\n"
        f"   - **当前值**: {CONFIG.macro_coefficient}\n"
        f"   - **说明**: 宏观市场影响系数\n\n"
        f"🔹 `resonance_coefficient`\n"
        f"   - **当前值**: {CONFIG.resonance_coefficient}\n"
        f"   - **说明**: 信号共振强度系数\n"
        "--------------------------------\n"
        "**修改指令**:\n"
        "`/set <参数名> <新值>`\n\n"
        "**示例**:\n"
        "`/set macro_coefficient 0.9`"
    )
    await update.message.reply_text(report, parse_mode='Markdown')

@execute_safe
async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置一个可配置的参数，并使其立即、持久化生效"""
    try:
        parts = update.message.text.split()
        if len(parts) != 3:
            await update.message.reply_text("❌ **格式错误**\n请使用: `/set <参数名> <新值>`", parse_mode='Markdown')
            return
        
        _, key, value_str = parts
        
        allowed_keys = ['run_mode', 'macro_coefficient', 'resonance_coefficient']
        if key not in allowed_keys:
            await update.message.reply_text(f"❌ **无效的参数名**: `{key}`", parse_mode='Markdown')
            return

        # 根据 key 进行类型验证和转换
        new_value = None
        if key == 'run_mode':
            if value_str.lower() not in ['live', 'simulate']:
                await update.message.reply_text(f"❌ **无效的值**: `run_mode` 必须是 `live` 或 `simulate`。", parse_mode='Markdown')
                return
            new_value = value_str.lower()
        else: # macro_coefficient, resonance_coefficient
            try:
                new_value = float(value_str)
            except ValueError:
                await update.message.reply_text(f"❌ **无效的值**: `{key}` 必须是一个数字。", parse_mode='Markdown')
                return

        # 写入数据库并更新内存中的配置
        await set_setting(key, str(new_value))
        setattr(CONFIG, key, new_value) # 直接更新 CONFIG 对象的属性
        
        logger.info(f"✅ 系统设置已更新: {key} = {new_value}")
        await update.message.reply_text(f"✅ **设置已更新**\n`{key}` 已成功设置为 `{new_value}`。\n此设置**立即生效**。", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"设置参数失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 设置参数时发生内部错误。")

@execute_safe
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    positions = await get_open_positions()
    if not positions:
        await update.message.reply_text("📭 当前没有持仓。")
        return
    report = "📈 **当前持仓**:\n" + "\n".join([f"- {p['symbol']} ({p['trade_type']})" for p in positions])
    await update.message.reply_text(report, parse_mode='Markdown')

@execute_safe
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 **最近操作日志**:\n此功能暂未实现。")

# --- 4. Bot 启动与关闭逻辑 (最终稳定版) ---
async def start_bot(app_instance: FastAPI):
    """在FastAPI的生命周期中，安全地启动Telegram Bot"""
    logger.info("正在启动Telegram Bot...")
    application = app_instance.state.telegram_app
    
    # 添加所有命令和消息处理器
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("set", set_command)) # 新增 set 命令
    
    application.add_handler(MessageHandler(filters.Regex('^📊 系统状态$'), status_command))
    application.add_handler(MessageHandler(filters.Regex('^📈 当前持仓$'), positions_command))
    application.add_handler(MessageHandler(filters.Regex('^📋 操作日志$'), logs_command))
    application.add_handler(MessageHandler(filters.Regex('^⚙️ 设置$'), settings_command))
    
    # 修复了事件循环冲突的最终方案
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    logger.info("Telegram Bot 初始化完成，轮询已在后台开始。")

async def stop_bot(app_instance: FastAPI):
    """在FastAPI的生命周期中，安全地关闭Telegram Bot"""
    logger.info("正在关闭Telegram Bot...")
    application = app_instance.state.telegram_app
    
    if application.updater and application.updater.running:
        await application.updater.stop()
    await application.stop()
    await application.shutdown()
    
    logger.info("Telegram Bot 轮询已停止。")
