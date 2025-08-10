
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View
import logging
from typing import Dict, Any
from src.config import CONFIG

logger = logging.getLogger(__name__)

# --- 主面板视图 ---
class MainPanelView(View):
    """主控制面板的按钮视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        # 添加按钮
        self.add_item(Button(label="📊 详细持仓", style=discord.ButtonStyle.secondary, custom_id="main_panel:positions"))
        self.add_item(Button(label="🚨 报警历史", style=discord.ButtonStyle.secondary, custom_id="main_panel:alerts"))
        self.add_item(Button(label="⚙️ 参数设置", style=discord.ButtonStyle.secondary, custom_id="main_panel:settings"))
        self.add_item(Button(label="🔄 刷新", style=discord.ButtonStyle.primary, custom_id="main_panel:refresh"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 可以在这里添加权限检查
        return True

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
        # 切换到设置视图
        embed = discord.Embed(title="⚙️ 参数设置", description="在这里调整系统的核心策略参数。", color=discord.Color.purple())
        # ... (未来在这里添加参数显示的字段) ...
        await interaction.response.edit_message(embed=embed, view=SettingsPanelView(self.bot))

    @discord.ui.button(label="🔄 刷新", style=discord.ButtonStyle.primary, custom_id="main_panel:refresh")
    async def refresh_panel(self, interaction: discord.Interaction, button: Button):
        # 重新调用 /status 命令的逻辑来刷新
        status_cog = self.bot.get_cog("交易系统")
        if status_cog:
            await interaction.response.defer() # 先响应，避免超时
            await status_cog.status(interaction)
            # 删除原始的 "Thinking..." 消息
            await interaction.delete_original_response()


# --- 设置面板视图 ---
class SettingsPanelView(View):
    """参数设置面板的视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        # 添加组件
        self.add_item(Button(label="💾 保存设置", style=discord.ButtonStyle.success, custom_id="settings_panel:save", disabled=True)) # 默认禁用
        self.add_item(Button(label="⬅️ 返回主面板", style=discord.ButtonStyle.secondary, custom_id="settings_panel:back"))

    @discord.ui.button(label="💾 保存设置", style=discord.ButtonStyle.success, custom_id="settings_panel:save")
    async def save_settings(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        # TODO: 实现保存配置到数据库的逻辑
        await interaction.followup.send("✅ 设置已保存。（功能待实现）", ephemeral=True)

    @discord.ui.button(label="⬅️ 返回主面板", style=discord.ButtonStyle.secondary, custom_id="settings_panel:back")
    async def back_to_main(self, interaction: discord.Interaction, button: Button):
        # 切换回主面板视图
        status_cog = self.bot.get_cog("交易系统")
        if status_cog:
            await interaction.response.defer()
            await status_cog.status(interaction)
            await interaction.delete_original_response()
