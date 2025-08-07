import logging
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from typing import Optional, Dict, Any
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
        async def before_any_command(ctx: commands.Context):
            logger.info(f"🟢 用户 {ctx.author} 调用了命令: {ctx.command} 内容: {ctx.message.content}")

        @_bot_instance.after_invoke
        async def after_any_command(ctx: commands.Context):
            logger.info(f"✅ 命令 {ctx.command} 执行完成")

        @_bot_instance.event
        async def on_command_error(ctx: commands.Context, error: Exception):
            logger.error(f"❌ 命令 {ctx.command} 出错: {error}")
            if not ctx.response.is_done():
                await ctx.send(f"⚠️ 命令执行失败: {str(error)}", ephemeral=True)
    
    return _bot_instance

# ================= Bot 命令 Cog =================
class TradingCommands(commands.Cog, name="交易系统"):
    """交易系统相关命令"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.bot_data: Dict[str, Any] = {
            'exchange': None,
            'db_pool': None,
            'alert_system': None,  # 添加报警系统引用
            'trading_engine': None  # 添加交易引擎引用
        }
        self.alert_status = {
            'active': False,
            'last_alert': None,
            'alert_count': 0,
            'alerts': {}  # 添加报警历史记录
        }
        # 添加宏观状态缓存
        self._macro_status: Optional[Dict[str, Any]] = None
        self._last_macro_update: float = 0
        # 添加共振池状态缓存
        self._resonance_status: Optional[Dict[str, Any]] = None
        self._last_resonance_update: float = 0
    
    # 新增：获取宏观状态方法
    async def get_macro_status(self) -> Dict[str, Any]:
        """获取宏观状态信息"""
        current_time = asyncio.get_event_loop().time()
        
        # 如果缓存不存在或过期（超过5分钟），重新获取
        if (not self._macro_status or 
            current_time - self._last_macro_update > 300):
            
            logger.info("更新宏观状态缓存...")
            try:
                if hasattr(self.bot, 'bot_data') and 'trading_engine' in self.bot.bot_data:
                    trading_engine = self.bot.bot_data['trading_engine']
                    if hasattr(trading_engine, 'get_macro_status'):
                        self._macro_status = await trading_engine.get_macro_status()
                        self._last_macro_update = current_time
            except Exception as e:
                logger.error(f"获取宏观状态失败: {e}")
                # 如果获取失败，返回默认值
                if not self._macro_status:
                    self._macro_status = {
                        'trend': '未知',
                        'btc1d': '未知',
                        'eth1d': '未知',
                        'confidence': 0,
                        'last_update': current_time
                    }
        
        return self._macro_status.copy() if self._macro_status else {
            'trend': '未知',
            'btc1d': '未知',
            'eth1d': '未知',
            'confidence': 0,
            'last_update': current_time
        }

    # 新增：获取共振池状态方法
    async def get_resonance_status(self) -> Dict[str, Any]:
        """获取共振池状态信息"""
        current_time = asyncio.get_event_loop().time()
        
        # 如果缓存不存在或过期（超过1分钟），重新获取
        if (not self._resonance_status or 
            current_time - self._last_resonance_update > 60):
            
            logger.info("更新共振池状态缓存...")
            try:
                if hasattr(self.bot, 'bot_data') and 'trading_engine' in self.bot.bot_data:
                    trading_engine = self.bot.bot_data['trading_engine']
                    if hasattr(trading_engine, 'get_resonance_pool'):
                        pool_data = await trading_engine.get_resonance_pool()
                        # 转换数据格式以适配前端显示
                        self._resonance_status = {
                            'signal_count': pool_data.get('count', 0),
                            'pending_signals': [
                                f"{signal_id}: {signal_data.get('status', 'unknown')}"
                                for signal_id, signal_data in pool_data.get('signals', {}).items()
                                if signal_data.get('status') == 'pending'
                            ],
                            'last_update': current_time
                        }
                        self._last_resonance_update = current_time
            except Exception as e:
                logger.error(f"获取共振池状态失败: {e}")
                # 如果获取失败，返回默认值
                if not self._resonance_status:
                    self._resonance_status = {
                        'signal_count': 0,
                        'pending_signals': [],
                        'last_update': current_time
                    }
        
        return self._resonance_status.copy() if self._resonance_status else {
            'signal_count': 0,
            'pending_signals': [],
            'last_update': current_time
        }
    
    # 旧版文本命令（!status）
    @commands.command(name="status", help="查看系统状态")
    async def text_status(self, ctx: commands.Context):
        """查看系统状态 - 文本命令版本"""
        try:
            embed = discord.Embed(
                title="📊 系统状态",
                color=discord.Color.green()
            )
            embed.add_field(name="运行模式", value=CONFIG.run_mode)
            embed.add_field(name="Bot状态", value="🟢 在线")
            embed.add_field(name="延迟", value=f"{round(self.bot.latency * 1000)} ms")
            
            # 添加宏观状态
            macro_status = await self.get_macro_status()
            macro_text = f"""宏观：{macro_status['trend']}
