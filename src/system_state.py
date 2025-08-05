import asyncio
import logging
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

class SystemState:
    """系统状态管理（最小改进版）"""
    _state: str = "STARTING"
    _lock = asyncio.Lock()
    _alert_callback: Optional[Callable[[str, str], Awaitable[None]]] = None

    @classmethod
    def set_alert_callback(cls, callback: Callable[[str, str], Awaitable[None]]) -> None:
        """
        设置状态变更回调函数
        
        Args:
            callback: 回调函数，接收旧状态和新状态作为参数
            
        Raises:
            TypeError: 当回调不是可调用对象时
        """
        if not callable(callback):
            raise TypeError("回调必须是可调用对象")
        cls._alert_callback = callback

    @classmethod
    async def set_state(cls, new_state: str) -> None:
        """
        设置系统状态
        
        Args:
            new_state: 新状态，必须是以下值之一：
                      "STARTING", "ACTIVE", "PAUSED", "HALTED", "EMERGENCY"
                      
        Raises:
            ValueError: 当状态值不在允许范围内时
        """
        valid_states = {"STARTING", "ACTIVE", "PAUSED", "HALTED", "EMERGENCY"}
        if new_state not in valid_states:
            raise ValueError(f"非法状态: {new_state}")

        async with cls._lock:
            old_state = cls._state
            if old_state == new_state:
                return

            cls._state = new_state
            logger.critical(f"状态变更: {old_state} → {new_state}")

            if cls._alert_callback:
                try:
                    await cls._alert_callback(old_state, new_state)
                except Exception as e:
                    logger.error(f"回调执行失败: {e}", exc_info=True)

    @classmethod
    async def get_state(cls) -> str:
        """
        获取当前系统状态
        
        Returns:
            str: 当前系统状态值
        """
        async with cls._lock:
            return cls._state
