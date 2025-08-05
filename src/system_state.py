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
    def set_alert_callback(cls, callback: Callable[[str, str], Awaitable[None]]):
        """设置回调（仅增加类型检查）"""
        if not callable(callback):
            raise TypeError("回调必须是可调用对象")
        cls._alert_callback = callback

    @classmethod
    async def set_state(cls, new_state: str):
        """状态变更（仅增加基础校验）"""
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
        """获取当前状态（线程安全）"""
        async with cls._lock:
            return cls._state
