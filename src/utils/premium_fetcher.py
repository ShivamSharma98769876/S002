"""
Utility module for fetching option premiums from Kite API
Uses the same format and logic as get_premium_by_symbol.py
"""

from typing import Optional, Tuple, Dict, List
from datetime import datetime, timedelta, date
import calendar
import pandas as pd
from src.utils.logger import get_logger

logger = get_logger("premium_fetcher")


def get_exchange_for_segment(segment: str) -> str:
    """
    Get the correct exchange for a given segment.
    
    Args:
        segment: Trading segment (NIFTY, BANKNIFTY, SENSEX)
        
    Returns:
        Exchange code: "BFO" for SENSEX, "NFO" for others
    """
    segment_upper = segment.upper()
    if segment_upper == "SENSEX":
        return "BFO"
    return "NFO"


def is_last_day_of_month(expiry_date: datetime, day_of_week: int) -> bool:
    """
    Check if the expiry date is the last occurrence of a specific day of week in the month
    
    Args:
        expiry_date: Expiry date as datetime
        day_of_week: Day of week (0=Monday, 1=Tuesday, ..., 6=Sunday)
        
    Returns:
        True if it's the last occurrence of that day in the month, False otherwise
    """
    # Get the last day of the month
    last_day = calendar.monthrange(expiry_date.year, expiry_date.month)[1]
    last_date = datetime(expiry_date.year, expiry_date.month, last_day)
    
    # Find the last occurrence of the specified day of week
    while last_date.weekday() != day_of_week:
        last_date -= timedelta(days=1)
    
    return expiry_date.date() == last_date.date()


def is_last_thursday_of_month(expiry_date: datetime) -> bool:
    """
    Check if the expiry date is the last Thursday of the month
    
    Args:
        expiry_date: Expiry date as datetime
        
    Returns:
        True if it's the last Thursday of the month, False otherwise
    """
    return is_last_day_of_month(expiry_date, 3)  # 3 = Thursday


def is_last_tuesday_of_month(expiry_date: datetime) -> bool:
    """
    Check if the expiry date is the last Tuesday of the month
    
    Args:
        expiry_date: Expiry date as datetime
        
    Returns:
        True if it's the last Tuesday of the month, False otherwise
    """
    return is_last_day_of_month(expiry_date, 1)  # 1 = Tuesday


def is_weekly_expiry(segment: str, expiry_date: datetime, expiry_config: Optional[Dict] = None) -> bool:
    """
    Determine if an expiry is weekly or monthly based on segment, date, and config
    
    Rules:
    - BANKNIFTY: Always monthly (last Thursday of month) - format: BANKNIFTY25DEC59800PE
    - NIFTY: Weekly (Tuesday) and monthly - format: NIFTY25DEC26200CE (monthly) or NIFTY25D0226200CE (weekly)
    - SENSEX: Weekly (Thursday) and monthly - format: SENSEX25DEC85700PE (monthly) or SENSEX25D0485700PE (weekly)
    
    Args:
        segment: Trading segment (NIFTY, BANKNIFTY, SENSEX)
        expiry_date: Expiry date as datetime
        expiry_config: Optional expiry configuration dict from config.json
        
    Returns:
        True if weekly format, False if monthly format
    """
    segment_upper = segment.upper()
    
    # Default config if not provided
    if expiry_config is None:
        expiry_config = {
            "BANKNIFTY": {"duration": "Monthly", "day_of_week": "Thursday"},
            "NIFTY": {"duration": "Weekly", "day_of_week": "Tuesday"},
            "SENSEX": {"duration": "Weekly", "day_of_week": "Thursday"}
        }
    
    # Get segment config (default to NIFTY config if segment not found)
    seg_config = expiry_config.get(segment_upper, expiry_config.get("NIFTY", {"duration": "Weekly", "day_of_week": "Tuesday"}))
    duration = seg_config.get("duration", "Weekly")
    day_of_week_str = seg_config.get("day_of_week", "Thursday")
    
    # Map day name to weekday number
    day_map = {
        "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
        "Friday": 4, "Saturday": 5, "Sunday": 6
    }
    day_of_week = day_map.get(day_of_week_str, 3)  # Default to Thursday
    
    if segment_upper == "BANKNIFTY":
        # BANKNIFTY: Always monthly (last Thursday)
        return False
    elif segment_upper == "NIFTY":
        # NIFTY: Weekly (Tuesday) if not last Tuesday, monthly if last Tuesday
        is_last_day = is_last_day_of_month(expiry_date, day_of_week)
        return not is_last_day
    elif segment_upper == "SENSEX":
        # SENSEX: Weekly (Thursday) if not last Thursday, monthly if last Thursday
        is_last_day = is_last_day_of_month(expiry_date, day_of_week)
        return not is_last_day
    else:
        # Default: check if last occurrence of configured day
        is_last_day = is_last_day_of_month(expiry_date, day_of_week)
        if duration == "Monthly":
            return False
        else:
            return not is_last_day


