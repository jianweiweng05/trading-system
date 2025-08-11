import logging
from typing import Dict, Any, Optional
import httpx
import json
import time

logger = logging.getLogger(__name__)

class AIClient:
    """AI客户端，用于调用DeepSeek API"""
    
    def __init__(self, api_key: str) -> None:
        self.api_key: str = api_key
        self.base_url: str = "https://api.deepseek.com/v1"
    
    async def analyze_macro(self, data: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """分析宏观数据"""
        # --- 【修改】修正了 prompt 中的中文逗号为英文逗号 ---
        prompt = f"""
你是一位顶级的、遵循严格指令的宏观经济学家AI，为一家大型对冲基金提供每日的加密市场牛熊状态判断。

**任务:**
分析以下多维度情报，并严格按照你的"三维度牛熊判定框架"，输出最终的判断。

**情报输入:**
- **历史回测总结:** {data.get('price_trend_summary', '无')}
- **链上根基情报:** {data.get('onchain_summary', '未知')}
- **资金燃料情报:** {data.get('funding_summary', '未知')}
- **当前实时信号:** {data.get('current_signals', '无')}

**分析与决策流程:**
# --- 【最小化修改处】---
# 将打分范围从 0-1.5 调整为 0-1.0，从根源上解决 confidence > 1 的问题。
1.  **逐一评估三大维度** (价格趋势, 链上根基, 资金燃料) 并给出0-1.0之间的分数。
2.  **计算综合指数** (`综合指数 = (价格分 * 40%) + (链上分 * 30%) + (资金分 * 30%)`)。
3.  **最终状态判定** (牛市 ≥ 0.75, 熊市 ≤ 0.35, 否则为中性)。

**输出格式要求:**
你的回答必须是一个格式良好、可以被直接解析的JSON对象。
绝对不要返回任何解释性文字、注释、代码块标记(```json ... ```)或除了这个JSON对象之外的任何其他内容。
你的回答必须以 `{{` 开始，以 `}}` 结束。

**JSON对象结构:**
{{
    "market_season": "BULL",
    "confidence": 0.95,
    "reasoning": "综合指数强劲，主要由资金流入和链上巨鲸增持驱动。",
    "status_changed": true,
    "btc_trend": "bullish",
    "eth_trend": "neutral"
}}
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
                
                logger.info(f"AI 原始返回内容: {content}")
                
                parsed_result = json.loads(content)
                
                return {
                    "market_season": parsed_result.get("market_season", "NEUTRAL"),
                    "confidence": parsed_result.get("confidence", 0),
                    "reason": parsed_result.get("reasoning", "无"),
                    "status_changed": parsed_result.get("status_changed", False),
                    "btc_trend": parsed_result.get("btc_trend", "neutral"),
                    "eth_trend": parsed_result.get("eth_trend", "neutral"),
                    "timestamp": time.time()
                }
        except httpx.ReadTimeout:
            logger.error("AI 分析失败: 请求 DeepSeek API 超时。")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"AI 分析失败: 无法解析返回的JSON。错误: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"AI分析失败: {e}", exc_info=True)
            return None
