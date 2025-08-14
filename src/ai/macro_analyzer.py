import logging
import time
from typing import Dict, Any, Optional
import pandas as pd
from .ai_client import AIClient
# 假设的数据库和数据加载器导入
# from src.database import get_setting, set_setting
# from src.data_loader import load_strategy_data

logger = logging.getLogger(__name__)

class MacroAnalyzer:
    """
    宏观分析器 (最终版 - 基于“大一统”评分公式)
    """
    
    def __init__(self, api_key: str, factor_history_path: str = "factor_history_full.csv") -> None:
        self.ai_client: AIClient = AIClient(api_key)
        self.last_known_season: Optional[str] = None
        
        try:
            self.factor_history: pd.DataFrame = pd.read_csv(factor_history_path, index_col='Date', parse_dates=True)
            logging.info(f"成功加载因子历史数据，共 {len(self.factor_history)} 条记录。")
        except FileNotFoundError:
            logging.critical(f"致命错误: 因子历史数据文件未找到 -> {factor_history_path}")
            self.factor_history = pd.DataFrame()

        # 【核心】使用我们最终优化出的、最强模型的固定权重和阈值
        self.weights = {
            "w_macro": 0.43, "w_btc1d": 0.76,
            "p_long": 0.94, "p_eth1d": 0.89
        }
        self.bull_threshold = 0.25
        self.osc_threshold = 0.10
    
    async def get_macro_data_for_ai(self) -> Dict[str, str]:
        """为AI置信度分析提供文本情报"""
        # (此方法逻辑保持不变，仅为示例)
        return {
            "price_trend_summary": "策略组历史表现稳健。",
            "onchain_summary": "待实现。",
            "funding_summary": "待实现。",
            "current_signals": "BTC和ETH日线策略目前均处于多头状态。"
        }

    async def get_macro_decision(self) -> Dict[str, Any]:
        """
        获取最终的宏观决策。这是系统现在唯一需要调用的入口。
        """
        logger.info("开始执行“大一统”宏观评分...")
        
        if self.factor_history.empty:
            return {"market_season": "OSC", "score": 0, "confidence": 0.5, "liquidation_signal": None}

        # 1. 获取最新的量化因子状态
        today_factors = self.factor_history.iloc[-1]
        
        # 2. 获取实时的AI置信度
        text_data = await self.get_macro_data_for_ai()
        ai_confidence = await self.ai_client.get_confidence_score(text_data)
        
        # 3. 执行“分层评分”公式
        long_trend = (
            today_factors.get("Macro_Factor", 0) * ai_confidence * self.weights['w_macro'] +
            today_factors.get("BTC1d_Factor", 0) * self.weights['w_btc1d']
        )
        final_score = (
            long_trend * self.weights['p_long'] +
            today_factors.get("ETH1d_Factor", 0) * self.weights['p_eth1d']
        )
        
        # 4. 根据分数和阈值，确定宏观状态
        current_season = "OSC"
        if final_score > self.bull_threshold:
            current_season = "BULL"
        elif final_score < -self.osc_threshold:
            current_season = "BEAR"
        
        # 5. 检查状态切换，生成清场信号
        liquidation_signal = None
        # (假设 self.last_known_season 由外部持久化层管理，例如数据库或文件)
        # last_season = await get_setting("market_season", "OSC") 
        if self.last_known_season and current_season != self.last_known_season:
            logger.warning(f"宏观季节发生切换！由 {self.last_known_season} 切换至 {current_season}")
            if current_season == "BULL":
                liquidation_signal = "LIQUIDATE_ALL_SHORTS"
            elif current_season == "BEAR":
                liquidation_signal = "LIQUIDATE_ALL_LONGS"
        
        self.last_known_season = current_season
        # await set_setting("market_season", current_season)
        
        logger.info(f"最终评分: {final_score:.2f}, AI置信度: {ai_confidence:.2f}, 判定状态: {current_season}")
        
        # 6. 返回最终决策包
        return {
            "market_season": current_season,
            "score": final_score,
            "confidence": ai_confidence,
            "liquidation_signal": liquidation_signal
        }