def get_expiry_date(
    current_time: datetime,
    duration: str,
    day_of_week: str,
) -> Optional[datetime]:
    """
    Calculate the contract expiry date from config rules.

    This function is used by live and paper trading and **must always**
    respect the `expiry_config` from `config.json` via the parameters
    `duration` and `day_of_week`.

    Args:
        current_time: Current timestamp (usually candle/decision time)
        duration: "Weekly" or "Monthly"
        day_of_week: Day name, e.g. "Tuesday", "Thursday"

    Returns:
        Expiry date as a `datetime` (date component is used by callers),
        or None if it cannot be determined.
    """
    try:
        if current_time is None:
            return None

        # Normalise inputs
        duration = (duration or "Weekly").capitalize()
        day_of_week = (day_of_week or "Thursday").capitalize()

        day_map = {
            "Monday": 0,
            "Tuesday": 1,
            "Wednesday": 2,
            "Thursday": 3,
            "Friday": 4,
            "Saturday": 5,
            "Sunday": 6,
        }
        target_wd = day_map.get(day_of_week)
        if target_wd is None:
            # Fallback to Thursday if config has unexpected value
            target_wd = 3

        today: date = current_time.date()

        def next_weekly_expiry(from_date: date, weekday: int) -> date:
            """Get the next occurrence of `weekday` on or after `from_date`."""
            days_ahead = (weekday - from_date.weekday()) % 7
            return from_date + timedelta(days=days_ahead)

        def last_weekday_of_month(year: int, month: int, weekday: int) -> date:
            """Get the last occurrence of `weekday` in a given month."""
            last_day = calendar.monthrange(year, month)[1]
            d = date(year, month, last_day)
            while d.weekday() != weekday:
                d -= timedelta(days=1)
            return d

        if duration == "Weekly":
            expiry_d = next_weekly_expiry(today, target_wd)
        else:
            # Monthly: last configured weekday of the current month,
            # or next month if we've already passed it.
            expiry_d = last_weekday_of_month(today.year, today.month, target_wd)
            if today > expiry_d:
                # Move to next month
                if today.month == 12:
                    year, month = today.year + 1, 1
                else:
                    year, month = today.year, today.month + 1
                expiry_d = last_weekday_of_month(year, month, target_wd)

        # Return as datetime for consistency with existing callers
        return datetime.combine(expiry_d, datetime.min.time())
    except Exception as e:
        logger.debug(f"Error calculating expiry date for duration={duration}, day_of_week={day_of_week}: {e}")
        return None


