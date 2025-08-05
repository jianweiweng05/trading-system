import logging
from typing import Dict, Set, Optional

logger = logging.getLogger(__name__)

# --- 第一部分：宏观层 - 战略过滤器 ---
def get_macro_state(macro_status_code: int, btc_trend: str, eth_trend: str) -> Dict:
    """
    根据V3.1精简状态机逻辑，确定宏观状态。
    输入: 
        macro_status_code: 1(牛), 2(熊), 3(震荡)
        btc_trend/eth_trend: 'L'(多头), 'S'(空头), 'N'(中性)
    """
    # 输入验证
    if not isinstance(macro_status_code, int) or macro_status_code not in (1, 2, 3):
        logger.error(f"Invalid macro_status_code: {macro_status_code}")
        return {"macro_status": "ERROR", "macro_multiplier": 0.0, "base_leverage": 0.0}
    
    if btc_trend not in ('L', 'S', 'N') or eth_trend not in ('L', 'S', 'N'):
        logger.error(f"Invalid trend values - BTC:{btc_trend}, ETH:{eth_trend}")
        return {"macro_status": "ERROR", "macro_multiplier": 0.0, "base_leverage": 0.0}

    # 核心逻辑保持不变
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

# --- 第二部分：战术层 - 静态共振决策引擎 ---
def parse_signal_name(signal: str) -> Optional[str]:
    """安全解析信号名称"""
    try:
        parts = signal.split('/')
        if len(parts) != 2:
            raise ValueError
        return f"{parts[0]}{parts[1].replace('USDT', '')}"
    except Exception as e:
        logger.warning(f"Failed to parse signal {signal}: {str(e)}")
        return None

def get_resonance_decision(first_signal: str, combo_signals: Set[str]) -> Dict:
    """
    根据V3.3风险分层共振逻辑，返回决策指令。
    输入: 第一个触发信号的名称, 共振池中所有信号名的集合
    """
    # 安全解析信号名
    first_signal_parsed = parse_signal_name(first_signal)
    if not first_signal_parsed:
        return {"resonance_multiplier": 0.0}

    # 独立进场系数表 (保持不变)
    independent_coeffs = {
        "BTC10h": 1.0, "ETH4h": 0.9, "AVAX9h": 0.8, 
        "ADA4h": 0.4, "SOL10h": 0.3
    }
    
    # 共振增强系数表 (保持不变)
    enhancement_coeffs = {
        "BTC10h": 1.5, "ETH4h": 1.3, "AVAX9h": 1.1,
        "SOL10h": 1.0, "ADA4h": 1.0
    }

    # 计算总共振系数 (核心逻辑不变)
    c_r_total = independent_coeffs.get(first_signal_parsed, 0.0)
    
    for signal in (combo_signals - {first_signal}):
        parsed = parse_signal_name(signal)
        if parsed:
            c_r_total *= enhancement_coeffs.get(parsed, 1.0)
            
    return {"resonance_multiplier": c_r_total}

# --- 第三部分：执行层 - 动态风险仓位计算器 ---
def get_allocation_percent(macro_status: str, symbol: str) -> float:
    """
    根据宏观状态查询资本分配比例 (核心逻辑不变)
    """
    allocations = {
        "BULL": {"BTC": 0.30, "ETH": 0.25, "AVAX": 0.20, "ADA": 0.15, "SOL": 0.10},
        "BEAR": {"BTC": 0.45, "ETH": 0.25, "AVAX": 0.15, "ADA": 0.10, "SOL": 0.05},
        "OSC":  {"BTC": 0.40, "ETH": 0.30, "AVAX": 0.15, "ADA": 0.10, "SOL": 0.05}
    }
    
    market_type = next(
        (m for m in ["BULL", "BEAR", "OSC"] if m in macro_status),
        None
    )
    if not market_type: 
        return 0.0
    
    coin = symbol.split('/')[0] if '/' in symbol else symbol
    return allocations.get(market_type, {}).get(coin, 0.0)

def get_dynamic_risk_coefficient(current_drawdown: float, max_drawdown_limit: float = 0.15) -> float:
    """
    动态风险系数计算 (核心逻辑不变)
    """
    return max(0.1, 1 - current_drawdown / max_drawdown_limit)

def calculate_target_position_value(
    account_equity: float, 
    allocation_percent: float, 
    macro_multiplier: float,
    resonance_multiplier: float,
    dynamic_risk_coeff: float,
    fixed_leverage: float
) -> float:
    """
    最终目标仓位计算 (核心公式不变)
    """
    margin_to_use = account_equity * allocation_percent * macro_multiplier * resonance_multiplier * dynamic_risk_coeff
    return margin_to_use * fixed_leverage

# --- 第四部分：熔断层 - 轻量版熔断控制 ---
def check_circuit_breaker(price_fall_4h: float, fear_greed_index: int) -> Optional[Dict]:
    """
    熔断检查 (修正恐惧贪婪指数逻辑)
    """
    if not isinstance(price_fall_4h, (int, float)) or not isinstance(fear_greed_index, int):
        logger.error("Invalid circuit breaker inputs")
        return None

    # 高优先级熔断 (保持不变)
    if price_fall_4h > 0.15:
        return {
            "action": "LIQUIDATE_ALL", 
            "pause_hours": 24,
            "reason": f"High Priority: Price Fall > 15% ({price_fall_4h:.2%})"
        }
        
    # 中优先级熔断 (修正阈值)
    if fear_greed_index < 10:  # 原>90改为<10 (极度恐慌)
        return {
            "action": "REDUCE_RISK", 
            "risk_coeff_override": 0.1,
            "reason": f"Medium Priority: Fear & Greed Index < 10 ({fear_greed_index})"
        }
        
    return None
