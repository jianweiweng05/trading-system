
import logging
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from typing import Optional, Dict, Any
from fastapi import FastAPI
from sqlalchemy import text
from src.config import CONFIG

# ================= 日志配置 =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("discord_bot")

# ================= Discord Bot 实例 =================
_bot_instance: Optional[commands.Bot] = None

def get_bot() -> commands.Bot:
    """获取Discord机器人实例"""
    global _bot_instance
    if _bot_instance is None:
        intents = discord.Intents.default()
        intents.message_content = True
        _bot_instance = commands.Bot(
            command_prefix=CONFIG.discord_prefix,
            intents=intents
        )
        
        @_bot_instance.event
        async def on_ready():
            channel_id = int(CONFIG.discord_channel_id) if CONFIG.discord_channel_id else None
            if channel_id:
                channel = _bot_instance.get_channel(channel_id)
                if channel:
                    await channel.send("🤖 交易系统已连接")
                    logger.info("✅ Discord Bot 已发送连接成功消息")
                else:
                    logger.warning(f"⚠️ 找不到指定的频道 ID: {channel_id}")
            else:
                logger.warning("⚠️ 未配置 discord_channel_id")

            logger.info(f"✅ Discord Bot 已登录: {_bot_instance.user}")
            
            try:
                synced = await _bot_instance.tree.sync()
                logger.info(f"✅ 同步 Slash 命令成功: {len(synced)} 个命令")
            except Exception as e:
                logger.error(f"❌ 同步 Slash 命令失败: {e}")
        
        @_bot_instance.event
        async def on_command_error(ctx: commands.Context, error: Exception):
            logger.error(f"❌ 命令 {ctx.command} 出错: {error}")
            # 这个事件处理器主要用于旧的文本命令，对于 Slash Command 的错误处理通常在命令内部完成
            # 为保险起见，保留一个通用的反馈
            if isinstance(ctx, discord.Interaction):
                if not ctx.response.is_done():
                    await ctx.response.send_message(f"⚠️ 命令执行失败: {str(error)}", ephemeral=True)
            else:
                await ctx.send(f"⚠️ 命令执行失败: {str(error)}", ephemeral=True)

    return _bot_instance

# ================= Bot 命令 Cog =================
class TradingCommands(commands.Cog, name="TradingCommands"): # 【修改】使用英文类名作为 Cog 的内部名称
    """交易系统相关命令"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def get_macro_status(self) -> Dict[str, Any]:
        """获取宏观状态信息"""
        current_time = asyncio.get_event_loop().time()
        app_state = self.bot.app.state
        
        if (not hasattr(app_state, '_macro_status') or 
            current_time - getattr(app_state, '_last_macro_update', 0) > 300):
            
            logger.info("更新宏观状态缓存...")
            try:
                from src.database import db_pool
                async with db_pool.get_session() as session:
                    result = await session.execute(text('SELECT symbol, status FROM tv_status'))
                    rows = result.fetchall()
                
                tv_status = {row[0]: row[1] for row in rows}
                
                app_state._macro_status = {
                    'trend': '未知',
                    'btc1d': tv_status.get('btc', CONFIG.default_btc_status),
                    'eth1d': tv_status.get('eth', CONFIG.default_eth_status),
                    'confidence': 0,
                    'last_update': current_time
                }
                app_state._last_macro_update = current_time
                
            except Exception as e:
                logger.error(f"获取宏观状态失败: {e}")
                if not hasattr(app_state, '_macro_status'):
                    app_state._macro_status = {
                        'trend': '未知',
                        'btc1d': CONFIG.default_btc_status,
                        'eth1d': CONFIG.default_eth_status,
                        'confidence': 0,
                        'last_update': current_time
                    }
        
        return getattr(app_state, '_macro_status', {}).copy()

    # --- 【修改】这是现在唯一的 UI 命令 ---
    @app_commands.command(name="status", description="显示系统主控制面板")
    async def status(self, interaction: discord.Interaction):
        """显示统一的、交互式的主控制面板"""
        try:
            # 【修改】使用 edit_or_send 逻辑来处理刷新
            if interaction.message:
                await interaction.response.defer()
            else:
                await interaction.response.defer(ephemeral=True)

            # 导入并使用新的 UI View
            from src.discord_ui import MainPanelView
            view = MainPanelView(self.bot)
            embed = await view._get_main_panel_embed() # 调用辅助函数生成 embed

            if interaction.message:
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"status 命令执行失败: {e}", exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send("❌ 获取主面板失败，请检查日志。", ephemeral=True)
            else:
                await interaction.response.send_message("❌ 获取主面板失败，请检查日志。", ephemeral=True)

# ================= 生命周期管理 =================
async def initialize_bot(bot: commands.Bot, app: FastAPI):
    """初始化 Discord Bot"""
    try:
        bot.app = app
        bot.remove_command('help')
        
        await bot.add_cog(TradingCommands(bot))
        logger.info("✅ 交易系统命令Cog已添加")
        
        # 【修改】移除了加载旧的 TradingDashboard 的代码
        
        logger.info("🚀 正在启动 Discord Bot")
        await bot.start(CONFIG.discord_token)
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        raise

async def stop_bot_services():
    """关闭 Discord Bot"""
    bot = get_bot()
    if bot and bot.is_ready():
        await bot.close()
        logger.info("🛑 Discord Bot 已关闭")

async def start_discord_bot(app: FastAPI):
    """启动Discord Bot的入口函数"""
    bot = get_bot()
    try:
        await initialize_bot(bot, app)
    except Exception as e:
        logger.error(f"Discord Bot 启动失败: {e}")
        pass

# ================= 导出配置 =================
__all__ = ['get_bot', 'start_discord_bot', 'stop_bot_services']
