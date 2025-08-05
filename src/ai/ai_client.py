import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)

class AIClient:
    """AI客户端，用于调用DeepSeek API"""
    
    def __init__(self, api_key: str) -> None:
        self.api_key: str = api_key
        self.base_url: str = "https://api.deepseek.com/v1"
    
    async def analyze_macro(self, data: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """分析宏观数据"""
        prompt = f"""
你是一位顶级的宏观经济学家，为一家大型对冲基金提供每日的加密市场牛熊状态判断。

请分析以下多维度情报，并严格按照你的"三维度牛熊判定框架"，输出最终的判断。

---
**情报输入**
---
- **价格趋势情报:** {data['price_trend_summary']}
- **链上根基情报:** {data['onchain_summary']}
- **资金燃料情报:** {data['funding_summary']}

---
**你的分析与决策流程**
---
1.  **逐一评估三大维度**并给出0-1.5之间的分数。
2.  **计算综合指数** (`综合指数 = (价格分 * 40%) + (链上分 * 30%) + (资金分 * 30%)`)。
3.  **最终状态判定** (牛市 ≥ 0.75, 熊市 ≤ 0.35)。

---
**输出格式**
---
你必须只返回一个JSON对象，包含以下字段：
- "bull_bear_status": string ("牛市", "熊市", "中性")
- "composite_index": float
- "reasoning": string (一句话总结核心依据)
- "status_changed": boolean (假设前一天是"中性", 请判断是否发生改变)
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
                        "temperature": 0.7
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"AI分析失败: {e}", exc_info=True)
            return None
