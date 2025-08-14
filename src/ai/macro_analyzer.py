import logging
import time
from typing import Dict, Any, Optional, Tuple
import pandas as pd
from .ai_client import AIClient
from src.data_loader import load_strategy_data
from src.database import db_pool, text, get_position_by_symbol, get_setting, set_setting # 假设有 get/set setting

logger = logging.getLogger(__name__)

class MacroAnalyzer:
    """
    宏观分析器 (V3.0 - 基于您设计的“优化版牛熊判断”逻辑)
    """
    
    def __init__(self, api_key: str) -> None:
        self.ai_client: AIClient = AIClient(api_key)
        self.last_known_status: int = 0 # 用于信号确认机制
        self.consecutive_days: int = 0 # 用于信号确认机制
        
        # --- 【核心修改】定义您新方案中的所有阈值和权重 ---
        self.BULL_CRITERIA = {
            'ma_slope': 2.5,
            'whale_net': 40000,
            'stablecoin_growth': 30
        }
        self.BEAR_CRITERIA = {
            'ma_slope': -1.5,
            'whale_net': -25000,
            'stablecoin_growth': -5
        }
        self.WEIGHTS = {
            'ma_slope': 0.5,
            'whale_net': 0.3,
            'stablecoin_growth': 0.2
        }
        self.CONFIRM_DAYS = 3
    
    async def get_macro_data(self) -> Dict[str, Any]:
        """
        【核心修改】此方法现在只负责获取新方案需要的三个核心指标。
        """
        # TODO: 在实盘中，这里需要接入 Glassnode, TradingView 等API来获取真实数据
        logger.info("正在收集优化版牛熊判断所需的核心指标...")
        return {
            "ma_slope": 3.2,
            "whale_net_change": 50000,
            "stablecoin_growth": 35,
        }
    
    # --- analyze_market_status 被废弃 ---

    # --- 【核心修改】get_macro_decision 被彻底重写 ---
    async def get_macro_decision(self) -> Dict[str, Any]:
        """
        获取最终的宏观决策。
        完整实现了您设计的 judge_market_status_optimized 逻辑。
        """
        logger.info("开始执行优化版牛熊判断...")
        
        # 1. 获取最新的核心指标数据
        macro_data = await self.get_macro_data()
        ma_slope = macro_data.get('ma_slope', 0)
        whale_net_change = macro_data.get('whale_net_change', 0)
        stablecoin_growth = macro_data.get('stablecoin_growth', 0)

        # 2. 计算牛熊分数
        bull_score = (
            self.WEIGHTS['ma_slope'] * (ma_slope > self.BULL_CRITERIA['ma_slope']) +
            self.WEIGHTS['whale_net'] * (whale_net_change > self.BULL_CRITERIA['whale_net']) +
            self.WEIGHTS['stablecoin_growth'] * (stablecoin_growth > self.BULL_CRITERIA['stablecoin_growth'])
        )
        bear_score = (
            self.WEIGHTS['ma_slope'] * (ma_slope < self.BEAR_CRITERIA['ma_slope']) +
            self.WEIGHTS['whale_net'] * (whale_net_change < self.BEAR_CRITERIA['whale_net']) +
            self.WEIGHTS['stablecoin_growth'] * (stablecoin_growth < self.BEAR_CRITERIA['stablecoin_growth'])
        )

        # 3. 基于分数判断原始状态
        raw_status = 0
        if bull_score >= 0.7:
            raw_status = 1
        elif bear_score >= 0.7:
            raw_status = -1

        # 4. 【核心】实现信号确认机制
        # a. 从数据库或状态文件加载上一次的状态和连续天数
        last_status_from_db = await get_setting("macro_raw_status", 0) # 假设默认0
        consecutive_days_from_db = await get_setting("macro_consecutive_days", 0)

        if raw_status == last_status_from_db:
            self.consecutive_days = consecutive_days_from_db + 1
        else:
            self.consecutive_days = 1 # 信号变化，天数重置为1
        
        # b. 更新数据库
        await set_setting("macro_raw_status", raw_status)
        await set_setting("macro_consecutive_days", self.consecutive_days)

        # c. 最终状态判断
        if self.consecutive_days < self.CONFIRM_DAYS:
            market_status = 0  # 暂时保持中性，等信号确认
        else:
            market_status = raw_status
            
        # 5. 信号强度计算
        strength = bull_score - bear_score

        # 6. 状态名转换
        status_map = {1: "BULL", 0: "OSC", -1: "BEAR"}
        market_season = status_map.get(market_status, "OSC")
        
        logger.info(f"优化版判断完成: 原始状态={raw_status}, 连续天数={self.consecutive_days}, 最终状态={market_season}, 信号强度={strength:.2f}")
        
        # 7. 返回最终决策包 (格式与其他模块兼容)
        return {
            "market_season": market_season,
            "score": strength, # 使用信号强度作为score
            "confidence": (abs(strength) + 1) / 2, # 将强度映射到0.5-1.0的置信度
            "liquidation_signal": None # 这个模型不直接产生清场信号
        }

    async def get_detailed_status(self) -> Dict[str, Any]:
        """(此方法逻辑简化，直接返回最新决策的缓存)"""
        # 在真实应用中，这个方法也应该被重构，以反映新的决策逻辑
        # 为保持最小化修改，我们暂时让它返回一个简化的状态
        decision = await self.get_macro_decision()
        trend_map = {"BULL": "牛", "BEAR": "熊", "OSC": "震荡"}
        return {
            'trend': trend_map.get(decision['market_season'], '未知'),
            'score': decision.get('score', 0),
            'confidence': decision.get('confidence', 0.5),
            'last_update': time.time()
        }
