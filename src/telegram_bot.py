import os
import httpx

async def send_message(text: str):
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        api_url = os.getenv("TELEGRAM_API_URL", "https://api.telegram.org")
        
        if not token or not chat_id:
            print("错误：缺少TELEGRAM_BOT_TOKEN或TELEGRAM_CHAT_ID")
            return False
        
        url = f"{api_url}/bot{token}/sendMessage"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json={
                "chat_id": chat_id,
                "text": text
            })
            response.raise_for_status()
        return True
    except Exception as e:
        print(f"Telegram发送失败: {str(e)}")
        return False