BTC1d ({macro_status['btc1d']})
ETH1d ({macro_status['eth1d']})"""
            embed.add_field(name="🌍 宏观状态", value=macro_text, inline=False)
            
            # 添加共振池状态
            resonance_status = await self.get_resonance_status()
            resonance_text = f"⏳ 共振池 ({resonance_status['signal_count']}个信号)\n"
            if resonance_status['pending_signals']:
                resonance_text += "待处理信号：\n" + "\n".join(resonance_status['pending_signals'])
            else:
                resonance_text += "无待处理信号"
            embed.add_field(name="🔄 共振池状态", value=resonance_text, inline=False)
            
            # 添加报警状态显示
            alert_status = "🟢 正常" if not self.alert_status['active'] else "🔴 报警中"
            embed.add_field(name="报警状态", value=alert_status, inline=False)
            if self.alert_status['last_alert']:
                embed.add_field(name="最近报警", value=self.alert_status['last_alert'], inline=False)
            embed.add_field(name="总报警次数", value=str(self.alert_status['alert_count']), inline=True)
            
            await ctx.send(embed=embed)
            logger.info(f"✅ 用户 {ctx.author} 查看了系统状态")
        except Exception as e:
            logger.error(f"status 命令执行失败: {e}")
            if not ctx.response.is_done():
                await ctx.send("❌ 获取系统状态失败", ephemeral=True)
    
    # 新版 Slash 命令（/status）
    @app_commands.command(name="status", description="查看系统状态")
    async def slash_status(self, interaction: discord.Interaction):
        """查看系统状态 - 斜杠命令版本"""
        try:
            # 先发送一个延迟响应，避免交互超时
            await interaction.response.defer(ephemeral=True)
            
            embed = discord.Embed(
                title="📊 系统状态",
                color=discord.Color.green()
            )
            embed.add_field(name="运行模式", value=CONFIG.run_mode)
            embed.add_field(name="Bot状态", value="🟢 在线")
            embed.add_field(name="延迟", value=f"{round(self.bot.latency * 1000)} ms")
            
            # 添加宏观状态
            macro_status = await self.get_macro_status()
            macro_text = f"""宏观：{macro_status['trend']}
