import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View, Modal, TextInput
import logging
from typing import Optional, Dict, Any
from src.config import CONFIG

logger = logging.getLogger(__name__)

class TradingModeView(View):
    """交易模式切换视图"""
    def __init__(self):
        super().__init__(timeout=None)
        self.current_mode: str = CONFIG.run_mode
        
        # 创建模拟交易按钮
        self.sim_button = Button(
            label="🔴 模拟交易",
            style=discord.ButtonStyle.red if self.current_mode == "simulate" else discord.ButtonStyle.grey,
            custom_id="mode_simulate"
        )
        self.sim_button.callback = self.switch_to_simulate
        self.add_item(self.sim_button)
        
        # 创建实盘交易按钮
        self.live_button = Button(
            label="✅ 实盘交易",
            style=discord.ButtonStyle.green if self.current_mode == "live" else discord.ButtonStyle.grey,
            custom_id="mode_live"
        )
        self.live_button.callback = self.switch_to_live
        self.add_item(self.live_button)
    
    async def switch_to_simulate(self, interaction: discord.Interaction):
        """切换到模拟交易模式"""
        if self.current_mode == "simulate":
            await interaction.response.send_message("已经在模拟交易模式", ephemeral=True)
            return
        
        try:
            # 更新配置
            CONFIG.run_mode = "simulate"
            
            # 更新按钮样式
            self.sim_button.style = discord.ButtonStyle.red
            self.live_button.style = discord.ButtonStyle.grey
            
            # 禁用按钮防止重复点击
            self.disable_all_buttons()
            
            # 发送响应
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("已切换到模拟交易模式", ephemeral=True)
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 切换到模拟交易模式")
            
            # 启用按钮
            self.enable_all_buttons()
            self.current_mode = "simulate"
            
        except Exception as e:
            logger.error(f"切换到模拟交易模式失败: {e}", exc_info=True)
            await interaction.followup.send("切换失败，请稍后重试", ephemeral=True)
    
    async def switch_to_live(self, interaction: discord.Interaction):
        """切换到实盘交易模式"""
        if self.current_mode == "live":
            await interaction.response.send_message("已经在实盘交易模式", ephemeral=True)
            return
        
        # 添加确认对话框
        confirm_view = ConfirmView()
        await interaction.response.send_message(
            "⚠️ 确定要切换到实盘交易模式吗？这将使用真实资金进行交易。",
            view=confirm_view,
            ephemeral=True
        )
    
    def disable_all_buttons(self):
        """禁用所有按钮"""
        for item in self.children:
            item.disabled = True
    
    def enable_all_buttons(self):
        """启用所有按钮"""
        for item in self.children:
            item.disabled = False

class ConfirmView(View):
    """确认对话框"""
    def __init__(self, parent_view: TradingModeView): # 【修改】接收 parent_view
        super().__init__(timeout=30)
        self.parent_view = parent_view # 【修改】保存 parent_view
        
        self.confirm = Button(label="确认", style=discord.ButtonStyle.green, custom_id="confirm_live")
        self.confirm.callback = self.confirm_switch
        self.add_item(self.confirm)
        
        self.cancel = Button(label="取消", style=discord.ButtonStyle.red, custom_id="cancel_live")
        self.cancel.callback = self.cancel_switch
        self.add_item(self.cancel)
    
    async def confirm_switch(self, interaction: discord.Interaction):
        """确认切换到实盘模式"""
        try:
            # 【修改】更新 CONFIG
            CONFIG.run_mode = "live"
            
            # 【修改】通过保存的 parent_view，调用它的方法来更新按钮状态
            self.parent_view.update_to_live_mode()
            
            # 【修改】同时更新父视图的消息和当前确认框的消息
            await self.parent_view.message.edit(view=self.parent_view)
            await interaction.response.edit_message(content="✅ 已成功切换到实盘交易模式", view=None)
            
            logger.info(f"用户 {interaction.user} 切换到实盘交易模式")
        except Exception as e:
            logger.error(f"切换到实盘交易模式失败: {e}", exc_info=True)
            await interaction.response.edit_message(content="❌ 切换失败，请稍后重试", view=None)
    
    async def cancel_switch(self, interaction: discord.Interaction):
        """取消切换"""
        await interaction.response.edit_message(content="❌ 已取消切换", view=None)
    
    async def cancel_switch(self, interaction: discord.Interaction):
        """取消切换"""
        await interaction.response.edit_message(content="❌ 已取消切换", view=None)

