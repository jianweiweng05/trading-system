
import logging
import time
from typing import Dict, Any, Optional
from .ai_client import AIClient
# --- 【修改】导入我们新的“图书管理员” ---
from src.data_loader import load_strategy_data

logger = logging.getLogger(__name__)

class MacroAnalyzer:
    """宏观分析器 (已升级，增加了状态切换检测和清场逻辑)"""
    
    def __init__(self, api_key: str) -> None:
        self.ai_client: AIClient = AIClient(api_key)
        self.last_known_season: Optional[str] = None
        self._detailed_status: Optional[Dict[str, Any]] = None
        self._last_status_update: float = 0
    
    # --- 【修改】get_macro_data 函数现在会加载真实的历史数据 ---
    async def get_macro_data(self) -> Dict[str, str]:
        """获取宏观分析数据，现在会结合历史回测数据"""
        
        # 1. 加载历史数据
        # 假设你的核心 Excel 文件名为 'strategy_summary.xlsx'
        # 你可以根据你的实际文件名进行修改
        strategy_df = load_strategy_data("strategy_summary.xlsx")
        
        # 2. 从历史数据中提取关键信息
        price_trend_summary = "历史数据未加载。"
        onchain_summary = "链上数据分析待实现。"
        funding_summary = "资金费率分析待实现。"

        if strategy_df is not None and not strategy_df.empty:
            # 假设 Excel 中有 'summary' 列包含了分析摘要
            # 这是一个示例，你需要根据你 Excel 的实际结构来提取
            if 'price_trend_summary' in strategy_df.columns:
                price_trend_summary = strategy_df['price_trend_summary'].iloc[0]
            
            if 'onchain_summary' in strategy_df.columns:
                onchain_summary = strategy_df['onchain_summary'].iloc[0]

            if 'funding_summary' in strategy_df.columns:
                funding_summary = strategy_df['funding_summary'].iloc[0]
        
        # 3. 返回结合了历史数据的分析材料
        return {
            "price_trend_summary": price_trend_summary,
            "onchain_summary": onchain_summary,
            "funding_summary": funding_summary
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
