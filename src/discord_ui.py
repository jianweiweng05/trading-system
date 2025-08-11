import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View, Modal, TextInput
import logging
from typing import Optional, Dict, Any
from src.config import CONFIG

logger = logging.getLogger(__name__)

# --- 主面板视图 ---
class MainPanelView(View):
    """主控制面板的按钮视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    def _convert_macro_status(self, trend: str, btc_status: str, eth_status: str) -> str:
        """将宏观状态转换为简化的中文字符"""
        # 转换宏观季节
        trend_map = {
            'BULL': '牛',
            'BEAR': '熊',
            'NEUTRAL': '中',
            '中性': '中',  # 【修改】添加中文映射
            'UNKNOWN': '未知'
        }
        trend_char = trend_map.get(trend.upper(), '未知')
        
        # 转换BTC状态
        btc_map = {
            'BULLISH': '牛',
            'BEARISH': '熊',
            'NEUTRAL': '中',
            'UNKNOWN': '未知',
            'neutral': '中',  # 处理小写情况
            'bullish': '牛',  # 处理小写情况
            'bearish': '熊'   # 处理小写情况
         }

        btc_char = btc_map.get(btc_status.upper(), '未知')
        
        # 转换ETH状态
        eth_char = btc_map.get(eth_status.upper(), '未知')
        
        return f"{trend_char}/{btc_char}/{eth_char}"

    async def _get_main_panel_embed(self) -> discord.Embed:
        """一个辅助函数，用于生成主面板的 Embed 内容"""
        embed = discord.Embed(title="🎛️ 主控制面板", color=discord.Color.blue())
        embed.description = "使用下方按钮查看详细信息或进行操作。"
        
        app_state = self.bot.app.state
        trading_engine = getattr(app_state, 'trading_engine', None)
        
        # 1. 获取宏观状态
        status_cog = self.bot.get_cog("TradingCommands")
        macro_status = {}
        if status_cog:
            macro_status = await status_cog.get_macro_status()
        
        # 【修改】使用正确的键名获取数据
        trend = macro_status.get('trend', '未知')
        btc_status = macro_status.get('btc_trend', '未知')  # 【修改】从 btc1d 改为 btc_trend
        eth_status = macro_status.get('eth_trend', '未知')  # 【修改】从 eth1d 改为 eth_trend
        
        # 【修改】添加日志记录，帮助调试
        logger.info(f"宏观状态数据: trend={trend}, btc_status={btc_status}, eth_status={eth_status}")
        
        macro_text = self._convert_macro_status(trend, btc_status, eth_status)
        embed.add_field(name="🌍 宏观状态", value=macro_text, inline=True)

        # 2. 获取核心持仓和盈亏
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

        # 3. 获取报警状态
        alert_system = getattr(app_state, 'alert_system', None)
        alert_status_text = "⚪ 未启用"
        if alert_system:
            alert_status = alert_system.get_status()
            alert_status_text = f"{'🔴' if alert_status.get('active') else '🟢'} 正常"
        embed.add_field(name="🚨 报警状态", value=alert_status_text, inline=True)

        # 4. 获取共振池状态
        pool_text = "⚪ 未启用"
        if trading_engine:
            # 【修改】增加了 await
            pool_data = await trading_engine.get_resonance_pool()
            pool_text = f"⏳ {pool_data.get('pending_count', 0)} 个待处理"
        embed.add_field(name="📡 共振池", value=pool_text, inline=True)

        embed.set_footer(text=f"模式: {CONFIG.run_mode.upper()} | 最后刷新于")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @discord.ui.button(label="📊 详细持仓", style=discord.ButtonStyle.secondary, custom_id="main_panel:positions")
    async def show_positions(self, interaction: discord.Interaction, button: Button):
        try:
            # 【修改】使用 send_message 发送一个全新的、临时的响应
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
            # 【修改】使用 send_message 发送一个全新的、临时的响应
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
            # 【修改】正确的刷新逻辑：重新构建 Embed，然后用 edit_message 更新
            new_embed = await self._get_main_panel_embed()
            await interaction.response.edit_message(embed=new_embed, view=self)
        except Exception as e:
            logger.error(f"刷新面板失败: {e}", exc_info=True)
            # 如果编辑失败，尝试发送一个错误消息
            await interaction.followup.send("❌ 刷新失败。", ephemeral=True)

# --- 设置面板视图 ---
class SettingsPanelView(View):
    """参数设置面板的视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="⬅️ 返回主面板", style=discord.ButtonStyle.secondary, custom_id="settings_panel:back")
    async def back_to_main(self, interaction: discord.Interaction, button: Button):
        try:
            # 切换回主面板视图
            main_panel_view = MainPanelView(self.bot)
            new_embed = await main_panel_view._get_main_panel_embed()
            await interaction.response.edit_message(embed=new_embed, view=main_panel_view)
        except Exception as e:
            logger.error(f"返回主面板失败: {e}", exc_info=True)
            await interaction.followup.send("❌ 返回失败。", ephemeral=True)
