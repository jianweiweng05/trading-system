import logging
from typing import Dict, Set, Optional, Any
import re
# --- 【新增】导入我们需要的pandas和numpy库 ---
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# 模块级常量 (无变动)
MAX_DRAWDOWN_LIMIT = 0.15
MARKET_ALLOCATIONS = {
    "BULL": {"BTC": 0.30, "ETH": 0.25, "AVAX": 0.20, "ADA": 0.15, "SOL": 0.10},
    "BEAR": {"BTC": 0.45, "ETH": 0.25, "AVAX": 0.15, "ADA": 0.10, "SOL": 0.05},
    "OSC":  {"BTC": 0.40, "ETH": 0.30, "AVAX": 0.15, "ADA": 0.10, "SOL": 0.05}
}

# --- 【核心修改】第一部分：旧的宏观层被废弃 ---
# def get_macro_state(...):
#     """此函数不再使用"""
#     pass

# --- 【核心新增】全新的、统一的决策引擎 ---

# 我们将最终确认的权重和阈值，作为常量定义在这里
BEST_WEIGHTS = {
    "w_macro": 0.43, "w_btc1d": 0.76,
    "p_long": 0.94, "p_eth1d": 0.89
}
BEST_BULL_THRESHOLD = 0.25
BEST_OSC_THRESHOLD = 0.10
LEVERAGE_MAP = {"BULL": 3.0, "OSC": 1.0, "BEAR": 2.0}

def get_unified_decision(
    factor_data: pd.Series, # 一个包含当天所有因子值的Pandas Series
    eth_daily_returns: pd.Series # ETH的日收益率序列，用于模拟AI置信度
) -> Dict[str, Any]:
    """
    这是新的核心决策函数。
    它接收所有量化因子，并计算出最终的宏观决策。
    """
    # 1. 模拟AI置信度
    ai_confidence = 1 - (eth_daily_returns.rolling(20).std() / eth_daily_returns.rolling(20).std().max())
    ai_confidence = ai_confidence.fillna(0.5).iloc[-1] # 取最新一天的值

    # 2. 计算“长周期趋势”分
    long_trend = (
        factor_data.get("Macro_Factor", 0) * ai_confidence * BEST_WEIGHTS['w_macro'] +
        factor_data.get("BTC1d_Factor", 0) * BEST_WEIGHTS['w_btc1d']
    )
    
    # 3. 计算“最终信号”分
    final_score = (
        long_trend * BEST_WEIGHTS['p_long'] +
        factor_data.get("ETH1d_Factor", 0) * BEST_WEIGHTS['p_eth1d']
    )
    
    # 4. 根据分数和阈值，确定宏观状态
    state = "OSC"
    if final_score > BEST_BULL_THRESHOLD:
        state = "BULL"
    elif final_score < -BEST_OSC_THRESHOLD:
        state = "BEAR"
    
    # 5. 获取对应的杠杆
    leverage = LEVERAGE_MAP.get(state, 1.0)
    
    logger.info(f"最终评分: {final_score:.2f}, 判定状态: {state}, 基础杠杆: {leverage:.1f}x")

    # 6. 返回最终的、可供下游使用的决策包
    return {
        "macro_status": state,
        "base_leverage": leverage,
        "score": final_score,
        "confidence": ai_confidence
    }


# --- 第二部分：战术层 (无变动) ---
def parse_signal_name(signal: str) -> Optional[str]:
    """(此方法保持不变)"""
    try:
        match = re.match(r'^([A-Z]{3,4})\d+h/([A-Z]{3,4})USDT$', signal)
        if not match: raise ValueError
        return f"{match.group(1)}{match.group(2)}"
    except Exception as e:
        logger.warning(f"Failed to parse signal {signal}: {str(e)}")
        return None

