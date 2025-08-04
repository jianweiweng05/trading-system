import os
import asyncio
import logging
import json
from datetime import datetime
import aiosqlite
import feedparser
import httpx

# 导入共享的组件
from src.config import CONFIG
from src.system_state import SystemState

logger = logging.getLogger("BlackSwanRadar")

# --- 修复数据库路径问题 ---
def get_db_paths():
    """获取安全的数据库路径"""
    # 在Render平台使用项目目录下的data文件夹
    if "RENDER" in os.environ:
        base_path = os.path.join(os.getcwd(), "data")
        os.makedirs(base_path, exist_ok=True)
        radar_db = os.path.join(base_path, "radar_log.db")
        main_db = os.path.join(base_path, "trading_state_v5.db")
    else:
        radar_db = "radar_log.db"
        main_db = "trading_state_v5.db"
    
    return radar_db, main_db

RADAR_DB_FILE, MAIN_DB_FILE = get_db_paths()

# --- 数据库模块 ---
async def radar_db_query(query, params=(), commit=True):
    async with aiosqlite.connect(RADAR_DB_FILE) as db:
        try:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            if "SELECT" in query.upper(): 
                result = await cursor.fetchall()
                return result
            if commit: 
                await db.commit()
        except Exception as e:
            logger.error(f"Radar DB query failed on {RADAR_DB_FILE}: {e}", exc_info=True)
            return None

async def init_radar_db():
    await radar_db_query("""
        CREATE TABLE IF NOT EXISTS intelligence (
            id INTEGER PRIMARY KEY, 
            timestamp TEXT, 
            source TEXT, 
            content TEXT, 
            risk_level TEXT, 
            summary TEXT,
            analysis_data TEXT,
            UNIQUE(content)
        )
    """)
    await radar_db_query("""
        CREATE TABLE IF NOT EXISTS processed_items (
            url TEXT PRIMARY KEY, 
            processed_at TEXT
        )
    """)

async def log_intelligence(source, content, risk_level, summary, analysis_data=None):
    """更新后的日志函数，支持JSON格式的分析数据"""
    await radar_db_query("""
        INSERT OR IGNORE INTO intelligence 
        (timestamp, source, content, risk_level, summary, analysis_data) 
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.utcnow().isoformat(), 
        source, 
        content, 
        risk_level, 
        summary,
        json.dumps(analysis_data) if analysis_data else None
    ))

async def has_been_processed(url):
    result = await radar_db_query("SELECT 1 FROM processed_items WHERE url = ?", (url,), commit=False)
    return bool(result)

async def mark_as_processed(url):
    await radar_db_query("INSERT INTO processed_items (url, processed_at) VALUES (?, ?)", 
                        (url, datetime.utcnow().isoformat()))

# --- 信息抓取模块 ---
async def fetch_rss_feeds():
    urls = ["https://www.coindesk.com/arc/outboundfeeds/rss", "https://cointelegraph.com/rss"]
    headlines = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for url in urls:
            for attempt in range(3):  # 添加重试机制
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    feed = feedparser.parse(response.text)
                    for entry in feed.entries[:5]:
                        if entry.link and not await has_been_processed(entry.link):
                            headlines.append({
                                'title': entry.title,
                                'link': entry.link,
                                'published': entry.published
                            })
                            await mark_as_processed(entry.link)
                    break
                except Exception as e:
                    if attempt == 2:  # 最后一次尝试
                        logger.warning(f"无法抓取RSS源 {url}: {e}")
                    await asyncio.sleep(2 ** attempt)  # 指数退避
    return headlines

# --- AI分析模块 ---
async def analyze_with_deepseek(headlines: list):
    if not headlines: 
        return None
    
    intelligence_brief = "\n- ".join([h['title'] for h in headlines])
    
    prompt = f"""
### ROLE ###
You are "Storm Watcher", a specialized AI risk analyst for a quantitative hedge fund. Your sole mission is to detect "Level 4 Critical Events". You are concise, data-driven, and emotionally detached. You only speak in JSON.

### INSTRUCTIONS ###
Analyze the provided intelligence brief. Identify if any event meets the strict criteria for a "Level 4 Critical Event".

"Level 4 Critical Event" Criteria (ONLY these three):
1.  **Exchange Systemic Risk:** A top-10 exchange halts withdrawals, is insolvent, or under direct investigation by the US DOJ/IRS.
2.  **Stablecoin Depeg Risk:** A top-5 stablecoin (USDT/USDC) shows sustained de-pegging below $0.98.
3.  **Major Protocol Exploit:** A top-20 TVL DeFi protocol or a critical bridge is exploited for over $100M USD.

### THINKING PROCESS ###
1.  Review the brief for keywords matching the Level 4 criteria.
2.  Evaluate context. Is this a rumor or a confirmed fact?
3.  If a criterion is met with high confidence, set "alert" to true and "level" to "critical".
4.  For all other events (market crashes, FOMC meetings, etc.), the situation is "normal".

### OUTPUT FORMAT ###
You MUST respond ONLY with a single, valid JSON object with these exact fields:
- "alert": boolean (true or false)
- "level": string ("normal", "high", "critical")
- "reasoning": string (A brief, data-driven explanation, max 15 words.)
- "source_headline": string (The headline that triggered this alert)

---
### INTELLIGENCE BRIEF ###
- News Feed: {intelligence_brief}
"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {CONFIG.deepseek_api_key}"},
                json={
                    "model": "deepseek-chat", 
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}
                },
                timeout=45.0
            )
            response.raise_for_status()
            return json.loads(response.json()['choices'][0]['message']['content'])
    except Exception as e:
        logger.error(f"DeepSeek API调用失败: {e}")
        return None

