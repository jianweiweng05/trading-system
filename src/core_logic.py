import logging
import pandas as pd
from typing import Dict, Tuple

# 导入共享的组件
from database import db_query

logger = logging.getLogger(__name__)

# --- 第一部分：宏观层 - 战略过滤器 ---
def get_macro_state(btc_trend: str, eth_trend: str) -> Dict:
    """
    根据白皮书1.1宏观战略决策矩阵，确定宏观状态。
    输入: btc1d 和 eth1d 的趋势 ('long', 'short', 'neutral')
    """
    state_map = {
        ('long', 'long'): ("BULL_TOTAL_ATTACK", 168, 1.2),
        ('long', 'neutral'): ("BULL_BTC_LEAD", 168, 1.0),
        ('long', 'short'): ("MIXED_MARKET", 48, 0.5), # 领导层冲突
        ('neutral', 'long'): ("BULL_ETH_LEAD", 168, 0.8),
        ('short', 'short'): ("BEAR_TOTAL_DEFENSE", 72, 1.0),
        ('short', 'neutral'): ("BEAR_BTC_LEAD", 72, 0.8),
        ('short', 'long'): ("MIXED_MARKET", 48, 0.5), # 领导层冲突
        ('neutral', 'short'): ("BEAR_ETH_LEAD", 72, 0.6),
        ('neutral', 'neutral'): ("CHAOS", 24, 0.0),
    }
    
    status, window, multiplier = state_map.get((btc_trend, eth_trend), ("CHAOS", 24, 0.0))
    
    return {
        "macro_status": status,
        "observation_window": window,
        "macro_multiplier": multiplier
    }

# --- 第二部分：战术层 - 动态共振决策引擎 ---
def get_dynamic_window(macro_status: str, volatility_index: float) -> int:
    """
    根据白皮书2.1，计算动态观察窗口。
    输入: 宏观状态 和 0-1的波动率指数
    """
    base_window = 168 if "BULL" in macro_status else 72
    if "MIXED" in macro_status: base_window = 48
    if "CHAOS" in macro_status: return 24
        
    volatility_factor = 1.8 - (0.3 * volatility_index) # 原公式似乎有误，应为加成，这里按意图修正
    dynamic_window = base_window * volatility_factor
    
    # 施加绝对上下限
    return max(24, min(240, dynamic_window))

def get_resonance_decision(combo_signals: set) -> Dict:
    """
    根据白皮书2.3共振组合基础分表，返回决策指令。
    输入: 共振池中所有信号名的集合
    """
    # 识别核心信号
    has_btc = any("BTC" in s for s in combo_signals)
    has_eth = any("ETH" in s for s in combo_signals)
    has_avax = any("AVAX" in s for s in combo_signals)
    has_sol_ada = any("SOL" in s or "ADA" in s for s in combo_signals)
    is_avax_first = "AVAX9h" in combo_signals and len(combo_signals) == 1 # 简化判断
    
    # 决策矩阵
    if has_btc and has_eth:
        return {"quality_grade": "A+", "base_firepower": 0.9, "base_leverage": 3.0}
    if has_btc and (has_avax or has_sol_ada):
        return {"quality_grade": "A", "base_firepower": 0.7, "base_leverage": 2.5}
    if has_eth and has_avax:
        return {"quality_grade": "B+", "base_firepower": 0.6, "base_leverage": 2.0}
    if has_eth and has_sol_ada:
        return {"quality_grade": "B", "base_firepower": 0.5, "base_leverage": 2.0}
    if is_avax_first:
        return {"quality_grade": "C", "base_firepower": 0.15, "base_leverage": 1.0}
    
    # 所有其他情况，包括纯山寨币组合和独立信号
    return {"quality_grade": "D", "base_firepower": 0.0, "base_leverage": 0.0}

# --- 第三部分：执行层 - 四维动态仓位计算器 ---
def get_allocation_percent(macro_status: str, symbol: str) -> float:
    """
    根据白皮书3.1资本分配表，查询分配比例。
    """
    allocations = {
        "BULL": {"BTC": 0.30, "ETH": 0.25, "AVAX": 0.20, "ADA": 0.15, "SOL": 0.10},
        "BEAR": {"BTC": 0.50, "ETH": 0.35, "AVAX": 0.05, "ADA": 0.05, "SOL": 0.05}
    }
    
    market_type = "BULL" if "BULL" in macro_status else ("BEAR" if "BEAR" in macro_status else None)
    if not market_type: return 0.0
    
    coin = symbol.split('/')[0]
    return allocations.get(market_type, {}).get(coin, 0.0)

def calculate_final_firepower(base_firepower: float, macro_multiplier: float) -> float:
    """根据白皮书3.2计算最终火力系数"""
    return base_firepower * macro_multiplier

def get_volatility_multiplier(btc_atr_percent: float) -> float:
    """根据白皮书3.3.2查询波动率杠杆乘数"""
    if btc_atr_percent < 0.015: # < 1.5%
        return 1.2
    if btc_atr_percent > 0.04: # > 4.0%
        return 0.75
    return 1.0

def calculate_final_safe_leverage(base_leverage: float, macro_status: str, vol_multiplier: float) -> float:
    """
    根据白皮书3.3.3的三阶段衰减模型，计算最终安全杠杆。
    """
    # 确定宏观杠杆规则
    if "BEAR" in macro_status or "CHAOS" in macro_status:
        macro_leverage_rule = 1.0
    else:
        macro_leverage_rule = base_leverage
    
    # 乘以波动率乘数
    raw_leverage = macro_leverage_rule * vol_multiplier
    
    # 三阶段衰减
    if raw_leverage <= 2.0:
        final_leverage = raw_leverage
    elif raw_leverage <= 4.0:
        final_leverage = 2.0 + (raw_leverage - 2.0) * 0.6
    else:
        final_leverage = 2.0 + (2.0 * 0.6) + (raw_leverage - 4.0) * 0.3
        
    # 施加绝对上限
    return min(final_leverage, 3.0)

def calculate_target_position_value(
    account_equity: float, 
    allocation_percent: float, 
    final_firepower: float, 
    final_leverage: float
) -> float:
    """
    根据白皮书总公式，计算最终目标仓位名义价值。
    """
    return account_equity * allocation_percent * final_firepower * final_leverage