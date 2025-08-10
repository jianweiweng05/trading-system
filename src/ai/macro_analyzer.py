
import logging
import time
from typing import Dict, Any, Optional
import pandas as pd # 【修改】导入 pandas 用于数据分析
from .ai_client import AIClient
from src.data_loader import load_strategy_data
from src.database import db_pool, text

logger = logging.getLogger(__name__)

class MacroAnalyzer:
    """宏观分析器 (已升级，增加了状态切换检测和清场逻辑)"""
    
    def __init__(self, api_key: str) -> None:
        self.ai_client: AIClient = AIClient(api_key)
        self.last_known_season: Optional[str] = None
        self._detailed_status: Optional[Dict[str, Any]] = None
        self._last_status_update: float = 0
    
    # --- 【修改】get_macro_data 函数现在会自己计算回测总结 ---
    async def get_macro_data(self) -> Dict[str, str]:
        """获取宏观分析数据，现在会批量加载并自己计算所有策略的回测总结"""
        
        strategy_files = [
            "BTC1d.xlsx", "BTC10h.xlsx", "ETH1d多.xlsx", "ETH1d空.xlsx",
            "ETH4h.xlsx", "AVAX9h.xlsx", "SOL10h.xlsx", "ADA4h.xlsx"
        ]
        
        all_summaries = []

        for filename in strategy_files:
            strategy_df = load_strategy_data(filename)
            
            if strategy_df is not None and not strategy_df.empty:
                # --- 新增的 Pandas 数据分析逻辑 ---
                try:
                    # 假设你的 Excel/CSV 有一个名为 '净利润' 的列
                    # 你需要根据你的实际列名进行修改
                    PROFIT_COLUMN = '净利润'
                    
                    if PROFIT_COLUMN not in strategy_df.columns:
                        logger.warning(f"在文件 {filename} 中找不到 '{PROFIT_COLUMN}' 列，无法计算统计数据。")
                        continue

                    # 计算核心指标
                    total_profit = strategy_df[PROFIT_COLUMN].sum()
                    total_trades = len(strategy_df)
                    winning_trades = strategy_df[strategy_df[PROFIT_COLUMN] > 0]
                    losing_trades = strategy_df[strategy_df[PROFIT_COLUMN] < 0]
                    
                    win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
                    
                    avg_win = winning_trades[PROFIT_COLUMN].mean() if not winning_trades.empty else 0
                    avg_loss = abs(losing_trades[PROFIT_COLUMN].mean()) if not losing_trades.empty else 0
                    
                    profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')

                    # 生成总结文本
                    summary_text = (
                        f"总净利润 ${total_profit:,.2f}, "
                        f"胜率 {win_rate:.2f}%, "
                        f"盈亏比 {profit_factor:.2f}, "
                        f"总交易次数 {total_trades}."
                    )
                    all_summaries.append(f"策略 {filename} 的回测表现: {summary_text}")

                except Exception as e:
                    logger.error(f"为文件 {filename} 计算统计数据时出错: {e}")
        
        combined_summary = "\n".join(all_summaries)

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

        return {
            "price_trend_summary": combined_summary if combined_summary else "未能加载任何策略的历史数据。",
            "onchain_summary": "链上数据分析待实现。",
            "funding_summary": "资金费率分析待实现。",
            "current_signals": tv_status_summary
        }
    
    async def analyze_market_status(self) -> Optional[Dict[str, Any]]:
        # ... (此函数保持不变) ...
        logger.info("正在调用AI模型进行底层宏观分析...")
        macro_data = await self.get_macro_data()
        result = await self.ai_client.analyze_macro(macro_data)
        if not result or 'market_season' not in result:
            logger.error("AI宏观分析失败或返回格式无效", exc_info=True)
            return None
        return result

    async def get_macro_decision(self) -> Dict[str, Any]:
        # ... (此函数保持不变) ...
        logger.info("开始进行宏观决策...")
        ai_analysis = await self.analyze_market_status()
        if not ai_analysis:
            return {"current_season": self.last_known_season or "UNKNOWN", "liquidation_signal": None, "reason": "AI analysis failed, no action taken."}
        current_season = ai_analysis['market_season']
        liquidation_signal = None
        reason = f"AI analysis complete. Current season: {current_season}."
        if self.last_known_season and current_season != self.last_known_season:
            logger.warning(f"宏观季节发生切换！ 由 {self.last_known_season} 切换至 {current_season}")
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
        return {"current_season": current_season, "ai_confidence": ai_analysis.get('confidence'), "liquidation_signal": liquidation_signal, "reason": reason}
    
    async def get_detailed_status(self) -> Dict[str, Any]:
        # ... (此函数保持不变) ...
        current_time = time.time()
        if (not self._detailed_status or current_time - self._last_status_update > 300):
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
                    self._detailed_status = {'trend': '未知', 'btc1d': '未知', 'eth1d': '未知', 'confidence': 0, 'last_update': current_time}
        return self._detailed_status.copy()
