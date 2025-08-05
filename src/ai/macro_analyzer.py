import logging
from typing import Dict, Any
from .ai_client import AIClient

logger = logging.getLogger(__name__)

class MacroAnalyzer:
    """宏观分析器"""
    
    def __init__(self, api_key: str):
        self.ai_client = AIClient(api_key)
    
    async def get_macro_data(self) -> Dict[str, str]:
        """获取宏观分析数据"""
        # 此处为简化版，实际应从多个来源抓取数据
        return {
            "price_trend_summary": "BTC和ETH的200日均线斜率均大于3度，呈稳定上涨趋势。",
            "onchain_summary": "巨鲸地址过去30天净增持超过5万枚BTC，矿工持仓稳定。",
            "funding_summary": "交易所稳定币存量年增长率超过40%，市场资金充足。"
        }
    
    async def analyze_market_status(self) -> Dict[str, Any]:
        """分析市场状态"""
        logger.info("开始宏观市场分析...")
        macro_data = await self.get_macro_data()
        result = await self.ai_client.analyze_macro(macro_data)
        
        if not result:
            logger.error("AI宏观分析失败")
            return None
            
        return result