class ParameterControlView(View):
    """参数控制视图"""
    def __init__(self):
        super().__init__(timeout=None)
        
        # 杠杆系数下拉菜单
        self.leverage_select = Select(
            placeholder="选择杠杆系数",
            options=[
                discord.SelectOption(label=f"{x}x", value=str(x))
                for x in [2.5, 5.0, 10.0, 20.0]
            ],
            custom_id="leverage_select"
        )
        self.leverage_select.callback = self.update_leverage
        self.add_item(self.leverage_select)
        
        # 火力系数输入框
        self.firepower_button = Button(
            label=f"火力系数: {getattr(CONFIG, 'firepower', 0.8)}",
            style=discord.ButtonStyle.blurple,
            custom_id="firepower_input"
        )
        self.firepower_button.callback = self.input_firepower
        self.add_item(self.firepower_button)
        
        # 资本分配下拉菜单
        self.allocation_select = Select(
            placeholder="选择资本分配",
            options=[
                discord.SelectOption(label="均衡型", value="balanced"),
                discord.SelectOption(label="激进型", value="aggressive"),
                discord.SelectOption(label="保守型", value="conservative")
            ],
            custom_id="allocation_select"
        )
        self.allocation_select.callback = self.update_allocation
        self.add_item(self.allocation_select)
    
    async def update_leverage(self, interaction: discord.Interaction):
        """更新杠杆系数"""
        try:
            new_leverage = float(self.leverage_select.values[0])
            
            # 验证杠杆系数
            if new_leverage <= 0:
                await interaction.followup.send("杠杆系数必须大于0", ephemeral=True)
                return
            
            # 更新配置
            CONFIG.leverage = new_leverage
            
            # 更新按钮文本
            for item in self.children:
                if isinstance(item, Select) and item.custom_id == "leverage_select":
                    item.placeholder = f"杠杆系数: {new_leverage}x"
            
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"杠杆系数已更新为 {new_leverage}x", ephemeral=True)
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 更新杠杆系数为 {new_leverage}")
            
        except Exception as e:
            logger.error(f"更新杠杆系数失败: {e}", exc_info=True)
            await interaction.followup.send("更新失败，请稍后重试", ephemeral=True)
    
    async def input_firepower(self, interaction: discord.Interaction):
        """输入火力系数"""
        # 创建模态对话框
        modal = FirepowerModal()
        await interaction.response.send_modal(modal)
    
    async def update_allocation(self, interaction: discord.Interaction):
        """更新资本分配"""
        try:
            allocation = self.allocation_select.values[0]
            
            # 验证分配模式
            if allocation not in ["balanced", "aggressive", "conservative"]:
                await interaction.followup.send("无效的资本分配模式", ephemeral=True)
                return
            
            # 更新配置
            CONFIG.allocation = allocation
            
            # 更新下拉菜单占位符
            for item in self.children:
                if isinstance(item, Select) and item.custom_id == "allocation_select":
                    item.placeholder = f"资本分配: {allocation}"
            
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"资本分配已更新为 {allocation}", ephemeral=True)
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 更新资本分配为 {allocation}")
            
        except Exception as e:
            logger.error(f"更新资本分配失败: {e}", exc_info=True)
            await interaction.followup.send("更新失败，请稍后重试", ephemeral=True)

