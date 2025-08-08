from sqlalchemy import text
import logging
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from typing import Optional, Dict, Any
from fastapi import FastAPI # 【修改】导入 FastAPI 用于类型注解
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
                conn = db_pool.get_simple_session()
                try:
                    cursor = await conn.execute(text('SELECT symbol, status FROM tv_status'))
                    rows = await cursor.fetchall()
                    tv_status = {row['symbol']: row['status'] for row in rows}
                    
                    app_state._macro_status = {
                        'trend': '未知',
                        'btc1d': tv_status.get('btc', CONFIG.default_btc_status),
                        'eth1d': tv_status.get('eth', CONFIG.default_eth_status),
                        'confidence': 0,
                        'last_update': current_time
                    }
                    app_state._last_macro_update = current_time
                finally:
                    await conn.close()
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

    # --- 【修改】将重复逻辑提取到这个辅助函数中 ---
    async def _create_status_embed(self) -> discord.Embed:
        """创建一个包含当前系统状态的 Discord Embed 对象"""
        embed = discord.Embed(
            title="📊 系统状态",
            color=discord.Color.green()
        )
        embed.add_field(name="运行模式", value=CONFIG.run_mode)
        embed.add_field(name="Bot状态", value="🟢 在线")
        embed.add_field(name="延迟", value=f"{round(self.bot.latency * 1000)} ms")
        
        macro_status = await self.get_macro_status()
        macro_text = f"""宏观：{macro_status.get('trend', '未知')}
BTC1d ({macro_status.get('btc1d', '未知')})
ETH1d ({macro_status.get('eth1d', '未知')})"""
        embed.add_field(name="🌍 宏观状态", value=macro_text, inline=False)
        
        return embed

    # --- 【修改】简化 text_status，调用辅助函数 ---
    @commands.command(name="status", help="查看系统状态")
    async def text_status(self, ctx: commands.Context):
        """查看系统状态 - 文本命令版本"""
        try:
            embed = await self._create_status_embed()
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"status 命令执行失败: {e}")
            await ctx.send("❌ 获取系统状态失败", ephemeral=True)

    # --- 【修改】简化 slash_status，调用辅助函数 ---
    @app_commands.command(name="status", description="查看系统状态")
    async def slash_status(self, interaction: discord.Interaction):
        """查看系统状态 - 斜杠命令版本"""
        try:
            await interaction.response.defer(ephemeral=True)
            embed = await self._create_status_embed()
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"slash status 命令执行失败: {e}")
            await interaction.followup.send("❌ 获取系统状态失败", ephemeral=True)

# ================= 生命周期管理 =================
# --- 【修改】将 app: Any 改为 app: FastAPI ---
async def initialize_bot(bot: commands.Bot, app: FastAPI):
    """初始化 Discord Bot"""
    try:
        bot.app = app
        bot.remove_command('help')
        
        await bot.add_cog(TradingCommands(bot))
        logger.info("✅ 交易系统命令Cog已添加")
        
        from src.discord_ui import TradingDashboard
        await bot.add_cog(TradingDashboard(bot))
        logger.info("✅ 交易面板Cog已添加")
        
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

# --- 【修改】将 app: Any 改为 app: FastAPI ---
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
