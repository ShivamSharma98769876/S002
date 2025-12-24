"""
Live data utilities for Live Trader

Provides simple helper functions to fetch live index prices and small intraday
history snapshots using the Zerodha Kite API.
"""

from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd

from src.api.kite_client import KiteClient
from src.utils.logger import get_logger

logger = get_logger("live_data")


INDEX_SYMBOL_MAP = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "SENSEX": "BSE:SENSEX",
}

# Known index instrument tokens from Zerodha instruments dump
INDEX_INSTRUMENT_TOKENS = {
    "NIFTY": 256265,      # NSE:NIFTY 50
    "BANKNIFTY": 260105,  # NSE:NIFTY BANK
    "SENSEX": 265,        # BSE:SENSEX
}

# Map internal interval format to Kite API format
# Kite API expects: "minute" (1min), "3minute", "5minute", "15minute", "30minute", "60minute", "day"
KITE_INTERVAL_MAP = {
    "1minute": "minute",  # Kite uses "minute" for 1-minute, not "1minute"
    "3minute": "3minute",
    "5minute": "5minute",
    "15minute": "15minute",
    "30minute": "30minute",
    "1hour": "60minute",
    "1day": "day",
    # Also handle shortened formats if they come in
    "1min": "minute",
    "3min": "3minute",
    "5min": "5minute",
    "15min": "15minute",
    "30min": "30minute",
    "60min": "60minute",
}


def convert_interval_to_kite_format(interval: str) -> str:
    """
    Convert internal interval format to Kite API format.
    
    Kite API expects:
    - "minute" for 1-minute (not "1minute" or "1min")
    - "5minute" for 5-minute (not "5min")
    - "15minute" for 15-minute (not "15min")
    - etc.
    
    Args:
        interval: Internal interval string (e.g., "1minute", "5minute", "5min")
        
    Returns:
        Kite API interval string (e.g., "minute", "5minute", "15minute")
    """
    # If already in correct Kite format, return as-is
    if interval in ["minute", "3minute", "5minute", "15minute", "30minute", "60minute", "day"]:
        return interval
    
    # Convert from internal format to Kite format
    interval_lower = interval.lower()
    kite_interval = KITE_INTERVAL_MAP.get(interval_lower, interval)
    
    if kite_interval != interval:
        logger.debug(f"Converted interval '{interval}' to Kite format '{kite_interval}'")
    
    return kite_interval


def get_segment_index_symbol(segment: str) -> str:
    """
    Map logical segment name to Kite index symbol.
    """
    key = segment.upper()
    if key not in INDEX_SYMBOL_MAP:
        raise ValueError(f"Unsupported segment for live data: {segment}")
    return INDEX_SYMBOL_MAP[key]


def fetch_live_index_ltp(kite_client: KiteClient, segment: str) -> float:
    """
    Fetch latest traded price (LTP) for a given index segment.

    Args:
        kite_client: Authenticated KiteClient instance
        segment: 'NIFTY', 'BANKNIFTY', or 'SENSEX'

    Returns:
        Latest traded price as float.
    """
    return kite_client.get_index_ltp(segment)


