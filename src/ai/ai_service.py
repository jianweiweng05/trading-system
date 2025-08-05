import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import CONFIG
from database import set_config
from .macro_analyzer import MacroAnalyzer
from .report_generator import ReportGenerator
from .black_swan_radar import BlackSwanRadar

logger = logging.getLogger("ai_service")

class AIService:
    """AI服务主类"""
    
    def __init__(self) -> None:
        self.macro_analyzer: MacroAnalyzer = MacroAnalyzer(CONFIG.deepseek_api_key)
        self.report_generator: ReportGenerator = ReportGenerator(CONFIG.deepseek_api_key)
        self.black_swan_radar: BlackSwanRadar = BlackSwanRadar(CONFIG.deepseek_api_key)
        self.scheduler: AsyncIOScheduler = AsyncIOScheduler(timezone="UTC")
    
    async def send_discord_webhook(self, webhook_url: str, content: str, title: str, color: int) -> None:
        """通过Webhook向Discord发送消息"""
        if not webhook_url:
            logger.error("Discord Webhook URL未设置")
            return
        
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                payload = {
                    "embeds": [{
                        "title": title,
                        "description": content,
                        "color": color,
                        "timestamp": datetime.utcnow().isoformat()
                    }]
                }
                response = await client.post(webhook_url, json=payload, timeout=10.0)
                response.raise_for_status()
                logger.info(f"成功发送消息到Discord: {title}")
        except Exception as e:
            logger.error(f"发送Discord消息失败: {e}", exc_info=True)
    
    async def daily_macro_check(self) -> None:
        """每日宏观检查任务"""
        logger.info("开始每日宏观牛熊状态检查...")
        
        result = await self.macro_analyzer.analyze_market_status()
        if not result:
            logger.error("AI宏观分析失败，跳过本次检查")
            return
        
        new_status = result.get("bull_bear_status")
        await set_config("macro_bull_bear_status", new_status)
        logger.info(f"宏观状态已更新到主数据库: {new_status}")
        
        if result.get("status_changed"):
            title = "🚨 宏观状态变盘警报! 🚨"
            content = f"**AI判断:** 市场已切换为 **{new_status}**\n" \
                      f"**综合指数:** {result.get('composite_index')}\n" \
                      f"**核心依据:** {result.get('reasoning')}"
            await self.send_discord_webhook(
                CONFIG.discord_alert_webhook,
                content,
                title,
                15158332  # 红色
            )
    
    async def generate_periodic_report(self, period: str) -> Optional[Dict[str, Any]]:
        """生成周期性报告"""
        report = await self.report_generator.generate_periodic_report(period)
        if report:
            await self.send_discord_webhook(
                CONFIG.discord_report_webhook,
                report["content"],
                report["title"],
                report["color"]
            )
        return report
    
    async def black_swan_scan(self) -> None:
        """黑天鹅扫描任务"""
        logger.info("执行黑天鹅风险扫描...")
        report = await self.black_swan_radar.scan_and_alert()
        
        if report:
            await self.send_discord_webhook(
                CONFIG.discord_alert_webhook,
                report['content'],
                report['title'],
                report['color']
            )
    
    async def start(self) -> None:
        """启动AI服务"""
        logger.info("AI参谋部 (报告与宏观) 已启动")
        
        # 每日 UTC 0点 (北京时间早上8点) 执行宏观检查
        self.scheduler.add_job(
            self.daily_macro_check,
            'cron',
            hour=0,
            minute=0,
            id='daily_macro_check'
        )
        
        # 每周一 UTC 0:05 (北京时间早上8:05) 发送周报
        self.scheduler.add_job(
            lambda: self.generate_periodic_report("周"),
            'cron',
            day_of_week='mon',
            hour=0,
            minute=5,
            id='weekly_report'
        )
        
        # 每月1号 UTC 0:10 (北京时间早上8:10) 发送月报
        self.scheduler.add_job(
            lambda: self.generate_periodic_report("月"),
            'cron',
            day=1,
            hour=0,
            minute=10,
            id='monthly_report'
        )
        
        # 添加黑天鹅扫描任务
        self.scheduler.add_job(
            self.black_swan_scan,
            'cron',
            hour='*/2',  # 每2小时扫描一次
            id='black_swan_scan'
        )
        
        self.scheduler.start()
        
        # 保持服务运行
        while True:
            await asyncio.sleep(3600)
    
    async def stop(self) -> None:
        """停止AI服务"""
        self.scheduler.shutdown()
        logger.info("AI参谋部已关闭")

# 全局服务实例
ai_service: AIService = AIService()

async def start_ai_service() -> None:
    """启动AI服务的入口函数"""
    await ai_service.start()

if __name__ == "__main__":
    try:
        asyncio.run(start_ai_service())
    except (KeyboardInterrupt, SystemExit):
        logger.info("AI参谋部正在关闭")
