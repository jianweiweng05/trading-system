import logging
import discord
from discord.ext import commands
from src.config import CONFIG

# ================= 日志配置 =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("discord_bot")

# ================= Discord Bot 初始化 =================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=CONFIG.discord_prefix,
    intents=intents
)

# ================= Bot 事件处理 =================
@bot.event
async def on_ready():
    """Bot 成功启动事件"""
    channel = bot.get_channel(int(CONFIG.discord_channel_id))
    if channel:
        await channel.send("🤖 交易系统已连接")
        logger.info("✅ Discord Bot 已发送连接成功消息")
    else:
        logger.warning("⚠️ 找不到指定的频道，请检查 CONFIG.discord_channel_id 是否正确")
    logger.info(f"✅ Discord Bot 已登录: {bot.user}")

# ================= 命令日志 =================
@bot.before_invoke
async def before_any_command(ctx):
    logger.info(f"🟢 用户 {ctx.author} 调用了命令: {ctx.command} 内容: {ctx.message.content}")

@bot.after_invoke
async def after_any_command(ctx):
    logger.info(f"✅ 命令 {ctx.command} 执行完成")

@bot.event
async def on_command_error(ctx, error):
    logger.error(f"❌ 命令 {ctx.command} 出错: {error}")
    await ctx.send(f"⚠️ 命令执行失败: {str(error)}")

# ================= Bot 命令 Cog =================
class TradingCommands(commands.Cog, name="交易系统"):
    """交易系统相关命令"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="status", help="查看系统状态")
    async def status(self, ctx):
        """查看系统状态"""
        try:
            embed = discord.Embed(
                title="📊 系统状态",
                color=discord.Color.green()
            )
            embed.add_field(name="运行模式", value=CONFIG.run_mode)
            embed.add_field(name="Bot状态", value="🟢 在线")
            embed.add_field(name="延迟", value=f"{round(self.bot.latency * 1000)} ms")
            
            # 如果有交易所数据，添加到状态中
            if hasattr(self.bot, 'bot_data') and 'exchange' in self.bot.bot_data:
                embed.add_field(name="交易所连接", value="🟢 已连接", inline=False)
            else:
                embed.add_field(name="交易所连接", value="🔴 未连接", inline=False)
            
            await ctx.send(embed=embed)
            logger.info(f"✅ 用户 {ctx.author} 查看了系统状态")
        except Exception as e:
            logger.error(f"status 命令执行失败: {e}")
            await ctx.send("❌ 获取系统状态失败")

# ================= 生命周期管理 =================
async def initialize_bot(bot):
    """初始化 Discord Bot"""
    try:
        # 移除默认的help命令
        bot.remove_command('help')
        
        # 添加Cog
        await bot.add_cog(TradingCommands(bot))
        logger.info("✅ 交易系统命令Cog已添加")
        
        logger.info("🚀 正在启动 Discord Bot")
        
        # 启动Discord机器人
        await bot.start(CONFIG.discord_token)
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        raise

async def stop_bot_services(bot):
    """关闭 Discord Bot"""
    if bot.is_ready():
        await bot.close()
        logger.info("🛑 Discord Bot 已关闭")

# ================= 导出配置 =================
__all__ = ['initialize_bot', 'stop_bot_services']