def fetch_recent_index_candles(
    kite_client: KiteClient,
    segment: str,
    interval: str = "5minute",
    lookback_minutes: int = 60,
) -> pd.DataFrame:
    """
    Fetch a recent intraday candle history for an index using Kite's historical_data API.

    Args:
        kite_client: Authenticated KiteClient instance
        segment: 'NIFTY', 'BANKNIFTY', or 'SENSEX'
        interval: Kite interval string (e.g. '3minute', '5minute', '15minute')
        lookback_minutes: How many minutes of history to fetch from now.

    Returns:
        pandas DataFrame with columns: open, high, low, close, volume indexed by timestamp.
    """
    if not kite_client.is_authenticated():
        from src.utils.exceptions import AuthenticationError

        raise AuthenticationError("Not authenticated. Please authenticate first.")

    seg = segment.upper()
    instrument_token = INDEX_INSTRUMENT_TOKENS.get(seg)
    if instrument_token is None:
        raise ValueError(f"Unsupported segment for historical data: {segment}")

    # Use IST time for all calculations (critical for Azure which runs in GMT)
    from src.utils.date_utils import get_current_ist_time
    ist_now = get_current_ist_time()
    end = ist_now.replace(tzinfo=None)  # Convert to naive for API compatibility
    start = end - timedelta(minutes=lookback_minutes)

    # Convert interval to Kite API format
    kite_interval = convert_interval_to_kite_format(interval)

    try:
        candles = kite_client.kite.historical_data(
            instrument_token,
            start,
            end,
            kite_interval,
            continuous=False,
            oi=False,
        )
        if not candles:
            logger.warning(f"No historical candles returned for {segment} ({interval})")
            return pd.DataFrame()

        df = pd.DataFrame(candles)
        if "date" not in df.columns:
            logger.warning(f"Historical candles missing 'date' column for {segment}")
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        logger.info(
            f"Bootstrapped {len(df)} candles for {segment} covering "
            f"{df.index[0]} to {df.index[-1]} ({interval})"
        )
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.error(f"Error fetching recent index candles for {segment}: {e}", exc_info=True)
        return pd.DataFrame()


def fetch_last_trading_day_candles(
    kite_client: KiteClient,
    segment: str,
    interval: str = "5minute",
) -> pd.DataFrame:
    """
    Fetch complete candle data for the last trading day.
    
    This is useful when recent candles are not available (e.g., market just opened,
    API issues, etc.) and we need historical data to proceed with trading.
    
    Args:
        kite_client: Authenticated KiteClient instance
        segment: 'NIFTY', 'BANKNIFTY', or 'SENSEX'
        interval: Kite interval string (e.g. '3minute', '5minute', '15minute')
    
    Returns:
        pandas DataFrame with columns: open, high, low, close, volume indexed by timestamp.
        Returns empty DataFrame if fetch fails.
    """
    if not kite_client.is_authenticated():
        from src.utils.exceptions import AuthenticationError
        raise AuthenticationError("Not authenticated. Please authenticate first.")

    from src.utils.date_utils import get_current_ist_time, get_market_hours
    from datetime import timedelta
    
    seg = segment.upper()
    instrument_token = INDEX_INSTRUMENT_TOKENS.get(seg)
    if instrument_token is None:
        logger.error(f"Unsupported segment for historical data: {segment}")
        return pd.DataFrame()

    # Get last trading day
    ist_time = get_current_ist_time()
    market_open, market_close = get_market_hours()
    
    # Calculate last trading day (yesterday, or skip weekends)
    last_trading_day = ist_time.date() - timedelta(days=1)
    while last_trading_day.weekday() >= 5:  # Skip weekends
        last_trading_day -= timedelta(days=1)
    
    # Create date range for last trading day (market hours)
    from_date = datetime.combine(last_trading_day, market_open)
    to_date = datetime.combine(last_trading_day, market_close)
    
    # Convert interval to Kite API format
    kite_interval = convert_interval_to_kite_format(interval)
    
    try:
        logger.info(
            f"📅 Fetching complete last trading day ({last_trading_day}) candles for {segment} "
            f"from {from_date} to {to_date} ({interval})..."
        )
        
        candles = kite_client.kite.historical_data(
            instrument_token,
            from_date,
            to_date,
            kite_interval,
            continuous=False,
            oi=False,
        )
        
        if not candles:
            logger.warning(f"No historical candles returned for last trading day {last_trading_day} ({segment}, {interval})")
            return pd.DataFrame()

        df = pd.DataFrame(candles)
        if "date" not in df.columns:
            logger.warning(f"Historical candles missing 'date' column for {segment}")
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        
        # Filter to last trading day only (in case API returns extra data)
        df = df[df.index.date == last_trading_day]
        
        logger.info(
            f"✅ Fetched {len(df)} candles for last trading day {last_trading_day} ({segment}) "
            f"covering {df.index[0]} to {df.index[-1]} ({interval})"
        )
        
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.error(
            f"Error fetching last trading day candles for {segment} ({last_trading_day}): {e}",
            exc_info=True
        )
        return pd.DataFrame()


