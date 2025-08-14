import logging
import asyncio
import time
from typing import Optional, Dict, Any, List
from ccxt.async_support import binance
from sqlalchemy import select, insert, update, delete
from src.config import CONFIG
from src.alert_system import AlertSystem
from src.database import db_pool, ResonanceSignal
# --- 【新增】导入我们新的核心决策模块 ---
from src.ai.macro_analyzer import MacroAnalyzer
from src.core_logic import ( # 假设您的core_logic.py现在包含了这些
    calculate_target_position_value, 
    get_allocation_percent,
    get_dynamic_risk_coefficient
)


logger = logging.getLogger(__name__)

class TradingEngine:
    """交易引擎核心类"""
    
    ORDER_CHECK_INTERVAL = 1
    
    def __init__(self, exchange: binance, alert_system: AlertSystem):
        self.exchange = exchange
        self.alert_system = alert_system
        self.active_orders: Dict[str, Dict] = {}
        self.order_timeout = CONFIG.alert_order_timeout
        self.slippage_threshold = CONFIG.alert_slippage_threshold
        self.min_partial_fill = CONFIG.alert_min_partial_fill
        self.max_daily_loss = CONFIG.alert_max_daily_loss
        self.api_retry_count = CONFIG.alert_api_retry_count
        
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset_time = time.time()
        
        self.resonance_pool: Dict[str, Dict] = {}
        self.signal_timeout = CONFIG.macro_cache_timeout
        
        # --- 【核心修改】实例化新的宏观分析器 ---
        # 假设因子文件路径在配置中
        factor_file_path = getattr(CONFIG, 'factor_history_file', 'factor_history_full.csv')
        self.macro_analyzer = MacroAnalyzer(CONFIG.deepseek_api_key, factor_file_path)

    async def initialize(self) -> None:
        """
        异步初始化交易引擎。
        """
        logger.info("正在初始化交易引擎...")
        await self._load_resonance_pool_from_db()
        logger.info("✅ 交易引擎初始化完成")

    # --- 【核心修改】execute_order 被彻底重构，以整合新的决策逻辑 ---
    async def execute_order(self, symbol: str, side: str, 
                          # 不再需要外部传入amount, order_type, price
                          # 这些将由内部逻辑决定
                          signal_data: Dict[str, Any] 
                         ) -> Optional[Dict[str, Any]]:
        """
        执行交易决策的统一入口。
        """
        try:
            # 1. 获取最终的宏观决策
            macro_decision = await self.macro_analyzer.get_macro_decision()
            macro_status = macro_decision.get("market_season", "OSC")
            
            # 2. 方向性过滤
            market_dir = 1 if macro_status == "BULL" else -1 if macro_status == "BEAR" else 0
            signal_dir = 1 if side.lower() == 'long' else -1 if side.lower() == 'short' else 0
            
            if market_dir != signal_dir:
                logger.info(f"信号被过滤: 信号方向({side})与宏观主方向({macro_status})不符。")
                return None

            # 3. 获取所有需要的系数来计算仓位
            # (这里需要获取账户权益和当前回撤，假设有辅助函数)
            account_equity = await self.exchange.fetch_balance()['total']['USDT']
            current_drawdown = await get_current_drawdown_from_db() # 假设

            allocation_percent = get_allocation_percent(macro_status, symbol)
            dynamic_risk_coeff = get_dynamic_risk_coefficient(current_drawdown)
            
            # (简化版，暂时不考虑共振和AI置信度，因为它们已在宏观评分中)
            resonance_multiplier = 1.0
            
            # 4. 计算最终仓位价值
            # (调用我们core_logic.py中的函数)
            position_details = calculate_target_position_value(
                account_equity=account_equity,
                symbol=symbol,
                macro_decision=macro_decision,
                dynamic_risk_coeff=dynamic_risk_coeff,
                # ... 其他需要的参数 ...
            )
            
            target_value = position_details["target_position_value"]
            if target_value <= 0:
                logger.info("计算出的目标仓位为0，不执行交易。")
                return None

            # 5. 执行下单
            # (这里的逻辑与您原始的execute_order类似)
            current_price = await self.exchange.fetch_ticker(symbol)['last']
            amount = target_value / current_price
            
            order_params = {'symbol': symbol, 'type': 'market', 'side': side, 'amount': amount}
            order_result = await self._execute_with_retry(
                lambda: self.exchange.create_order(**order_params)
            )
            
            # ... (后续的订单监控逻辑) ...
            
            return order_result

        except Exception as e:
            await self.alert_system.trigger_alert(
                alert_type="ORDER_FAILED", message=f"交易执行失败: {str(e)}", level="emergency"
            )
            # 不再向上抛出异常，而是返回None，避免主循环崩溃
            return None
    
    async def _check_balance(self, symbol: str, amount: float, price: Optional[float] = None):
        """(此方法保持不变)"""
        # ...
    
    async def _execute_with_retry(self, func, max_retries: int = 3) -> Any:
        """(此方法保持不变)"""
        # ...
    
    async def _monitor_order(self, order_id: str):
        """(此方法保持不变)"""
        # ...
    
    async def cancel_order(self, order_id: str) -> bool:
        """(此方法保持不变)"""
        # ...
    
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        """(此方法保持不变)"""
        # ...
    
    def update_daily_pnl(self, pnl: float):
        """(此方法保持不变)"""
        # ...
    
    def reset_daily_stats(self):
        """(此方法保持不变)"""
        # ...
    
    async def check_exchange_health(self) -> bool:
        """(此方法保持不变)"""
        # ...
    
    def get_active_orders(self) -> Dict[str, Dict]:
        """(此方法保持不变)"""
        # ...
    
    def get_daily_stats(self) -> Dict[str, Any]:
        """(此方法保持不变)"""
        # ...
    
    async def add_signal(self, signal_id: str, signal_data: Dict[str, Any]) -> None:
        """(此方法保持不变)"""
        # ...

    async def remove_signal(self, signal_id: str) -> None:
        """(此方法保持不变)"""
        # ...

    def get_resonance_pool(self) -> Dict[str, Any]:
        """(此方法保持不变)"""
        # ...

    async def update_signal_status(self, signal_id: str, status: str) -> None:
        """(此方法保持不变)"""
        # ...

    async def _load_resonance_pool_from_db(self):
        """(此方法保持不变)"""
        # ...

    # --- 【核心修改】旧的宏观状态管理函数被彻底废弃 ---
    # async def get_macro_status(self) -> Dict[str, Any]: ...
    # def update_macro_status(self, ...) -> None: ...
    
    # (get_resonance_pool 的异步版本保持不变)
    async def get_resonance_pool(self) -> Dict[str, Any]:
        """获取共振池状态"""
        # ... (与原始代码相同) ...
        pass
