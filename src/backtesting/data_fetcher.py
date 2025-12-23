"""
Historical Data Fetcher for Backtesting
Fetches historical OHLCV data from Yahoo Finance API
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pandas as pd
try:
    import yfinance as yf
except ImportError:
    yf = None
from src.api.kite_client import KiteClient
from src.config.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger("backtesting")


class HistoricalDataFetcher:
    """Fetches historical data for backtesting using Yahoo Finance"""
    
    def __init__(self, kite_client: KiteClient = None):
        self.kite_client = kite_client
        self.instrument_cache = {}
        
        # Map segments to Yahoo Finance symbols
        self.yahoo_symbols = {
            "NIFTY": "^NSEI",  # NIFTY 50
            "SENSEX": "^BSESN",  # SENSEX
            "BANKNIFTY": "^NSEBANK"  # NIFTY BANK
        }
        
        if yf is None:
            logger.warning("yfinance not installed. Please install it: pip install yfinance")
    
    def get_instrument_token(
        self,
        segment: str,
        instrument_name: str,
        expiry: Optional[str] = None
    ) -> Optional[int]:
        """
        Get instrument token for the given segment and instrument
        
        Args:
            segment: NIFTY, SENSEX, or BANKNIFTY
            instrument_name: Base instrument name (e.g., "NIFTY", "BANKNIFTY")
            expiry: Expiry date in format "YYYY-MM-DD" (optional)
        
        Returns:
            Instrument token or None if not found
        """
        cache_key = f"{segment}_{instrument_name}_{expiry}"
        if cache_key in self.instrument_cache:
            return self.instrument_cache[cache_key]
        
        try:
            if not self.kite_client.is_authenticated():
                logger.error("Kite client not authenticated")
                return None
            
            # Get correct exchange for segment
            from src.utils.premium_fetcher import get_exchange_for_segment
            exchange = get_exchange_for_segment(segment)
            segment_code = 'BFO' if exchange == 'BFO' else 'NFO'
            
            # Get instruments list from the correct exchange
            instruments = self.kite_client.kite.instruments(exchange)
            
            # Filter by segment and instrument name
            filtered = [
                inst for inst in instruments
                if inst['name'] == instrument_name and
                inst['segment'] == segment_code
            ]
            
            if not filtered:
                logger.warning(f"No instruments found for {instrument_name}")
                return None
            
            # If expiry specified, filter by expiry
            if expiry:
                expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
                filtered = [
                    inst for inst in filtered
                    if inst['expiry'].date() == expiry_date
                ]
            
            # Get the most liquid (highest volume) or nearest expiry
            if filtered:
                # Sort by expiry (nearest first)
                filtered.sort(key=lambda x: x['expiry'])
                instrument = filtered[0]
                token = instrument['instrument_token']
                self.instrument_cache[cache_key] = token
                return token
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting instrument token: {e}")
            return None
    
    def fetch_historical_data(
        self,
        instrument_token: int = None,
        from_date: datetime = None,
        to_date: datetime = None,
        interval: str = "15minute",
        continuous: bool = False
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data (legacy method for Zerodha API)
        This method is kept for backward compatibility but is not used for backtesting.
        Backtesting now uses Yahoo Finance via fetch_segment_data()
        
        Args:
            instrument_token: Instrument token (not used with Yahoo Finance)
            from_date: Start date
            to_date: End date
            interval: Time interval
            continuous: Whether to fetch continuous contract data
        
        Returns:
            DataFrame with OHLCV data
        """
        logger.warning("fetch_historical_data() called but backtesting uses Yahoo Finance. Use fetch_segment_data() instead.")
        return pd.DataFrame()
    
    def fetch_segment_data_from_kite(
        self,
        segment: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "5minute"
    ) -> pd.DataFrame:
        """
        Fetch historical data for a segment using Kite API (same as backtest)
        
        Args:
            segment: NIFTY, SENSEX, or BANKNIFTY
            from_date: Start date
            to_date: End date
            interval: Time interval (5minute, 15minute, etc.)
        
        Returns:
            DataFrame with OHLCV data indexed by datetime
        """
        if not self.kite_client or not self.kite_client.is_authenticated():
            logger.error("Kite client not authenticated")
            return pd.DataFrame()
        
        # Map segment to instrument name
        segment_map = {
            "NIFTY": "NIFTY",
            "BANKNIFTY": "BANKNIFTY",
            "SENSEX": "SENSEX"
        }
        
        instrument_name = segment_map.get(segment.upper())
        if not instrument_name:
            logger.error(f"Invalid segment: {segment}")
            return pd.DataFrame()
        
        # Get instrument token
        instrument_token = self.get_instrument_token(segment, instrument_name)
        if not instrument_token:
            logger.error(f"Could not get instrument token for {segment}")
            return pd.DataFrame()
        
        logger.info(f"Fetching {segment} data from Kite API (token: {instrument_token})")
        
        try:
            # Convert datetime to naive (Kite API expects naive datetime)
            from_date_naive = from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
            to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date
            
            # Fetch historical data
            candles = self.kite_client.kite.historical_data(
                instrument_token,
                from_date_naive,
                to_date_naive,
                interval,
                continuous=False,
                oi=False
            )
            
            if not candles:
                logger.warning(f"No data returned from Kite API for {segment}")
                return pd.DataFrame()
            
            # Convert to DataFrame
            df = pd.DataFrame(candles)
            df['date'] = pd.to_datetime(df['date'])
            
            # Set timezone to IST if not set
            if df['date'].dt.tz is None:
                try:
                    from pytz import timezone
                    ist = timezone('Asia/Kolkata')
                    df['date'] = df['date'].dt.tz_localize(ist)
                except ImportError:
                    from datetime import timezone as dt_timezone
                    ist_offset = dt_timezone(timedelta(hours=5, minutes=30))
                    df['date'] = df['date'].dt.tz_localize(ist_offset)
            
            # Set date as index
            df.set_index('date', inplace=True)
            
            # Rename columns to match expected format
            df.rename(columns={
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            }, inplace=True)
            
            # Ensure we have the required columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in required_cols:
                if col not in df.columns:
                    logger.error(f"Missing column: {col}")
                    return pd.DataFrame()
            
            # Sort by date
            df.sort_index(inplace=True)
            
            logger.info(f"Fetched {len(df)} candles from Kite API")
            return df[required_cols]
            
        except Exception as e:
            logger.error(f"Error fetching data from Kite API: {e}")
            return pd.DataFrame()
    
    def fetch_segment_data(
        self,
        segment: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "15minute",
        expiry: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetch historical data for a segment using Yahoo Finance
        
        Args:
            segment: NIFTY, SENSEX, or BANKNIFTY
            from_date: Start date
            to_date: End date
            interval: Time interval (15minute, 1hour, 1day, etc.)
            expiry: Expiry date (optional, not used for Yahoo Finance)
        
        Returns:
            DataFrame with OHLCV data
        """
        if yf is None:
            logger.error("yfinance library not installed. Please install: pip install yfinance")
            raise ImportError("yfinance library not installed. Please install: pip install yfinance")
        
        # Get Yahoo Finance symbol for the segment
        yahoo_symbol = self.yahoo_symbols.get(segment.upper())
        if not yahoo_symbol:
            logger.error(f"Invalid segment: {segment}. Valid segments: {list(self.yahoo_symbols.keys())}")
            raise ValueError(f"Invalid segment: {segment}. Valid segments: {list(self.yahoo_symbols.keys())}")
        
        logger.info(f"Fetching {segment} data from Yahoo Finance (symbol: {yahoo_symbol})")
        
        try:
            
            # Convert interval to yfinance format
            interval_map = {
                "1minute": "1m",
                "3minute": "3m",
                "5minute": "5m",
                "15minute": "15m",
                "30minute": "30m",
                "1hour": "1h",
                "1day": "1d",
                "1week": "1wk",
                "1month": "1mo"
            }
            
            yf_interval = interval_map.get(interval.lower(), "15m")
            
            # For intraday data (minutes), yfinance requires period instead of start/end
            # For daily data, we can use start/end dates
            is_intraday = yf_interval in ["1m", "3m", "5m", "15m", "30m", "1h"]
            
            try:
                ticker = yf.Ticker(yahoo_symbol)
                
                if is_intraday:
                    # For intraday, calculate period needed
                    days_diff = (to_date - from_date).days
                    if days_diff <= 7:
                        period = "7d"
                    elif days_diff <= 60:
                        period = "60d"
                    else:
                        period = "1y"
                    
                    logger.info(f"Fetching intraday data with period: {period}, interval: {yf_interval}")
                    df = ticker.history(period=period, interval=yf_interval)
                    
                    # Filter by date range - make end date inclusive
                    if not df.empty:
                        # Convert timezone-aware index to naive if needed, or make dates timezone-aware
                        if df.index.tz is not None:
                            # Remove timezone from index for comparison
                            df.index = df.index.tz_localize(None)
                        # Build inclusive date range [from_date, to_date_end)
                        range_start = from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
                        # Add one day so we include all candles of the to_date
                        range_end = to_date + timedelta(days=1)
                        range_end = range_end.replace(tzinfo=None) if range_end.tzinfo else range_end
                        df = df[(df.index >= range_start) & (df.index < range_end)]
                else:
                    # For daily/weekly/monthly data, use start and end
                    logger.info(f"Fetching daily data from {from_date.date()} to {to_date.date()} (inclusive)")
                    # Ensure dates are timezone-naive for yfinance
                    from_date_naive = from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
                    to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date
                    # yfinance 'end' is exclusive, so add one day to include to_date
                    end_inclusive = to_date_naive + timedelta(days=1)
                    df = ticker.history(start=from_date_naive, end=end_inclusive, interval=yf_interval)
                    
                    # Remove timezone from index if present
                    if not df.empty and df.index.tz is not None:
                        df.index = df.index.tz_localize(None)
                
                if df.empty:
                    logger.warning(f"No data returned from Yahoo Finance for {yahoo_symbol}")
                    return pd.DataFrame()
                
                # Rename columns to match expected format
                df.rename(columns={
                    'Open': 'open',
                    'High': 'high',
                    'Low': 'low',
                    'Close': 'close',
                    'Volume': 'volume'
                }, inplace=True)
                
                # Ensure we have required columns
                required_columns = ['open', 'high', 'low', 'close']
                if not all(col in df.columns for col in required_columns):
                    logger.error(f"Missing required columns. Available: {df.columns.tolist()}")
                    return pd.DataFrame()
                
                # Add volume if missing (set to 0)
                if 'volume' not in df.columns:
                    df['volume'] = 0
                
                # Sort by datetime
                df.sort_index(inplace=True)
                
                logger.info(f"Fetched {len(df)} candles for {segment} from Yahoo Finance")
                logger.debug(f"Date range: {df.index.min()} to {df.index.max()}")
                
                return df
                
            except Exception as e:
                logger.error(f"Error fetching data from Yahoo Finance: {e}", exc_info=True)
                raise  # Re-raise to be caught by the route handler
            
        except (ImportError, ValueError) as e:
            # Re-raise import and value errors
            raise
        except Exception as e:
            logger.error(f"Error fetching segment data: {e}", exc_info=True)
            raise  # Re-raise to be caught by the route handler

