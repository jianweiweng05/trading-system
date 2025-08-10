
import logging
import time # 【修改】添加缺失的导入
from typing import Dict, Any, Optional
from .ai_client import AIClient

logger = logging.getLogger(__name__)

class MacroAnalyzer:
    """宏观分析器 (已升级，增加了状态切换检测和清场逻辑)"""
    
    def __init__(self, api_key: str) -> None:
        self.ai_client: AIClient = AIClient(api_key)
        self.last_known_season: Optional[str] = None
        self._detailed_status: Optional[Dict[str, Any]] = None
        self._last_status_update: float = 0
    
    async def get_macro_data(self) -> Dict[str, str]:
        """获取宏观分析数据 (无变动)"""
        return {
            "price_trend_summary": "BTC和ETH的200日均线斜率均大于3度，呈稳定上涨趋势。",
            "onchain_summary": "巨鲸地址过去30天净增持超过5万枚BTC，矿工持仓稳定。",
            "funding_summary": "交易所稳定币存量年增长率超过40%，市场资金充足。"
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

    # --- 【修改】get_macro_decision 函数被完整替换为逻辑正确的版本 ---
    async def get_macro_decision(self) -> Dict[str, Any]:
        """
        获取最终的宏观决策，包含状态切换时的清场指令。
        这是您系统现在应该调用的主要入口。
        """
        logger.info("开始进行宏观决策...")
        
        # 1. 获取AI对当前市场的分析
        ai_analysis = await self.analyze_market_status()
        
        if not ai_analysis:
            # 如果AI分析失败，返回一个安全的"无操作"指令
            return {
                "current_season": self.last_known_season or "UNKNOWN",
                "liquidation_signal": None,
                "reason": "AI analysis failed, no action taken."
            }

        # 2. 定义变量
        current_season = ai_analysis['market_season']
        liquidation_signal = None
        reason = f"AI analysis complete. Current season: {current_season}."

        # 3. 核心逻辑：检查宏观季节是否发生变化
        if self.last_known_season and current_season != self.last_known_season:
            logger.warning(
                f"宏观季节发生切换！"
                f"由 {self.last_known_season} 切换至 {current_season}"
            )
            
            if current_season == "BULL":
                liquidation_signal = "LIQUIDATE_ALL_SHORTS"
                reason = (
                    f"宏观季节由 {self.last_known_season} 转为 BULL. "
                    f"触发指令：清算所有空头仓位。"
                )
            
            elif current_season == "BEAR":
                liquidation_signal = "LIQUIDATE_ALL_LONGS"
                reason = (
                    f"宏观季节由 {self.last_known_season} 转为 BEAR. "
                    f"触发指令：清算所有多头仓位。"
                )
   
        # 4. 更新"状态记忆"
        self.last_known_season = current_season
        
        # 5. 更新详细状态缓存
        self._detailed_status = {
            'trend': '牛' if current_season == 'BULL' else '熊' if current_season == 'BEAR' else '震荡',
            'btc1d': ai_analysis.get('btc_trend', '中性'),
            'eth1d': ai_analysis.get('eth_trend', '中性'),
            'confidence': ai_analysis.get('confidence', 0),
            'last_update': ai_analysis.get('timestamp')
        }
        self._last_status_update = ai_analysis.get('timestamp', 0)
        
        # 6. 【修改】将最新的宏观季节持久化到数据库
        try:
            from src.database import set_setting
            await set_setting('market_season', current_season)
            logger.info(f"宏观状态 '{current_season}' 已成功持久化到数据库")
        except Exception as e:
            logger.error(f"持久化宏观状态失败: {e}", exc_info=True)
            # 即使持久化失败，程序也应该继续运行，不应中断
        
        # 7. 返回最终决策包
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
