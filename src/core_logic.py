
import logging
from typing import Dict, Set, Optional, Any # 【修改】在这里补上了 Any
import re

logger = logging.getLogger(__name__)

# 模块级常量 (保持不变)
MAX_DRAWDOWN_LIMIT = 0.15
MARKET_ALLOCATIONS = {
    "BULL": {"BTC": 0.30, "ETH": 0.25, "AVAX": 0.20, "ADA": 0.15, "SOL": 0.10},
    "BEAR": {"BTC": 0.45, "ETH": 0.25, "AVAX": 0.15, "ADA": 0.10, "SOL": 0.05},
    "OSC":  {"BTC": 0.40, "ETH": 0.30, "AVAX": 0.15, "ADA": 0.10, "SOL": 0.05}
}

# --- 第一部分：宏观层 - 战略过滤器 ---
def get_macro_state(macro_status_code: int, btc_trend: str, eth_trend: str) -> Dict:
    """
    根据V3.1精简状态机逻辑，确定宏观状态。
    输入: 
        macro_status_code: 1(牛), 2(熊), 3(震荡)
        btc_trend/eth_trend: 'L'(多头), 'S'(空头), 'N'(中性)
    """
    # 输入验证 (保持不变)
    if not isinstance(macro_status_code, int) or macro_status_code not in (1, 2, 3):
        logger.error(f"Invalid macro_status_code: {macro_status_code}")
        return {"macro_status": "ERROR", "macro_multiplier": 0.0, "base_leverage": 0.0}
    
    if not isinstance(btc_trend, str) or not isinstance(eth_trend, str):
        logger.error("Trend parameters must be strings")
        return {"macro_status": "ERROR", "macro_multiplier": 0.0, "base_leverage": 0.0}
    
    if btc_trend not in ('L', 'S', 'N') or eth_trend not in ('L', 'S', 'N'):
        logger.error(f"Invalid trend values - BTC:{btc_trend}, ETH:{eth_trend}")
        return {"macro_status": "ERROR", "macro_multiplier": 0.0, "base_leverage": 0.0}

    # 核心逻辑 (保持不变)
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
        # 使用正则表达式优化解析
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

    # 计算总共振系数 (优化过滤无效信号)
    c_r_total = independent_coeffs.get(first_signal_parsed, 0.0)
    
    # 提前过滤无效信号
    valid_signals = (parse_signal_name(s) for s in combo_signals - {first_signal})
    valid_signals = (s for s in valid_signals if s is not None)
    
    for signal in valid_signals:
        c_r_total *= enhancement_coeffs.get(signal, 1.0)
            
    return {"resonance_multiplier": c_r_total}

# --- 第三部分：执行层 - 动态风险仓位计算器 ---
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

# --- 请将这个新函数，粘贴到 get_dynamic_risk_coefficient 和 calculate_target_position_value 之间 ---
def get_confidence_weight(confidence: float) -> float:
    """
    根据 AI 置信度，返回阶梯式的仓位调节系数。
    遵循风控建议，初期加仓上限设为 1.05x。
    """
    if confidence >= 0.90:
        return 1.05  # 奖励性加仓 (初期保守上限)
    elif confidence >= 0.75:
        return 1.0   # 正常仓位
    elif confidence >= 0.60:
        return 0.6   # 惩罚性减仓
    else:
        return 0.0   # 一票否决

# --- 请用这段新代码，替换你现有的 calculate_target_position_value 整个函数 ---
def calculate_target_position_value(
    account_equity: float, 
    allocation_percent: float, 
    macro_decision: Dict[str, Any],
    resonance_multiplier: float,
    dynamic_risk_coeff: float,
    confidence_weight: float, # 【修改】新增参数
    fixed_leverage: float
) -> float:
    """
    最终目标仓位计算
    """
    macro_multiplier = macro_decision.get("macro_multiplier", 0.0)
    base_leverage = macro_decision.get("base_leverage", 0.0)
    
    # 【修改】在最终公式中乘以 confidence_weight
    margin_to_use = account_equity * allocation_percent * macro_multiplier * resonance_multiplier * dynamic_risk_coeff * confidence_weight
    
    return margin_to_use * fixed_leverage

# --- 第四部分：熔断层 - 轻量版熔断控制 ---
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
