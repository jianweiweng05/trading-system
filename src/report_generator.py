import os
import asyncio
import logging
from datetime import datetime, timedelta
import aiosqlite
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

# --- 1. 从我们自己的模块中导入所有“专家”和“工具” ---
from config import CONFIG

logger = logging.getLogger("ReportGenerator")

# --- 2. 数据库功能 (独立于交易数据库) ---
async def radar_db_query(query, params=(), commit=True):
    async with aiosqlite.connect(CONFIG.radar_db_path) as db:
        try:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            if "SELECT" in query.upper(): return await cursor.fetchall()
            if commit: await db.commit()
        except Exception as e:
            logger.error(f"报告生成器DB查询失败: {e}", exc_info=True)

# --- 3. 报告生成模块 ---
async def get_intelligence_for_period(days: int):
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = await radar_db_query("SELECT summary FROM intelligence WHERE timestamp >= ? AND risk_level IN ('high', 'critical')", (cutoff_date,), commit=False)
    return [row['summary'] for row in rows] if rows else []

async def generate_report_with_deepseek(period: str, intelligence: list):
    if not intelligence:
        return f"**上{period}回顾:**\n- 过去{ '7天' if period=='周' else '30天' }内，AI雷达未侦测到值得报告的高风险事件。"

    intelligence_brief = "\n- ".join(intelligence)
    prompt = f"""
你是一位顶级的宏观经济策略师，为对冲基金撰写每周加密市场展望报告。你的风格必须专业、简洁、数据驱动。

请基于以下过去{ '一周' if period=='周' else '一个月' }由“风暴守望者”AI雷达筛选出的核心情报数据，撰写一份完整的《加密市场战略情报{period}报》。报告必须包含“上{period}回顾”、“本{period}展望”和“AI战略洞察”三个部分，并给出一个核心观点。

核心情报数据：
{intelligence_brief}

请直接以Markdown格式输出最终的报告内容，不要包含任何解释。
"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {CONFIG.deepseek_api_key}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90.0
            )
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"DeepSeek报告生成失败: {e}")
        return f"AI报告生成失败: {e}"

# --- 4. 定时任务与主程序 ---
async def send_weekly_report():
    bot = Bot(token=CONFIG.telegram_bot_token)
    logger.info("正在生成战略情报周报...")
    
    intelligence = await get_intelligence_for_period(7)
    report_content = await generate_report_with_deepseek("周", intelligence)
    
    header = f"📰 **AI战略情报周报**\n"
    await bot.send_message(CONFIG.admin_chat_id, header + report_content, parse_mode='Markdown')
    logger.info("战略情报周报已发送。")

async def send_monthly_report():
    bot = Bot(token=CONFIG.telegram_bot_token)
    logger.info("正在生成战略情报月报...")
    
    intelligence = await get_intelligence_for_period(30)
    report_content = await generate_report_with_deepseek("月", intelligence)
    
    header = f"📅 **AI战略情报月报**\n"
    await bot.send_message(CONFIG.admin_chat_id, header + report_content, parse_mode='Markdown')
    logger.info("战略情报月报已发送。")

async def start_reporter():
    """启动报告生成器的入口函数"""
    logger.info("报告生成器已启动，正在等待计划任务...")
    scheduler = AsyncIOScheduler(timezone="UTC")
    
    # 每周一 UTC 00:05 (北京时间早上8:05) 发送周报
    scheduler.add_job(send_weekly_report, 'cron', day_of_week='mon', hour=0, minute=5)
    
    # 每月1号 UTC 00:10 (北京时间早上8:10) 发送月报
    scheduler.add_job(send_monthly_report, 'cron', day=1, hour=0, minute=10)
    
    scheduler.start()
    
    # 保持脚本持续运行
    while True:
        await asyncio.sleep(3600)