import logging
import asyncio
import time
import aiohttp
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from src.config import CONFIG

logger = logging.getLogger(__name__)

@dataclass
class AlertRecord:
    """报警记录"""
    type: str
    message: str
    level: str
    timestamp: float
    resolved: bool = False

class AlertSystem:
    """报警系统核心类"""
    
    def __init__(self, webhook_url: str, cooldown_period: int = 300):
        self.webhook_url = webhook_url
        self.cooldown_period = cooldown_period
        self.is_running = False
        self._alerts: List[AlertRecord] = []
        self._last_alert_time: Dict[str, float] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        
        # 报警级别配置
        self.level_config = {
            'emergency': {
                'color': 0xFF0000,  # 红色
                'cooldown': 60,     # 1分钟
                'retry': 3         # 重试3次
            },
            'warning': {
                'color': 0xFFA500,  # 橙色
                'cooldown': 300,   # 5分钟
                'retry': 2         # 重试2次
            },
            'info': {
                'color': 0x0000FF,  # 蓝色
                'cooldown': 600,   # 10分钟
                'retry': 1         # 重试1次
            }
        }
    
    async def start(self):
        """启动报警系统"""
        if self.is_running:
            return
            
        self.is_running = True
        self._session = aiohttp.ClientSession()
        logger.info("✅ 报警系统已启动")
    
    async def stop(self):
        """停止报警系统"""
        if not self.is_running:
            return
            
        self.is_running = False
        if self._session:
            await self._session.close()
        logger.info("🛑 报警系统已停止")
    
    async def trigger_alert(self, alert_type: str, message: str, level: str = "warning"):
        """触发报警"""
        if not self.is_running:
            logger.warning("报警系统未运行")
            return
        
        # 检查冷却时间
        if not self._check_cooldown(alert_type, level):
            logger.debug(f"报警 {alert_type} 在冷却期内，跳过")
            return
        
        # 创建报警记录
        alert = AlertRecord(
            type=alert_type,
            message=message,
            level=level,
            timestamp=time.time()
        )
        self._alerts.append(alert)
        
        # 更新最后报警时间
        self._last_alert_time[alert_type] = alert.timestamp
        
        # 发送报警通知
        await self._send_alert(alert)
        
        # 记录日志
        logger.warning(f"触发报警: {alert_type} - {message}")
    
    def _check_cooldown(self, alert_type: str, level: str) -> bool:
        """检查报警是否在冷却期内"""
        if alert_type not in self._last_alert_time:
            return True
        
        level_config = self.level_config.get(level, self.level_config['warning'])
        time_since_last = time.time() - self._last_alert_time[alert_type]
        return time_since_last >= level_config['cooldown']
    
    async def _send_alert(self, alert: AlertRecord):
        """发送报警通知"""
        if not self.webhook_url or not self._session:
            logger.warning("Webhook URL 未配置或会话未初始化")
            return
        
        level_config = self.level_config.get(alert.level, self.level_config['warning'])
        
        # 准备报警消息
        embed = {
            "title": self._get_alert_title(alert.type),
            "description": alert.message,
            "color": level_config['color'],
            "timestamp": datetime.fromtimestamp(alert.timestamp).isoformat(),
            "fields": [
                {
                    "name": "报警类型",
                    "value": alert.type,
                    "inline": True
                },
                {
                    "name": "报警级别",
                    "value": alert.level.upper(),
                    "inline": True
                },
                {
                    "name": "处理建议",
                    "value": self._get_suggestion(alert.type),
                    "inline": False
                }
            ]
        }
        
        # 准备 Webhook 数据
        webhook_data = {
            "embeds": [embed]
        }
        
        # 发送通知（带重试机制）
        for attempt in range(level_config['retry']):
            try:
                async with self._session.post(
                    self.webhook_url,
                    json=webhook_data,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 204:
                        logger.info(f"报警通知发送成功: {alert.type}")
                        return
                    else:
                        logger.warning(f"报警通知发送失败: HTTP {response.status}")
            except Exception as e:
                logger.error(f"报警通知发送异常 (尝试 {attempt + 1}/{level_config['retry']}): {e}")
                if attempt < level_config['retry'] - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
        
        logger.error(f"报警通知发送失败: {alert.type}")
    
    def _get_alert_title(self, alert_type: str) -> str:
        """获取报警标题"""
        titles = {
            'ORDER_FAILED': '🚨 订单执行失败',
            'ORDER_TIMEOUT': '⚠️ 订单超时',
            'PARTIAL_FILL': '⚠️ 部分成交',
            'INSUFFICIENT_FUNDS': '❌ 资金不足',
            'HIGH_SLIPPAGE': '⚠️ 高滑点',
            'EXCHANGE_ERROR': '🔴 交易所错误',
            'STRATEGY_ERROR': '🚨 策略错误',
            'LIQUIDATION': '⚠️ 清仓指令'
        }
        return titles.get(alert_type, '⚠️ 系统报警')
    
    def _get_suggestion(self, alert_type: str) -> str:
        """获取处理建议"""
        suggestions = {
            'ORDER_FAILED': '① 检查API配额 ② 切换备用账号',
            'ORDER_TIMEOUT': '① 撤单改价 ② 改市价单',
            'PARTIAL_FILL': '① 补单 ② 撤单',
            'INSUFFICIENT_FUNDS': '① 充值 ② 降低仓位',
            'HIGH_SLIPPAGE': '① 检查流动性 ② 调整滑点容忍度',
            'EXCHANGE_ERROR': '① 检查VPN ② 切换备用交易所',
            'STRATEGY_ERROR': '① 暂停策略 ② 检查参数',
            'LIQUIDATION': '① 确认清仓原因 ② 评估市场风险'
        }
        return suggestions.get(alert_type, '请检查系统状态')
    
    def get_status(self) -> Dict[str, Any]:
        """获取报警系统状态"""
        return {
            'active': self.is_running,
            'last_alert': self._alerts[-1].message if self._alerts else None,
            'alert_count': len(self._alerts),
            'pending_alerts': len([a for a in self._alerts if not a.resolved])
        }
    
    def get_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取报警历史"""
        return [
            {
                'type': alert.type,
                'message': alert.message,
                'level': alert.level,
                'timestamp': alert.timestamp,
                'resolved': alert.resolved
            }
            for alert in self._alerts[-limit:]
        ]
    
    def resolve_alert(self, alert_type: str):
        """解决指定类型的报警"""
        for alert in self._alerts:
            if alert.type == alert_type and not alert.resolved:
                alert.resolved = True
                logger.info(f"报警已解决: {alert_type}")
    
    def clear_resolved_alerts(self):
        """清除已解决的报警"""
        self._alerts = [a for a in self._alerts if not a.resolved]
        logger.info("已清除所有已解决的报警")