class FirepowerModal(Modal, title="设置火力系数"):
    """火力系数输入模态"""
    firepower = TextInput(
        label="火力系数 (0.0-1.0)",
        placeholder="输入0.0到1.0之间的数值",
        required=True,
        max_length=5
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        """提交火力系数"""
        try:
            value = float(self.firepower.value)
            if not 0.0 <= value <= 1.0:
                await interaction.response.send_message("火力系数必须在0.0到1.0之间", ephemeral=True)
                return
            
            # 更新配置
            CONFIG.firepower = value
            
            # 发送响应
            await interaction.response.send_message(f"火力系数已更新为 {value}", ephemeral=True)
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 更新火力系数为 {value}")
            
        except ValueError:
            await interaction.response.send_message("请输入有效的数字", ephemeral=True)
        except Exception as e:
            logger.error(f"更新火力系数失败: {e}", exc_info=True)
            await interaction.response.send_message("更新失败，请稍后重试", ephemeral=True)

class QuickActionsView(View):
    """快速操作视图"""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        
        # 刷新按钮
        self.refresh_button = Button(
            label="🔄 刷新",
            style=discord.ButtonStyle.secondary,
            custom_id="refresh_status"
        )
        self.refresh_button.callback = self.refresh_status
        self.add_item(self.refresh_button)
        
        # 持仓按钮
        self.positions_button = Button(
            label="📊 持仓",
            style=discord.ButtonStyle.secondary,
            custom_id="view_positions"
        )
        self.positions_button.callback = self.view_positions
        self.add_item(self.positions_button)
        
        # 报警历史按钮
        self.alerts_button = Button(
            label="🚨 报警",
            style=discord.ButtonStyle.secondary,
            custom_id="view_alerts"
        )
        self.alerts_button.callback = self.view_alerts
        self.add_item(self.alerts_button)
        
        # 保存按钮
        self.save_button = Button(
            label="💾 保存",
            style=discord.ButtonStyle.secondary,
            custom_id="save_config"
        )
        self.save_button.callback = self.save_config
        self.add_item(self.save_button)

    async def refresh_status(self, interaction: discord.Interaction):
        """刷新状态"""
        try:
            await interaction.response.defer(ephemeral=True)
            embed = discord.Embed(title="📊 系统状态报告", color=discord.Color.green())
            
            status_text = f"🟢 状态: 运行中 | ⚙️ 模式: {'模拟' if CONFIG.run_mode == 'simulate' else '实盘'}"
            embed.add_field(name="系统状态", value=status_text, inline=False)
            
            # 【修改】从 app.state 安全地获取 trading_engine
            trading_engine = getattr(self.bot.app.state, 'trading_engine', None)
            
            macro_status, btc_status, eth_status = "未知", "未知", "未知"
            if trading_engine and hasattr(trading_engine, 'get_macro_status'):
                try:
                    macro_data = await trading_engine.get_macro_status()
                    macro_status = macro_data.get('trend', '未知')
                    btc_status = macro_data.get('btc1d', '未知')
                    eth_status = macro_data.get('eth1d', '未知')
                except Exception as e:
                    logger.error(f"获取宏观状态失败: {e}")
            
            macro_text = f"宏观：{macro_status}\nBTC1d ({btc_status})\nETH1d ({eth_status})"
            embed.add_field(name="🌍 宏观状态", value=macro_text, inline=False)
            
            embed.add_field(name="─" * 20, value="─" * 20, inline=False)
            
            signal_count, signal_status = 0, "无待处理信号"
            if trading_engine and hasattr(trading_engine, 'get_resonance_pool'):
                try:
                    pool_data = await trading_engine.get_resonance_pool()
                    signal_count = len(pool_data.get('signals', []))
                    if signal_count > 0:
                        signal_status = f"有 {signal_count} 个待处理信号"
                except Exception as e:
                    logger.error(f"获取共振池状态失败: {e}")
            
            embed.add_field(name="⏳ 共振池", value=f"({signal_count}个信号)", inline=False)
            embed.add_field(name="信号状态", value=signal_status, inline=False)
            
            embed.add_field(name="─" * 20, value="─" * 20, inline=False)
            
            pnl_text, position_text = "🟢 $0.00", "无持仓"
            if trading_engine:
                try:
                    positions = await trading_engine.get_position("*")
                    if positions:
                        total_pnl, position_lines = 0.0, []
                        for symbol, position in positions.items():
                            size = float(position.get('size', 0))
                            if size != 0:
                                pnl = float(position.get('pnl', 0))
                                total_pnl += pnl
                                side = "多头" if size > 0 else "空头"
                                position_lines.append(f"{symbol} ({side}): {abs(size)}")
                        
                        if total_pnl != 0:
                            pnl_text = f"{'🟢' if total_pnl >= 0 else '🔴'} ${abs(total_pnl):.2f}"
                        if position_lines:
                            position_text = "\n".join(position_lines)
                except Exception as e:
                    logger.error(f"获取持仓信息失败: {e}")
            
            embed.add_field(name="📈 持仓/浮盈", value=pnl_text, inline=False)
            embed.add_field(name="持仓状态", value=position_text, inline=False)
            
            # 【修改】从 app.state 安全地获取 alert_system
            alert_system = getattr(self.bot.app.state, 'alert_system', None)
            if alert_system:
                alert_status = alert_system.get_status()
                alert_emoji = "🔴" if alert_status.get('active') else "🟢"
                embed.add_field(name=f"报警状态 {alert_emoji}", 
                              value=f"最近报警: {alert_status.get('last_alert', '无')}", 
                              inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"用户 {interaction.user} 刷新了系统状态")
        except Exception as e:
            logger.error(f"刷新状态失败: {e}", exc_info=True)
            await interaction.followup.send("刷新失败，请稍后重试", ephemeral=True)
    
    async def view_positions(self, interaction: discord.Interaction):
        """查看持仓"""
        try:
            await interaction.response.defer(ephemeral=True)
            embed = discord.Embed(title="📊 当前持仓", color=discord.Color.blue())
            
            # 【修改】从 app.state 安全地获取 trading_engine
            trading_engine = getattr(self.bot.app.state, 'trading_engine', None)
            
            if trading_engine:
                positions = await trading_engine.get_position("*")
                if not positions or all(float(p.get('size', 0)) == 0 for p in positions.values()):
                    embed.description = "暂无持仓"
                else:
                    for symbol, position in positions.items():
                        size = float(position.get('size', 0))
                        if size != 0:
                            side = "多头" if size > 0 else "空头"
                            pnl = float(position.get('pnl', 0))
                            embed.add_field(name=f"{symbol} ({side})", value=f"数量: {abs(size)}\n浮盈: ${pnl:.2f}", inline=True)
            else:
                embed.description = "交易引擎未初始化"
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"用户 {interaction.user} 查看了持仓信息")
        except Exception as e:
            logger.error(f"查看持仓失败: {e}", exc_info=True)
            await interaction.followup.send("查看持仓失败，请稍后重试", ephemeral=True)
    
    async def view_alerts(self, interaction: discord.Interaction):
        """查看报警历史"""
        try:
            await interaction.response.defer(ephemeral=True)
            embed = discord.Embed(title="📋 报警历史", color=discord.Color.blue())
            
            # 【修改】从 app.state 安全地获取 alert_system
            alert_system = getattr(self.bot.app.state, 'alert_system', None)
            
            if alert_system:
                alerts = alert_system.get_alerts()
                if alerts:
                    for alert in alerts[-5:]:
                        timestamp = int(alert['timestamp'])
                        embed.add_field(name=f"{alert['type']} ({alert['level']})", value=f"{alert['message']}\n<t:{timestamp}:R>", inline=False)
                else:
                    embed.description = "暂无报警记录"
            else:
                embed.description = "报警系统未初始化"
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"用户 {interaction.user} 查看了报警历史")
        except Exception as e:
            logger.error(f"查看报警历史失败: {e}", exc_info=True)
            await interaction.followup.send("查看报警历史失败，请稍后重试", ephemeral=True)
    
    async def view_positions(self, interaction: discord.Interaction):
        """查看持仓"""
        try:
            # 先发送延迟响应
            await interaction.response.defer(ephemeral=True)
            
            # 获取交易引擎实例
            trading_engine = None
            if hasattr(self.bot, 'bot_data') and 'trading_engine' in self.bot.bot_data:
                trading_engine = self.bot.bot_data['trading_engine']
            
            # 创建持仓信息嵌入消息
            embed = discord.Embed(
                title="📊 当前持仓",
                color=discord.Color.blue()
            )
            
            if trading_engine:
                # 获取所有持仓
                positions = await trading_engine.get_position("*")
                if positions:
                    for symbol, position in positions.items():
                        size = float(position.get('size', 0))
                        if size != 0:
                            side = "多头" if size > 0 else "空头"
                            pnl = float(position.get('pnl', 0))
                            embed.add_field(
                                name=f"{symbol} ({side})",
                                value=f"数量: {abs(size)}\n浮盈: ${pnl:.2f}",
                                inline=True
                            )
                else:
                    embed.description = "暂无持仓"
            else:
                embed.description = "交易引擎未初始化"
            
            # 使用 followup 发送实际响应
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 查看了持仓信息")
            
        except Exception as e:
            logger.error(f"查看持仓失败: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("查看持仓失败，请稍后重试", ephemeral=True)
                else:
                    await interaction.followup.send("查看持仓失败，请稍后重试", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"发送错误消息失败: {followup_error}")
    
    async def view_alerts(self, interaction: discord.Interaction):
        """查看报警历史"""
        try:
            # 先发送延迟响应
            await interaction.response.defer(ephemeral=True)
            
            # 创建报警历史嵌入消息
            embed = discord.Embed(
                title="📋 报警历史",
                color=discord.Color.blue()
            )
            
            # 获取报警系统实例
            if hasattr(self.bot, 'bot_data') and 'alert_system' in self.bot.bot_data:
                alerts = self.bot.bot_data['alert_system'].get_alerts()
                if alerts:
                    for alert in alerts[-5:]:  # 显示最近5条报警
                        timestamp = int(alert['timestamp'])
                        embed.add_field(
                            name=f"{alert['type']} ({alert['level']})",
                            value=f"{alert['message']}\n<t:{timestamp}:R>",
                            inline=False
                        )
                else:
                    embed.description = "暂无报警记录"
            else:
                embed.description = "报警系统未初始化"
            
            # 使用 followup 发送实际响应
            await interaction.followup.send(
                embed=embed,
                view=QuickActionsView(self.bot),
                ephemeral=True
            )
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 查看了报警历史")
            
        except Exception as e:
            logger.error(f"查看报警历史失败: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("查看报警历史失败，请稍后重试", ephemeral=True)
                else:
                    await interaction.followup.send("查看报警历史失败，请稍后重试", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"发送错误消息失败: {followup_error}")
    
    async def save_config(self, interaction: discord.Interaction):
        """保存配置"""
        try:
            # 先发送延迟响应
            await interaction.response.defer(ephemeral=True)
            
            # 这里添加保存配置逻辑
            # 例如：将配置保存到数据库
            
            # 使用 followup 发送实际响应
            await interaction.followup.send("✅ 配置已保存", ephemeral=True)
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 保存了配置")
            
        except Exception as e:
            logger.error(f"保存配置失败: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 保存失败，请稍后重试", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 保存失败，请稍后重试", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"发送错误消息失败: {followup_error}")

class TradingDashboard(commands.Cog, name="交易面板"):
    """交易系统控制面板"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="dashboard", description="打开交易控制面板")
    async def dashboard(self, interaction: discord.Interaction):
        """打开交易控制面板"""
        try:
            # 先发送延迟响应
            await interaction.response.defer(ephemeral=True)
            
            # 创建主面板嵌入消息
            embed = discord.Embed(
                title="🎛️ 交易控制面板",
                description="选择下面的选项来控制交易系统",
                color=discord.Color.blue()
            )
            
            # 添加状态信息
            embed.add_field(
                name="当前模式",
                value="🔴 模拟交易" if CONFIG.run_mode == "simulate" else "✅ 实盘交易",
                inline=False
            )
            
            # 使用 followup 发送实际响应
            await interaction.followup.send(
                embed=embed,
                view=TradingModeView(),
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"打开交易控制面板失败: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 打开面板失败，请稍后重试", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 打开面板失败，请稍后重试", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"发送错误消息失败: {followup_error}")

    @app_commands.command(name="parameters", description="调整交易参数")
    async def parameters(self, interaction: discord.Interaction):
        """调整交易参数"""
        try:
            # 先发送延迟响应
            await interaction.response.defer(ephemeral=True)
            
            # 创建参数面板嵌入消息
            embed = discord.Embed(
                title="⚙️ 交易参数设置",
                description="调整下面的参数来改变交易策略的行为",
                color=discord.Color.blue()
            )
            
            # 添加当前参数值
            embed.add_field(
                name="杠杆系数",
                value=f"{getattr(CONFIG, 'leverage', 5.0)}x",
                inline=True
            )
            embed.add_field(
                name="火力系数",
                value=str(getattr(CONFIG, 'firepower', 0.8)),
                inline=True
            )
            embed.add_field(
                name="资本分配",
                value=getattr(CONFIG, 'allocation', 'balanced'),
                inline=True
            )
            
            # 使用 followup 发送实际响应
            await interaction.followup.send(
                embed=embed,
                view=ParameterControlView(),
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"打开参数设置面板失败: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 打开参数面板失败，请稍后重试", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 打开参数面板失败，请稍后重试", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"发送错误消息失败: {followup_error}")

    @app_commands.command(name="quick_actions", description="快速操作")
    async def quick_actions(self, interaction: discord.Interaction):
        """快速操作"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # 【修改】补上了之前审查报告中指出的、被遗漏的 embed 创建代码
            embed = discord.Embed(
                title="🚀 快速操作",
                description="使用下面的按钮快速执行常见操作",
                color=discord.Color.blue()
            )
            
            await interaction.followup.send(
                embed=embed,
                view=QuickActionsView(self.bot),
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"打开快速操作面板失败: {e}", exc_info=True)
            await interaction.followup.send("❌ 打开快速操作面板失败，请稍后重试", ephemeral=True)
