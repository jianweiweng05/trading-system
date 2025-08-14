import logging
from typing import Dict, Any, Optional
import httpx
import json
import time

logger = logging.getLogger(__name__)

class AIClient:
    """AI客户端，只负责获取AI置信度"""
    
    def __init__(self, api_key: str) -> None:
        self.api_key: str = api_key
        self.base_url: str = "https://api.deepseek.com/v1"
    
    async def get_confidence_score(self, data: Dict[str, str]) -> float:
        """
        分析宏观文本情报，并返回一个0-1之间的置信度分数。
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
                
                # 确保置信度在0-1之间
                return min(max(confidence, 0.0), 1.0)

        except Exception as e:
            logger.error(f"AI置信度分析失败: {e}", exc_info=True)
            return 0.5 # 在失败时，返回一个保守的中性置信度
