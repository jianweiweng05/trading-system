# --- 请用这段新代码，完整替换你现有的 macro_analyzer.py 文件 ---

import logging
import time
from typing import Dict, Any, Optional
from .ai_client import AIClient
from src.data_loader import load_strategy_data
# --- 【修改】导入数据库相关的工具 ---
from src.database import db_pool, text

logger = logging.getLogger(__name__)

class MacroAnalyzer:
    """宏观分析器 (已升级，增加了状态切换检测和清场逻辑)"""
    
    def __init__(self, api_key: str) -> None:
        self.ai_client: AIClient = AIClient(api_key)
        self.last_known_season: Optional[str] = None
        self._detailed_status: Optional[Dict[str, Any]] = None
        self._last_status_update: float = 0
    
    # --- 【修改】get_macro_data 函数现在会加载历史数据和实时TV信号 ---
    async def get_macro_data(self) -> Dict[str, str]:
        """获取宏观分析数据，现在会结合历史数据和最新的TV信号"""
        
        # 1. 加载静态的历史数据总结
        strategy_files = [
            "BTC1d.xlsx", "BTC10h.xlsx", "ETH1d多.xlsx", "ETH1d空.xlsx",
            "ETH4h.xlsx", "AVAX9h.xlsx", "SOL10h.xlsx", "ADA4h.xlsx"
        ]
        all_summaries = []
        SUMMARY_COLUMN_NAME = "策略总结" # <--- 请确保这个列名与你的 Excel 文件一致

        for filename in strategy_files:
            strategy_df = load_strategy_data(filename)
            if strategy_df is not None and SUMMARY_COLUMN_NAME in strategy_df.columns:
                summary_text = strategy_df[SUMMARY_COLUMN_NAME].iloc[0]
                all_summaries.append(f"策略 {filename} 的回测总结: {summary_text}")
            else:
                logger.warning(f"在文件 {filename} 中找不到 '{SUMMARY_COLUMN_NAME}' 列，已跳过。")
        
        combined_summary = "\n".join(all_summaries) if all_summaries else "未能加载任何策略的历史数据。"

        # 2. 加载最新的、持久化的 TV 日线信号
        tv_status_summary = "TV 日线信号未知。"
        try:
            async with db_pool.get_session() as session:
                result = await session.execute(text('SELECT symbol, status FROM tv_status'))
                rows = result.fetchall()
                if rows:
                    status_texts = [f"{row[0].upper()} 的当前 1D 信号是 {row[1]}" for row in rows]
                    tv_status_summary = " ".join(status_texts)
        except Exception as e:
            logger.error(f"在宏观分析中加载TV状态失败: {e}")

        # 3. 将所有信息整合后返回
        return {
            "price_trend_summary": combined_summary,
            "onchain_summary": "链上数据分析待实现。",
            "funding_summary": "资金费率分析待实现。",
            "current_signals": tv_status_summary # 新增字段，专门给AI看当前信号
        }
    
    async def analyze_market_status(self) -> Optional[Dict[str, Any]]:
        """
        分析市场状态 (此函数现在作为底层分析工具，为其调用者服务)
        """
        logger.info("正在调用AI模型进行底层宏观分析...")
        macro_data = await self.get_macro_data()
        result = await self.ai_client.analyze_macro(macro_data)
        
        if not result or 'market_season' not in result:
            logger.error("AI宏观分析失败或返回格式无效", exc_info=True)
            return None
            
        return result

    async def get_macro_decision(self) -> Dict[str, Any]:
        """
        获取最终的宏观决策，包含状态切换时的清场指令。
        这是您系统现在应该调用的主要入口。
        """
        logger.info("开始进行宏观决策...")
        
        ai_analysis = await self.analyze_market_status()
        
        if not ai_analysis:
            return {
                "current_season": self.last_known_season or "UNKNOWN",
                "liquidation_signal": None,
                "reason": "AI analysis failed, no action taken."
            }

        current_season = ai_analysis['market_season']
        liquidation_signal = None
        reason = f"AI analysis complete. Current season: {current_season}."

        if self.last_known_season and current_season != self.last_known_season:
            logger.warning(
                f"宏观季节发生切换！"
                f"由 {self.last_known_season} 切换至 {current_season}"
            )
            if current_season == "BULL":
                liquidation_signal = "LIQUIDATE_ALL_SHORTS"
                reason = f"宏观季节由 {self.last_known_season} 转为 BULL. 触发指令：清算所有空头仓位。"
            elif current_season == "BEAR":
                liquidation_signal = "LIQUIDATE_ALL_LONGS"
                reason = f"宏观季节由 {self.last_known_season} 转为 BEAR. 触发指令：清算所有多头仓位。"
        
        self.last_known_season = current_season
        
        current_timestamp = ai_analysis.get('timestamp', time.time())
        self._detailed_status = {
            'trend': '牛' if current_season == 'BULL' else '熊' if current_season == 'BEAR' else '震荡',
            'btc1d': ai_analysis.get('btc_trend', '中性'),
            'eth1d': ai_analysis.get('eth_trend', '中性'),
            'confidence': ai_analysis.get('confidence', 0),
            'last_update': current_timestamp
        }
        self._last_status_update = current_timestamp
        
        try:
            from src.database import set_setting
            await set_setting('market_season', current_season)
            logger.info(f"宏观状态 '{current_season}' 已成功持久化到数据库")
        except Exception as e:
            logger.error(f"持久化宏观状态失败: {e}", exc_info=True)
        
        return {
            "current_season": current_season,
            "ai_confidence": ai_analysis.get('confidence'),
            "liquidation_signal": liquidation_signal,
            "reason": reason
        }
    
    async def get_detailed_status(self) -> Dict[str, Any]:
        """
        获取详细的宏观状态信息，用于UI显示
        """
        current_time = time.time()
        if (not self._detailed_status or 
            current_time - self._last_status_update > 300):
            
            logger.info("更新宏观状态缓存...")
            ai_analysis = await self.analyze_market_status()
            
            if ai_analysis:
                self._detailed_status = {
                    'trend': '牛' if ai_analysis.get('market_season') == 'BULL' else '熊' if ai_analysis.get('market_season') == 'BEAR' else '震荡',
                    'btc1d': ai_analysis.get('btc_trend', '中性'),
                    'eth1d': ai_analysis.get('eth_trend', '中性'),
                    'confidence': ai_analysis.get('confidence', 0),
                    'last_update': ai_analysis.get('timestamp', current_time)
                }
                self._last_status_update = current_time
            else:
                if not self._detailed_status:
                    self._detailed_status = {
                        'trend': '未知',
                        'btc1d': '未知',
                        'eth1d': '未知',
                        'confidence': 0,
                        'last_update': current_time
                    }
        
        return self._detailed_status.copy()
