import os
import sys
# 完全消除 pandas_ta 警告
os.environ["PYTHONWARNINGS"] = "ignore::DeprecationWarning"
sys.warnoptions = []

import logging
import pandas as pd
import numpy as np
import warnings
from typing import Dict, Tuple, Optional
from config import DEBUG_MODE, LOG_LEVEL

# 双重确保过滤 setuptools 弃用警告
warnings.filterwarnings("ignore", category=DeprecationWarning, 
                        message="pkg_resources is deprecated.*")

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL if LOG_LEVEL else logging.DEBUG if DEBUG_MODE else logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# 策略状态常量
STRATEGY_BULLISH = "bullish"
STRATEGY_BEARISH = "bearish"
STRATEGY_NEUTRAL = "neutral"

# 信号身份类型
SIGNAL_TREND_FOLLOWING = "trend_following"
SIGNAL_REVERSAL = "reversal"
SIGNAL_BREAKOUT = "breakout"

# 波动环境
VOLATILITY_HIGH = "high"
VOLATILITY_MEDIUM = "medium"
VOLATILITY_LOW = "low"

# ================= 市场分析函数 =================
async def get_market_analytics(exchange, symbol: str, timeframe: str = "1h", limit: int = 100) -> Dict:
    """
    获取市场分析数据
    :param exchange: 交易所实例
    :param symbol: 交易对
    :param timeframe: 时间框架
    :param limit: 数据点数
    :return: 市场分析数据字典
    """
    try:
        logger.info(f"开始获取市场分析数据: {symbol} {timeframe}")
        
        # 获取K线数据
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        # 转换为DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # 计算技术指标
        df = calculate_technical_indicators(df)
        
        # 分析市场状态
        current_price = df['close'].iloc[-1]
        volatility_env = assess_volatility(df)
        trend_strength = assess_trend_strength(df)
        
        # 构建返回数据
        market_data = {
            'symbol': symbol,
            'timeframe': timeframe,
            'current_price': current_price,
            'volatility_env': volatility_env,
            'trend_strength': trend_strength,
            'indicators': {
                'rsi': df['rsi'].iloc[-1],
                'macd': df['MACD'].iloc[-1],
                'macd_signal': df['MACD_signal'].iloc[-1],
                'bb_upper': df['BB_upper'].iloc[-1],
                'bb_middle': df['BB_middle'].iloc[-1],
                'bb_lower': df['BB_lower'].iloc[-1],
                'atr': df['atr'].iloc[-1],
            },
            'df': df  # 包含所有指标的完整DataFrame
        }
        
        logger.debug(f"市场分析完成: {symbol} 价格: {current_price:.2f} 波动: {volatility_env}")
        return market_data
        
    except Exception as e:
        logger.error(f"获取市场分析数据失败: {e}")
        raise

