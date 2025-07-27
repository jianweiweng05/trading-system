import pandas as pd
import numpy as np
import pandas_ta as ta  # 修正后的导入语句
import logging
from datetime import datetime, timedelta
import ccxt

logger = logging.getLogger(__name__)

# ================= 技术分析函数 =================

def calculate_technical_indicators(df):
    """
    计算技术指标
    """
    try:
        # 计算相对强弱指数 (RSI)
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # 计算移动平均收敛发散 (MACD)
        macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        
        # 计算布林带 (Bollinger Bands)
        bollinger = ta.bbands(df['close'], length=20)
        df = pd.concat([df, bollinger], axis=1)
        
        # 计算平均真实波幅 (ATR)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        logger.debug("技术指标计算完成")
        return df
        
    except Exception as e:
        logger.error(f"技术指标计算失败: {e}")
        return df

# ================= 市场分析 =================

async def get_market_analytics(exchange, symbol, timeframe='1h', lookback=200):
    """
    获取市场分析数据
    """
    try:
        logger.info(f"获取市场分析: {symbol} {timeframe}")
        
        # 获取K线数据
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=lookback)
        
        # 转换为DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # 计算技术指标
        df = calculate_technical_indicators(df)
        
        # 计算波动率环境
        volatility_env = "high" if df['atr'].iloc[-1] > df['atr'].mean() else "low"
        
        # 计算趋势强度
        trend_strength = "strong" if abs(df['MACDh_12_26_9'].iloc[-1]) > 0.5 else "weak"
        
        return {
            'symbol': symbol,
            'indicators': {
                'rsi': round(df['rsi'].iloc[-1], 2),
                'macd': round(df['MACD_12_26_9'].iloc[-1], 4),
                'macd_signal': round(df['MACDs_12_26_9'].iloc[-1], 4),
                'macd_hist': round(df['MACDh_12_26_9'].iloc[-1], 4),
                'bb_upper': round(df['BBU_20_2.0'].iloc[-1], 2),
                'bb_middle': round(df['BBM_20_2.0'].iloc[-1], 2),
                'bb_lower': round(df['BBL_20_2.0'].iloc[-1], 2),
                'atr': round(df['atr'].iloc[-1], 2)
            },
            'volatility_env': volatility_env,
            'trend_strength': trend_strength,
            'last_price': round(df['close'].iloc[-1], 2)
        }
        
    except Exception as e:
        logger.error(f"市场分析失败: {e}")
        return {'error': str(e)}

# ================= 策略状态判断 =================

def determine_strategy_status(btc_trend, eth_trend):
    """
    根据BTC和ETH趋势确定整体策略状态
    """
    try:
        # 如果两者都是上升趋势
        if btc_trend == 'up' and eth_trend == 'up':
            return 'bullish'
        
        # 如果两者都是下降趋势
        elif btc_trend == 'down' and eth_trend == 'down':
            return 'bearish'
        
        # 如果趋势不一致
        else:
            return 'neutral'
            
    except Exception as e:
        logger.error(f"策略状态判断失败: {e}")
        return 'neutral'

# ================= 信号身份识别 =================

async def get_signal_identity(strategy_name, direction):
    """
    识别信号身份（趋势跟随或反转）
    """
    try:
        # 趋势跟随策略
        trend_following_strategies = ['GoldenCross', 'EMA_Crossover', 'TrendFollowing']
        
        # 反转策略
        reversal_strategies = ['RSI_Overbought', 'Stochastic_Reversal', 'MeanReversion']
        
        if strategy_name in trend_following_strategies:
            return 'trend_following'
        elif strategy_name in reversal_strategies:
            return 'reversal'
        else:
            # 默认根据方向判断
            return 'trend_following' if direction == 'long' else 'reversal'
            
    except Exception as e:
        logger.error(f"信号身份识别失败: {e}")
        return 'trend_following'

# ================= 风险调整系数 =================

def calculate_rsc(strategy_status, signal_identity, volatility_env):
    """
    计算风险规模系数 (Risk Scale Coefficient)
    """
    try:
        # 基础系数
        base_rsc = 1.0
        
        # 根据策略状态调整
        if strategy_status == 'bullish':
            base_rsc *= 1.2
        elif strategy_status == 'bearish':
            base_rsc *= 0.8
            
        # 根据信号类型调整
        if signal_identity == 'trend_following':
            base_rsc *= 1.1
        elif signal_identity == 'reversal':
            base_rsc *= 0.9
            
        # 根据波动环境调整
        if volatility_env == 'high':
            base_rsc *= 0.7
        elif volatility_env == 'low':
            base_rsc *= 1.3
            
        # 确保在合理范围内
        rsc = max(0.3, min(base_rsc, 1.8))
        
        logger.info(f"RSC计算: 策略状态={strategy_status}, 信号类型={signal_identity}, "
                   f"波动环境={volatility_env}, 最终RSC={rsc:.2f}")
        
        return rsc
        
    except Exception as e:
        logger.error(f"RSC计算失败: {e}")
        return 1.0  # 默认值