"""
Trading Block Manager
Manages trading block status and auto-reset at market open (from config.json)
"""

from datetime import datetime, time as dt_time
from typing import Optional
from src.utils.logger import get_logger
from src.database.repository import DailyStatsRepository

logger = get_logger("risk")


class TradingBlockManager:
    """Manages trading block status"""
    
    def __init__(self, daily_stats_repo: DailyStatsRepository):
        self.daily_stats_repo = daily_stats_repo
        self.trading_blocked = False
        # Get market open time from config
        from src.utils.date_utils import get_market_hours
        market_open, _ = get_market_hours()
        self.block_reset_time = market_open
    
    def check_and_reset_block(self):
        """Check if it's time to reset trading block (market open from config)"""
        from src.utils.date_utils import get_current_ist_time, is_market_open
        
        ist_time = get_current_ist_time()
        current_time = ist_time.time()
        
        # Reset block at market open (from config)
        if current_time >= self.block_reset_time and is_market_open():
            if self.trading_blocked:
                self.reset_block()
    
    def set_block(self, reason: str = "Loss limit reached"):
        """Set trading block"""
        self.trading_blocked = True
        logger.warning(f"Trading blocked: {reason}")
        
        # Update database
        self.daily_stats_repo.update_daily_stats(trading_blocked=True)
    
    def reset_block(self):
        """Reset trading block"""
        if self.trading_blocked:
            self.trading_blocked = False
            market_open_str = self.block_reset_time.strftime("%H:%M")
            logger.info(f"Trading block reset at {market_open_str} (market open)")
            
            # Update database
            self.daily_stats_repo.update_daily_stats(
                daily_loss_used=0.0,  # Reset for new day
                loss_limit_hit=False,
                trading_blocked=False
            )
    
    def is_blocked(self) -> bool:
        """Check if trading is blocked"""
        self.check_and_reset_block()
        return self.trading_blocked

