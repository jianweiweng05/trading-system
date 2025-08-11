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
        try:
            # 直接从 app.state 中获取 macro_analyzer 实例
            app_state = self.bot.app.state
            macro_analyzer = getattr(app_state, 'macro_analyzer', None)
            
            if macro_analyzer:
                # 调用 macro_analyzer 的 get_detailed_status() 方法获取详细数据
                detailed_status = await macro_analyzer.get_detailed_status()
                
                # 【修改】添加日志，记录获取到的原始数据
                logger.info(f"从 macro_analyzer 获取到的原始数据: {detailed_status}")
                
                return {
                    'trend': detailed_status.get('trend', '未知'),
                    'btc_trend': detailed_status.get('btc_trend', '未知'),
                    'eth_trend': detailed_status.get('eth_trend', '未知'),
                    'confidence': detailed_status.get('confidence', 0),
                    'last_update': detailed_status.get('last_update', asyncio.get_event_loop().time())
                 }

            else:
                logger.warning("未找到 macro_analyzer 实例")
                return {
                    'trend': '未知',
                    'btc_trend': '未知',
                    'eth_trend': '未知',
                    'confidence': 0,
                    'last_update': asyncio.get_event_loop().time()
                }
                
        except Exception as e:
            logger.error(f"获取宏观状态失败: {e}")
            # 如果查询失败，返回默认状态
            return {
                'trend': '未知',
                'btc_trend': '未知',
                'eth_trend': '未知',
                'confidence': 0,
                'last_update': asyncio.get_event_loop().time()
            }

    @app_commands.command(name="status", description="显示系统主控制面板")
    async def status(self, interaction: discord.Interaction):
        """显示统一的、交互式的主控制面板"""
        try:
            if interaction.message:
                await interaction.response.defer()
            else:
                await interaction.response.defer(ephemeral=True)

            from src.discord_ui import MainPanelView
            from src.core_logic import get_confidence_weight # 【修改】导入转换器

            view = MainPanelView(self.bot)
            embed = discord.Embed(title="🎛️ 主控制面板", color=discord.Color.blue())
            embed.description = "使用下方按钮查看详细信息或进行操作。"
            
            app_state = self.bot.app.state
            trading_engine = getattr(app_state, 'trading_engine', None)
            
            macro_status = await self.get_macro_status()
            
            # 【修改】增加置信度和仓位系数的计算和显示
            ai_confidence = macro_status.get('confidence', 0.0)
            conf_weight = get_confidence_weight(ai_confidence)
            
            # 【修改】修改宏观状态显示逻辑，从详细状态报告中提取信息
            trend = macro_status.get('trend', '未知')
            btc_trend = macro_status.get('btc_trend', '未知')
            eth_trend = macro_status.get('eth_trend', '未知')
            
            # 【修改】添加日志，记录提取的数据
            logger.info(f"提取的宏观状态数据: trend={trend}, btc_trend={btc_trend}, eth_trend={eth_trend}")
            
            # 使用简化的显示格式
            # 使用转换函数将状态转换为简化的中文显示
            trend_display = view._convert_macro_status(trend, btc_trend, eth_trend)
            
            macro_text = f"**宏观状态**: {trend_display}\n"
            macro_text += f"**AI 置信度**: {ai_confidence:.2f}\n"
            macro_text += f"**仓位系数**: {conf_weight:.2f}x"
            embed.add_field(name="🌍 宏观状态", value=macro_text, inline=True)

            # ... (后面获取持仓、报警、共振池的逻辑保持不变) ...
            pnl_text, position_text = "无", "无持仓"
            if trading_engine:
                positions = await trading_engine.get_position("*")
                if positions:
                    total_pnl = sum(float(p.get('pnl', 0)) for p in positions.values() if p)
                    pnl_text = f"{'🟢' if total_pnl >= 0 else '🔴'} ${total_pnl:,.2f}"
                    active_positions = [f"{p['symbol']} ({'多' if float(p.get('size',0)) > 0 else '空'})" for p in positions.values() if p and float(p.get('size', 0)) != 0]
                    if active_positions: position_text = ", ".join(active_positions)
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
                pool_data = await trading_engine.get_resonance_pool()
                pool_text = f"⏳ {pool_data.get('pending_count', 0)} 个待处理"
            embed.add_field(name="📡 共振池", value=pool_text, inline=True)

            embed.set_footer(text=f"模式: {CONFIG.run_mode.upper()} | 最后刷新于")
            embed.timestamp = discord.utils.utcnow()

            if interaction.message:
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"status 命令执行失败: {e}", exc_info=True)
            # ... (错误处理) ...
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
