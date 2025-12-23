"""
Date and Time Utility Functions
"""

from datetime import datetime, time, date
from pytz import timezone
from typing import Tuple

IST = timezone('Asia/Kolkata')


def get_market_hours() -> Tuple[time, time]:
    """
    Get market open and close times from config.json
    
    Returns:
        Tuple of (market_open_time, market_close_time)
        Defaults to 9:30 AM and 3:30 PM if not configured
    """
    try:
        from src.config.config_manager import ConfigManager
        import json
        config_manager = ConfigManager()
        config_path = config_manager.config_dir / "config.json"
        if config_path.exists():
            with open(config_path, 'r') as f:
                config_data = json.load(f)
                market_hours = config_data.get("market_hours", {})
                open_time_str = market_hours.get("open_time", "09:30")
                close_time_str = market_hours.get("close_time", "15:30")
                
                # Parse time string (format: "HH:MM")
                open_hour, open_minute = map(int, open_time_str.split(":"))
                close_hour, close_minute = map(int, close_time_str.split(":"))
                
                return time(open_hour, open_minute), time(close_hour, close_minute)
    except Exception as e:
        from src.utils.logger import get_logger
        logger = get_logger("date_utils")
        logger.warning(f"Could not load market hours from config: {e}, using defaults (9:30 AM - 3:30 PM)")
    
    # Default values
    return time(9, 30), time(15, 30)


def get_current_ist_time() -> datetime:
    """Get current time in IST"""
    return datetime.now(IST)


def is_market_open() -> bool:
    """Check if market is currently open (uses config.json for market hours)"""
    ist_time = get_current_ist_time()
    current_time = ist_time.time()
    market_open, market_close = get_market_hours()
    
    # Check if it's a weekday (Monday=0, Sunday=6)
    if ist_time.weekday() >= 5:  # Saturday or Sunday
        return False
    
    return market_open <= current_time <= market_close


def get_next_trading_day() -> date:
    """Get next trading day date"""
    ist_time = get_current_ist_time()
    next_day = ist_time.date()
    
    # Skip weekends
    while next_day.weekday() >= 5:
        from datetime import timedelta
        next_day += timedelta(days=1)
    
    return next_day


def get_trading_day_start_time(target_date: date) -> datetime:
    """Get trading day start time (from config.json) for a given date"""
    market_open, _ = get_market_hours()
    return datetime.combine(target_date, market_open).replace(tzinfo=IST)

