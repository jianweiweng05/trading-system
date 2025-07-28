import os
import httpx
import logging

logger = logging.getLogger(__name__)

async def send_message(text: str):
    try:
        # 获取环境变量
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        # 记录获取到的值（不记录敏感信息）
        logger.info(f"Telegram配置: token={'已设置' if token else '未设置'}, chat_id={'已设置' if chat_id else '未设置'}")
        
        if not token or not chat_id:
            logger.error("无法发送消息: TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未设置")
            return False
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        logger.info(f"准备发送消息到: {url.split('/bot')[0]}...")  # 不暴露完整token
        
        # 发送请求
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json={
                "chat_id": chat_id,
                "text": text
            })
            response.raise_for_status()
            
        logger.info("Telegram消息发送成功")
        return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Telegram API错误: HTTP {e.response.status_code}")
        return False
    except Exception as e:
        logger.error(f"Telegram发送失败: {str(e)}")
        return False
