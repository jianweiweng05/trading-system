import logging
from typing import Dict, Set, Optional, Any
import re

logger = logging.getLogger(__name__)

# 模块级常量 (无变动)
MAX_DRAWDOWN_LIMIT = 0.15
MARKET_ALLOCATIONS = {
    "BULL": {"BTC": 0.30, "ETH": 0.25, "AVAX": 0.20, "ADA": 0.15, "SOL": 0.10},
    "BEAR": {"BTC": 0.45, "ETH": 0.25, "AVAX": 0.15, "ADA": 0.10, "SOL": 0.05},
    "OSC":  {"BTC": 0.40, "ETH": 0.30, "AVAX": 0.15, "ADA": 0.10, "SOL": 0.05}
}

# --- 第一部分：宏观层 - 战略过滤器 (无变动) ---
def get_macro_state(macro_status_code: int, btc_trend: str, eth_trend: str) -> Dict:
    """
    根据V3.1精简状态机逻辑，确定宏观状态。
    输入: 
        macro_status_code: 1(牛), 2(熊), 3(震荡)
        btc_trend/eth_trend: 'L'(多头), 'S'(空头), 'N'(中性)
    """
    if not isinstance(macro_status_code, int) or macro_status_code not in (1, 2, 3):
        logger.error(f"Invalid macro_status_code: {macro_status_code}")
        return {"macro_status": "ERROR", "macro_multiplier": 0.0, "base_leverage": 0.0}
    
    if not isinstance(btc_trend, str) or not isinstance(eth_trend, str):
        logger.error("Trend parameters must be strings")
        return {"macro_status": "ERROR", "macro_multiplier": 0.0, "base_leverage": 0.0}
    
    if btc_trend not in ('L', 'S', 'N') or eth_trend not in ('L', 'S', 'N'):
        logger.error(f"Invalid trend values - BTC:{btc_trend}, ETH:{eth_trend}")
        return {"macro_status": "ERROR", "macro_multiplier": 0.0, "base_leverage": 0.0}

    if macro_status_code == 1 and btc_trend == 'L':
        status, c_m, l_base = "BULL_ACTIVE", 1.5, 3.0
    elif macro_status_code == 2 and btc_trend == 'S' and eth_trend == 'S':
        status, c_m, l_base = "BEAR_ACTIVE", 1.1, 2.0
    elif macro_status_code == 3 and btc_trend == 'N' and eth_trend == 'N':
        status, c_m, l_base = "OSC_NEUTRAL", 0.3, 1.0
    else:
        status, c_m, l_base = "FILTERED", 0.0, 0.0

    return {
        "macro_status": status,
        "macro_multiplier": c_m,
        "base_leverage": l_base
    }

# --- 第二部分：战术层 - 静态共振决策引擎 (无变动) ---
def parse_signal_name(signal: str) -> Optional[str]:
    """安全解析信号名称"""
    try:
        match = re.match(r'^([A-Z]{3,4})\d+h/([A-Z]{3,4})USDT$', signal)
        if not match:
            raise ValueError
        return f"{match.group(1)}{match.group(2)}"
    except Exception as e:
        logger.warning(f"Failed to parse signal {signal}: {str(e)}")
        return None

def get_resonance_decision(first_signal: str, combo_signals: Set[str]) -> Dict:
    """
    根据V3.3风险分层共振逻辑，返回决策指令。
    输入: 第一个触发信号的名称, 共振池中所有信号名的集合
    """
    first_signal_parsed = parse_signal_name(first_signal)
    if not first_signal_parsed:
        return {"resonance_multiplier": 0.0}

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
            
    return {"resonance_multiplier": c_r_total}

# --- 第三部分：执行层 - 动态风险仓位计算器 (有修改) ---
def _extract_market_type(macro_status: str) -> Optional[str]:
    """从宏观状态字符串中提取市场类型"""
    return next(
        (m for m in ["BULL", "BEAR", "OSC"] if m in macro_status),
        None
    )

