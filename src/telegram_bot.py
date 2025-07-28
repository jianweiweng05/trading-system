import os
import httpx
import logging

logger = logging.getLogger(__name__)

async def send_message(text: str):
    try:
        # 终极解决方案：直接从系统环境获取
        token = os.environ['TELEGRAM_BOT_TOKEN']
        chat_id = os.environ['TELEGRAM_CHAT_ID']
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        
        # 添加详细日志
        logger.info("正在发送Telegram消息...")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            })
            
            # 记录关键信息
            logger.info(f"Telegram响应: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"发送失败: {response.text}")
            
            return response.status_code == 200
            
    except KeyError:
        logger.error("环境变量未设置: TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
        return False
    except Exception as e:
        logger.error(f"严重错误: {str(e)}")
        return False