# ================= 技术指标计算 =================
def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    使用 pandas-ta 计算技术指标（已处理弃用警告）
    :param df: 包含OHLCV数据的DataFrame
    :return: 添加了技术指标的DataFrame
    """
    try:
        # 在导入前过滤警告
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            import pandas_ta as ta
            
            # 计算RSI
            df.ta.rsi(length=14, append=True)
            
            # 计算MACD
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            
            # 计算布林带
            df.ta.bbands(length=20, std=2, append=True)
            
            # 计算ATR
            df.ta.atr(length=14, append=True)
            
            # 重命名列以保持兼容
            df.rename(columns={
                'RSI_14': 'rsi',  # 修复：添加 RSI 列映射
                'MACD_12_26_9': 'MACD',  # 修复：添加 MACD 列映射
                'MACDs_12_26_9': 'MACD_signal',  # 修复：添加 MACD 信号列映射
                'MACDh_12_26_9': 'MACD_hist',  # 修复：添加 MACD 直方图映射
                'BBL_20_2.0': 'BB_lower',
                'BBM_20_2.0': 'BB_middle',
                'BBU_20_2.0': 'BB_upper',
                'ATRr_14': 'atr'
            }, inplace=True)
        
        logger.debug("技术指标计算完成")
        return df
        
    except Exception as e:
        logger.error(f"技术指标计算失败: {e}")
        return df

# ================= 波动性评估 =================
def assess_volatility(df: pd.DataFrame, lookback: int = 14) -> str:
    """
    评估市场波动性环境
    :param df: 包含技术指标的DataFrame
    :param lookback: 回溯周期
    :return: 波动性环境 (high/medium/low)
    """
    try:
        # 使用ATR作为波动性指标
        current_atr = df['atr'].iloc[-1]
        median_atr = df['atr'].rolling(lookback).median().iloc[-1]
        
        # 计算波动率分类
        if current_atr > median_atr * 1.5:
            return VOLATILITY_HIGH
        elif current_atr > median_atr * 1.2:
            return VOLATILITY_MEDIUM
        else:
            return VOLATILITY_LOW
            
    except Exception as e:
        logger.error(f"波动性评估失败: {e}")
        return VOLATILITY_MEDIUM

# ================= 趋势强度评估 =================
def assess_trend_strength(df: pd.DataFrame, lookback: int = 20) -> float:
    """
    评估当前趋势强度
    :param df: 包含技术指标的DataFrame
    :param lookback: 回溯周期
    :return: 趋势强度分数 (0.0 - 1.0)
    """
    try:
        # 在导入前过滤警告
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            import pandas_ta as ta
            
            # 1. ADX指标
            df.ta.adx(length=14, append=True)
            
            # 修复：添加 ADX 列映射
            df.rename(columns={'ADX_14': 'adx'}, inplace=True)
            adx = df['adx'].iloc[-1]
            
            # 2. 移动平均线斜率
            df['ma20'] = df['close'].rolling(20).mean()
            ma_slope = (df['ma20'].iloc[-1] - df['ma20'].iloc[-5]) / 5
            
            # 3. RSI位置
            rsi_position = (df['rsi'].iloc[-1] - 30) / 40  # 30-70范围标准化
            
            # 综合评分 (0-1)
            trend_strength = min(1.0, max(0.0, 
                (adx / 70 * 0.4) + 
                (np.tanh(ma_slope / df['close'].iloc[-1] * 100) * 0.4) + 
                (rsi_position * 0.2)
            ))
        
        logger.debug(f"趋势强度评估: ADX={adx:.1f}, MA斜率={ma_slope:.4f}, RSI位置={rsi_position:.2f}, 综合={trend_strength:.2f}")
        return trend_strength
        
    except Exception as e:
        logger.error(f"趋势强度评估失败: {e}")
        return 0.5

# ================= 策略状态判断 =================
def determine_strategy_status(btc_trend: str, eth_trend: str) -> str:
    """
    根据BTC和ETH趋势确定整体策略状态
    :param btc_trend: BTC趋势 ('up'/'down')
    :param eth_trend: ETH趋势 ('up'/'down')
    :return: 策略状态 (bullish/bearish/neutral)
    """
    try:
        # 简化逻辑：两者同向时采用该方向，否则中性
        if btc_trend == 'up' and eth_trend == 'up':
            return STRATEGY_BULLISH
        elif btc_trend == 'down' and eth_trend == 'down':
            return STRATEGY_BEARISH
        else:
            return STRATEGY_NEUTRAL
    except Exception as e:
        logger.error(f"策略状态判断失败: {e}")
        return STRATEGY_NEUTRAL

# ================= 信号身份识别 =================
async def get_signal_identity(strategy_name: str, direction: str) -> str:
    """
    根据策略名称和方向识别信号身份
    :param strategy_name: 策略名称
    :param direction: 信号方向 ('buy'/'sell')
    :return: 信号身份类型
    """
    try:
        # 策略名称映射
        strategy_types = {
            "GoldenCross": SIGNAL_TREND_FOLLOWING,
            "DeathCross": SIGNAL_TREND_FOLLOWING,
            "RSI_Reversal": SIGNAL_REVERSAL,
            "Breakout": SIGNAL_BREAKOUT
        }
        
        # 默认处理
        return strategy_types.get(strategy_name, SIGNAL_TREND_FOLLOWING)
    except Exception as e:
        logger.error(f"信号身份识别失败: {e}")
        return SIGNAL_TREND_FOLLOWING

# ================= 风险系数计算 =================
def calculate_rsc(strategy_status: str, signal_identity: str, volatility_env: str) -> float:
    """
    计算风险调整系数 (Risk Scaling Coefficient)
    :param strategy_status: 策略状态 (bullish/bearish/neutral)
    :param signal_identity: 信号身份 (trend_following/reversal/breakout)
    :param volatility_env: 波动环境 (high/medium/low)
    :return: 风险调整系数
    """
    try:
        # 基础风险系数
        rsc = 1.0
        
        # 策略状态调整
        status_factors = {
            STRATEGY_BULLISH: 1.2,
            STRATEGY_BEARISH: 0.8,
            STRATEGY_NEUTRAL: 1.0
        }
        rsc *= status_factors.get(strategy_status, 1.0)
        
        # 信号类型调整
        identity_factors = {
            SIGNAL_TREND_FOLLOWING: 1.1,
            SIGNAL_REVERSAL: 0.9,
            SIGNAL_BREAKOUT: 1.3
        }
        rsc *= identity_factors.get(signal_identity, 1.0)
        
        # 波动环境调整
        volatility_factors = {
            VOLATILITY_HIGH: 0.7,
            VOLATILITY_MEDIUM: 1.0,
            VOLATILITY_LOW: 1.3
        }
        rsc *= volatility_factors.get(volatility_env, 1.0)
        
        # 限制在合理范围
        rsc = max(0.5, min(2.0, rsc))
        
        logger.debug(f"风险系数计算: 状态={strategy_status}, 信号={signal_identity}, 波动={volatility_env}, RSC={rsc:.2f}")
        return rsc
        
    except Exception as e:
        logger.error(f"风险系数计算失败: {e}")
        return 1.0

# ================= 目标仓位计算 =================
def calculate_target_position(signal, rsc: float) -> float:
    """
    计算目标仓位
    :param signal: 交易信号
    :param rsc: 风险调整系数
    :return: 目标仓位数量
    """
    try:
        # 基础仓位量
        base_amount = signal['base_amount']  # 修复：使用字典访问
        
        # 应用风险系数
        target_amount = base_amount * rsc
        
        logger.info(f"目标仓位计算: 基础={base_amount}, RSC={rsc:.2f}, 目标={target_amount:.4f}")
        return target_amount
    except Exception as e:
        logger.error(f"目标仓位计算失败: {e}")
        return signal['base_amount']  # 修复：使用字典访问

# ================= 信号处理核心逻辑 =================
async def process_trading_signal(exchange, signal: dict, run_mode: str) -> Dict:
    """
    处理交易信号的核心逻辑
    :param exchange: 交易所实例
    :param signal: 交易信号字典
    :param run_mode: 运行模式 (live/simulate)
    :return: 处理结果字典
    """
    try:
        logger.info(f"开始处理交易信号: {signal['symbol']} {signal['direction']}")
        
        # 获取市场分析数据
        market_data = await get_market_analytics(exchange, signal['symbol'])
        
        # 确定策略状态
        strategy_status = determine_strategy_status(
            signal.get('btc_trend', 'neutral'), 
            signal.get('eth_trend', 'neutral')
        )
        
        # 识别信号身份
        signal_identity = await get_signal_identity(
            signal.get('strategy_name', 'Unknown'), 
            signal['direction']
        )
        
        # 计算风险系数
        rsc = calculate_rsc(
            strategy_status, 
            signal_identity, 
            market_data['volatility_env']
        )
        
        # 计算目标仓位
        target_amount = calculate_target_position(signal, rsc)
        
        # 返回处理结果
        result = {
            'status': 'success',
            'symbol': signal['symbol'],
            'direction': signal['direction'],
            'base_amount': signal['base_amount'],
            'target_amount': target_amount,
            'strategy_status': strategy_status,
            'signal_identity': signal_identity,
            'volatility_env': market_data['volatility_env'],
            'rsc': rsc,
            'current_price': market_data['current_price']
        }
        
        logger.info(f"信号处理完成: {signal['symbol']} 目标仓位={target_amount:.4f}")
        return result
        
    except Exception as e:
        logger.error(f"信号处理失败: {e}")
        return {
            'status': 'error',
            'message': str(e)
        }

# ================= 测试函数 =================
if __name__ == "__main__":
    # 模拟测试
    class MockExchange:
        async def fetch_ohlcv(self, symbol, timeframe, limit):
            # 生成模拟数据
            np.random.seed(42)
            prices = np.cumprod(1 + np.random.randn(100) * 0.01) * 50000
            timestamps = [i * 3600000 for i in range(100)]  # 每小时一个点
            
            # 创建包含随机波动的OHLCV数据
            ohlc_data = []
            for ts, p in zip(timestamps, prices):
                open_p = p
                high_p = p + abs(np.random.randn() * 100)
                low_p = p - abs(np.random.randn() * 100)
                close_p = p + np.random.randn() * 50
                volume = 1000 + abs(np.random.randn() * 500)
                ohlc_data.append([ts, open_p, high_p, low_p, close_p, volume])
                
            return ohlc_data
    
    async def test():
        # 创建模拟信号
        test_signal = {
            'symbol': 'BTC/USDT',
            'direction': 'buy',
            'base_amount': 0.1,
            'strategy_name': 'GoldenCross',
            'btc_trend': 'up',
            'eth_trend': 'up'
        }
        
        # 处理信号
        exchange = MockExchange()
        result = await process_trading_signal(exchange, test_signal, 'simulate')
        
        # 打印结果
        print("\n测试结果:")
        for key, value in result.items():
            print(f"{key}: {value}")
    
    import asyncio
    asyncio.run(test())
