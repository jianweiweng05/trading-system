import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
from datetime import datetime
from typing import Optional

from src.config import CONFIG
from src.system_state import SystemState
from src.database import get_db_connection

logger = logging.getLogger("discord_bot")

# 全局变量
_bot_instance = None

def get_bot():
    """获取Discord机器人实例"""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = TradingBot()
    return _bot_instance

async def initialize_bot(bot):
    """初始化Discord机器人"""
    try:
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
        
        await bot.start(CONFIG.discord_token)
    except Exception as e:
        logger.error(f"Discord机器人初始化失败: {e}")
        raise

async def stop_bot_services(bot):
    """停止Discord机器人服务"""
    try:
        await bot.close()
        logger.info("✅ Discord服务已停止")
    except Exception as e:
        logger.error(f"停止Discord服务失败: {e}")

class TradingBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="市场动态"
            )
        )
        self.initialized = False
        self.bot_data = {}  # 添加这行

    async def setup_hook(self):
        """设置机器人启动时的钩子"""
        # 添加命令Cog
        await self.add_cog(TradingCommands(self))
        await self.add_cog(TradingPanel(self))
        logger.info("✅ 交易系统命令Cog已添加")
        logger.info("✅ 交易面板Cog已添加")

    async def on_ready(self):
        """机器人启动完成时的回调"""
        if not self.initialized:
            logger.info("🚀 正在启动 Discord Bot")
            self.initialized = True
            
            # 同步斜杠命令
            try:
                synced = await self.tree.sync()
                logger.info(f"✅ 同步 Slash 命令成功: {len(synced)} 个命令")
            except Exception as e:
                logger.error(f"❌ 同步 Slash 命令失败: {e}")

            # 发送启动通知
            if CONFIG.discord_notification_channel:
                channel = self.get_channel(CONFIG.discord_notification_channel)
                if channel:
                    await channel.send("🚀 交易系统已启动")
                    logger.info("✅ Discord Bot 已发送连接成功消息")

            logger.info(f"✅ Discord Bot 已登录: {self.user}")

