import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View, Modal, TextInput
import logging
from typing import Optional, Dict, Any
from src.config import CONFIG

logger = logging.getLogger(__name__)

# --- 模态弹窗 (无变动) ---

class ModeSwitchModal(Modal, title="切换运行模式"):
    """(此部分保持不变)"""
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
    confirm_input = TextInput(label='输入 "LIVE" 或 "SIMULATE" 以切换', placeholder='例如: LIVE', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        # ... (逻辑不变) ...
        pass

class EmergencyStopModal(Modal, title="🚨 确认强制平仓"):
    """(此部分保持不变)"""
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
    confirm_input = TextInput(label='请输入 "强制平仓" 四个字以确认', placeholder='强制平仓', required=True, min_length=4, max_length=4)
    async def on_submit(self, interaction: discord.Interaction):
        # ... (逻辑不变) ...
        pass


# --- 主面板视图 (有修改) ---
class MainPanelView(View):
    """主控制面板的按钮视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    # --- 【核心修改】_convert_macro_status 方法被删除，不再需要 ---

    async def _get_main_panel_embed(self) -> discord.Embed:
        """一个辅助函数，用于生成主面板的 Embed 内容 (已适配新宏观系统)"""
        embed = discord.Embed(title="🎛️ 主控制面板", color=discord.Color.blue())
        embed.description = "使用下方按钮查看详细信息或进行操作。"
        
        app_state = self.bot.app.state
        trading_engine = getattr(app_state, 'trading_engine', None)
        
        # --- 【核心修改】适配新的宏观决策逻辑和显示 ---
        status_cog = self.bot.get_cog("TradingCommands")
        macro_decision = {}
        if status_cog:
            # get_macro_status 现在返回的是我们新的、完整的决策包
            macro_decision = await status_cog.get_macro_status()
        
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
        pnl_text = "无"
        position_text = "无持仓"
        if trading_engine:
            positions = await trading_engine.get_position("*")
            if positions:
                total_pnl = sum(float(p.get('unrealizedPnl', 0)) for p in positions.values() if p)
                pnl_text = f"{'🟢' if total_pnl >= 0 else '🔴'} ${total_pnl:,.2f}"
            
            active_positions = [f"{p['symbol']} ({'多' if float(p.get('contracts',0)) > 0 else '空'})" 
                                for p in positions.values() if p and float(p.get('contracts', 0)) != 0]
            if active_positions:
                position_text = ", ".join(active_positions)

        embed.add_field(name="📈 核心持仓", value=position_text, inline=True)
        embed.add_field(name="💰 今日浮盈", value=pnl_text, inline=True)

        alert_system = getattr(app_state, 'alert_system', None)
        alert_status_text = "⚪ 未启用"
        if alert_system:
            alert_status = alert_system.get_status()
            alert_status_text = f"🔴 报警中" if alert_status.get('active') else "🟢 正常"
        embed.add_field(name="🚨 报警状态", value=alert_status_text, inline=True)

        pool_text = "⚪ 未启用"
        if trading_engine:
            pool_data = await trading_engine.get_resonance_pool()
            pool_text = f"⏳ {pool_data.get('pending_count', 0)} 个待处理"
        embed.add_field(name="📡 共振池", value=pool_text, inline=True)

        embed.set_footer(text=f"模式: {CONFIG.run_mode.upper()} | 最后刷新于")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @discord.ui.button(label="📊 详细持仓", style=discord.ButtonStyle.secondary, custom_id="main_panel:positions")
    async def show_positions(self, interaction: discord.Interaction, button: Button):
        """(此方法保持不变)"""
        # ...
        pass

    @discord.ui.button(label="🚨 报警历史", style=discord.ButtonStyle.secondary, custom_id="main_panel:alerts")
    async def show_alerts(self, interaction: discord.Interaction, button: Button):
        """(此方法保持不变)"""
        # ...
        pass

    @discord.ui.button(label="⚙️ 参数设置", style=discord.ButtonStyle.secondary, custom_id="main_panel:settings")
    async def show_settings(self, interaction: discord.Interaction, button: Button):
        """(此方法保持不变)"""
        # ...
        pass

    @discord.ui.button(label="🔄 刷新", style=discord.ButtonStyle.primary, custom_id="main_panel:refresh")
    async def refresh_panel(self, interaction: discord.Interaction, button: Button):
        """(此方法保持不变)"""
        try:
            new_embed = await self._get_main_panel_embed()
            await interaction.response.edit_message(embed=new_embed, view=self)
        except Exception as e:
            logger.error(f"刷新面板失败: {e}", exc_info=True)
            await interaction.followup.send("❌ 刷新失败。", ephemeral=True)

    @discord.ui.button(label="切换模式", style=discord.ButtonStyle.secondary, custom_id="main_panel:switch_mode", row=2)
    async def switch_mode(self, interaction: discord.Interaction, button: Button):
        """(此方法保持不变)"""
        await interaction.response.send_modal(ModeSwitchModal(self.bot))

    @discord.ui.button(label="🚨 强制平仓", style=discord.ButtonStyle.danger, custom_id="main_panel:emergency_stop", row=2)
    async def emergency_stop(self, interaction: discord.Interaction, button: Button):
        """(此方法保持不变)"""
        await interaction.response.send_modal(EmergencyStopModal(self.bot))


# --- 设置面板视图 (无变动) ---
class SettingsPanelView(View):
    """(此部分保持不变)"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="⬅️ 返回主面板", style=discord.ButtonStyle.secondary, custom_id="settings_panel:back")
    async def back_to_main(self, interaction: discord.Interaction, button: Button):
        # ... (逻辑不变) ...
        pass