BTC1d ({macro_status['btc1d']})
ETH1d ({macro_status['eth1d']})"""
            embed.add_field(name="🌍 宏观状态", value=macro_text, inline=False)
            
            # 添加共振池状态
            resonance_status = await self.get_resonance_status()
            resonance_text = f"⏳ 共振池 ({resonance_status['signal_count']}个信号)\n"
            if resonance_status['pending_signals']:
                resonance_text += "待处理信号：\n" + "\n".join(resonance_status['pending_signals'])
            else:
                resonance_text += "无待处理信号"
            embed.add_field(name="🔄 共振池状态", value=resonance_text, inline=False)
            
            # 添加报警状态显示
            alert_status = "🟢 正常" if not self.alert_status['active'] else "🔴 报警中"
            embed.add_field(name="报警状态", value=alert_status, inline=False)
            if self.alert_status['last_alert']:
                embed.add_field(name="最近报警", value=self.alert_status['last_alert'], inline=False)
            embed.add_field(name="总报警次数", value=str(self.alert_status['alert_count']), inline=True)
            
            # 使用 followup 发送实际响应
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user} 查看了系统状态")
            
        except discord.errors.InteractionResponded:
            logger.error("交互已响应，无法再次发送响应")
        except Exception as e:
            logger.error(f"slash status 命令执行失败: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 获取系统状态失败", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 获取系统状态失败", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"发送错误消息失败: {followup_error}")

    # 新增：报警触发方法
    async def trigger_alert(self, alert_type: str, message: str, level: str = "warning"):
        """触发报警"""
        # 更新报警状态
        self.alert_status['active'] = True
        self.alert_status['last_alert'] = f"{alert_type}: {message}"
        self.alert_status['alert_count'] += 1
        
        # 记录报警历史
        self.alert_status['alerts'][alert_type] = {
            'message': message,
            'timestamp': asyncio.get_event_loop().time(),
            'level': level
        }
        
        # 发送报警消息到指定频道
        channel = self.bot.get_channel(int(CONFIG.discord_channel_id))
        if channel:
            # 根据报警级别选择颜色
            color_map = {
                'emergency': discord.Color.red(),
                'warning': discord.Color.orange(),
                'info': discord.Color.blue()
            }
            color = color_map.get(level, discord.Color.red())
            
            # 根据报警类型选择标题图标
            icon_map = {
                'ORDER_FAILED': '🚨',
                'ORDER_TIMEOUT': '⚠️',
                'PARTIAL_FILL': '⚠️',
                'INSUFFICIENT_FUNDS': '❌',
                'HIGH_SLIPPAGE': '⚠️',
                'EXCHANGE_ERROR': '🔴',
                'STRATEGY_ERROR': '🚨'
            }
            icon = icon_map.get(alert_type, '⚠️')
            
            embed = discord.Embed(
                title=f"{icon} 系统报警",
                description=message,
                color=color
            )
            embed.add_field(name="报警类型", value=alert_type, inline=True)
            embed.add_field(name="报警级别", value=level.upper(), inline=True)
            embed.add_field(name="报警次数", value=str(self.alert_status['alert_count']), inline=True)
            
            # 添加处理建议
            suggestions = {
                'ORDER_FAILED': "① 检查API配额 ② 切换备用账号",
                'ORDER_TIMEOUT': "① 撤单改价 ② 改市价单",
                'PARTIAL_FILL': "① 补单 ② 撤单",
                'INSUFFICIENT_FUNDS': "① 充值 ② 降低仓位",
                'HIGH_SLIPPAGE': "① 检查流动性 ② 调整滑点容忍度",
                'EXCHANGE_ERROR': "① 检查VPN ② 切换备用交易所",
                'STRATEGY_ERROR': "① 暂停策略 ② 检查参数"
            }
            if alert_type in suggestions:
                embed.add_field(name="处理建议", value=suggestions[alert_type], inline=False)
            
            await channel.send(embed=embed)
        
        # 如果有报警系统实例，也触发报警
        if self.bot.bot_data.get('alert_system'):
            try:
                await self.bot.bot_data['alert_system'].trigger_alert(
                    alert_type=alert_type,
                    message=message,
                    level=level
                )
            except Exception as e:
                logger.error(f"触发报警系统失败: {e}")
        
        logger.warning(f"触发报警: {alert_type} - {message}")

    # 新增：报警历史命令
    @commands.command(name="alerts", help="查看报警历史")
    async def text_alerts(self, ctx: commands.Context):
        """查看报警历史 - 文本命令版本"""
        try:
            embed = discord.Embed(
                title="📋 报警历史",
                color=discord.Color.blue()
            )
            
            if not self.alert_status['alerts']:
                embed.description = "暂无报警记录"
            else:
                for alert_type, alert_data in self.alert_status['alerts'].items():
                    timestamp = int(alert_data['timestamp'])
                    embed.add_field(
                        name=f"{alert_type} ({alert_data['level'].upper()})",
                        value=f"{alert_data['message']}\n<t:{timestamp}:R>",
                        inline=False
                    )
            
            await ctx.send(embed=embed)
            logger.info(f"✅ 用户 {ctx.author} 查看了报警历史")
        except Exception as e:
            logger.error(f"alerts 命令执行失败: {e}")
            if not ctx.response.is_done():
                await ctx.send("❌ 获取报警历史失败", ephemeral=True)

    # 新增：报警历史 Slash 命令
    @app_commands.command(name="alerts", description="查看报警历史")
    async def slash_alerts(self, interaction: discord.Interaction):
        """查看报警历史 - 斜杠命令版本"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            embed = discord.Embed(
                title="📋 报警历史",
                color=discord.Color.blue()
            )
            
            if not self.alert_status['alerts']:
                embed.description = "暂无报警记录"
            else:
                for alert_type, alert_data in self.alert_status['alerts'].items():
                    timestamp = int(alert_data['timestamp'])
                    embed.add_field(
                        name=f"{alert_type} ({alert_data['level'].upper()})",
                        value=f"{alert_data['message']}\n<t:{timestamp}:R>",
                        inline=False
                    )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"✅ 用户 {interaction.user} 查看了报警历史")
            
        except discord.errors.InteractionResponded:
            logger.error("交互已响应，无法再次发送响应")
        except Exception as e:
            logger.error(f"slash alerts 命令执行失败: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 获取报警历史失败", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 获取报警历史失败", ephemeral=True)
            except Exception as followup_error:
                logger.error(f"发送错误消息失败: {followup_error}")

# ================= 生命周期管理 =================
async def initialize_bot(bot: commands.Bot):
    """初始化 Discord Bot"""
    try:
        # 初始化数据库连接池
        from src.database import db_pool
        bot.bot_data['db_pool'] = db_pool
        
        # 移除默认的help命令
        bot.remove_command('help')
        
        # 添加交易系统命令Cog
        trading_cog = TradingCommands(bot)
        await bot.add_cog(trading_cog)
        logger.info("✅ 交易系统命令Cog已添加")
        
        # 添加交易面板Cog
        from src.discord_ui import TradingDashboard
        await bot.add_cog(TradingDashboard(bot))
        logger.info("✅ 交易面板Cog已添加")
        
        logger.info("🚀 正在启动 Discord Bot")
        
        # 启动Discord机器人
        await bot.start(CONFIG.discord_token)
    except Exception as e:
        logger.error(f"Discord机器人启动失败: {e}")
        raise

async def stop_bot_services(bot: commands.Bot):
    """关闭 Discord Bot"""
    if bot.is_ready():
        await bot.close()
        logger.info("🛑 Discord Bot 已关闭")

async def start_discord_bot():
    """启动Discord Bot的入口函数"""
    bot = get_bot()
    try:
        await initialize_bot(bot)
    except Exception as e:
        logger.error(f"Discord Bot 启动失败: {e}")
        raise

# ================= 导出配置 =================
__all__ = ['get_bot', 'initialize_bot', 'stop_bot_services', 'start_discord_bot']
