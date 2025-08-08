
import logging
import asyncio # 【修改】导入我们需要的 asyncio 库
from typing import Dict, Any, List, Optional
from datetime import datetime
from .ai_client import AIClient
from src.config import CONFIG

logger = logging.getLogger(__name__)

class BlackSwanRadar:
    """黑天鹅雷达模块"""
    
    def __init__(self, api_key: str) -> None:
        self.ai_client: AIClient = AIClient(api_key)
        self.alert_thresholds: Dict[str, float] = {
            'price_volatility': 0.15,  # 价格波动阈值
            'volume_surge': 2.0,      # 交易量激增阈值
            'funding_rate': 0.01     # 资金费率异常阈值
        }
    
    async def collect_market_data(self) -> Dict[str, Any]:
        """收集市场数据"""
        # TODO: 实现实际的市场数据收集逻辑
        return {
            'price_volatility': 0.12,
            'volume_surge': 1.8,
            'funding_rate': 0.008,
            'social_sentiment': 'neutral',
            'news_events': []
        }
    
    async def analyze_risk_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析风险信号"""
        signals = []
        
        # 价格波动分析
        if market_data['price_volatility'] > self.alert_thresholds['price_volatility']:
            signals.append({
                'type': 'price_volatility',
                'severity': 'high',
                'description': f"价格波动率异常: {market_data['price_volatility']:.2%}",
                'timestamp': datetime.utcnow()
            })
        
        # 交易量分析
        if market_data['volume_surge'] > self.alert_thresholds['volume_surge']:
            signals.append({
                'type': 'volume_surge',
                'severity': 'medium',
                'description': f"交易量激增: {market_data['volume_surge']:.1f}倍",
                'timestamp': datetime.utcnow()
            })
        
        # 资金费率分析
        if abs(market_data['funding_rate']) > self.alert_thresholds['funding_rate']:
            signals.append({
                'type': 'funding_rate',
                'severity': 'medium',
                'description': f"资金费率异常: {market_data['funding_rate']:.2%}",
                'timestamp': datetime.utcnow()
            })
        
        return signals
    
    async def generate_alert_report(self, signals: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """生成警报报告"""
        if not signals:
            return None
        
        # 按严重程度排序
        severity_order = {'high': 3, 'medium': 2, 'low': 1}
        signals.sort(key=lambda x: severity_order.get(x['severity'], 0), reverse=True)
        
        # 生成报告内容
        report_content = "⚠️ **黑天鹅风险警报** ⚠️\n\n"
        for signal in signals:
            emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(signal['severity'], '⚪')
            report_content += f"{emoji} **{signal['type']}** ({signal['severity']})\n"
            report_content += f"   {signal['description']}\n\n"
        
        return {
            'title': '🚨 黑天鹅风险警报',
            'content': report_content,
            'color': 15158332,  # 红色
            'signals': signals
        }
    
    async def scan_and_alert(self) -> Optional[Dict[str, Any]]:
        """执行扫描并发送警报"""
        logger.info("开始黑天鹅风险扫描...")
        
        # 收集市场数据
        market_data = await self.collect_market_data()
        
        # 分析风险信号
        signals = await self.analyze_risk_signals(market_data)
        
        # 生成警报报告
        report = await self.generate_alert_report(signals)
        
        if report:
            logger.warning(f"检测到黑天鹅风险信号: {len(signals)}个")
            return report
        
        logger.info("未检测到黑天鹅风险信号")
        return None

# --- 【这里是核心修改】 ---
# 黑天鹅雷达启动函数
async def start_black_swan_radar():
    """
    启动黑天鹅雷达的入口函数。
    这个函数现在包含一个无限循环，每30分钟执行一次扫描。
    """
    radar = BlackSwanRadar(CONFIG.deepseek_api_key)
    
    while True:
        try:
            await radar.scan_and_alert()
            
            # 扫描完成后，强制休息30分钟（1800秒）
            logger.info("黑天鹅雷达完成一次扫描，将休眠30分钟...")
            await asyncio.sleep(1800)
            
        except Exception as e:
            logger.error(f"黑天鹅雷达在循环中遇到错误: {e}", exc_info=True)
            # 即使发生错误，也等待一段时间再重试，避免快速失败导致CPU占满
            await asyncio.sleep(60)


if __name__ == "__main__":
    # 这部分保持不变，用于单独测试此文件
    import asyncio
    try:
        asyncio.run(start_black_swan_radar())
    except (KeyboardInterrupt, SystemExit):
        logger.info("黑天鹅雷达正在关闭")