def build_tradingsymbol(segment: str, strike: int, option_type: str, expiry: str, expiry_config: Optional[Dict] = None) -> str:
    """
    Build trading symbol in appropriate format (weekly or monthly)
    
    Weekly format: SEGMENT + YY + M + DD + STRIKE + OPTIONTYPE
    Example: NIFTY25D0226200CE (for 2025, Dec 2nd, strike 26200, CE)
    Where M = first letter of month name (J=Jan, F=Feb, M=Mar, A=Apr, M=May, J=Jun, J=Jul, A=Aug, S=Sep, O=Oct, N=Nov, D=Dec)
    
    Monthly format: SEGMENT + YY + MMM + STRIKE + OPTIONTYPE
    Example: BANKNIFTY25DEC59800PE (for 2025, Dec expiry, strike 59800, PE)
    
    Args:
        segment: Trading segment (NIFTY, BANKNIFTY, SENSEX)
        strike: Strike price
        option_type: CE or PE
        expiry: Expiry date in YYYY-MM-DD format
        
    Returns:
        Trading symbol string (e.g., NIFTY25D0226200CE or BANKNIFTY25DEC59800PE)
    """
    try:
        # Parse expiry date
        expiry_date = datetime.strptime(expiry, "%Y-%m-%d")
        
        # Determine if weekly or monthly format
        is_weekly = is_weekly_expiry(segment, expiry_date, expiry_config)
        
        year = expiry_date.strftime("%y")  # 25 for 2025
        
        if is_weekly:
            # Weekly format: SEGMENT + YY + M + DD + STRIKE + OPTIONTYPE
            # M = first letter of month name (J=Jan, F=Feb, M=Mar, A=Apr, M=May, J=Jun,
            #                                 J=Jul, A=Aug, S=Sep, O=Oct, N=Nov, D=Dec)
            month_letter = expiry_date.strftime("%b")[0].upper()  # First letter of month (D for DEC)
            day = expiry_date.strftime("%d")  # 02 for 2nd
            trading_symbol = f"{segment.upper()}{year}{month_letter}{day}{strike}{option_type.upper()}"
        else:
            # Monthly format: SEGMENT + YY + MMM + STRIKE + OPTIONTYPE
            month = expiry_date.strftime("%b").upper()  # DEC
            trading_symbol = f"{segment.upper()}{year}{month}{strike}{option_type.upper()}"
        
        return trading_symbol
    except (ValueError, AttributeError) as e:
        logger.debug(f"Error building trading symbol for {segment} {strike} {option_type} {expiry}: {e}")
        return None


def find_instrument_by_tradingsymbol(
    tradingsymbol: str,
    instruments: List[Dict],
    exchange: str = "NFO"
) -> Optional[Dict]:
    """
    Find instrument by tradingsymbol (most reliable method)
    
    Args:
        tradingsymbol: Trading symbol (e.g., BANKNIFTY25DEC59900PE)
        instruments: List of instruments from Kite API
        exchange: Exchange name (default: NFO)
        
    Returns:
        Instrument dict if found, None otherwise
    """
    for inst in instruments:
        if inst.get('tradingsymbol') == tradingsymbol:
            return inst
    return None


