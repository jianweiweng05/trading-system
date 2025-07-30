# 文件: src/telegram_bot.py (请完整复制)

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
from database import get_open_positions, get_setting, set_setting

logger = logging.getLogger(__name__)

# --- 1. 键盘布局 ---
MAIN_KEYBOARD = [
    ["📊 系统状态", "⚙️ 设置"],
    ["📈 当前持仓", "📋 操作日志"],
]
REPLY_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

# --- 2. 命令处理器 ---
@execute_safe
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **交易机器人指挥中心**\n请使用下方仪表盘操作。", reply_markup=REPLY_MARKUP, parse_mode='Markdown')

@execute_safe
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示所有可配置的参数"""
    try:
        run_mode = await get_setting('run_mode', 'N/A')
        macro_coefficient = await get_setting('macro_coefficient', 'N/A')
        resonance_coefficient = await get_setting('resonance_coefficient', 'N/A')

        report = (
            f"⚙️ **系统当前设置**\n"
            "--------------------------------\n"
            f"🔹 **运行模式 (run_mode)**: `{run_mode.upper()}`\n"
            f"🔹 **宏观系数 (macro_coefficient)**: `{macro_coefficient}`\n"
            f"🔹 **共振系数 (resonance_coefficient)**: `{resonance_coefficient}`\n"
            f"🔹 **杠杆 (leverage)**: `3` (固定值)\n"
            "--------------------------------\n"
            "**修改指令**:\n"
            "`/set <参数名> <新值>`\n\n"
            "**示例**:\n"
            "`/set macro_coefficient 0.9`"
        )
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"获取设置失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 获取设置时发生错误。")

@execute_safe
async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置一个可配置的参数"""
    try:
        # 1. 解析输入
        parts = update.message.text.split()
        if len(parts) != 3:
            await update.message.reply_text("❌ **格式错误**\n请使用: `/set <参数名> <新值>`", parse_mode='Markdown')
            return
        
        _, key, value = parts
        
        # 2. 验证参数名是否合法
        allowed_keys = ['run_mode', 'macro_coefficient', 'resonance_coefficient']
        if key not in allowed_keys:
            await update.message.reply_text(f"❌ **无效的参数名**: `{key}`\n合法的参数名包括: `{', '.join(allowed_keys)}`", parse_mode='Markdown')
            return

        # 3. 验证值是否合法 (可根据需要扩展)
        if key in ['macro_coefficient', 'resonance_coefficient']:
            try:
                float(value)
            except ValueError:
                await update.message.reply_text(f"❌ **无效的值**: `{key}` 必须是一个数字。", parse_mode='Markdown')
                return
        
        if key == 'run_mode' and value.lower() not in ['live', 'simulate']:
            await update.message.reply_text(f"❌ **无效的值**: `run_mode` 必须是 `live` 或 `simulate`。", parse_mode='Markdown')
            return

        # 4. 写入数据库并更新内存中的配置
        await set_setting(key, value.lower())
        setattr(CONFIG.strategy, key, value.lower() if key == 'run_mode' else float(value))
        
        logger.info(f"✅ 设置已更新: {key} = {value}")
        await update.message.reply_text(f"✅ **设置已更新**\n`{key}` 已成功设置为 `{value}`。\n此设置**立即生效**。", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"设置参数失败: {e}", exc_info=True)
        await update.message.reply_text("⚠️ 设置参数时发生内部错误。")

# (其他 status_command, positions_command 等命令保持不变)
# (execute_safe 装饰器, start_bot, stop_bot 等也保持我们最终的稳定版本不变)
