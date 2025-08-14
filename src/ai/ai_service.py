import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.config import CONFIG
from src.database import set_config, get_config # 假设 get_config 存在
from .macro_analyzer import MacroAnalyzer
from .report_generator import ReportGenerator
from .black_swan_radar import BlackSwanRadar

logger = logging.getLogger("ai_service")

class AIService:
    """AI服务主类"""
    
    def __init__(self) -> None:
        # --- 【核心修改】初始化MacroAnalyzer时，需要传入因子文件路径 ---
        # 我们假设路径在配置文件中
        factor_file_path = getattr(CONFIG, 'factor_history_file', 'factor_history_full.csv')
        self.macro_analyzer: MacroAnalyzer = MacroAnalyzer(CONFIG.deepseek_api_key, factor_file_path)
        
        self.report_generator: ReportGenerator = ReportGenerator(CONFIG.deepseek_api_key)
        self.black_swan_radar: BlackSwanRadar = BlackSwanRadar(CONFIG.deepseek_api_key)
        self.scheduler: AsyncIOScheduler = AsyncIOScheduler(timezone="UTC")
    
    async def send_discord_webhook(self, webhook_url: str, content: str, title: str, color: int) -> None:
        """(此方法保持不变)"""
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
    
    # --- 【核心修改】daily_macro_check 被彻底重写，以适配新的 MacroAnalyzer ---
    async def daily_macro_check(self) -> None:
        """每日宏观检查任务 (适配最终的“大一统”评分模型)"""
        logger.info("开始每日宏观决策...")
        
        # 1. 调用新的核心决策方法
        decision = await self.macro_analyzer.get_macro_decision()
        if not decision:
            logger.error("宏观决策失败，跳过本次检查")
            return
        
        current_season = decision.get("market_season", "OSC")
        score = decision.get("score", 0)
        confidence = decision.get("confidence", 0.5)
        liquidation_signal = decision.get("liquidation_signal")

        # 2. 持久化新的宏观状态到数据库
        await set_config("market_season", current_season)
        logger.info(f"宏观状态已更新: {current_season} (分数: {score:.2f}, 置信度: {confidence:.2f})")
        
        # 3. 检查并处理清场信号
        if liquidation_signal:
            # 这里的逻辑与我们之前在main.py中设计的完全一样
            # 它现在被移到了这个服务模块中，逻辑更集中
            title = "🚨 **宏观换季清场警报!** 🚨"
            reason = f"市场季节已从 {self.macro_analyzer.last_known_season} 切换为 **{current_season}**"
            
            if liquidation_signal == "LIQUIDATE_ALL_LONGS":
                content = f"{reason}\n\n**执行指令: 立即清算所有多头仓位！**"
                # await liquidate_all_long_positions() # 在这里调用真实的平仓函数
            elif liquidation_signal == "LIQUIDATE_ALL_SHORTS":
                content = f"{reason}\n\n**执行指令: 立即清算所有空头仓位！**"
                # await liquidate_all_short_positions() # 在这里调用真实的平仓函数
            
            await self.send_discord_webhook(
                CONFIG.discord_alert_webhook,
                content,
                title,
                15158332  # 红色
            )
    
    async def generate_periodic_report(self, period: str) -> Optional[Dict[str, Any]]:
        """(此方法保持不变)"""
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
        """(此方法保持不变)"""
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
        """(此方法保持不变)"""
        logger.info("AI参谋部 (报告与宏观) 已启动")
        
        self.scheduler.add_job(
            self.daily_macro_check, 'cron', hour=0, minute=0, id='daily_macro_check'
        )
        self.scheduler.add_job(
            lambda: self.generate_periodic_report("周"), 'cron', day_of_week='mon', hour=0, minute=5, id='weekly_report'
        )
        self.scheduler.add_job(
            lambda: self.generate_periodic_report("月"), 'cron', day=1, hour=0, minute=10, id='monthly_report'
        )
        self.scheduler.add_job(
            self.black_swan_scan, 'cron', hour='*/2', id='black_swan_scan'
        )
        self.scheduler.start()
        
        while True:
            await asyncio.sleep(3600)
    
    async def stop(self) -> None:
        """(此方法保持不变)"""
        self.scheduler.shutdown()
        logger.info("AI参谋部已关闭")

# 全局服务实例 (无变动)
ai_service: AIService = AIService()

async def start_ai_service() -> None:
    """(此方法保持不变)"""
    await ai_service.start()

if __name__ == "__main__":
    try:
        asyncio.run(start_ai_service())
    except (KeyboardInterrupt, SystemExit):
        logger.info("AI参谋部正在关闭")
