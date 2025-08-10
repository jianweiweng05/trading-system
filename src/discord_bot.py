
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
        
        @_bot_instance.before_invoke
        async def before_any_command(ctx: commands.Context):
            logger.info(f"🟢 用户 {ctx.author} 调用了命令: {ctx.command} 内容: {ctx.message.content}")

        @_bot_instance.after_invoke
        async def after_any_command(ctx: commands.Context):
            logger.info(f"✅ 命令 {ctx.command} 执行完成")

        @_bot_instance.event
        async def on_command_error(ctx: commands.Context, error: Exception):
            logger.error(f"❌ 命令 {ctx.command} 出错: {error}")
            if not ctx.response.is_done():
                await ctx.send(f"⚠️ 命令执行失败: {str(error)}", ephemeral=True)
    
    return _bot_instance

# ================= Bot 命令 Cog =================
class TradingCommands(commands.Cog, name="交易系统"):
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

    # --- 【修改】移除了不必要的 _create_status_embed 和旧的 status 命令 ---

    @app_commands.command(name="status", description="显示系统主控制面板")
    async def status(self, interaction: discord.Interaction):
        """显示统一的、交互式的主控制面板"""
        try:
            await interaction.response.defer(ephemeral=True)

            embed = discord.Embed(title="🎛️ 主控制面板", color=discord.Color.blue())
            embed.description = "使用下方按钮查看详细信息或进行操作。"
            
            app_state = self.bot.app.state
            trading_engine = getattr(app_state, 'trading_engine', None)
            
            macro_status = await self.get_macro_status()
            macro_text = f"**宏观季节**: {macro_status.get('trend', '未知')}\n"
            macro_text += f"**BTC 1D**: {macro_status.get('btc1d', '未知')}\n"
            macro_text += f"**ETH 1D**: {macro_status.get('eth1d', '未知')}"
            embed.add_field(name="🌍 宏观状态", value=macro_text, inline=True)

            pnl_text = "无"
            position_text = "无持仓"
            if trading_engine:
                positions = await trading_engine.get_position("*")
                if positions:
                    total_pnl = sum(float(p.get('pnl', 0)) for p in positions.values() if p)
                    pnl_text = f"{'🟢' if total_pnl >= 0 else '🔴'} ${total_pnl:,.2f}"
                    active_positions = [f"{p['symbol']} ({'多' if float(p.get('size',0)) > 0 else '空'})" 
                                        for p in positions.values() if p and float(p.get('size', 0)) != 0]
                    if active_positions:
                        position_text = ", ".join(active_positions)

            embed.add_field(name="📈 核心持仓", value=position_text, inline=True)
            embed.add_field(name="💰 今日浮盈", value=pnl_text, inline=True)

            alert_system = getattr(app_state, 'alert_system', None)
            alert_status_text = "⚪ 未启用"
            if alert_system:
                alert_status = alert_system.get_status()
                alert_status_text = f"{'🔴' if alert_status.get('active') else '🟢'} 正常"
            embed.add_field(name="🚨 报警状态", value=alert_status_text, inline=True)

            pool_text = "⚪ 未启用"
            if trading_engine:
                pool_data = trading_engine.get_resonance_pool()
                pool_text = f"⏳ {pool_data.get('pending_count', 0)} 个待处理"
            embed.add_field(name="📡 共振池", value=pool_text, inline=True)

            embed.set_footer(text=f"模式: {CONFIG.run_mode.upper()} | 最后刷新于")
            embed.timestamp = discord.utils.utcnow()

            from src.discord_ui import MainPanelView
            await interaction.followup.send(embed=embed, view=MainPanelView(self.bot), ephemeral=True)

        except Exception as e:
            logger.error(f"status 命令执行失败: {e}", exc_info=True)
            await interaction.followup.send("❌ 获取主面板失败，请检查日志。", ephemeral=True)

# ================= 生命周期管理 =================
async def initialize_bot(bot: commands.Bot, app: FastAPI):
    """初始化 Discord Bot"""
    try:
        bot.app = app
        bot.remove_command('help')
        
        # --- 【修改】确保 TradingCommands Cog 被正确添加 ---
        await bot.add_cog(TradingCommands(bot))
        logger.info("✅ 交易系统命令Cog已添加")

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
