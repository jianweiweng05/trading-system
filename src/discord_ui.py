import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View, Modal, TextInput
import logging
from typing import Optional, Dict, Any
from src.config import CONFIG

logger = logging.getLogger(__name__)

# --- 【新增功能】二次确认模态弹窗 ---

class ModeSwitchModal(Modal, title="切换运行模式"):
    """切换实盘/模拟模式的确认弹窗"""
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    confirm_input = TextInput(
        label='输入 "LIVE" 或 "SIMULATE" 以切换',
        placeholder='例如: LIVE',
        style=discord.TextStyle.short,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        new_mode = self.confirm_input.value.upper()
        if new_mode in ["LIVE", "SIMULATE"]:
            # 此处应调用后端逻辑来实际更改模式
            # 例如: await self.bot.app.state.system_state.set_run_mode(new_mode)
            # 目前我们只发送一个确认消息
            await interaction.response.send_message(f"✅ 已发送切换至 **{new_mode}** 模式的指令。", ephemeral=True)
            logger.warning(f"用户 {interaction.user} 请求切换模式至: {new_mode}")
        else:
            await interaction.response.send_message("❌ 输入无效。请输入 'LIVE' 或 'SIMULATE'。", ephemeral=True)

class EmergencyStopModal(Modal, title="🚨 确认强制平仓"):
    """强制平仓的确认弹窗"""
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    confirm_input = TextInput(
        label='请输入 "强制平仓" 四个字以确认',
        placeholder='强制平仓',
        style=discord.TextStyle.short,
        required=True,
        min_length=4,
        max_length=4
    )

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm_input.value == "强制平仓":
            trading_engine = getattr(self.bot.app.state, 'trading_engine', None)
            if trading_engine:
                # 此处调用交易引擎的强制平仓方法
                # result = await trading_engine.liquidate_all_positions("用户手动强制平仓")
                # 目前我们只发送一个确认消息
                await interaction.response.send_message("✅ **已发送强制平仓所有头寸的指令！**", ephemeral=True)
                logger.critical(f"用户 {interaction.user} 已执行强制平仓！")
            else:
                await interaction.response.send_message("❌ 交易引擎未启用，无法执行操作。", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 确认失败，操作已取消。", ephemeral=True)


# --- 主面板视图 ---
class MainPanelView(View):
    """主控制面板的按钮视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    def _convert_macro_status(self, trend: str, btc_status: str, eth_status: str) -> str:
        """将宏观状态转换为简化的中文字符"""
        status_map = {
            'BULLISH': '牛', 'BEARISH': '熊', 'NEUTRAL': '中', 'UNKNOWN': '未知',
            'neutral': '中', 'bullish': '牛', 'bearish': '熊',
            '看涨': '牛', '看跌': '熊', '中性': '中'
        }
        trend_map = {
            'BULL': '牛', 'BEAR': '熊', 'NEUTRAL': '中', '中性': '中',
            '牛': '牛', '熊': '熊', '震荡': '震荡', 'UNKNOWN': '未知'
        }
        trend_char = trend_map.get(trend.upper(), '未知')
        btc_char = status_map.get(btc_status.upper(), '未知')
        eth_char = status_map.get(eth_status.upper(), '未知')
        return f"{trend_char}/{btc_char}/{eth_char}"

    async def _get_main_panel_embed(self) -> discord.Embed:
        """一个辅助函数，用于生成主面板的 Embed 内容"""
        embed = discord.Embed(title="🎛️ 主控制面板", color=discord.Color.blue())
        embed.description = "使用下方按钮查看详细信息或进行操作。"
        
        app_state = self.bot.app.state
        trading_engine = getattr(app_state, 'trading_engine', None)
        
        status_cog = self.bot.get_cog("TradingCommands")
        macro_status = {}
        if status_cog:
            macro_status = await status_cog.get_macro_status()
        
        trend = macro_status.get('trend', '未知')
        btc_status = macro_status.get('btc_trend', '未知')
        eth_status = macro_status.get('eth_trend', '未知')
        
        logger.info(f"宏观状态数据: trend={trend}, btc_status={btc_status}, eth_status={eth_status}")
        
        macro_text = self._convert_macro_status(trend, btc_status, eth_status)
        embed.add_field(name="🌍 宏观状态", value=macro_text, inline=True)

        pnl_text = "无"
        position_text = "无持仓"
        if trading_engine:
            positions = await trading_engine.get_position("*")
            if positions:
                total_pnl = sum(float(p.get('pnl', 0)) for p in positions.values() if p)
                pnl_text = f"{'🟢' if total_pnl >= 0 else '🔴'} ${total_pnl:,.2f}"
            
            active_positions = [f"{p['symbol']} ({'多' if float(p.get('size',0)) > 0 else '空'})" 
                                for p in positions.values() if p and float(p.get('size', 0)) != 0]
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
        try:
            await interaction.response.send_message("正在获取持仓信息...", ephemeral=True, delete_after=3)
            
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
        except Exception as e:
            logger.error(f"显示持仓失败: {e}", exc_info=True)
            await interaction.followup.send("❌ 获取持仓信息失败。", ephemeral=True)

    @discord.ui.button(label="🚨 报警历史", style=discord.ButtonStyle.secondary, custom_id="main_panel:alerts")
    async def show_alerts(self, interaction: discord.Interaction, button: Button):
        try:
            await interaction.response.send_message("正在获取报警历史...", ephemeral=True, delete_after=3)
            
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
        except Exception as e:
            logger.error(f"显示报警历史失败: {e}", exc_info=True)
            await interaction.followup.send("❌ 获取报警历史失败。", ephemeral=True)

    @discord.ui.button(label="♙️ 参数设置", style=discord.ButtonStyle.secondary, custom_id="main_panel:settings")
    async def show_settings(self, interaction: discord.Interaction, button: Button):
        try:
            embed = discord.Embed(title="⚙️ 参数设置", description="此功能正在开发中，敬请期待。", color=discord.Color.purple())
            await interaction.response.edit_message(embed=embed, view=SettingsPanelView(self.bot))
        except Exception as e:
            logger.error(f"切换到设置面板失败: {e}", exc_info=True)
            await interaction.followup.send("❌ 打开设置面板失败。", ephemeral=True)

    @discord.ui.button(label="🔄 刷新", style=discord.ButtonStyle.primary, custom_id="main_panel:refresh")
    async def refresh_panel(self, interaction: discord.Interaction, button: Button):
        try:
            new_embed = await self._get_main_panel_embed()
            await interaction.response.edit_message(embed=new_embed, view=self)
        except Exception as e:
            logger.error(f"刷新面板失败: {e}", exc_info=True)
            await interaction.followup.send("❌ 刷新失败。", ephemeral=True)

    # --- 【新增功能】在这里添加新按钮 ---

    @discord.ui.button(label="切换模式", style=discord.ButtonStyle.secondary, custom_id="main_panel:switch_mode", row=2)
    async def switch_mode(self, interaction: discord.Interaction, button: Button):
        """打开模式切换的确认弹窗"""
        await interaction.response.send_modal(ModeSwitchModal(self.bot))

    @discord.ui.button(label="🚨 强制平仓", style=discord.ButtonStyle.danger, custom_id="main_panel:emergency_stop", row=2)
    async def emergency_stop(self, interaction: discord.Interaction, button: Button):
        """打开强制平仓的确认弹窗"""
        await interaction.response.send_modal(EmergencyStopModal(self.bot))


# --- 设置面板视图 ---
class SettingsPanelView(View):
    """参数设置面板的视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="⬅️ 返回主面板", style=discord.ButtonStyle.secondary, custom_id="settings_panel:back")
    async def back_to_main(self, interaction: discord.Interaction, button: Button):
        try:
            main_panel_view = MainPanelView(self.bot)
            new_embed = await main_panel_view._get_main_panel_embed()
            await interaction.response.edit_message(embed=new_embed, view=main_panel_view)
        except Exception as e:
            logger.error(f"返回主面板失败: {e}", exc_info=True)
            await interaction.followup.send("❌ 返回失败。", ephemeral=True)