def get_allocation_percent(macro_status: str, symbol: str) -> float:
    """
    根据宏观状态查询资本分配比例
    
    Args:
        macro_status: 宏观状态字符串
        symbol: 交易对符号，如'BTC/USDT'
        
    Returns:
        float: 分配比例，范围0.0-1.0
    """
    market_type = _extract_market_type(macro_status)
    if not market_type: 
        return 0.0
    
    coin = symbol.split('/')[0] if '/' in symbol else symbol
    return MARKET_ALLOCATIONS.get(market_type, {}).get(coin, 0.0)

def get_dynamic_risk_coefficient(current_drawdown: float) -> float:
    """
    动态风险系数计算
    
    Args:
        current_drawdown: 当前回撤率
        
    Returns:
        float: 动态风险系数，范围0.1-1.0
    """
    return max(0.1, 1 - current_drawdown / MAX_DRAWDOWN_LIMIT)

# --- 【修改】get_confidence_weight 函数 ---
def get_confidence_weight(confidence: float) -> float:
    """
    根据 AI 置信度，返回阶梯式的仓位调节系数。
    遵循更严格的风险管理原则，将奖励性加仓上限设为 1.0x。
    """
    # 【修改】增加输入验证，确保置信度在0-1之间
    if not 0.0 <= confidence <= 1.0:
        logger.warning(f"接收到无效的置信度值: {confidence}。将使用默认权重 1.0。")
        # 在接收到无效值时，返回一个安全的中性值，而不是基于错误数据计算
        return 1.0

    if confidence >= 0.90:
        return 1.0   # 【修改】奖励性加仓上限改为 1.0
    elif confidence >= 0.75:
        return 1.0   # 正常仓位
    elif confidence >= 0.60:
        return 0.6   # 惩罚性减仓
    else:
        return 0.0   # 一票否决

# --- 【修改】calculate_target_position_value 整个函数 ---
def calculate_target_position_value(
    account_equity: float, 
    allocation_percent: float, 
    macro_decision: Dict[str, Any],
    resonance_multiplier: float,
    dynamic_risk_coeff: float,
    confidence_weight: float
) -> float:
    """
    最终目标仓位计算 (修正版，逻辑更清晰安全)
    """
    # 1. 从唯一的、正确的指令来源中，提取所有需要的宏观参数
    macro_multiplier = macro_decision.get("macro_multiplier", 0.0)
    base_leverage = macro_decision.get("base_leverage", 0.0)
    
    # 2. 计算保证金 (所有动态系数相乘)
    margin_to_use = (
        account_equity * 
        allocation_percent * 
        macro_multiplier * 
        resonance_multiplier * 
        dynamic_risk_coeff * 
        confidence_weight
    )
    
    # 3. 乘以从指令中获取的、正确的杠杆
    return margin_to_use * base_leverage

# --- 第四部分：熔断层 - 轻量版熔断控制 (无变动) ---
def check_circuit_breaker(price_fall_4h: float, fear_greed_index: int) -> Optional[Dict]:
    """
    熔断检查
    
    Args:
        price_fall_4h: 4小时价格跌幅
        fear_greed_index: 恐惧贪婪指数
        
    Returns:
        Optional[Dict]: 熔断指令字典，如果不需要熔断则返回None
    """
    if not isinstance(price_fall_4h, (int, float)) or not isinstance(fear_greed_index, int):
        logger.error("Invalid circuit breaker inputs")
        return None

    if price_fall_4h > 0.15:
        return {
            "action": "LIQUIDATE_ALL", 
            "pause_hours": 24,
            "reason": f"High Priority: Price Fall > 15% ({price_fall_4h:.2%})"
        }
        
    if fear_greed_index < 10:
        return {
            "action": "REDUCE_RISK", 
            "risk_coeff_override": 0.1,
            "reason": f"Medium Priority: Fear & Greed Index < 10 ({fear_greed_index})"
        }
        
    return None
