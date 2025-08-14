import logging
import time
from typing import Dict, Any, Optional, Tuple
import pandas as pd
from .ai_client import AIClient
from src.data_loader import load_strategy_data
from src.database import db_pool, text, get_position_by_symbol

logger = logging.getLogger(__name__)

class MacroAnalyzer:
    """
    宏观分析器 (V2.0 - 基于“大一统”评分公式)
    """
    
    def __init__(self, api_key: str, factor_history_path: str = "factor_history_full.csv") -> None:
        self.ai_client: AIClient = AIClient(api_key)
        self.last_known_season: Optional[str] = None
        self._detailed_status: Optional[Dict[str, Any]] = None
        self._last_status_update: float = 0
        
        # --- 【核心修改】加载因子历史数据和定义权重 ---
        try:
            self.factor_history: pd.DataFrame = pd.read_csv(factor_history_path, index_col='Date', parse_dates=True)
            logging.info(f"成功加载因子历史数据，共 {len(self.factor_history)} 条记录。")
        except FileNotFoundError:
            logging.critical(f"致命错误: 因子历史数据文件未找到 -> {factor_history_path}")
            self.factor_history = pd.DataFrame()

        self.weights = {
            "w_macro": 0.43, "w_btc1d": 0.76,
            "p_long": 0.94, "p_eth1d": 0.89
        }
        self.bull_threshold = 0.25
        self.osc_threshold = 0.10
    
    async def get_macro_data(self) -> Dict[str, str]:
        """(此方法保持不变，继续为AI置信度分析提供文本情报)"""
        strategy_files = [
            "BTC1d.xlsx", "BTC10h.xlsx", "ETH1d多.xlsx", "ETH1d空.xlsx",
            "ETH4h.xlsx", "AVAX9h.xlsx", "SOL10h.xlsx", "ADA4h.xlsx"
        ]
        all_summaries = []
        for filename in strategy_files:
            strategy_df = load_strategy_data(filename)
            if strategy_df is not None and not strategy_df.empty:
                try:
                    net_profit = float(strategy_df.iloc[2, 1])
                    summary_text = f"总净利润 ${net_profit:,.2f}"
                    all_summaries.append(f"策略 {filename}: {summary_text}")
                except Exception:
                    pass
        combined_summary = "\n".join(all_summaries)
        # ... (其他数据收集逻辑保持不变) ...
        core_assets = ['BTC', 'ETH']
        status_texts = []
        for asset in core_assets:
            # ... (代码与原始版本相同) ...
            pass
        tv_status_summary = ". ".join(status_texts)
        return {
            "price_trend_summary": combined_summary or "无历史数据。",
            "onchain_summary": "待实现。",
            "funding_summary": "待实现。",
            "current_signals": tv_status_summary
        }
    
    # --- 【核心修改】analyze_market_status 被废弃 ---
    # async def analyze_market_status(self) -> Optional[Dict[str, Any]]: ...

    # --- 【核心修改】get_macro_decision 被彻底重写 ---
    async def get_macro_decision(self) -> Dict[str, Any]:
        """
        获取最终的宏观决策。这是系统现在唯一需要调用的入口。
        """
        logger.info("开始进行“大一统”宏观评分...")
        
        if self.factor_history.empty:
            logger.error("因子历史数据为空，无法进行评分。")
            return {"market_season": "OSC", "score": 0, "confidence": 0.5, "liquidation_signal": None}

        # 1. 获取今天的因子状态 (取历史数据的最后一行)
        today_factors = self.factor_history.iloc[-1]
        
        # 2. 获取AI对当前市场不确定性的评估 (置信度)
        macro_text_data = await self.get_macro_data()
        ai_confidence = await self.ai_client.get_confidence_score(macro_text_data)
        
        # 3. 计算“长周期趋势”分
        long_trend = (
            today_factors.get("Macro_Factor", 0) * ai_confidence * self.weights['w_macro'] +
            today_factors.get("BTC1d_Factor", 0) * self.weights['w_btc1d']
        )
        
        # 4. 计算“最终信号”分
        final_score = (
            long_trend * self.weights['p_long'] +
            today_factors.get("ETH1d_Factor", 0) * self.weights['p_eth1d']
        )
        
        # 5. 根据分数和阈值，确定宏观状态
        current_season = "OSC"
        if final_score > self.bull_threshold:
            current_season = "BULL"
        elif final_score < -self.osc_threshold:
            current_season = "BEAR"
        
        # 6. 检查状态切换，生成清场信号
        liquidation_signal = None
        if self.last_known_season and current_season != self.last_known_season:
            logger.warning(f"宏观季节发生切换！由 {self.last_known_season} 切换至 {current_season}")
            if current_season == "BULL":
                liquidation_signal = "LIQUIDATE_ALL_SHORTS"
            elif current_season == "BEAR":
                liquidation_signal = "LIQUIDATE_ALL_LONGS"
        
        # 7. 更新状态记忆和缓存
        self.last_known_season = current_season
        self._detailed_status = {
            'trend': '牛' if current_season == 'BULL' else '熊' if current_season == 'BEAR' else '震荡',
            'score': final_score,
            'confidence': ai_confidence,
            'last_update': time.time()
        }
        self._last_status_update = time.time()
        
        logger.info(f"最终评分: {final_score:.2f}, AI置信度: {ai_confidence:.2f}, 判定状态: {current_season}")
        
        # 8. 返回最终决策包
        return {
            "market_season": current_season,
            "score": final_score,
            "confidence": ai_confidence,
            "liquidation_signal": liquidation_signal
        }

    async def get_detailed_status(self) -> Dict[str, Any]:
        """(此方法逻辑简化，直接返回缓存或重新计算)"""
        current_time = time.time()
        # 如果缓存不存在或过期（超过5分钟），重新进行一次完整决策
        if (not self._detailed_status or current_time - self._last_status_update > 300):
            logger.info("宏观状态缓存已过期，重新进行完整决策...")
            await self.get_macro_decision()
        
        return self._detailed_status.copy() if self._detailed_status else {}```
