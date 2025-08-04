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
    
    @commands.command(name="help", help="显示帮助信息")
    async def help(self, ctx, command_name=None):
        """显示可用命令的帮助信息"""
        if command_name:
            # 显示特定命令的帮助
            command = self.bot.get_command(command_name)
            if command:
                embed = discord.Embed(
                    title=f"命令: {CONFIG.discord_prefix}{command.name}",
                    description=command.help or "无描述",
                    color=discord.Color.blue()
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"找不到命令: {command_name}")
        else:
            # 显示所有命令的帮助
            embed = discord.Embed(
                title="交易系统帮助",
                description=f"以下是可用的命令 (前缀: {CONFIG.discord_prefix}):",
                color=discord.Color.blue()
            )
            
            # 按分类添加命令
            for cog_name, cog in self.bot.cogs.items():
                commands_list = []
                for command in cog.get_commands():
                    if not command.hidden:
                        commands_list.append(f"**{CONFIG.discord_prefix}{command.name}** - {command.help or '无描述'}")
                
                if commands_list:
                    embed.add_field(name=cog_name, value="\n".join(commands_list), inline=False)
            
            await ctx.send(embed=embed)

# ================= 生命周期管理 =================
async def initialize_bot(app):
    """初始化 Discord Bot"""
    # 添加Cog
    await bot.add_cog(TradingCommands(bot))
    logger.info("✅ 交易系统命令Cog已添加")
    
    app.state.discord_bot = bot
    logger.info("🚀 正在启动 Discord Bot")
    await bot.start(CONFIG.discord_token)

async def stop_bot_services(app):
    """关闭 Discord Bot"""
    if hasattr(app.state, 'discord_bot'):
        await bot.close()
        logger.info("🛑 Discord Bot 已关闭")

# ================= 导出配置 =================
__all__ = ['initialize_bot', 'stop_bot_services']
