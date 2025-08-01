import discord
from discord.ext import commands, tasks
from config import CONFIG

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=CONFIG.discord_prefix, 
    intents=intents,
    help_command=None  # 禁用默认help命令
)

class TradingView(discord.ui.View):
    """交易控制面板"""
    def __init__(self):
        super().__init__(timeout=None)  # 永久存活
    
    @discord.ui.button(label="暂停策略", style=discord.ButtonStyle.red)
    async def pause_strategy(self, interaction, button):
        # 调用原有交易暂停逻辑
        await interaction.response.edit_message(content="⏸️ 策略已暂停")

@bot.event
async def on_ready():
    """Bot上线初始化"""
    channel = bot.get_channel(int(CONFIG.discord_channel_id))
    await channel.send(embed=discord.Embed(
        title="📈 交易系统已连接",
        description=f"模式: {CONFIG.run_mode.upper()}",
        color=0x00ff00
    ))
    status_update.start()  # 启动状态轮询

@tasks.loop(seconds=10)
async def status_update():
    """自动推送状态更新"""
    channel = bot.get_channel(int(CONFIG.discord_channel_id))
    embed = discord.Embed(title="系统状态")
    embed.add_field(name="持仓", value=get_positions())
    await channel.send(embed=embed)

@bot.command()
async def start(ctx):
    """启动命令"""
    await ctx.send(
        "请选择操作:", 
        view=TradingView(),
        embed=discord.Embed(color=0x7289da).add_field(
            name="指令列表",
            value="!status - 实时状态\n!positions - 当前持仓"
        )
    )
