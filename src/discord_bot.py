import logging
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from typing import Optional, Dict, Any
from src.config import CONFIG

# ================= 日志配置 =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("discord_bot")

# ================= Discord Bot 实例 =================
# 创建一个全局的Discord机器人实例
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
        
        # 添加on_ready事件
        @_bot_instance.event
        async def on_ready():
            channel = _bot_instance.get_channel(int(CONFIG.discord_channel_id))
            if channel:
                await channel.send("🤖 交易系统已连接")
                logger.info("✅ Discord Bot 已发送连接成功消息")
            else:
                logger.warning("⚠️ 找不到指定的频道，请检查 CONFIG.discord_channel_id 是否正确")
            logger.info(f"✅ Discord Bot 已登录: {_bot_instance.user}")
            
            # 🔑 同步 Slash Commands
            try:
                synced = await _bot_instance.tree.sync()
                logger.info(f"✅ 同步 Slash 命令成功: {len(synced)} 个命令")
            except Exception as e:
                logger.error(f"❌ 同步 Slash 命令失败: {e}")
        
        # 添加命令日志
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
        self.bot.bot_data: Dict[str, Any] = {
            'exchange': None,
            'db_pool': None
        }
    
    async def check_exchange_status(self) -> bool:
        """检查交易所连接状态"""
        try:
            # 检查是否有交易所数据
            if not hasattr(self.bot, 'bot_data') or 'exchange' not in self.bot.bot_data:
                return False
            
            exchange = self.bot.bot_data['exchange']
            
            # 检查交易所对象是否有效
            if not exchange:
                return False
            
            # 尝试获取服务器时间来验证连接
            try:
                await exchange.fetch_time()
                return True
            except Exception as e:
                logger.error(f"验证交易所连接失败: {e}")
                return False
                
        except Exception as e:
            logger.error(f"检查交易所状态失败: {e}")
            return False
    
    # 旧版文本命令（!status）
    @commands.command(name="status", help="查看系统状态")
    async def text_status(self, ctx: commands.Context):
        """查看系统状态 - 文本命令版本"""
        try:
            embed = discord.Embed(
                title="📊 系统状态",
                color=discord.Color.green()
            )
            embed.add_field(name="运行模式", value=CONFIG.run_mode)
            embed.add_field(name="Bot状态", value="🟢 在线")
            embed.add_field(name="延迟", value=f"{round(self.bot.latency * 1000)} ms")
            
            # 检查交易所连接状态
            exchange_status = await self.check_exchange_status()
            if exchange_status:
                embed.add_field(name="交易所连接", value="🟢 已连接", inline=False)
            else:
                embed.add_field(name="交易所连接", value="🔴 未连接，有问题。", inline=False)
            
            await ctx.send(embed=embed)
            logger.info(f"✅ 用户 {ctx.author} 查看了系统状态")
        except Exception as e:
            logger.error(f"status 命令执行失败: {e}")
            if not ctx.response.is_done():
                await ctx.send("❌ 获取系统状态失败", ephemeral=True)
    
    # 新版 Slash 命令（/status）
    @app_commands.command(name="status", description="查看系统状态")
    async def slash_status(self, interaction: discord.Interaction):
        """查看系统状态 - 斜杠命令版本"""
        try:
            embed = discord.Embed(
                title="📊 系统状态",
                color=discord.Color.green()
            )
            embed.add_field(name="运行模式", value=CONFIG.run_mode)
            embed.add_field(name="Bot状态", value="🟢 在线")
            embed.add_field(name="延迟", value=f"{round(self.bot.latency * 1000)} ms")
            
            # 检查交易所连接状态
            exchange_status = await self.check_exchange_status()
            if exchange_status:
                embed.add_field(name="交易所连接", value="🟢 已连接", inline=False)
            else:
                embed.add_field(name="交易所连接", value="🔴 未连接，有问题。", inline=False)
            
            await interaction.response.send_message(embed=embed)
            logger.info(f"✅ 用户 {interaction.user} 查看了系统状态")
        except discord.errors.InteractionResponded:
            logger.error("交互已响应，无法再次发送响应")
        except Exception as e:
            logger.error(f"slash status 命令执行失败: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 获取系统状态失败", ephemeral=True)

# ================= 生命周期管理 =================
async def initialize_bot(bot: commands.Bot):
    """初始化 Discord Bot"""
    try:
        # 初始化数据库连接池
        from src.database import db_pool
        bot.bot_data['db_pool'] = db_pool
        
        # 等待交易所连接建立
        max_retries = 20
        retry_delay = 2
        
        for i in range(max_retries):
            if hasattr(bot, 'bot_data') and bot.bot_data.get('exchange'):
                logger.info("✅ 交易所连接已就绪，启动Discord机器人")
                break
            if i < max_retries - 1:
                logger.info(f"等待交易所连接建立... ({i + 1}/{max_retries})")
                await asyncio.sleep(retry_delay)
        else:
            logger.warning("⚠️ 交易所连接未就绪，Discord机器人仍将启动")
        
        # 验证交易所连接
        if bot.bot_data.get('exchange'):
            try:
                await bot.bot_data['exchange'].fetch_time()
                logger.info("✅ 交易所连接验证成功")
            except Exception as e:
                logger.error(f"❌ 交易所连接验证失败: {e}")
                bot.bot_data['exchange'] = None
        
        # 移除默认的help命令
        bot.remove_command('help')
        
        # 添加交易系统命令Cog
        await bot.add_cog(TradingCommands(bot))
        logger.info("✅ 交易系统命令Cog已添加")
        
        # 添加交易面板Cog
        from src.discord_ui import TradingDashboard
        await bot.add_cog(TradingDashboard(bot))
        logger.info("✅ 交易面板Cog已添加")
        
        logger.info("🚀 正在启动 Discord Bot")
        
        # 启动Discord机器人
        await bot.start(CONFIG.discord_token)
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        raise

async def stop_bot_services(bot: commands.Bot):
    """关闭 Discord Bot"""
    if bot.is_ready():
        await bot.close()
        logger.info("🛑 Discord Bot 已关闭")

async def start_discord_bot():
    """启动Discord Bot的入口函数"""
    bot = get_bot()
    try:
        await initialize_bot(bot)
    except Exception as e:
        logger.error(f"Discord Bot 启动失败: {e}")
        raise

# ================= 导出配置 =================
__all__ = ['get_bot', 'initialize_bot', 'stop_bot_services', 'start_discord_bot']
