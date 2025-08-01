import discord
from discord.ext import commands
from config import CONFIG

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=CONFIG.discord_prefix,
    intents=intents
)

@bot.event
async def on_ready():
    channel = bot.get_channel(int(CONFIG.discord_channel_id))
    await channel.send("🤖 交易系统已连接")

@bot.command()
async def status(ctx):
    """查看系统状态"""
    embed = discord.Embed(title="📊 系统状态")
    embed.add_field(name="运行模式", value=CONFIG.run_mode)
    await ctx.send(embed=embed)

# 保持与原有Telegram相同的功能函数名
async def initialize_bot(app):
    """替换原telegram_bot的初始化"""
    app.state.discord_bot = bot
    await bot.start(CONFIG.discord_token)

async def stop_bot_services(app):
    """替换原telegram关闭逻辑"""
    if hasattr(app.state, 'discord_bot'):
        await bot.close()
