import logging
import time
from typing import Dict, Any, Optional
import pandas as pd
from .ai_client import AIClient
from src.data_loader import load_strategy_data
from src.database import db_pool, text, get_position_by_symbol # 【修改】新增导入

logger = logging.getLogger(__name__)

class MacroAnalyzer:
    """宏观分析器 (已升级，增加了状态切换检测和清场逻辑)"""
    
    def __init__(self, api_key: str) -> None:
        self.ai_client: AIClient = AIClient(api_key)
        self.last_known_season: Optional[str] = None
        self._detailed_status: Optional[Dict[str, Any]] = None
        self._last_status_update: float = 0
    
    async def get_macro_data(self) -> Dict[str, str]:
        """获取宏观分析数据，现在会批量加载并自己计算所有策略的回测总结"""
        
        strategy_files = [
            "BTC1d.xlsx", "BTC10h.xlsx", "ETH1d多.xlsx", "ETH1d空.xlsx",
            "ETH4h.xlsx", "AVAX9h.xlsx", "SOL10h.xlsx", "ADA4h.xlsx"
        ]
        
        all_summaries = []

        for filename in strategy_files:
            strategy_df = load_strategy_data(filename)
            
            if strategy_df is not None and not strategy_df.empty:
                try:
                    net_profit = float(strategy_df.iloc[2, 1])
                    gross_profit = float(strategy_df.iloc[3, 1])
                    gross_loss = float(strategy_df.iloc[4, 1])
                    
                    summary_text = (
                        f"总净利润 ${net_profit:,.2f}, "
                        f"毛利润 ${gross_profit:,.2f}, "
                        f"毛亏损 ${gross_loss:,.2f}."
                    )
                    all_summaries.append(f"策略 {filename} 的回测表现: {summary_text}")

                except (IndexError, ValueError, TypeError) as e:
                    logger.error(f"为文件 {filename} 提取或计算统计数据时出错: {e}。请检查Excel格式。")
        
        combined_summary = "\n".join(all_summaries)

        # --- 【修改】重写实时信号获取逻辑，优先内部事实 ---
        
        # 1. 定义需要关注的核心资产
        core_assets = ['BTC', 'ETH']
        status_texts = []

        for asset in core_assets:
            asset_status = "中性" # 默认状态为中性
            
            # 2. 优先查询内部真实持仓
            # 注意：get_position_by_symbol 需要的 symbol 格式可能为 'BTC/USDT'
            # 这里我们假设它能处理 'BTC' 这样的简单格式，如果不行则需要调整
            open_position = await get_position_by_symbol(asset)
            
            if open_position:
                # 如果有持仓，内部事实就是最可靠的信号
                if open_position.trade_type == 'LONG':
                    asset_status = "看涨"
                elif open_position.trade_type == 'SHORT':
                    asset_status = "看跌"
                logger.info(f"检测到 {asset} 存在持仓，内部状态判定为: {asset_status}")
            else:
                # 3. 如果没有持仓，才去参考外部信号 (tv_status)
                try:
                    async with db_pool.get_session() as session:
                        # 我们只关心最新的、有效的外部信号
                        stmt = text("SELECT status FROM tv_status WHERE symbol = :symbol")
                        result = await session.execute(stmt, {"symbol": asset.lower()})
                        external_signal = result.scalar_one_or_none()
                        
                        if external_signal:
                            # 这里可以根据需要转换信号格式，例如 'buy' -> '看涨'
                            if external_signal.lower() in ['buy', 'long']:
                                asset_status = "看涨机会"
                            elif external_signal.lower() in ['sell', 'short']:
                                asset_status = "看跌机会"
                            else:
                                asset_status = "中性" # 外部信号也是中性
                            logger.info(f"{asset} 无持仓，参考外部信号判定为: {asset_status}")
                        else:
                            logger.info(f"{asset} 无持仓，且无有效外部信号，判定为: 中性")
                            
                except Exception as e:
                    logger.error(f"查询 {asset} 的外部TV状态失败: {e}，判定为: 中性")

            status_texts.append(f"{asset} 的当前状态是 {asset_status}")

        tv_status_summary = ". ".join(status_texts)
        # --- 【修改结束】---

        return {
            "price_trend_summary": combined_summary if combined_summary else "未能加载任何策略的历史数据。",
            "onchain_summary": "链上数据分析待实现。",
            "funding_summary": "资金费率分析待实现。",
            "current_signals": tv_status_summary
        }
    
    async def analyze_market_status(self) -> Optional[Dict[str, Any]]:
        # ... (此函数保持不变) ...
        logger.info("正在调用AI模型进行底层宏观分析...")
        macro_data = await self.get_macro_data()
        result = await self.ai_client.analyze_macro(macro_data)
        if not result or 'market_season' not in result:
            logger.error("AI宏观分析失败或返回格式无效", exc_info=True)
            return None
        return result

    async def get_macro_decision(self) -> Dict[str, Any]:
        # ... (此函数保持不变) ...
        logger.info("开始进行宏观决策...")
        ai_analysis = await self.analyze_market_status()
        if not ai_analysis:
            return {"current_season": self.last_known_season or "UNKNOWN", "liquidation_signal": None, "reason": "AI analysis failed, no action taken."}
        current_season = ai_analysis['market_season']
        liquidation_signal = None
        reason = f"AI analysis complete. Current season: {current_season}."
        if self.last_known_season and current_season != self.last_known_season:
            logger.warning(f"宏观季节发生切换！ 由 {self.last_known_season} 切换至 {current_season}")
            if current_season == "BULL":
                liquidation_signal = "LIQUIDATE_ALL_SHORTS"
                reason = f"宏观季节由 {self.last_known_season} 转为 BULL. 触发指令：清算所有空头仓位。"
            elif current_season == "BEAR":
                liquidation_signal = "LIQUIDATE_ALL_LONGS"
                reason = f"宏观季节由 {self.last_known_season} 转为 BEAR. 触发指令：清算所有多头仓位。"
        self.last_known_season = current_season
        current_timestamp = ai_analysis.get('timestamp', time.time())
        self._detailed_status = {
            'trend': '牛' if current_season == 'BULL' else '熊' if current_season == 'BEAR' else '震荡',
            'btc_trend': ai_analysis.get('btc_trend', '中性'),
            'eth_trend': ai_analysis.get('eth_trend', '中性'),
            'confidence': ai_analysis.get('confidence', 0),
            'last_update': current_timestamp
        }
        self._last_status_update = current_timestamp
        try:
            from src.database import set_setting
            await set_setting('market_season', current_season)
            logger.info(f"宏观状态 '{current_season}' 已成功持久化到数据库")
        except Exception as e:
            logger.error(f"持久化宏观状态失败: {e}", exc_info=True)
        return {"current_season": current_season, "ai_confidence": ai_analysis.get('confidence'), "liquidation_signal": liquidation_signal, "reason": reason}
    
    async def get_detailed_status(self) -> Dict[str, Any]:
        # ... (此函数保持不变) ...
        current_time = time.time()
        if (not self._detailed_status or current_time - self._last_status_update > 300):
            logger.info("更新宏观状态缓存...")
            ai_analysis = await self.analyze_market_status()
            if ai_analysis:
                self._detailed_status = {
                    'trend': '牛' if ai_analysis.get('market_season') == 'BULL' else '熊' if ai_analysis.get('market_season') == 'BEAR' else '震荡',
                    'btc_trend': ai_analysis.get('btc_trend', '中性'),
                    'eth_trend': ai_analysis.get('eth_trend', '中性'),
                    'confidence': ai_analysis.get('confidence', 0),
                    'last_update': ai_analysis.get('timestamp', current_time)
                }
                self._last_status_update = current_time
            else:
                if not self._detailed_status:
                    self._detailed_status = {
                        'trend': '未知', 
                        'btc_trend': '未知',
                        'eth_trend': '未知',
                        'confidence': 0, 
                        'last_update': current_time
                    }
        return self._detailed_status.copy()
