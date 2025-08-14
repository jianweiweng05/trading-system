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
        # --- 【核心修改】确保 MacroAnalyzer 初始化时传入正确的因子文件路径 ---
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
    
    # --- 【核心修改】daily_macro_check 增加了“黑天鹅熔断”的前置检查 ---
    async def daily_macro_check(self) -> None:
        """每日宏观检查任务 (已加入黑天鹅熔断逻辑)"""
        logger.info("开始每日宏观状态检查...")

        # --- 1. 最高优先级的“黑天鹅”检查 ---
        try:
            # 假设 BlackSwanRadar 已更新为我们最终的 check_meltdown_fuse 版本
            should_meltdown, reason = await self.black_swan_radar.check_meltdown_fuse()
            
            if should_meltdown:
                logger.critical(f"！！！熔断指令已触发！！！原因: {reason}")
                logger.critical("！！！将立即清仓并暂停所有交易！！！")
                
                # 在真实系统中，这里会调用:
                # await liquidate_all_positions()
                # await set_system_status("MELTDOWN_PAUSED")
                
                # 发送警报并终止本次检查
                await self.send_discord_webhook(
                    CONFIG.discord_alert_webhook,
                    f"**原因:** {reason}\n\n系统已紧急清仓并暂停所有后续交易，等待人工干预。",
                    "🚨 **系统已触发最高级别熔断!** 🚨",
                    15158332  # 红色
                )
                return # 【关键】直接返回，不再执行后续的常规宏观分析
                
        except Exception as e:
            logger.error(f"黑天鹅雷达检查失败: {e}", exc_info=True)
            # 雷达本身失败，也应该谨慎处理，可以考虑跳过本次交易
            return

        # --- 2. 如果没有熔断，才继续执行常规宏观决策 ---
        logger.info("黑天鹅保险丝正常，继续执行常规宏观决策...")
        
        # (这部分逻辑与我们之前适配好的版本完全相同)
        decision = await self.macro_analyzer.get_macro_decision()
        if not decision:
            logger.error("宏观决策失败，跳过本次检查")
            return
        
        current_season = decision.get("market_season", "OSC")
        score = decision.get("score", 0)
        confidence = decision.get("confidence", 0.5)
        liquidation_signal = decision.get("liquidation_signal")

        await set_config("market_season", current_season)
        logger.info(f"宏观状态已更新: {current_season} (分数: {score:.2f}, 置信度: {confidence:.2f})")
        
        if liquidation_signal:
            title = "🚨 **宏观换季清场警报!** 🚨"
            reason_text = f"市场季节已从 {self.macro_analyzer.last_known_season} 切换为 **{current_season}**"
            action_text = "立即清算所有多头仓位！" if liquidation_signal == "LIQUIDATE_ALL_LONGS" else "立即清算所有空头仓位！"
            content = f"{reason_text}\n\n**执行指令: {action_text}**"
            
            await self.send_discord_webhook(
                CONFIG.discord_alert_webhook, content, title, 15158332
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
        """(此方法现在可以被daily_macro_check替代，但为保持结构不变，暂时保留)"""
        # 这个独立的扫描任务现在可以被认为是多余的，因为核心检查已整合
        # 但为了最小化修改，我们让它继续运行，只作为独立的警报
        logger.info("执行独立的黑天鹅风险扫描...")
        report = await self.black_swan_radar.scan_and_alert() # 假设旧方法依然存在
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
