
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View, Modal, TextInput
import logging
from typing import Optional, Dict, Any
from src.config import CONFIG

logger = logging.getLogger(__name__)

class TradingModeView(View):
    # ... (这个类保持不变) ...
    def __init__(self):
        super().__init__(timeout=None)
        self.current_mode: str = CONFIG.run_mode
        self.sim_button = Button(label="🔴 模拟交易", style=discord.ButtonStyle.red if self.current_mode == "simulate" else discord.ButtonStyle.grey, custom_id="mode_simulate")
        self.sim_button.callback = self.switch_to_simulate
        self.add_item(self.sim_button)
        self.live_button = Button(label="✅ 实盘交易", style=discord.ButtonStyle.green if self.current_mode == "live" else discord.ButtonStyle.grey, custom_id="mode_live")
        self.live_button.callback = self.switch_to_live
        self.add_item(self.live_button)
    
    def update_to_live_mode(self):
        self.sim_button.style = discord.ButtonStyle.grey
        self.live_button.style = discord.ButtonStyle.green
        self.current_mode = "live"
    
    async def switch_to_simulate(self, interaction: discord.Interaction):
        if self.current_mode == "simulate":
            await interaction.response.send_message("已经在模拟交易模式", ephemeral=True)
            return
        try:
            CONFIG.run_mode = "simulate"
            self.current_mode = "simulate"
            self.sim_button.style = discord.ButtonStyle.red
            self.live_button.style = discord.ButtonStyle.grey
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("已切换到模拟交易模式", ephemeral=True)
            logger.info(f"用户 {interaction.user} 切换到模拟交易模式")
        except Exception as e:
            logger.error(f"切换到模拟交易模式失败: {e}", exc_info=True)
            await interaction.followup.send("切换失败，请稍后重试", ephemeral=True)
    
    async def switch_to_live(self, interaction: discord.Interaction):
        if self.current_mode == "live":
            await interaction.response.send_message("已经在实盘交易模式", ephemeral=True)
            return
        confirm_view = ConfirmView(self)
        await interaction.response.send_message(
            "⚠️ 确定要切换到实盘交易模式吗？这将使用真实资金进行交易。",
            view=confirm_view,
            ephemeral=True
        )

class ConfirmView(View):
    # ... (这个类保持不变) ...
    def __init__(self, parent_view: "TradingModeView"):
        super().__init__(timeout=30)
        self.parent_view = parent_view
        self.confirm = Button(label="确认", style=discord.ButtonStyle.green, custom_id="confirm_live")
        self.confirm.callback = self.confirm_switch
        self.add_item(self.confirm)
        self.cancel = Button(label="取消", style=discord.ButtonStyle.red, custom_id="cancel_live")
        self.cancel.callback = self.cancel_switch
        self.add_item(self.cancel)
    
    async def confirm_switch(self, interaction: discord.Interaction):
        try:
            CONFIG.run_mode = "live"
            self.parent_view.update_to_live_mode()
            if interaction.message:
                await interaction.message.edit(view=self.parent_view)
            await interaction.response.edit_message(content="✅ 已成功切换到实盘交易模式", view=None)
            logger.info(f"用户 {interaction.user} 切换到实盘交易模式")
        except Exception as e:
            logger.error(f"切换到实盘交易模式失败: {e}", exc_info=True)
            await interaction.response.edit_message(content="❌ 切换失败，请稍后重试", view=None)
    
    async def cancel_switch(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="❌ 已取消切换", view=None)

# ... (ParameterControlView 和 FirepowerModal 保持不变，因为我们计划移除它们) ...
class ParameterControlView(View):
    pass
class FirepowerModal(Modal, title="设置火力系数"):
    pass

# --- 【修改】重构 MainPanelView 和 SettingsPanelView，统一使用装饰器 ---
class MainPanelView(View):
    """主控制面板的按钮视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="📊 详细持仓", style=discord.ButtonStyle.secondary, custom_id="main_panel:positions")
    async def show_positions(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title="📊 详细持仓", color=discord.Color.blue())
        trading_engine = getattr(self.bot.app.state, 'trading_engine', None)
        if trading_engine:
            positions = await trading_engine.get_position("*")
            if not positions or all(float(p.get('size', 0)) == 0 for p in positions.values() if p):
                embed.description = "当前无任何持仓。"
            else:
                for symbol, pos in positions.items():
                    if pos and float(pos.get('size', 0)) != 0:
                        side = "🟢 多头" if float(pos.get('size', 0)) > 0 else "🔴 空头"
                        pnl = float(pos.get('pnl', 0))
                        embed.add_field(
                            name=f"{symbol} ({side})",
                            value=f"**数量**: {abs(float(pos.get('size', 0)))}\n**均价**: ${float(pos.get('entryPrice', 0)):,.2f}\n**浮盈**: ${pnl:,.2f}",
                            inline=True
                        )
        else:
            embed.description = "交易引擎未初始化。"
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🚨 报警历史", style=discord.ButtonStyle.secondary, custom_id="main_panel:alerts")
    async def show_alerts(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title="🚨 最近 5 条报警历史", color=discord.Color.orange())
        alert_system = getattr(self.bot.app.state, 'alert_system', None)
        if alert_system:
            alerts = alert_system.get_alerts()
            if not alerts:
                embed.description = "暂无报警记录。"
            else:
                for alert in reversed(alerts[-5:]):
                    timestamp = int(alert['timestamp'])
                    embed.add_field(
                        name=f"**{alert['type']}** ({alert['level']})",
                        value=f"{alert['message']}\n*发生于 <t:{timestamp}:R>*",
                        inline=False
                    )
        else:
            embed.description = "报警系统未初始化。"
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="⚙️ 参数设置", style=discord.ButtonStyle.secondary, custom_id="main_panel:settings")
    async def show_settings(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(title="⚙️ 参数设置", description="在这里调整系统的核心策略参数。", color=discord.Color.purple())
        await interaction.response.edit_message(embed=embed, view=SettingsPanelView(self.bot))

    @discord.ui.button(label="🔄 刷新", style=discord.ButtonStyle.primary, custom_id="main_panel:refresh")
    async def refresh_panel(self, interaction: discord.Interaction, button: Button):
        # 【修改】使用英文类名 "TradingCommands" 来获取 Cog
        status_cog = self.bot.get_cog("TradingCommands")
        if status_cog and hasattr(status_cog, 'status'):
            await interaction.response.defer()
            # 直接调用 status 命令的 coroutine
            await status_cog.status(interaction)
            # 删除原始的 "Thinking..." 消息
            await interaction.delete_original_response()

class SettingsPanelView(View):
    """参数设置面板的视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="💾 保存设置", style=discord.ButtonStyle.success, custom_id="settings_panel:save", disabled=True)
    async def save_settings(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        # TODO: 实现保存配置到数据库的逻辑
        await interaction.followup.send("✅ 设置已保存。（功能待实现）", ephemeral=True)

    @discord.ui.button(label="⬅️ 返回主面板", style=discord.ButtonStyle.secondary, custom_id="settings_panel:back")
    async def back_to_main(self, interaction: discord.Interaction, button: Button):
        # 【修改】使用英文类名 "TradingCommands" 来获取 Cog
        status_cog = self.bot.get_cog("TradingCommands")
        if status_cog and hasattr(status_cog, 'status'):
            await interaction.response.defer()
            await status_cog.status(interaction)
            await interaction.delete_original_response()

# --- 【修改】移除旧的 TradingDashboard Cog ---
# class TradingDashboard(commands.Cog, name="交易面板"):
#    ... (整个类被移除)
