import logging
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View, Modal, TextInput
from src.config import CONFIG

# ================= 日志配置 =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("discord_bot")

# ================= Discord Bot 实例 =================
# 创建一个全局的Discord机器人实例
_bot_instance = None

def get_bot():
    """获取Discord机器人实例"""
    global _bot_instance
    if _bot_instance is None:
        intents = discord.Intents.default()
        intents.message_content = True
        _bot_instance = commands.Bot(
            command_prefix=CONFIG.discord_prefix,
            intents=intents
        )
        
        # 添加on_ready事件
        @_bot_instance.event
        async def on_ready():
            channel = _bot_instance.get_channel(int(CONFIG.discord_channel_id))
            if channel:
                await channel.send("🤖 交易系统已连接")
                logger.info("✅ Discord Bot 已发送连接成功消息")
            else:
                logger.warning("⚠️ 找不到指定的频道，请检查 CONFIG.discord_channel_id 是否正确")
            logger.info(f"✅ Discord Bot 已登录: {_bot_instance.user}")
            
            # 🔑 同步 Slash Commands
            try:
                synced = await _bot_instance.tree.sync()
                logger.info(f"✅ 同步 Slash 命令成功: {len(synced)} 个命令")
            except Exception as e:
                logger.error(f"❌ 同步 Slash 命令失败: {e}")
        
        # 添加命令日志
        @_bot_instance.before_invoke
        async def before_any_command(ctx):
            logger.info(f"🟢 用户 {ctx.author} 调用了命令: {ctx.command} 内容: {ctx.message.content}")

        @_bot_instance.after_invoke
        async def after_any_command(ctx):
            logger.info(f"✅ 命令 {ctx.command} 执行完成")

        @_bot_instance.event
        async def on_command_error(ctx, error):
            logger.error(f"❌ 命令 {ctx.command} 出错: {error}")
            await ctx.send(f"⚠️ 命令执行失败: {str(error)}")
    
    return _bot_instance

# ================= Bot 命令 Cog =================
class TradingCommands(commands.Cog, name="交易系统"):
    """交易系统相关命令"""
    
    def __init__(self, bot):
        self.bot = bot
    
    # 旧版文本命令（!status）
    @commands.command(name="status", help="查看系统状态")
    async def text_status(self, ctx):
        """查看系统状态 - 文本命令版本"""
        try:
            embed = discord.Embed(
                title="📊 系统状态",
                color=discord.Color.green()
            )
            embed.add_field(name="运行模式", value=CONFIG.run_mode)
            embed.add_field(name="Bot状态", value="🟢 在线")
            embed.add_field(name="延迟", value=f"{round(self.bot.latency * 1000)} ms")
            
            # 如果有交易所数据，添加到状态中
            if hasattr(self.bot, 'bot_data') and 'exchange' in self.bot.bot_data:
                embed.add_field(name="交易所连接", value="🟢 已连接", inline=False)
            else:
                embed.add_field(name="交易所连接", value="🔴 未连接", inline=False)
            
            await ctx.send(embed=embed)
            logger.info(f"✅ 用户 {ctx.author} 查看了系统状态")
        except Exception as e:
            logger.error(f"status 命令执行失败: {e}")
            await ctx.send("❌ 获取系统状态失败")
    
    # 新版 Slash 命令（/status）
    @app_commands.command(name="status", description="查看系统状态")
    async def slash_status(self, interaction: discord.Interaction):
        """查看系统状态 - 斜杠命令版本"""
        try:
            embed = discord.Embed(
                title="📊 系统状态",
                color=discord.Color.green()
            )
            embed.add_field(name="运行模式", value=CONFIG.run_mode)
            embed.add_field(name="Bot状态", value="🟢 在线")
            embed.add_field(name="延迟", value=f"{round(self.bot.latency * 1000)} ms")
            
            # 如果有交易所数据，添加到状态中
            if hasattr(self.bot, 'bot_data') and 'exchange' in self.bot.bot_data:
                embed.add_field(name="交易所连接", value="🟢 已连接", inline=False)
            else:
                embed.add_field(name="交易所连接", value="🔴 未连接", inline=False)
            
            await interaction.response.send_message(embed=embed)
            logger.info(f"✅ 用户 {interaction.user} 查看了系统状态")
        except Exception as e:
            logger.error(f"slash status 命令执行失败: {e}")
            await interaction.response.send_message("❌ 获取系统状态失败", ephemeral=True)

# ================= 交易面板 UI 组件 =================
class TradingModeView(View):
    """交易模式切换视图"""
    def __init__(self):
        super().__init__(timeout=None)
        self.current_mode = CONFIG.run_mode
        
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
            self.sim_button.disabled = True
            self.live_button.disabled = True
            
            # 发送响应
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("已切换到模拟交易模式", ephemeral=True)
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 切换到模拟交易模式")
            
            # 启用按钮
            self.sim_button.disabled = False
            self.live_button.disabled = False
            self.current_mode = "simulate"
            
        except Exception as e:
            logger.error(f"切换到模拟交易模式失败: {e}")
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

