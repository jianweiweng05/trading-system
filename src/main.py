import os
import time
from fastapi import FastAPI

# 添加启动日志
print(">>> 应用启动中...")

# 确保应用快速响应健康检查
app = FastAPI()

@app.on_event("startup")
async def startup_event():
    # 将初始化操作放入后台线程
    import threading
    threading.Thread(target=initialize_system, daemon=True).start()

def initialize_system():
    # 您的初始化代码放在这里
    print(">>> 后台初始化开始...")
    time.sleep(5)  # 模拟初始化延迟
    print(">>> 后台初始化完成")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# 您的其他路由...
import os
# 必须在所有导入之前设置环境变量
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["PYDANTIC_DISABLE_WARNINGS"] = "1"
import os
# 必须在所有导入之前设置环境变量
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["PYDANTIC_DISABLE_WARNINGS"] = "1"
