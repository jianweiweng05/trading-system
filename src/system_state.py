import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

class SystemState:
    """
    一个线程安全的、全局的系统状态管理器 (单例模式)。
    负责同步整个应用的状态，并在状态变更时触发回调。
    """
    _instance = None
    _state: str = "STARTING"  # 初始状态
    _lock = asyncio.Lock()
    _alert_callback: Callable[[str, str], Awaitable[None]] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SystemState, cls).__new__(cls)
        return cls._instance
    
    @classmethod
    def set_alert_callback(cls, callback: Callable[[str, str], Awaitable[None]]):
        """
        设置状态变更时的警报回调函数。
        这个函数必须是一个可等待的异步函数。
        """
        cls._alert_callback = callback
    
    @classmethod
    async def set_state(cls, new_state: str, application=None):
        """安全地更新系统状态，并在变更时触发警报。"""
        valid_states = ["STARTING", "ACTIVE", "PAUSED", "HALTED", "EMERGENCY"]
        if new_state not in valid_states:
            logger.error(f"尝试设置一个无效的系统状态: {new_state}")
            raise ValueError(f"无效状态: {new_state}")
        
        async with cls._lock:
            old_state = cls._state
            if old_state != new_state:
                cls._state = new_state
                logger.critical(f"系统状态已变更: 从 {old_state} -> {new_state}")
                
                # 如果设置了回调函数，则异步调用它
                if cls._alert_callback:
                    # 使用application参数来避免循环导入
                    asyncio.create_task(cls._alert_callback(old_state, new_state, application))
    
    @classmethod
    async def get_state(cls) -> str:
        """安全地获取当前系统状态"""
        async with cls._lock:
            return cls._state
    
    @classmethod
    async def is_active(cls) -> bool:
        """检查系统是否处于允许新开仓的活动状态"""
        async with cls._lock:
            return cls._state == "ACTIVE"