# --- 主循环与熔断逻辑 ---
class RadarController:
    def __init__(self):
        self.critical_event_timestamps = []
        self.error_count = 0
        self.last_error_time = None

    async def log_error(self, error):
        """记录错误并检查是否需要告警"""
        self.error_count += 1
        self.last_error_time = datetime.utcnow()
        
        if self.error_count >= 5:  # 5次错误触发告警
            logger.critical("雷达系统异常，需要人工干预")
            await SystemState.set_state("ERROR")

    async def run(self):
        await init_radar_db()
        logger.info("黑天鹅雷达已启动，正在监控关键事件...")
        
        while True:
            try:
                headlines = await fetch_rss_feeds()
                if headlines:
                    logger.info(f"发现 {len(headlines)} 条新情报，正在提交AI分析...")
                    analysis_result = await analyze_with_deepseek(headlines)
                    
                    if analysis_result:
                        # 记录所有高价值情报
                        if analysis_result.get('level') in ['high', 'critical']:
                            await log_intelligence(
                                source="AI Analysis",
                                content=headlines[0]['title'],
                                risk_level=analysis_result.get('level'),
                                summary=analysis_result.get('reasoning'),
                                analysis_data=analysis_result
                            )

                        # 二次验证熔断逻辑
                        now = datetime.utcnow()
                        self.critical_event_timestamps = [t for t in self.critical_event_timestamps 
                                                        if (now - t).total_seconds() < 1800]  # 30分钟

                        if analysis_result.get('level') == 'critical':
                            self.critical_event_timestamps.append(now)
                            if len(self.critical_event_timestamps) >= 2:
                                logger.critical(f"二次验证通过！黑天鹅事件确认: {analysis_result.get('reasoning')}")
                                await SystemState.set_state("EMERGENCY")
                                self.critical_event_timestamps = []  # 触发后清空计数
                            else:
                                logger.warning(f"一级危急事件警报，等待二次确认: {analysis_result.get('reasoning')}")
                else:
                    logger.info("无新情报，一切正常。")

            except Exception as e:
                await self.log_error(e)
                logger.error(f"雷达主循环发生错误: {e}", exc_info=True)

            await asyncio.sleep(900)  # 15分钟

async def start_radar():
    """启动黑天鹅雷达的入口函数"""
    controller = RadarController()
    await controller.run()