def get_resonance_decision(first_signal: str, combo_signals: Set[str]) -> Dict[str, Any]:
    """(此方法保持不变，但在新框架下其作用被弱化)"""
    first_signal_parsed = parse_signal_name(first_signal)
    if not first_signal_parsed:
        return {"weight": 0.0, "direction": "NEUTRAL"}
    independent_coeffs = {
        "BTC10h": 1.0, "ETH4h": 0.9, "AVAX9h": 0.8, 
        "ADA4h": 0.4, "SOL10h": 0.3
    }
    enhancement_coeffs = {
        "BTC10h": 1.5, "ETH4h": 1.3, "AVAX9h": 1.1,
        "SOL10h": 1.0, "ADA4h": 1.0
    }
    c_r_total = independent_coeffs.get(first_signal_parsed, 0.0)
    valid_signals = (parse_signal_name(s) for s in combo_signals - {first_signal})
    valid_signals = (s for s in valid_signals if s is not None)
    for signal in valid_signals:
        c_r_total *= enhancement_coeffs.get(signal, 1.0)
    direction = "LONG" if "多" in first_signal else "SHORT" if "空" in first_signal else "NEUTRAL"
    return {"weight": c_r_total, "direction": direction}

# --- 第三部分：执行层 (有修改) ---
def _extract_market_type(macro_status: str) -> Optional[str]:
    """(此方法保持不变)"""
    return next(
        (m for m in ["BULL", "BEAR", "OSC"] if m in macro_status),
        None
    )

def get_allocation_percent(macro_status: str, symbol: str) -> float:
    """(此方法保持不变)"""
    market_type = _extract_market_type(macro_status)
    if not market_type: 
        return 0.0
    coin = symbol.split('/')[0] if '/' in symbol else symbol
    return MARKET_ALLOCATIONS.get(market_type, {}).get(coin, 0.0)

def get_dynamic_risk_coefficient(current_drawdown: float) -> float:
    """(此方法保持不变)"""
    return max(0.1, 1 - current_drawdown / MAX_DRAWDOWN_LIMIT)

# get_confidence_weight 不再需要，因为置信度已融入主公式

# --- 【核心修改】calculate_target_position_value 被重构 ---
def calculate_target_position_value(
    account_equity: float, 
    symbol: str,
    macro_decision: Dict[str, Any], # 接收来自新 get_unified_decision 的决策包
    dynamic_risk_coeff: float
) -> Dict[str, float]:
    """
    最终目标仓位计算 (已适配新宏观系统)
    """
    # 1. 从宏观决策中提取核心参数
    macro_status = macro_decision.get("macro_status", "OSC")
    base_leverage = macro_decision.get("base_leverage", 0.0)
    
    # 2. 获取该资产的资金分配比例
    allocation_percent = get_allocation_percent(macro_status, symbol)
    
    # 3. 计算最终仓位系数 (简化版，暂时不考虑小时级共振)
    #    在新的“大一统”模型下，所有择时能力都已包含在score里
    #    所以基础的乘数就是1.0
    final_position_coefficient = (
        allocation_percent * 
        1.0 * # 基础乘数
        dynamic_risk_coeff
    )
    
    # 4. 计算保证金和最终仓位价值
    margin_to_use = account_equity * final_position_coefficient
    target_value = margin_to_use * base_leverage

    return {
        "target_position_value": target_value,
        "final_position_coefficient": final_position_coefficient
    }

# --- 第四部分：熔断层 (无变动) ---
def check_circuit_breaker(price_fall_4h: float, fear_greed_index: int) -> Optional[Dict]:
    """(此方法保持不变)"""
    if not isinstance(price_fall_4h, (int, float)) or not isinstance(fear_greed_index, int):
        logger.error("Invalid circuit breaker inputs")
        return None
    if price_fall_4h > 0.15:
        return {"action": "LIQUIDATE_ALL", "pause_hours": 24, "reason": f"High Priority: Price Fall > 15% ({price_fall_4h:.2%})"}
    if fear_greed_index < 10:
        return {"action": "REDUCE_RISK", "risk_coeff_override": 0.1, "reason": f"Medium Priority: Fear & Greed Index < 10 ({fear_greed_index})"}
    return None