def fetch_premium_by_tradingsymbol(
    kite_client,
    tradingsymbol: str,
    timestamp: datetime,
    exchange: str = "NFO",
    window_minutes: int = 10,
    interval: str = "5minute"
) -> Optional[Tuple[float, Dict]]:
    """
    Fetch premium for a trading symbol at a specific timestamp
    Uses the same logic as get_premium_by_symbol.py
    
    Args:
        kite_client: Authenticated KiteClient instance
        tradingsymbol: Trading symbol (e.g., BANKNIFTY25DEC59900PE)
        timestamp: Timestamp to get premium for
        exchange: Exchange name (default: NFO)
        window_minutes: Minutes before/after timestamp to fetch (default: 10)
        interval: Kite interval string (default: "5minute")
        
    Returns:
        Tuple of (premium, instrument_details) or None if not found
    """
    try:
        # Check authentication
        if not kite_client or not kite_client.is_authenticated():
            logger.debug("Kite client not authenticated")
            return None
        
        # Get all NFO instruments
        instruments = kite_client.kite.instruments(exchange)
        
        # Find the instrument by tradingsymbol
        instrument = find_instrument_by_tradingsymbol(tradingsymbol, instruments, exchange)
        
        if not instrument:
            logger.debug(f"Trading symbol '{tradingsymbol}' not found in {exchange} exchange")
            return None
        
        # Get instrument token
        instrument_token = instrument['instrument_token']
        
        # Make timestamp timezone-aware (IST)
        if timestamp.tzinfo is None:
            try:
                from pytz import timezone
                ist = timezone('Asia/Kolkata')
                timestamp = ist.localize(timestamp)
            except ImportError:
                from datetime import timezone as dt_timezone
                ist_offset = dt_timezone(timedelta(hours=5, minutes=30))
                timestamp = timestamp.replace(tzinfo=ist_offset)
        
        # Fetch historical data around the target timestamp
        from_date = timestamp - timedelta(minutes=window_minutes)
        to_date = timestamp + timedelta(minutes=window_minutes)
        
        # Kite API expects timezone-naive datetimes
        from_date_naive = from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
        to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date
        
        # Fetch historical data
        candles = kite_client.kite.historical_data(
            instrument_token,
            from_date_naive,
            to_date_naive,
            interval,
            continuous=False,
            oi=False
        )
        
        if not candles:
            logger.debug(f"No historical data found for {tradingsymbol} around {timestamp}")
            return None
        
        # Convert to DataFrame for easier processing
        df = pd.DataFrame(candles)
        df['date'] = pd.to_datetime(df['date'])
        
        # Ensure both are timezone-aware (Kite returns IST timezone)
        if df['date'].dt.tz is None:
            try:
                from pytz import timezone
                ist = timezone('Asia/Kolkata')
                df['date'] = df['date'].dt.tz_localize(ist)
            except ImportError:
                from datetime import timezone as dt_timezone
                ist_offset = dt_timezone(timedelta(hours=5, minutes=30))
                df['date'] = df['date'].dt.tz_localize(ist_offset)
        
        # Find the candle closest to the target timestamp
        df['time_diff'] = abs(df['date'] - timestamp)
        closest_candle = df.loc[df['time_diff'].idxmin()]
        
        # Use close price as premium
        premium = float(closest_candle['close'])
        
        # Store instrument details
        instrument_details = {
            'instrument_type': instrument.get('instrument_type', ''),
            'tradingsymbol': instrument.get('tradingsymbol', tradingsymbol),
            'exchange': instrument.get('exchange', exchange),
            'instrument_token': instrument_token,
            'strike': instrument.get('strike', 0),
            'expiry': instrument.get('expiry', None)
        }
        
        return (premium, instrument_details)
        
    except Exception as e:
        logger.debug(f"Error fetching premium for {tradingsymbol} at {timestamp}: {e}")
        return None


def fetch_premium_by_params(
    kite_client,
    segment: str,
    strike: int,
    option_type: str,
    expiry: str,
    timestamp: datetime,
    exchange: str = "NFO",
    window_minutes: int = 10,
    interval: str = "5minute",
    expiry_config: Optional[Dict] = None
) -> Optional[Tuple[float, Dict]]:
    """
    Fetch premium by building tradingsymbol from parameters
    This is a convenience wrapper that builds the tradingsymbol and calls fetch_premium_by_tradingsymbol
    
    Args:
        kite_client: Authenticated KiteClient instance
        segment: Trading segment (NIFTY, BANKNIFTY, SENSEX)
        strike: Strike price
        option_type: CE or PE
        expiry: Expiry date in YYYY-MM-DD format
        timestamp: Timestamp to get premium for
        exchange: Exchange name (default: NFO)
        window_minutes: Minutes before/after timestamp to fetch (default: 10)
        interval: Kite interval string (default: "5minute")
        expiry_config: Optional expiry configuration dict from config.json
        
    Returns:
        Tuple of (premium, instrument_details) or None if not found
    """
    # Auto-detect exchange based on segment if default was used
    if exchange == "NFO":
        exchange = get_exchange_for_segment(segment)
    
    # Build tradingsymbol
    tradingsymbol = build_tradingsymbol(segment, strike, option_type, expiry, expiry_config)
    
    if not tradingsymbol:
        logger.debug(f"Could not build tradingsymbol for {segment} {strike} {option_type} {expiry}")
        return None
    
    # Fetch premium using tradingsymbol
    return fetch_premium_by_tradingsymbol(
        kite_client,
        tradingsymbol,
        timestamp,
        exchange,
        window_minutes,
        interval
    )

