import hmac
import hashlib
import json
import httpx
import asyncio
import os
from dotenv import load_dotenv

# --- 配置区 ---
# 加载您项目根目录下的 .env 文件
load_dotenv()

# 您的Render服务器的URL
# 请务必将其替换成您真实的URL
BASE_URL = "https://your-system-name.onrender.com" 

# 从环境变量中读取您的真实密钥
# 请确保您的.env文件中有 TV_WEBHOOK_SECRET 这个变量
WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET")

# --- 测试用的JSON消息 (无密码) ---
TRADE_SIGNAL_PAYLOAD = {
  "strategy_id": "TEST_BTC10h",
  "symbol": "BTC/USDT",
  "action": "long"
}

FACTOR_UPDATE_PAYLOAD = {
  "signal_type": "FACTOR_UPDATE",
  "factor_name": "TEST_BTC1d_Factor",
  "status": "long"
}

def generate_signature(secret: str, payload: bytes) -> str:
    """生成HMAC-SHA256签名"""
    return hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()

async def send_test_request(url: str, payload: dict):
    """发送一个带签名的测试请求"""
    if not WEBHOOK_SECRET:
        print("错误: 未在.env文件中找到 TV_WEBHOOK_SECRET。请先设置。")
        return

    print(f"\n--- 准备发送测试请求至: {url} ---")
    
    # 1. 将JSON数据转换为bytes
    payload_bytes = json.dumps(payload).encode('utf-8')
    
    # 2. 生成签名
    signature = generate_signature(WEBHOOK_SECRET, payload_bytes)
    print(f"生成的签名 (X-Tv-Signature): {signature}")
    
    # 3. 构建请求头
    headers = {
        'Content-Type': 'application/json',
        'X-Tv-Signature': signature
    }
    
    # 4. 发送请求
    try:
        async with httpx.AsyncClient() as client:
            print("正在发送请求...")
            response = await client.post(url, content=payload_bytes, headers=headers, timeout=30.0)
            
            print(f"服务器响应状态码: {response.status_code}")
            print(f"服务器响应内容: {response.text}")
            
            if response.is_success:
                print("✅ 测试成功！服务器已正确接收并处理了信号。")
            else:
                print("❌ 测试失败！请检查服务器日志以获取详细错误信息。")

    except httpx.ConnectError as e:
        print(f"❌ 连接错误: 无法连接到服务器 {BASE_URL}。请确认您的服务正在运行且URL正确。")
    except Exception as e:
        print(f"❌ 发生未知错误: {e}")

async def main():
    # --- 在这里选择您想测试的信号 ---
    
    # 测试“行动信号”
    await send_test_request(f"{BASE_URL}/webhook/trade_signal", TRADE_SIGNAL_PAYLOAD)
    
    # 测试“状态信号”
    # await send_test_request(f"{BASE_URL}/webhook/factor_update", FACTOR_UPDATE_PAYLOAD)

if __name__ == "__main__":
    asyncio.run(main())
