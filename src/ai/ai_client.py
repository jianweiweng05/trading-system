import logging
from typing import Dict, Any, Optional
import httpx
import json
import time
# --- 【新增】导入我们需要的pandas库来进行数据操作 ---
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class AIClient:
    """
    AI客户端 (已重构为“宏观评分引擎”)
    """
    
    def __init__(self, api_key: str) -> None:
        self.api_key: str = api_key
        self.base_url: str = "https://api.deepseek.com/v1"
        # --- 【新增】定义最终的、固定的权重和阈值 ---
        self.weights = {
            "w_macro": 0.43, "w_btc1d": 0.76,
            "p_long": 0.94, "p_eth1d": 0.89
        }
        self.bull_threshold = 0.25
        self.osc_threshold = 0.10

    async def get_confidence_score(self, data: Dict[str, str]) -> float:
        """
        此方法只负责调用AI，获取市场不确定性的评估（置信度）。
        """
        prompt = f"""
你是一位专业的市场风险分析师。请分析以下宏观情报，并给出一个范围在0.0到1.0之间的“市场确定性指数”（即置信度），其中1.0代表市场趋势极其明确、风险极低，0.0代表市场极度混乱、风险极高。

**情报输入:**
- **历史回测总结:** {data.get('price_trend_summary', '无')}
- **链上根基情报:** {data.get('onchain_summary', '未知')}
- **资金燃料情报:** {data.get('funding_summary', '未知')}
- **当前实时信号:** {data.get('current_signals', '无')}

**输出格式要求:**
你的回答必须是一个只包含一个"confidence"字段的JSON对象。
例如: {{"confidence": 0.85}}
你的回答必须以 `{{` 开始，以 `}}` 结束。
"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                
                logger.info(f"AI 原始置信度返回内容: {content}")
                
                parsed_result = json.loads(content)
                confidence = float(parsed_result.get("confidence", 0.5))
                
                return min(max(confidence, 0.0), 1.0)

        except Exception as e:
            logger.error(f"AI置信度分析失败: {e}", exc_info=True)
            return 0.5

    # --- 【核心修改】analyze_macro 被彻底重写 ---
    async def analyze_macro(self, factor_data: pd.Series, ai_confidence: float) -> Dict[str, Any]:
        """
        这是新的核心决策函数。
        它接收所有量化因子和AI置信度，并计算出最终的宏观决策。
        
        Args:
            factor_data: 一个包含当天所有因子值的Pandas Series。
                         例如: {'Macro_Factor': 1, 'BTC1d_Factor': 1, 'ETH1d_Factor': 0}
            ai_confidence: 一个0-1之间的浮点数，代表AI的置信度。
                         
        Returns:
            一个包含最终决策的字典。
        """
        logger.info("开始执行“大一统”宏观评分...")
        
        # 1. 计算“长周期趋势”分
        long_trend = (
            factor_data.get("Macro_Factor", 0) * ai_confidence * self.weights['w_macro'] +
            factor_data.get("BTC1d_Factor", 0) * self.weights['w_btc1d']
        )
        
        # 2. 计算“最终信号”分
        final_score = (
            long_trend * self.weights['p_long'] +
            factor_data.get("ETH1d_Factor", 0) * self.weights['p_eth1d']
        )
        
        # 3. 根据分数和阈值，确定宏观状态
        state = "OSC"
        if final_score > self.bull_threshold:
            state = "BULL"
        elif final_score < -self.osc_threshold: # 注意这里是负的震荡阈值
            state = "BEAR"
            
        logger.info(f"最终评分: {final_score:.2f}, 判定状态: {state}")

        # 4. 返回最终的、可供下游使用的决策包
        return {
            "market_season": state,
            "score": final_score,
            "confidence": ai_confidence, # 将AI置信度也一并返回，供监控
            "timestamp": time.time()
        }
