import os
from config import TELEGRAM_TOKEN, ADMIN_CHAT_ID

print("="*50)
print("环境配置验证")
print("="*50)
print(f"Telegram Token: {'已设置' if TELEGRAM_TOKEN else '未设置'}")
print(f"Admin Chat ID: {'已设置' if ADMIN_CHAT_ID else '未设置'}")
print("="*50)
