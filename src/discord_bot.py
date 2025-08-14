import logging
import discord
import time
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
    """(此函数保持不变)"""
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
            # ... (此事件处理器保持不变) ...
            pass
        
        @_bot_instance.event
        async def on_command_error(ctx: commands.Context, error: Exception):
            # ... (此事件处理器保持不变) ...
            pass

    return _bot_instance

# ================= Bot 命令 Cog =================
class TradingCommands(commands.Cog, name="TradingCommands"):
    """交易系统相关命令"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # --- 【核心修改】重写 get_macro_status 以适配新的 MacroAnalyzer ---
    async def get_macro_status(self) -> Dict[str, Any]:
        """获取宏观状态信息"""
        try:
            app_state = self.bot.app.state
            macro_analyzer = getattr(app_state, 'macro_analyzer', None)
            
            if not macro_analyzer:
                logger.warning("macro_analyzer实例未找到")
                return self._get_default_status()
            
            # 调用新的核心决策方法，它返回一个字典
            decision = await macro_analyzer.get_macro_decision()
            return decision
            
        except Exception as e:
            logger.error(f"获取宏观状态失败: {e}", exc_info=True)
            return self._get_default_status()

    def _get_default_status(self) -> Dict[str, Any]:
        """默认状态值"""
        return {
            'market_season': 'OSC',
            'score': 0.0,
            'confidence': 0.5,
            'last_update': time.time()
        }

    @app_commands.command(name="status", description="显示系统主控制面板")
    async def status(self, interaction: discord.Interaction):
        """显示统一的、交互式的主控制面板"""
        try:
            # Defer response
            await interaction.response.defer(ephemeral=True)

            from src.discord_ui import MainPanelView # 假设这个UI视图存在

            view = MainPanelView(self.bot)
            embed = discord.Embed(title="🎛️ 主控制面板", color=discord.Color.blue())
            embed.description = "使用下方按钮查看详细信息或进行操作。"
            
            app_state = self.bot.app.state
            trading_engine = getattr(app_state, 'trading_engine', None)
            
            # --- 【核心修改】适配新的宏观决策逻辑和显示 ---
            macro_decision = await self.get_macro_status()
            
            market_season = macro_decision.get('market_season', 'OSC')
            score = macro_decision.get('score', 0.0)
            ai_confidence = macro_decision.get('confidence', 0.0)
            
            state_display = {
                'BULL': '🐂 牛市',
                'BEAR': '🐻 熊市',
                'OSC': '🔄 震荡'
            }.get(market_season, '❓ 未知')
            
            macro_text = (
                f"**宏观状态**: {state_display}\n"
                f"**市场综合分数**: {score:.2f}\n"
                f"**AI 置信度**: {ai_confidence:.2f}"
            )
            embed.add_field(name="🌍 宏观参谋部", value=macro_text, inline=True)

            # --- (后面获取持仓、报警、共振池的逻辑保持不变) ---
            pnl_text, position_text = "无", "无持仓"
            if trading_engine:
                positions = await trading_engine.get_position("*")
                if positions:
                    total_pnl = sum(float(p.get('unrealizedPnl', 0)) for p in positions.values() if p) # 使用 unrealizedPnl
                    pnl_text = f"{'🟢' if total_pnl >= 0 else '🔴'} ${total_pnl:,.2f}"
                    active_positions = [f"{p['symbol']} ({'多' if float(p.get('contracts',0)) > 0 else '空'})" for p in positions.values() if p and float(p.get('contracts', 0)) != 0]
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

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"status 命令执行失败: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.followup.send(f"⚠️ 命令执行失败: `{str(e)}`", ephemeral=True)

# ================= 生命周期管理 =================
async def initialize_bot(bot: commands.Bot, app: FastAPI):
    """(此函数保持不变)"""
    try:
        bot.app = app
        bot.remove_command('help')
        
        await bot.add_cog(TradingCommands(bot))
        logger.info("✅ 交易系统命令Cog已添加")
        
        logger.info("🚀 正在启动 Discord Bot")
        await bot.start(CONFIG.discord_token)
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        raise

async def stop_bot_services():
    """(此函数保持不变)"""
    bot = get_bot()
    if bot and bot.is_ready():
        await bot.close()
        logger.info("🛑 Discord Bot 已关闭")

async def start_discord_bot(app: FastAPI):
    """(此函数保持不变)"""
    bot = get_bot()
    try:
        await initialize_bot(bot, app)
    except Exception as e:
        logger.error(f"Discord Bot 启动失败: {e}")
        pass

# ================= 导出配置 =================
__all__ = ['get_bot', 'start_discord_bot', 'stop_bot_services']