class TradingCommands(commands.Cog):
    """交易命令相关的Cog"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="status", description="查看系统状态")
    async def slash_status(self, interaction: discord.Interaction):
        try:
            # 获取系统状态信息
            embed = discord.Embed(
                title="系统状态",
                description="当前系统运行状态",
                color=discord.Color.blue()
            )
            
            # 添加状态信息
            state = await SystemState.get_state()
            embed.add_field(name="当前状态", value=state, inline=False)
            
            # 首次响应
            await interaction.response.defer(ephemeral=True)  # 先延迟响应
            
            # 然后发送实际消息
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            logger.info(f"✅ 用户 {interaction.user.name} 查看了系统状态")
            
        except Exception as e:
            logger.error(f"斜杠状态命令执行失败: {str(e)}", exc_info=True)
            # 只有在尚未响应的情况下才能发送错误消息
            if not interaction.response.is_done():
                await interaction.response.send_message("❌获取系统状态失败", ephemeral=True)

    @app_commands.command(name="trading_start", description="启动交易系统")
    async def slash_trading_start(self, interaction: discord.Interaction):
        try:
            await SystemState.set_state("ACTIVE")
            await interaction.response.send_message("✅ 交易系统已启动", ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user.name} 启动了交易系统")
        except Exception as e:
            logger.error(f"启动交易系统失败: {str(e)}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌启动交易系统失败", ephemeral=True)

    @app_commands.command(name="trading_stop", description="停止交易系统")
    async def slash_trading_stop(self, interaction: discord.Interaction):
        try:
            await SystemState.set_state("STOPPED")
            await interaction.response.send_message("✅ 交易系统已停止", ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user.name} 停止了交易系统")
        except Exception as e:
            logger.error(f"停止交易系统失败: {str(e)}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌停止交易系统失败", ephemeral=True)

    @app_commands.command(name="emergency_stop", description="紧急停止")
    async def slash_emergency_stop(self, interaction: discord.Interaction):
        try:
            await SystemState.set_state("EMERGENCY")
            await interaction.response.send_message("⚠️ 已触发紧急停止", ephemeral=True)
            logger.warning(f"⚠️ 用户 {interaction.user.name} 触发了紧急停止")
        except Exception as e:
            logger.error(f"紧急停止失败: {str(e)}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌紧急停止失败", ephemeral=True)

    @app_commands.command(name="set_risk", description="设置风险级别")
    @app_commands.describe(level="风险级别 (LOW/MEDIUM/HIGH)")
    async def slash_set_risk(self, interaction: discord.Interaction, level: str):
        try:
            level = level.upper()
            if level not in ["LOW", "MEDIUM", "HIGH"]:
                await interaction.response.send_message("❌ 无效的风险级别", ephemeral=True)
                return
            
            await SystemState.set_risk_level(level)
            await interaction.response.send_message(f"✅ 风险级别已设置为: {level}", ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user.name} 设置风险级别为: {level}")
        except Exception as e:
            logger.error(f"设置风险级别失败: {str(e)}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌设置风险级别失败", ephemeral=True)

class TradingPanel(commands.Cog):
    """交易面板相关的Cog"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="panel", description="显示交易控制面板")
    async def slash_panel(self, interaction: discord.Interaction):
        try:
            embed = discord.Embed(
                title="交易控制面板",
                description="系统控制面板",
                color=discord.Color.green()
            )
            
            # 添加控制选项
            state = await SystemState.get_state()
            embed.add_field(name="当前状态", value=state, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user.name} 查看了交易面板")
            
        except Exception as e:
            logger.error(f"显示交易面板失败: {str(e)}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌显示交易面板失败", ephemeral=True)

    @app_commands.command(name="positions", description="查看当前持仓")
    async def slash_positions(self, interaction: discord.Interaction):
        try:
            async with get_db_connection() as db:
                positions = await db.fetchall("SELECT * FROM positions")
            
            embed = discord.Embed(
                title="当前持仓",
                description="系统当前持仓情况",
                color=discord.Color.orange()
            )
            
            for pos in positions:
                embed.add_field(
                    name=f"{pos['symbol']} ({pos['side']})",
                    value=f"数量: {pos['size']}\n入场价: {pos['entry_price']}\n当前盈亏: {pos['pnl']}",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user.name} 查看了持仓信息")
            
        except Exception as e:
            logger.error(f"查看持仓失败: {str(e)}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌查看持仓失败", ephemeral=True)

    @app_commands.command(name="orders", description="查看当前订单")
    async def slash_orders(self, interaction: discord.Interaction):
        try:
            async with get_db_connection() as db:
                orders = await db.fetchall("SELECT * FROM orders WHERE status = 'OPEN'")
            
            embed = discord.Embed(
                title="当前订单",
                description="系统当前未完成订单",
                color=discord.Color.purple()
            )
            
            for order in orders:
                embed.add_field(
                    name=f"{order['symbol']} {order['type']}",
                    value=f"方向: {order['side']}\n价格: {order['price']}\n数量: {order['amount']}",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user.name} 查看了订单信息")
            
        except Exception as e:
            logger.error(f"查看订单失败: {str(e)}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌查看订单失败", ephemeral=True)

    @app_commands.command(name="balance", description="查看账户余额")
    async def slash_balance(self, interaction: discord.Interaction):
        try:
            async with get_db_connection() as db:
                balance = await db.fetchone("SELECT * FROM balance")
            
            embed = discord.Embed(
                title="账户余额",
                description="当前账户余额情况",
                color=discord.Color.gold()
            )
            
            if balance:
                embed.add_field(name="总资产", value=f"{balance['total_balance']:.2f} USDT", inline=False)
                embed.add_field(name="可用余额", value=f"{balance['available_balance']:.2f} USDT", inline=False)
                embed.add_field(name="持仓保证金", value=f"{balance['position_margin']:.2f} USDT", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user.name} 查看了账户余额")
            
        except Exception as e:
            logger.error(f"查看余额失败: {str(e)}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌查看余额失败", ephemeral=True)

    @app_commands.command(name="pnl", description="查看盈亏情况")
    async def slash_pnl(self, interaction: discord.Interaction):
        try:
            async with get_db_connection() as db:
                pnl = await db.fetchone("SELECT * FROM pnl_summary")
            
            embed = discord.Embed(
                title="盈亏统计",
                description="系统盈亏统计情况",
                color=discord.Color.dark_green()
            )
            
            if pnl:
                embed.add_field(name="今日盈亏", value=f"{pnl['daily_pnl']:.2f} USDT", inline=False)
                embed.add_field(name="总盈亏", value=f"{pnl['total_pnl']:.2f} USDT", inline=False)
                embed.add_field(name="胜率", value=f"{pnl['win_rate']:.2%}", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user.name} 查看了盈亏统计")
            
        except Exception as e:
            logger.error(f"查看盈亏失败: {str(e)}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌查看盈亏失败", ephemeral=True)

async def start_discord_bot():
    """启动Discord Bot的入口函数"""
    bot = get_bot()
    try:
        await initialize_bot(bot)
    except Exception as e:
        logger.error(f"Discord Bot 启动失败: {e}")
        raise

# 添加导出声明
__all__ = ['get_bot', 'initialize_bot', 'stop_bot_services', 'start_discord_bot']
