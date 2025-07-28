import os
import httpx
import logging

logger = logging.getLogger(__name__)

async def send_message(text: str):
    try:
        # 1. 获取环境变量
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        # 2. 验证参数
        if not token or not chat_id:
            logger.error("无法发送：缺少TOKEN或CHAT_ID")
            return False
        
        # 3. 准备请求
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"  # 关键修复：添加HTML解析模式
        }
        
        # 4. 发送请求（增加超时时间）
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            
            # 5. 记录详细响应
            logger.info(f"Telegram响应: {response.status_code} {response.text}")
            
            response.raise_for_status()
            return True
            
    except httpx.HTTPStatusError as e:
        logger.error(f"Telegram API错误: {e.response.status_code} {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"发送失败: {str(e)}")
        return False