class ConfirmView(View):
    """确认对话框"""
    def __init__(self):
        super().__init__(timeout=30)
        
        # 确认按钮
        self.confirm = Button(
            label="确认",
            style=discord.ButtonStyle.green,
            custom_id="confirm_live"
        )
        self.confirm.callback = self.confirm_switch
        self.add_item(self.confirm)
        
        # 取消按钮
        self.cancel = Button(
            label="取消",
            style=discord.ButtonStyle.red,
            custom_id="cancel_live"
        )
        self.cancel.callback = self.cancel_switch
        self.add_item(self.cancel)
    
    async def confirm_switch(self, interaction: discord.Interaction):
        """确认切换到实盘模式"""
        try:
            # 更新配置
            CONFIG.run_mode = "live"
            
            # 发送响应
            await interaction.response.edit_message(content="✅ 已切换到实盘交易模式", view=None)
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 切换到实盘交易模式")
            
        except Exception as e:
            logger.error(f"切换到实盘交易模式失败: {e}")
            await interaction.response.send_message("切换失败，请稍后重试", ephemeral=True)
    
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
                for x in [2.5, 5.0, 10.0, 20.0]  # 示例值，实际应从配置获取
            ],
            custom_id="leverage_select"
        )
        self.leverage_select.callback = self.update_leverage
        self.add_item(self.leverage_select)
        
        # 火力系数输入框
        self.firepower_button = Button(
            label=f"火力系数: {getattr(CONFIG, 'firepower', 0.8)}",  # 使用getattr获取默认值
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
            # 这里添加更新逻辑
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
            logger.error(f"更新杠杆系数失败: {e}")
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
            # 这里添加更新逻辑
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
            logger.error(f"更新资本分配失败: {e}")
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
            logger.error(f"更新火力系数失败: {e}")
            await interaction.response.send_message("更新失败，请稍后重试", ephemeral=True)

class QuickActionsView(View):
    """快速操作视图"""
    def __init__(self):
        super().__init__(timeout=None)
        
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
        
        # 保存按钮
        self.save_button = Button(
            label="💾 保存",
            style=discord.ButtonStyle.secondary,
            custom_id="save_config"
        )
        self.save_button.callback = self.save_config
        self.add_item(self.save_button)
        
        # 日志按钮
        self.log_button = Button(
            label="📝 日志",
            style=discord.ButtonStyle.secondary,
            custom_id="view_logs"
        )
        self.log_button.callback = self.view_logs
        self.add_item(self.log_button)
    
    async def refresh_status(self, interaction: discord.Interaction):
        """刷新状态"""
        # 这里添加刷新逻辑
        await interaction.response.defer()
        # 可以发送新的嵌入消息或更新现有消息
    
    async def view_positions(self, interaction: discord.Interaction):
        """查看持仓"""
        # 这里添加查看持仓逻辑
        await interaction.response.defer()
        # 可以发送持仓信息的嵌入消息
    
    async def save_config(self, interaction: discord.Interaction):
        """保存配置"""
        try:
            # 这里添加保存配置逻辑
            await interaction.response.send_message("✅ 配置已保存", ephemeral=True)
            
            # 记录日志
            logger.info(f"用户 {interaction.user} 保存了配置")
            
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            await interaction.response.send_message("❌ 保存失败，请稍后重试", ephemeral=True)
    
    async def view_logs(self, interaction: discord.Interaction):
        """查看日志"""
        # 这里添加查看日志逻辑
        await interaction.response.defer()
        # 可以发送最近日志的嵌入消息

class TradingDashboard(commands.Cog, name="交易面板"):
    """交易系统控制面板"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="dashboard", description="打开交易控制面板")
    async def dashboard(self, interaction: discord.Interaction):
        """打开交易控制面板"""
        try:
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
            
            # 发送消息并添加组件
            await interaction.response.send_message(
                embed=embed,
                view=TradingModeView(),
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"打开交易控制面板失败: {e}")
            await interaction.response.send_message("❌ 打开面板失败，请稍后重试", ephemeral=True)

    @app_commands.command(name="parameters", description="调整交易参数")
    async def parameters(self, interaction: discord.Interaction):
        """调整交易参数"""
        try:
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
            
            # 发送消息并添加组件
            await interaction.response.send_message(
                embed=embed,
                view=ParameterControlView(),
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"打开参数设置面板失败: {e}")
            await interaction.response.send_message("❌ 打开参数面板失败，请稍后重试", ephemeral=True)

    @app_commands.command(name="quick_actions", description="快速操作")
    async def quick_actions(self, interaction: discord.Interaction):
        """快速操作"""
        try:
            # 创建快速操作面板嵌入消息
            embed = discord.Embed(
                title="🚀 快速操作",
                description="使用下面的按钮快速执行常见操作",
                color=discord.Color.blue()
            )
            
            # 发送消息并添加组件
            await interaction.response.send_message(
                embed=embed,
                view=QuickActionsView(),
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"打开快速操作面板失败: {e}")
            await interaction.response.send_message("❌ 打开快速操作面板失败，请稍后重试", ephemeral=True)

# ================= 生命周期管理 =================
async def initialize_bot(bot):
    """初始化 Discord Bot"""
    try:
        # 移除默认的help命令
        bot.remove_command('help')
        
        # 添加交易系统命令Cog
        await bot.add_cog(TradingCommands(bot))
        logger.info("✅ 交易系统命令Cog已添加")
        
        # 添加交易面板Cog
        await bot.add_cog(TradingDashboard(bot))
        logger.info("✅ 交易面板Cog已添加")
        
        logger.info("🚀 正在启动 Discord Bot")
        
        # 启动Discord机器人
        await bot.start(CONFIG.discord_token)
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        raise

async def stop_bot_services(bot):
    """关闭 Discord Bot"""
    if bot.is_ready():
        await bot.close()
        logger.info("🛑 Discord Bot 已关闭")

# ================= 导出配置 =================
__all__ = ['get_bot', 'initialize_bot', 'stop_bot_services']
