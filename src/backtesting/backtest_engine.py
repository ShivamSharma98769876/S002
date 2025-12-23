"""
Backtesting Engine
Runs backtests on historical data using RSI strategy
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import re
from calendar import month_abbr
from src.trading.rsi_agent import (
    RSIStrategy, RSITradingAgent, Segment, TradeSignal, OptionType
)
from src.backtesting.data_fetcher import HistoricalDataFetcher
from src.utils.logger import get_logger

logger = get_logger("backtesting")


class BacktestResult:
    """Backtest result container"""
    
    def __init__(self):
        self.trades: List[Dict] = []
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.net_pnl = 0.0
        self.max_drawdown = 0.0
        self.max_profit = 0.0
        self.win_rate = 0.0
        self.profit_factor = 0.0
        self.start_date = None
        self.end_date = None
        self.initial_capital = 0.0
        self.final_capital = 0.0
        self.return_pct = 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "trades": self.trades,
            "summary": {
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "total_profit": self.total_profit,
                "total_loss": self.total_loss,
                "net_pnl": self.net_pnl,
                "max_drawdown": self.max_drawdown,
                "max_profit": self.max_profit,
                "win_rate": self.win_rate,
                "profit_factor": None if (self.profit_factor is not None and self.profit_factor == float('inf')) else self.profit_factor,
                "start_date": self.start_date.isoformat() if self.start_date else None,
                "end_date": self.end_date.isoformat() if self.end_date else None,
                "initial_capital": self.initial_capital,
                "final_capital": self.final_capital,
                "return_pct": self.return_pct
            }
        }


class BacktestEngine:
    """Backtesting engine for RSI strategy"""
    
    def __init__(self, data_fetcher: HistoricalDataFetcher):
        self.data_fetcher = data_fetcher
        self.option_premium_cache = {}  # Cache for option premiums: (segment, strike, option_type, expiry, timestamp) -> premium
        self._nfo_instruments_cache = None  # Cache for NFO instruments list (expensive to fetch)
        self._kite_authenticated = None  # Cache authentication status
        self._expiry_config = None  # Cache for expiry configuration
    
    def _load_expiry_config(self) -> Optional[Dict]:
        """Load expiry configuration from config.json"""
        if self._expiry_config is None:
            try:
                from src.config.config_manager import ConfigManager
                import json
                config_manager = ConfigManager()
                config_path = config_manager.config_dir / "config.json"
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config_data = json.load(f)
                        self._expiry_config = config_data.get("expiry_config", {})
                else:
                    # Default config
                    self._expiry_config = {
                        "BANKNIFTY": {"duration": "Monthly", "day_of_week": "Thursday"},
                        "NIFTY": {"duration": "Weekly", "day_of_week": "Tuesday"},
                        "SENSEX": {"duration": "Weekly", "day_of_week": "Thursday"}
                    }
            except Exception as e:
                logger.warning(f"Could not load expiry config: {e}, using defaults")
                self._expiry_config = {
                    "BANKNIFTY": {"duration": "Monthly", "day_of_week": "Thursday"},
                    "NIFTY": {"duration": "Weekly", "day_of_week": "Tuesday"},
                    "SENSEX": {"duration": "Weekly", "day_of_week": "Thursday"}
                }
        return self._expiry_config
    
    def _calculate_atm_strike(self, spot_price: float, segment: str) -> int:
        """
        Calculate ATM (At The Money) strike price
        
        Args:
            spot_price: Current spot price
            segment: Trading segment (NIFTY, SENSEX, BANKNIFTY)
        
        Returns:
            ATM strike price rounded to appropriate interval
        """
        if segment.upper() == "NIFTY":
            # NIFTY strikes are in multiples of 50
            return round(spot_price / 50) * 50
        elif segment.upper() == "BANKNIFTY":
            # BANKNIFTY strikes are in multiples of 100
            return round(spot_price / 100) * 100
        elif segment.upper() == "SENSEX":
            # SENSEX strikes are in multiples of 100
            return round(spot_price / 100) * 100
        else:
            # Default: round to nearest 50
            return round(spot_price / 50) * 50
    
    def _find_instrument_by_expiry(
        self,
        segment: str,
        strike: int,
        option_type: str,
        expiry: str,
        instruments: List[Dict]
    ) -> Optional[Dict]:
        """
        Find instrument by filtering instruments (EXACT same approach as Straddle10PointswithSL-Limit.py)
        Uses the same filtering logic: segment, name, instrument_type, strike, and expiry
        Handles both NFO (for NIFTY/BANKNIFTY) and BFO (for SENSEX) exchanges
        
        Args:
            segment: Trading segment (NIFTY, BANKNIFTY, SENSEX)
            strike: Strike price
            option_type: CE or PE
            expiry: Expiry date in YYYY-MM-DD format
            instruments: List of instruments from kite.instruments() (NFO or BFO based on segment)
            
        Returns:
            Instrument dict with tradingsymbol if found, None otherwise
        """
        try:
            # Map segment to base name (same as Straddle10PointswithSL-Limit.py)
            segment_map = {
                "NIFTY": "NIFTY",
                "BANKNIFTY": "BANKNIFTY",
                "SENSEX": "SENSEX"
            }
            base_name = segment_map.get(segment.upper())
            if not base_name:
                logger.warning(f"Unknown segment: {segment}")
                return None
            
            # Parse expiry date
            expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            
            # Helper function to get date from expiry (handles both datetime and date objects)
            def get_expiry_date(expiry_obj):
                if expiry_obj is None:
                    return None
                if isinstance(expiry_obj, datetime):
                    return expiry_obj.date()
                elif isinstance(expiry_obj, date):
                    return expiry_obj
                elif hasattr(expiry_obj, 'date') and callable(getattr(expiry_obj, 'date', None)):
                    try:
                        return expiry_obj.date()
                    except:
                        return None
                else:
                    # Try to parse as string if needed
                    try:
                        if isinstance(expiry_obj, str):
                            return datetime.strptime(expiry_obj, "%Y-%m-%d").date()
                    except:
                        pass
                    return None
            
            # Determine segment code based on exchange (BFO-OPT for BFO, NFO-OPT for NFO)
            from src.utils.premium_fetcher import get_exchange_for_segment
            exchange = get_exchange_for_segment(segment)
            segment_code = 'BFO-OPT' if exchange == 'BFO' else 'NFO-OPT'
            
            # Filter instruments: EXACT same approach as Straddle10PointswithSL-Limit.py
            # Filter by segment, name, instrument_type, strike, and expiry
            filtered = []
            for inst in instruments:
                # Check segment
                if inst.get('segment') != segment_code:
                    continue
                # Check name
                if inst.get('name') != base_name:
                    continue
                # Check instrument_type
                if inst.get('instrument_type') != option_type.upper():
                    continue
                # Check strike
                inst_strike = inst.get('strike')
                if inst_strike is None or float(inst_strike) != float(strike):
                    continue
                # Check expiry
                inst_expiry = get_expiry_date(inst.get('expiry'))
                if inst_expiry is None or inst_expiry != expiry_date:
                    continue
                
                # Match found!
                filtered.append(inst)
            
            if filtered:
                # Return the first match (should be unique)
                matched_instrument = filtered[0]
                logger.info(
                    f"Found instrument: {matched_instrument.get('tradingsymbol', 'N/A')} "
                    f"for {segment} {strike} {option_type} {expiry}"
                )
                return matched_instrument
            
            # Log detailed failure information
            logger.warning(
                f"NO INSTRUMENT FOUND for {segment} {strike} {option_type} {expiry}. "
                f"Available instruments count: {len(instruments)}. "
                f"Filtered by segment='{segment_code}' and name='{base_name}': "
                f"{len([i for i in instruments if i.get('segment') == segment_code and i.get('name') == base_name])}"
            )
            return None
            
        except (ValueError, AttributeError, TypeError) as e:
            logger.error(f"Error finding instrument for {segment} {strike} {option_type} {expiry}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    def _fetch_option_premium_from_kite(
        self,
        strike: int,
        option_type: str,
        segment: str,
        expiry: Optional[str],
        timestamp: datetime
    ) -> Optional[Tuple[float, Dict]]:
        """
        Fetch actual option premium from Kite API for a specific timestamp
        Uses the same format and logic as get_premium_by_symbol.py
        
        Args:
            strike: Strike price
            option_type: CE or PE
            segment: Trading segment
            expiry: Expiry date (YYYY-MM-DD)
            timestamp: Timestamp to get premium for
            
        Returns:
            Option premium if available, None otherwise
        """
        try:
            kite_client = self.data_fetcher.kite_client
            if not kite_client:
                return None
            
            # Check authentication status (cache it to avoid repeated checks)
            if self._kite_authenticated is None:
                self._kite_authenticated = kite_client.is_authenticated()
            
            if not self._kite_authenticated:
                return None
            
            # Align timestamp to the correct 5-minute candle boundary
            # For 5-minute candles, if timestamp is 14:38:06, it should use 14:35:00 (the start of the candle that contains this time)
            # Round DOWN to the nearest 5-minute boundary (candle start)
            timestamp_aligned = timestamp.replace(second=0, microsecond=0)
            minute = timestamp_aligned.minute
            # Round down to nearest 5-minute boundary
            minute_rounded = (minute // 5) * 5
            timestamp_aligned = timestamp_aligned.replace(minute=minute_rounded)
            
            cache_key = (segment, strike, option_type, expiry, timestamp_aligned.isoformat())
            if cache_key in self.option_premium_cache:
                cached_result = self.option_premium_cache[cache_key]
                # Check if it's a tuple (premium, details) or just premium
                if isinstance(cached_result, tuple):
                    return cached_result
                else:
                    # Old cache format - get details from instrument_details_cache
                    if hasattr(self, 'instrument_details_cache') and cache_key in self.instrument_details_cache:
                        return (cached_result, self.instrument_details_cache[cache_key])
                    return None
            
            # Use the premium fetcher utility (same as get_premium_by_symbol.py)
            from src.utils.premium_fetcher import fetch_premium_by_params
            
            if expiry:
                # Load expiry config
                expiry_config = self._load_expiry_config()
                
                # Try to fetch using tradingsymbol format (BANKNIFTY25DEC59900PE)
                # Exchange will be auto-detected based on segment (BFO for SENSEX, NFO for others)
                result = fetch_premium_by_params(
                    kite_client,
                    segment,
                    strike,
                    option_type,
                    expiry,
                    timestamp,
                    exchange="NFO",  # Default, will be auto-detected in fetch_premium_by_params
                    window_minutes=10,
                    interval="5minute",
                    expiry_config=expiry_config
                )
                
                if result:
                    premium, instrument_details = result
                    # Cache the result
                    self.option_premium_cache[cache_key] = (premium, instrument_details)
                    if not hasattr(self, 'instrument_details_cache'):
                        self.instrument_details_cache = {}
                    self.instrument_details_cache[cache_key] = instrument_details
                    return result
            
            # Fallback: Use the old filtering method if tradingsymbol lookup fails
            # Get correct exchange for segment
            from src.utils.premium_fetcher import get_exchange_for_segment
            exchange = get_exchange_for_segment(segment)
            segment_code = 'BFO-OPT' if exchange == 'BFO' else 'NFO-OPT'
            
            # Cache instruments by exchange (cache key includes exchange)
            cache_key = f"{exchange}_instruments"
            if not hasattr(self, '_instruments_cache'):
                self._instruments_cache = {}
            
            if cache_key not in self._instruments_cache:
                self._instruments_cache[cache_key] = kite_client.kite.instruments(exchange)
            
            instruments = self._instruments_cache[cache_key]
            
            # Use the same approach as Straddle10PointswithSL-Limit.py:
            # Find instrument by filtering instruments with segment, name, type, strike, and expiry
            instrument = None
            if expiry:
                instrument = self._find_instrument_by_expiry(segment, strike, option_type, expiry, instruments)
            
            if not instrument:
                # Fallback: try without expiry filtering (use nearest expiry)
                segment_map = {
                    "NIFTY": "NIFTY",
                    "BANKNIFTY": "BANKNIFTY",
                    "SENSEX": "SENSEX"
                }
                base_name = segment_map.get(segment.upper())
                if not base_name:
                    return None
                
                # Filter by base name, option type, and strike
                filtered = [
                    inst for inst in instruments
                    if inst.get('segment') == segment_code and
                    inst.get('name') == base_name and
                    inst.get('instrument_type') == option_type.upper() and
                    inst.get('strike') == float(strike)
                ]
                
                if not filtered:
                    return None
                
                # Use the first match (nearest expiry)
                instrument = filtered[0]
            
            # Get the instrument token
            instrument_token = instrument['instrument_token']
            
            # Store instrument details for debugging
            instrument_details = {
                'instrument_type': instrument.get('instrument_type', option_type.upper()),
                'tradingsymbol': instrument.get('tradingsymbol', ''),
                'exchange': instrument.get('exchange', 'NFO'),
                'instrument_token': instrument_token,
                'strike': instrument.get('strike', strike),
                'expiry': instrument.get('expiry', expiry)
            }
            
            # Use the aligned timestamp for fetching (ensures we get the correct 5-minute candle)
            fetch_timestamp = timestamp_aligned
            
            # Make fetch_timestamp timezone-aware for comparison (same as original timestamp)
            if fetch_timestamp.tzinfo is None:
                try:
                    from pytz import timezone
                    ist = timezone('Asia/Kolkata')
                    fetch_timestamp = ist.localize(fetch_timestamp)
                except ImportError:
                    from datetime import timezone as dt_timezone
                    ist_offset = dt_timezone(timedelta(hours=5, minutes=30))
                    fetch_timestamp = fetch_timestamp.replace(tzinfo=ist_offset)
            
            # Fetch historical data for the specific timestamp
            # Get data for a small window around the timestamp
            from_date = fetch_timestamp - timedelta(minutes=10)
            to_date = fetch_timestamp + timedelta(minutes=10)
            
            # Kite API expects timezone-naive datetimes
            from_date_naive = from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
            to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date
            
            # Determine interval based on timestamp (if it's a 5-minute candle, use 5minute)
            interval = "5minute"  # Default, can be made configurable
            
            try:
                candles = kite_client.kite.historical_data(
                    instrument_token,
                    from_date_naive,
                    to_date_naive,
                    interval,
                    continuous=False,
                    oi=False
                )
                
                if not candles:
                    return None
                
                # Find the candle closest to the timestamp
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
                
                # Use aligned timestamp for finding the closest candle
                df['time_diff'] = abs(df['date'] - fetch_timestamp)
                closest_candle = df.loc[df['time_diff'].idxmin()]
                
                # Use close price as premium
                premium = float(closest_candle['close'])
                
                # Cache the result (premium only for cache, details stored separately)
                self.option_premium_cache[cache_key] = (premium, instrument_details)
                
                # Store instrument details in a separate cache
                if not hasattr(self, 'instrument_details_cache'):
                    self.instrument_details_cache = {}
                self.instrument_details_cache[cache_key] = instrument_details
                
                return (premium, instrument_details)
                
            except Exception as e:
                logger.debug(f"Error fetching option premium from Kite: {e}")
                return None
                
        except Exception as e:
            logger.debug(f"Error in _fetch_option_premium_from_kite: {e}")
            return None
    
    def _estimate_option_premium(self, spot_price: float, strike: int, option_type: str, segment: str, days_to_expiry: int = 0, timestamp: Optional[datetime] = None, expiry: Optional[str] = None) -> Tuple[float, str]:
        """
        Get option premium - tries Kite API first, falls back to estimation
        
        Premium = Intrinsic Value + Time Value
        
        Intrinsic Value:
        - CE: max(0, spot - strike)
        - PE: max(0, strike - spot)
        
        Time Value:
        - Based on segment volatility and time to expiry
        - Decreases as expiry approaches
        
        Args:
            spot_price: Current spot price
            strike: Strike price
            option_type: CE or PE
            segment: Trading segment
            days_to_expiry: Days remaining until expiry (default: 0 for weekly expiry assumption)
            timestamp: Timestamp for historical data (optional)
            expiry: Expiry date in YYYY-MM-DD format (optional)
        
        Returns:
            Tuple of (premium, source) where source is "Kite API" or "Estimated"
        """
        # Try to fetch from Kite API first if timestamp and expiry are provided
        if timestamp is not None and expiry is not None:
            kite_result = self._fetch_option_premium_from_kite(
                strike, option_type, segment, expiry, timestamp
            )
            if kite_result is not None:
                kite_premium, instrument_details = kite_result
                # Store instrument details for later use in trade records
                if not hasattr(self, '_last_instrument_details'):
                    self._last_instrument_details = {}
                # Use a key based on timestamp to distinguish entry vs exit
                detail_key = f"{timestamp.isoformat()}_{strike}_{option_type}"
                self._last_instrument_details[detail_key] = instrument_details
                return (kite_premium, "Kite API")
            # If kite_premium is None, log why (for debugging) - use WARNING for entry/exit, DEBUG for intra-candle
            else:
                # Check if this is an entry/exit call (timestamp and expiry provided) vs intra-candle check
                is_entry_exit = timestamp is not None and expiry is not None
                log_level = logger.warning if is_entry_exit else logger.debug
                
                # Debug logging (only log once per unique combination to avoid spam)
                debug_key = f"{segment}_{strike}_{option_type}_{expiry}_{timestamp}"
                if not hasattr(self, '_kite_fetch_debug_logged'):
                    self._kite_fetch_debug_logged = set()
                if debug_key not in self._kite_fetch_debug_logged:
                    self._kite_fetch_debug_logged.add(debug_key)
                    kite_client = self.data_fetcher.kite_client if hasattr(self.data_fetcher, 'kite_client') else None
                    if not kite_client:
                        log_level(f"Kite API not available: No kite_client in data_fetcher (Segment: {segment}, Strike: {strike}, Type: {option_type}, Expiry: {expiry}, Timestamp: {timestamp})")
                    elif not (self._kite_authenticated if hasattr(self, '_kite_authenticated') and self._kite_authenticated is not None else kite_client.is_authenticated()):
                        log_level(f"Kite API not available: Not authenticated (Segment: {segment}, Strike: {strike}, Type: {option_type}, Expiry: {expiry}, Timestamp: {timestamp})")
                    else:
                        log_level(f"Kite API fetch returned None - falling back to estimation (Segment: {segment}, Strike: {strike}, Type: {option_type}, Expiry: {expiry}, Timestamp: {timestamp})")
        else:
            # Log missing parameters - use WARNING if this is for entry/exit, DEBUG for intra-candle
            is_entry_exit = False  # If timestamp/expiry missing, it's likely not entry/exit
            log_level = logger.debug
            if not hasattr(self, '_kite_missing_params_logged'):
                self._kite_missing_params_logged = set()
            missing_key = f"{segment}_{strike}_{option_type}"
            if missing_key not in self._kite_missing_params_logged:
                self._kite_missing_params_logged.add(missing_key)
                missing_params = []
                if timestamp is None:
                    missing_params.append("timestamp")
                if expiry is None:
                    missing_params.append("expiry")
                log_level(f"Kite API not attempted: Missing {', '.join(missing_params)} (Segment: {segment}, Strike: {strike}, Type: {option_type})")
        
        # Fall back to estimation if Kite data is not available
        # Calculate intrinsic value
        if option_type.upper() == "CE":
            intrinsic_value = max(0.0, spot_price - strike)
        elif option_type.upper() == "PE":
            intrinsic_value = max(0.0, strike - spot_price)
        else:
            intrinsic_value = 0.0
        
        # Calculate time value based on segment and moneyness
        # Base time value percentage (for ATM options with ~5 days to expiry)
        base_time_value_pct = 0.01  # 1% of spot price
        
        # Adjust based on segment volatility
        if segment.upper() == "BANKNIFTY":
            base_time_value_pct = 0.015  # Higher volatility
        elif segment.upper() == "SENSEX":
            base_time_value_pct = 0.008  # Lower volatility
        
        # Adjust time value based on moneyness (ITM/OTM)
        # Moneyness: percentage difference from ATM
        moneyness_pct = abs(spot_price - strike) / spot_price if spot_price > 0 else 0
        
        # Calculate moneyness in points (more accurate for options)
        moneyness_points = abs(spot_price - strike)
        
        # Segment-specific strike intervals
        if segment.upper() == "NIFTY":
            strike_interval = 50
        elif segment.upper() == "BANKNIFTY":
            strike_interval = 100
        elif segment.upper() == "SENSEX":
            strike_interval = 100
        else:
            strike_interval = 50
        
        # Time value is highest for ATM, decreases for ITM/OTM
        # For ATM options (within 1 strike interval), use full time value
        if moneyness_points <= strike_interval:
            time_value_multiplier = 1.0
        elif moneyness_points <= strike_interval * 2:  # 1-2 strikes away
            time_value_multiplier = 0.7
        elif moneyness_points <= strike_interval * 5:  # 2-5 strikes away
            time_value_multiplier = 0.5
        else:  # More than 5 strikes away
            time_value_multiplier = 0.2
        
        # Adjust for time to expiry (assume weekly expiry, ~5 days)
        # If days_to_expiry is 0, assume we're mid-week (3-4 days remaining)
        if days_to_expiry == 0:
            days_to_expiry = 4  # Assume 4 days to expiry for weekly options
        
        # Time value decays as expiry approaches
        # Linear decay: time_value = base * (days_to_expiry / 7)
        # But minimum 20% of base time value even on expiry day
        time_decay_factor = max(0.2, min(1.0, days_to_expiry / 7.0))
        
        # Calculate time value
        time_value = spot_price * base_time_value_pct * time_value_multiplier * time_decay_factor
        
        # Total premium = Intrinsic + Time Value
        premium = intrinsic_value + time_value
        
        # Ensure minimum premium (options rarely trade below certain levels)
        # Minimum is higher for ITM options
        if intrinsic_value > 0:
            min_premium = max(intrinsic_value * 1.1, 20.0)  # At least 10% above intrinsic or 20
        else:
            min_premium = 10.0 if segment.upper() in ["NIFTY", "BANKNIFTY"] else 20.0
        
        premium = max(premium, min_premium)
        
        return (round(premium, 2), "Estimated")
    
    def _calculate_days_to_expiry(self, current_date: datetime, expiry_date_str: Optional[str] = None) -> int:
        """
        Calculate days to expiry for options
        
        Args:
            current_date: Current date/time
            expiry_date_str: Expiry date in YYYY-MM-DD format (optional)
        
        Returns:
            Days to expiry (0 if expiry passed or not specified, defaults to 4 for weekly)
        """
        if expiry_date_str:
            try:
                expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d")
                days_to_expiry = (expiry_date.date() - current_date.date()).days
                return max(0, days_to_expiry)
            except:
                pass
        
        # Default: assume weekly expiry, calculate based on Thursday (typical expiry)
        # For simplicity, assume 4 days remaining for weekly options
        return 4
    
    def run_backtest(
        self,
        segment: str,
        from_date: datetime,
        to_date: datetime,
        time_interval: str = "5minute",
        rsi_period: int = 9,
        price_strength_ema: int = 3,
        volume_strength_wma: int = 21,  # TradingView uses WMA(21)
        initial_capital: float = 100000.0,
        expiry: Optional[str] = None,
        stop_loss: Optional[float] = None,
        trade_regime: str = "Buy"  # "Buy" or "Sell"
    ) -> BacktestResult:
        """
        Run backtest on historical data
        
        Args:
            segment: Trading segment (NIFTY, SENSEX, BANKNIFTY)
            from_date: Start date
            to_date: End date
            time_interval: Time interval for candles (5minute, 15minute, 30minute, 1hour)
            rsi_period: RSI period
            price_strength_ema: EMA period for Price Strength calculation (default: 3)
            volume_strength_wma: WMA period for Volume Strength calculation (default: 18)
            initial_capital: Initial capital
            expiry: Option expiry date (optional)
            stop_loss: Stop loss in points (optional, defaults to 50)
            trade_regime: Trade regime - "Buy" (default) or "Sell"
        
        Returns:
            BacktestResult object
        """
        # Validate trade_regime
        trade_regime = trade_regime.capitalize()  # Normalize to "Buy" or "Sell"
        if trade_regime not in ["Buy", "Sell"]:
            logger.warning(f"Invalid trade_regime '{trade_regime}', defaulting to 'Buy'")
            trade_regime = "Buy"
        
        logger.info(f"Starting backtest: {segment} from {from_date.date()} to {to_date.date()} with interval {time_interval}, Trade Regime: {trade_regime}")
        
        # Store expiry and trade_regime for premium calculations
        self.expiry = expiry
        self.trade_regime = trade_regime
        
        result = BacktestResult()
        result.start_date = from_date
        result.end_date = to_date
        result.initial_capital = initial_capital
        
        # Initialize strategy with configurable stop loss and indicator parameters
        segment_enum = Segment[segment.upper()]
        # Use provided stop_loss or default to 50
        stop_loss_value = stop_loss if stop_loss is not None else 50.0
        strategy = RSIStrategy(
            segment_enum, 
            rsi_period=rsi_period, 
            stop_loss=stop_loss_value, 
            trailing_stop=stop_loss_value,
            price_strength_ema=price_strength_ema,
            volume_strength_wma=volume_strength_wma,
            trade_regime=trade_regime
        )
        agent = RSITradingAgent(strategy)
        
        # Calculate how many candles we need to bootstrap indicators
        # WMA(21) is the limiting factor - needs 21 RSI values
        # RSI(9) needs 9 candles, so WMA(21) needs 21 RSI values = 9 + 20 = 29 candles total
        candles_needed_for_bootstrap = max(29, strategy.rsi_period + strategy.volume_strength_wma - 1)
        
        # Calculate how many days of historical data we need to bootstrap
        # For 5-minute candles: 29 candles = 145 minutes = ~2.4 hours
        # We'll fetch 2-3 days of data to ensure we have enough bootstrap data
        # This allows trading to start from market open time (from config) on the test day
        bootstrap_days = 3  # Fetch 3 days of data to ensure enough bootstrap candles
        
        # Fetch historical data including previous days for bootstrapping
        bootstrap_from_date = from_date - timedelta(days=bootstrap_days)
        logger.info(f"Fetching data from {bootstrap_from_date.date()} to {to_date.date()} (including {bootstrap_days} days before test period for indicator bootstrapping)")
        
        df = self.data_fetcher.fetch_segment_data(
            segment=segment,
            from_date=bootstrap_from_date,  # Start earlier to get bootstrap data
            to_date=to_date,
            interval=time_interval,
            expiry=expiry
        )
        
        if df.empty:
            logger.error("No historical data fetched")
            return result
        
        logger.info(f"Fetched {len(df)} candles (including bootstrap data)")
        
        # Find the index where the actual test period starts (from_date)
        # We'll use all data for indicators, but only trade during the test period
        test_period_start_idx = None
        if from_date.tzinfo:
            from_date_naive = from_date.replace(tzinfo=None)
        else:
            from_date_naive = from_date
        
        for idx in range(len(df)):
            candle_time = df.index[idx]
            if isinstance(candle_time, pd.Timestamp):
                if candle_time.tzinfo:
                    candle_time = candle_time.tz_localize(None)
            if candle_time >= from_date_naive:
                test_period_start_idx = idx
                break
        
        if test_period_start_idx is None:
            # If we can't find the exact start, use the calculated bootstrap index
            test_period_start_idx = candles_needed_for_bootstrap
            logger.warning(f"Could not find exact test period start, using index {test_period_start_idx}")
        else:
            logger.info(f"Test period starts at index {test_period_start_idx} (timestamp: {df.index[test_period_start_idx]})")
        
        # Start trading from the test period start, but ensure we have enough data for indicators
        # If test period starts before we have enough bootstrap data, wait until we have enough
        start_idx = max(test_period_start_idx, candles_needed_for_bootstrap)
        
        if start_idx > test_period_start_idx:
            logger.warning(
                f"Test period starts at index {test_period_start_idx}, but need {candles_needed_for_bootstrap} candles for indicators. "
                f"Starting from index {start_idx} (timestamp: {df.index[start_idx]})"
            )
        else:
            logger.info(f"Starting backtest from index {start_idx} (test period start: {test_period_start_idx}, timestamp: {df.index[start_idx]})")
        
        # Track equity curve
        equity_curve = [initial_capital]
        current_capital = initial_capital
        peak_capital = initial_capital
        
        # Debug: Count signals
        signal_count = 0
        pe_signals = 0
        ce_signals = 0
        no_candle_match = 0
        
        # Process each candle
        for idx in range(start_idx, len(df)):
            candle = df.iloc[idx]
            timestamp = candle.name if hasattr(candle, 'name') else df.index[idx]
            current_price = candle['close']
            
            # Track if we just entered a trade in this iteration (to skip exit checks on entry candle)
            just_entered = False
            
            # Check entry signals first if not in position
            if agent.current_position is None:
                # Check if we're in re-entry mode after SL hit
                allow_reentry = agent.waiting_for_reentry
                reentry_candle_type = agent.reentry_candle_type
                
                signal, option_type, reason, signal_details = strategy.generate_signal(
                    df, 
                    idx, 
                    allow_reentry=allow_reentry,
                    reentry_candle_type=reentry_candle_type
                )
                
                if signal in [TradeSignal.BUY_CE, TradeSignal.BUY_PE]:
                    # Store entry timestamp before entering
                    entry_timestamp = timestamp
                    
                    # Calculate strike and entry premium
                    strike = self._calculate_atm_strike(current_price, segment)
                    days_to_expiry_entry = self._calculate_days_to_expiry(timestamp, self.expiry)
                    entry_premium, entry_premium_source = self._estimate_option_premium(
                        current_price, 
                        strike, 
                        option_type.value, 
                        segment, 
                        days_to_expiry_entry,
                        timestamp=timestamp,
                        expiry=self.expiry
                    )
                    
                    # Extract Price Strength and Volume Strength from signal_details
                    entry_price_strength = signal_details.get('price_strength')
                    entry_volume_strength = signal_details.get('volume_strength')
                    
                    # Enter trade
                    entry_result = agent.enter_trade(
                        signal=signal,
                        option_type=option_type,
                        price=current_price,
                        timestamp=entry_timestamp,
                        reason=reason,
                        price_strength=entry_price_strength,
                        volume_strength=entry_volume_strength
                    )
                    
                    if entry_result['success']:
                        # Store premium and strike in agent
                        agent.entry_strike = strike
                        agent.entry_spot = current_price
                        agent.entry_premium = entry_premium
                        agent.entry_premium_source = entry_premium_source  # Store premium source
                        
                        # Store entry instrument details if available
                        entry_key = f"{entry_timestamp.isoformat()}_{strike}_{option_type.value}"
                        if hasattr(self, '_last_instrument_details') and entry_key in self._last_instrument_details:
                            agent.entry_instrument_details = self._last_instrument_details[entry_key]
                        else:
                            agent.entry_instrument_details = None
                        
                        just_entered = True
                        trade_action = "Bought" if self.trade_regime == "Buy" else "Sold"
                        logger.info(
                            f"Entry ({self.trade_regime}): {trade_action} {option_type.value} @ Premium ₹{entry_premium:.2f} ({entry_premium_source}), "
                            f"Strike: {strike}, Spot: ₹{current_price:.2f}, Time: {entry_timestamp}"
                        )
            
            # Check exit conditions if in position (but skip on the entry candle)
            if agent.current_position is not None and not just_entered:
                # Initialize exit tracking variables
                should_exit = False
                exit_reason = None
                stop_loss_hit = False
                trailing_stop_hit = False
                exit_premium = None
                
                # First, check if it's 3:15 PM - force square off all positions on same day
                # Get hour and minute from timestamp
                if isinstance(timestamp, pd.Timestamp):
                    hour = timestamp.hour
                    minute = timestamp.minute
                    current_date = timestamp.date()
                elif isinstance(timestamp, datetime):
                    hour = timestamp.hour
                    minute = timestamp.minute
                    current_date = timestamp.date()
                else:
                    # Try to parse as datetime
                    try:
                        ts = pd.Timestamp(timestamp)
                        hour = ts.hour
                        minute = ts.minute
                        current_date = ts.date()
                    except:
                        hour = 0
                        minute = 0
                        current_date = None
                
                # Check if it's 3:15 PM (15:15) - intraday square off
                if hour == 15 and minute == 15:
                    # Get entry date
                    entry_date = None
                    if hasattr(agent, 'entry_time') and agent.entry_time is not None:
                        if isinstance(agent.entry_time, pd.Timestamp):
                            entry_date = agent.entry_time.date()
                        elif isinstance(agent.entry_time, datetime):
                            entry_date = agent.entry_time.date()
                        else:
                            try:
                                entry_date = pd.Timestamp(agent.entry_time).date()
                            except:
                                pass
                    
                    # If entry was on the same day, force square off
                    if entry_date is not None and current_date is not None and entry_date == current_date:
                        logger.info(f"3:15 PM square off: Forcing exit of position entered on {entry_date}")
                        # Store entry price, lots, strike, premium, and strength values before exit
                        entry_price_before_exit = agent.entry_price
                        lots_before_exit = agent.lots
                        entry_strike_before_exit = agent.entry_strike
                        entry_premium_before_exit = agent.entry_premium
                        entry_price_strength_val = agent.entry_price_strength if hasattr(agent, 'entry_price_strength') else None
                        entry_volume_strength_val = agent.entry_volume_strength if hasattr(agent, 'entry_volume_strength') else None
                        
                        # Force exit at current price
                        exit_result = agent.exit_trade(
                            exit_price=current_price,
                            exit_time=timestamp,
                            reason="3:15 PM - Intraday square off"
                        )
                        
                        if exit_result['success']:
                            # Get entry candle data for verification
                            entry_candle_idx = None
                            for i in range(len(df)):
                                if df.index[i] == exit_result['entry_time']:
                                    entry_candle_idx = i
                                    break
                            
                            entry_candle_data = {}
                            if entry_candle_idx is not None and entry_candle_idx < len(df):
                                entry_candle = df.iloc[entry_candle_idx]
                                entry_candle_data = {
                                    "entry_candle_open": float(entry_candle.get('open', exit_result['entry_price'])),
                                    "entry_candle_high": float(entry_candle.get('high', exit_result['entry_price'])),
                                    "entry_candle_low": float(entry_candle.get('low', exit_result['entry_price'])),
                                    "entry_candle_close": float(entry_candle.get('close', exit_result['entry_price']))
                                }
                            
                            # Calculate exit premium based on exit spot price
                            exit_strike = entry_strike_before_exit if entry_strike_before_exit is not None else self._calculate_atm_strike(current_price, segment)
                            # Calculate days to expiry for exit (time has passed since entry)
                            days_to_expiry_exit = self._calculate_days_to_expiry(timestamp, self.expiry)
                            # Fetch ACTUAL exit premium from Kite API (not estimated)
                            exit_premium, exit_premium_source = self._estimate_option_premium(
                                current_price, 
                                exit_strike, 
                                exit_result['option_type'], 
                                segment, 
                                days_to_expiry_exit, 
                                timestamp=timestamp,  # Use actual timestamp to fetch from Kite API
                                expiry=self.expiry
                            )
                            
                            # Calculate P&L based on premium difference (not spot difference)
                            entry_premium_val = entry_premium_before_exit if entry_premium_before_exit is not None else 0.0
                            entry_premium_source_val = agent.entry_premium_source if hasattr(agent, 'entry_premium_source') else "Unknown"
                            exit_premium_val = exit_premium
                            # P&L calculation based on trade regime
                            # Buy: Profit when exit_premium > entry_premium → (exit - entry) * lots
                            # Sell: Profit when exit_premium < entry_premium → (entry - exit) * lots
                            if self.trade_regime == "Buy":
                                premium_pnl = (exit_premium_val - entry_premium_val) * exit_result['lots']
                                premium_return_pct = ((exit_premium_val - entry_premium_val) / entry_premium_val * 100) if entry_premium_val > 0 else 0.0
                            else:  # Sell
                                premium_pnl = (entry_premium_val - exit_premium_val) * exit_result['lots']
                                premium_return_pct = ((entry_premium_val - exit_premium_val) / entry_premium_val * 100) if entry_premium_val > 0 else 0.0
                            
                            # Update capital based on premium P&L
                            current_capital += premium_pnl
                            if entry_price_before_exit is not None and lots_before_exit > 0:
                                current_capital += (entry_price_before_exit * lots_before_exit)
                            equity_curve.append(current_capital)
                            
                            # Update peak for drawdown calculation
                            if current_capital > peak_capital:
                                peak_capital = current_capital
                            
                            # Calculate Stop Loss level based on entry premium (not spot price)
                            # For both CE and PE: SL Level = Entry Premium - Stop Loss Points
                            option_type = exit_result['option_type']
                            stop_loss_points = agent.strategy.stop_loss
                            # Use entry premium for stop loss level calculation
                            # Calculate stop loss level based on trade regime
                            if self.trade_regime == "Buy":
                                stop_loss_level = entry_premium_val - stop_loss_points
                            else:  # Sell
                                stop_loss_level = entry_premium_val + stop_loss_points
                            
                            # Get instrument details if available
                            entry_instrument_tradingsymbol = "N/A"
                            exit_instrument_tradingsymbol = "N/A"
                            entry_instrument_info = "N/A"
                            exit_instrument_info = "N/A"
                            remarks = "N/A"
                            
                            # Get entry instrument from agent if stored
                            if hasattr(agent, 'entry_instrument_details') and agent.entry_instrument_details:
                                entry_details = agent.entry_instrument_details
                                entry_instrument_tradingsymbol = entry_details.get('tradingsymbol', 'N/A')
                                entry_instrument_info = f"{entry_instrument_tradingsymbol} ({entry_details.get('instrument_type', 'N/A')})"
                            
                            # Format strike field using tradingsymbol format (e.g., BANKNIFTY25DEC59900PE)
                            strike_value = entry_strike_before_exit if entry_strike_before_exit is not None else exit_strike
                            if entry_instrument_tradingsymbol != "N/A":
                                # Use the actual tradingsymbol from Kite API
                                full_strike = entry_instrument_tradingsymbol
                            elif self.expiry:
                                # Build tradingsymbol using the format logic
                                from src.utils.premium_fetcher import build_tradingsymbol
                                expiry_config = self._load_expiry_config()
                                full_strike = build_tradingsymbol(segment, strike_value, option_type, self.expiry, expiry_config) or f"{option_type}{strike_value} {self.expiry}"
                            else:
                                # Fallback to old format if no expiry
                                full_strike = f"{option_type}{strike_value} N/A"
                            
                            # Get exit instrument from cache
                            if hasattr(self, '_last_instrument_details'):
                                exit_time_str = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)
                                exit_key = f"{exit_time_str}_{exit_strike}_{exit_result['option_type']}"
                                if exit_key in self._last_instrument_details:
                                    exit_details = self._last_instrument_details[exit_key]
                                    exit_instrument_tradingsymbol = exit_details.get('tradingsymbol', 'N/A')
                                    exit_instrument_info = f"{exit_instrument_tradingsymbol} ({exit_details.get('instrument_type', 'N/A')})"
                            
                            # Build remarks with tradingsymbols used
                            remarks_parts = []
                            if entry_instrument_tradingsymbol != "N/A":
                                remarks_parts.append(f"Entry: {entry_instrument_tradingsymbol}")
                            if exit_instrument_tradingsymbol != "N/A":
                                remarks_parts.append(f"Exit: {exit_instrument_tradingsymbol}")
                            if remarks_parts:
                                remarks = " | ".join(remarks_parts)
                            
                            # Record trade (completed trade with both entry and exit)
                            trade_record = {
                                "entry_time": exit_result['entry_time'].isoformat() if isinstance(exit_result['entry_time'], datetime) else str(exit_result['entry_time']),
                                "exit_time": timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),  # Use current candle timestamp
                                "option_type": exit_result['option_type'],  # CE or PE only
                                "strike": full_strike,  # Full strike: OptionType+Strike+Expiry
                                "entry_premium": entry_premium_val,  # Entry option premium
                                "exit_premium": exit_premium_val,  # Exit option premium
                                "premium_source": f"{entry_premium_source_val} / {exit_premium_source}",  # Source of premiums
                                "entry_spot": agent.entry_spot if hasattr(agent, 'entry_spot') and agent.entry_spot is not None else current_price,  # Spot price at entry
                                "exit_spot": current_price,  # Spot price at exit
                                "remarks": remarks,  # Remarks showing tradingsymbols used
                                "lots": exit_result['lots'],
                                "pnl": premium_pnl,  # P&L based on premium
                                "return_pct": premium_return_pct,  # Return % based on premium
                                "reason": exit_result['reason'],
                                "stop_loss_points": stop_loss_points,  # Stop loss in points
                                "stop_loss_level": stop_loss_level,  # Stop loss price level
                                "trade_regime": self.trade_regime,  # Trade regime: Buy or Sell
                                "entry_price_strength": entry_price_strength_val,  # Price Strength at entry
                                "entry_volume_strength": entry_volume_strength_val,  # Volume Strength at entry
                                **entry_candle_data
                            }
                            
                            result.trades.append(trade_record)
                            result.total_trades += 1
                            
                            if premium_pnl > 0:
                                result.winning_trades += 1
                                result.total_profit += premium_pnl
                            else:
                                result.losing_trades += 1
                                result.total_loss += abs(premium_pnl)
                            
                            # Calculate drawdown
                            drawdown = ((peak_capital - current_capital) / peak_capital) * 100
                            if drawdown > result.max_drawdown:
                                result.max_drawdown = drawdown
                            
                            # Update max profit
                            if premium_pnl > result.max_profit:
                                result.max_profit = premium_pnl
                            
                            # Skip to next candle (position is closed)
                            continue
                
                # Regular exit condition checks (stop loss, trailing stop, etc.)
                # All checks are based on OPTION PREMIUM, not spot price
                
                # Calculate current option premium
                # Use estimation only for intra-candle checks (performance optimization)
                # Kite API is only used for actual entry/exit premiums
                current_strike = agent.entry_strike if agent.entry_strike is not None else self._calculate_atm_strike(current_price, segment)
                days_to_expiry_current = self._calculate_days_to_expiry(timestamp, self.expiry)
                current_premium, current_premium_source = self._estimate_option_premium(
                    current_price, 
                    current_strike, 
                    agent.current_position.value, 
                    segment, 
                    days_to_expiry_current,
                    timestamp=None,  # Skip Kite API for intra-candle checks (performance)
                    expiry=None
                )
                
                # Also calculate premium at candle high/low for accurate stop loss checks
                # Use estimation only (skip Kite API) for these intra-candle checks to improve performance
                candle_low = candle.get('low', current_price)
                candle_high = candle.get('high', current_price)
                # For intra-candle checks, use estimation directly (no Kite API call for performance)
                premium_at_low, _ = self._estimate_option_premium(
                    candle_low, 
                    current_strike, 
                    agent.current_position.value, 
                    segment, 
                    days_to_expiry_current,
                    timestamp=None,  # Skip Kite API for intra-candle checks
                    expiry=None
                ) if candle_low != current_price else (current_premium, current_premium_source)
                premium_at_high, _ = self._estimate_option_premium(
                    candle_high, 
                    current_strike, 
                    agent.current_position.value, 
                    segment, 
                    days_to_expiry_current,
                    timestamp=None,  # Skip Kite API for intra-candle checks
                    expiry=None
                ) if candle_high != current_price else (current_premium, current_premium_source)
                
                exit_premium = current_premium  # Default to current premium
                exit_premium_source = current_premium_source  # Default to current premium source
                stop_loss_hit = False
                trailing_stop_hit = False
                
                # Calculate stop loss level based on option premium (not spot price)
                entry_premium = agent.entry_premium if agent.entry_premium is not None else 0.0
                
                # Update trailing stop FIRST (before checking if it was hit)
                # Trailing stop logic: Every 40 points premium increase → trail SL by 20 points (2:1 ratio)
                # Example: Entry Premium 897, SL = 897 - 50 = 847
                #          Premium 937 (897+40) → SL = 847 + 20 = 867
                #          Premium 977 (897+80) → SL = 847 + 40 = 887
                if entry_premium > 0:
                    # Calculate initial SL based on trade regime
                    # Buy: SL = entry_premium - stop_loss (premium drops below entry - SL)
                    # Sell: SL = entry_premium + stop_loss (premium rises above entry + SL)
                    if self.trade_regime == "Buy":
                        initial_sl_premium = entry_premium - agent.strategy.stop_loss
                    else:  # Sell
                        initial_sl_premium = entry_premium + agent.strategy.stop_loss
                    
                    # Calculate premium change from entry
                    premium_change = current_premium - entry_premium
                    
                    if self.trade_regime == "Buy":
                        # For Buy: Profit when premium increases, trail SL up when premium increases
                        if premium_change > 0:
                            # For every 40 points premium increase, move SL by 20 points (2:1 ratio)
                            increments = int(premium_change / 40)
                            trailing_sl_adjustment = increments * 20
                            new_trailing_stop_premium = initial_sl_premium + trailing_sl_adjustment
                        else:
                            # If premium hasn't increased, use initial SL
                            new_trailing_stop_premium = initial_sl_premium
                        
                        # Only move trailing stop up (can't go backward) for Buy
                        if agent.trailing_stop_price is None or new_trailing_stop_premium > agent.trailing_stop_price:
                            agent.trailing_stop_price = new_trailing_stop_premium
                            logger.debug(
                                f"Trailing SL updated (Buy regime, Premium-based): Entry Premium=₹{entry_premium:.2f}, "
                                f"Current Premium=₹{current_premium:.2f}, Premium Change=₹{premium_change:.2f}, "
                                f"New Trailing SL=₹{new_trailing_stop_premium:.2f} (Ratio: 40pts premium → 20pts SL)"
                            )
                    else:  # Sell
                        # For Sell: Profit when premium decreases, trail SL down when premium decreases
                        if premium_change < 0:
                            # For every 40 points premium decrease, move SL down by 20 points (2:1 ratio)
                            # premium_change is negative, so we use abs
                            increments = int(abs(premium_change) / 40)
                            trailing_sl_adjustment = increments * 20
                            new_trailing_stop_premium = initial_sl_premium - trailing_sl_adjustment
                        else:
                            # If premium hasn't decreased, use initial SL
                            new_trailing_stop_premium = initial_sl_premium
                        
                        # Only move trailing stop down (can't go backward) for Sell
                        if agent.trailing_stop_price is None or new_trailing_stop_premium < agent.trailing_stop_price:
                            agent.trailing_stop_price = new_trailing_stop_premium
                            logger.debug(
                                f"Trailing SL updated (Sell regime, Premium-based): Entry Premium=₹{entry_premium:.2f}, "
                                f"Current Premium=₹{current_premium:.2f}, Premium Change=₹{premium_change:.2f}, "
                                f"New Trailing SL=₹{new_trailing_stop_premium:.2f} (Ratio: 40pts premium decrease → 20pts SL down)"
                            )
                
                if agent.current_position == OptionType.CE:
                    # CE: Profit when premium goes UP, SL when premium goes DOWN (for Buy)
                    # For Sell: Profit when premium goes DOWN, SL when premium goes UP
                    # Calculate SL based on trade regime
                    if self.trade_regime == "Buy":
                        stop_loss_level_premium = entry_premium - agent.strategy.stop_loss
                        # For Buy: SL hit when premium drops below stop_loss_level
                        sl_hit_condition = premium_at_low <= stop_loss_level_premium
                        # Trailing stop check: premium at low hits trailing stop
                        trailing_sl_check = lambda ts: premium_at_low <= ts
                    else:  # Sell
                        stop_loss_level_premium = entry_premium + agent.strategy.stop_loss
                        # For Sell: SL hit when premium rises above stop_loss_level
                        sl_hit_condition = premium_at_high >= stop_loss_level_premium
                        # Trailing stop check: premium at high hits trailing stop
                        trailing_sl_check = lambda ts: premium_at_high >= ts
                    
                    if sl_hit_condition:
                        # Potential stop loss detected using estimates - VERIFY with Kite API
                        # For Sell: Check if premium at high (worst case) actually reached SL level
                        # For Buy: Check if premium at low (worst case) actually reached SL level
                        verify_premium_spot = candle_high if self.trade_regime == "Sell" else candle_low
                        verified_premium, verified_source = self._estimate_option_premium(
                            verify_premium_spot,
                            current_strike,
                            agent.current_position.value,
                            segment,
                            days_to_expiry_current,
                            timestamp=timestamp,  # Use actual timestamp to fetch from Kite API
                            expiry=self.expiry
                        )
                        # Only mark SL as hit if verified premium confirms it
                        if self.trade_regime == "Sell":
                            # Sell: SL hit when verified premium >= SL level
                            stop_loss_hit = verified_premium >= stop_loss_level_premium
                        else:  # Buy
                            # Buy: SL hit when verified premium <= SL level
                            stop_loss_hit = verified_premium <= stop_loss_level_premium
                        
                        if stop_loss_hit:
                            logger.info(
                                f"CE Stop Loss VERIFIED ({self.trade_regime} regime, Premium-based): Entry Premium=₹{entry_premium:.2f}, SL Level=₹{stop_loss_level_premium:.2f}, "
                                f"Verified Premium=₹{verified_premium:.2f} (Source: {verified_source}), "
                                f"Estimated Premium at Low=₹{premium_at_low:.2f}, Estimated Premium at High=₹{premium_at_high:.2f}"
                            )
                        else:
                            logger.debug(
                                f"CE Stop Loss NOT confirmed ({self.trade_regime} regime): Entry Premium=₹{entry_premium:.2f}, SL Level=₹{stop_loss_level_premium:.2f}, "
                                f"Verified Premium=₹{verified_premium:.2f} (Source: {verified_source}) did not reach SL level. "
                                f"Estimated Premium at Low=₹{premium_at_low:.2f}, Estimated Premium at High=₹{premium_at_high:.2f}"
                            )
                    else:
                        # Check trailing stop for CE (based on premium)
                        # Trailing stop is updated above, now check if it was hit
                        if agent.trailing_stop_price is not None:
                            trailing_stop_premium = agent.trailing_stop_price
                            if trailing_sl_check(trailing_stop_premium):
                                # Trailing stop was hit during the candle
                                # We'll fetch actual premium from Kite API at exit, not use calculated level
                                trailing_stop_hit = True
                                logger.debug(
                                    f"CE Trailing Stop hit ({self.trade_regime} regime, Premium-based): Entry Premium=₹{entry_premium:.2f}, "
                                    f"Trailing SL Premium=₹{trailing_stop_premium:.2f}, "
                                    f"Current Premium=₹{current_premium:.2f}, Premium at Low=₹{premium_at_low:.2f}, Premium at High=₹{premium_at_high:.2f}"
                                )
                
                elif agent.current_position == OptionType.PE:
                    # PE: Profit when premium goes UP (spot goes DOWN), SL when premium goes DOWN (spot goes UP) for Buy
                    # For Sell: Profit when premium goes DOWN (spot goes UP), SL when premium goes UP (spot goes DOWN)
                    # For PE: premium_at_low = premium when spot is at candle LOW → premium is HIGH (good for PE Buy, bad for PE Sell)
                    #         premium_at_high = premium when spot is at candle HIGH → premium is LOW (bad for PE Buy, good for PE Sell)
                    # Calculate SL based on trade regime
                    if self.trade_regime == "Buy":
                        stop_loss_level_premium = entry_premium - agent.strategy.stop_loss
                        # For Buy: SL hit when premium at high (worst case, when spot is high, premium is low) hits stop loss level
                        sl_hit_condition = premium_at_high <= stop_loss_level_premium
                        # Trailing stop check: premium at high hits trailing stop
                        trailing_sl_check = lambda ts: premium_at_high <= ts
                    else:  # Sell
                        stop_loss_level_premium = entry_premium + agent.strategy.stop_loss
                        # For Sell: SL hit when premium at low (worst case, when spot is low, premium is high) hits stop loss level
                        sl_hit_condition = premium_at_low >= stop_loss_level_premium
                        # Trailing stop check: premium at low hits trailing stop
                        trailing_sl_check = lambda ts: premium_at_low >= ts
                    
                    if sl_hit_condition:
                        # Potential stop loss detected using estimates - VERIFY with Kite API
                        # For Sell: Check if premium at low (worst case, when spot is low, premium is high) actually reached SL level
                        # For Buy: Check if premium at high (worst case, when spot is high, premium is low) actually reached SL level
                        verify_premium_spot = candle_low if self.trade_regime == "Sell" else candle_high
                        verified_premium, verified_source = self._estimate_option_premium(
                            verify_premium_spot,
                            current_strike,
                            agent.current_position.value,
                            segment,
                            days_to_expiry_current,
                            timestamp=timestamp,  # Use actual timestamp to fetch from Kite API
                            expiry=self.expiry
                        )
                        # Only mark SL as hit if verified premium confirms it
                        if self.trade_regime == "Sell":
                            # Sell: SL hit when verified premium >= SL level
                            stop_loss_hit = verified_premium >= stop_loss_level_premium
                        else:  # Buy
                            # Buy: SL hit when verified premium <= SL level
                            stop_loss_hit = verified_premium <= stop_loss_level_premium
                        
                        if stop_loss_hit:
                            logger.info(
                                f"PE Stop Loss VERIFIED ({self.trade_regime} regime, Premium-based): Entry Premium=₹{entry_premium:.2f}, SL Level=₹{stop_loss_level_premium:.2f}, "
                                f"Verified Premium=₹{verified_premium:.2f} (Source: {verified_source}), "
                                f"Estimated Premium at High (spot high, premium low)=₹{premium_at_high:.2f}, Estimated Premium at Low (spot low, premium high)=₹{premium_at_low:.2f}"
                            )
                        else:
                            logger.debug(
                                f"PE Stop Loss NOT confirmed ({self.trade_regime} regime): Entry Premium=₹{entry_premium:.2f}, SL Level=₹{stop_loss_level_premium:.2f}, "
                                f"Verified Premium=₹{verified_premium:.2f} (Source: {verified_source}) did not reach SL level. "
                                f"Estimated Premium at High (spot high, premium low)=₹{premium_at_high:.2f}, Estimated Premium at Low (spot low, premium high)=₹{premium_at_low:.2f}"
                            )
                    else:
                        # Check trailing stop for PE (based on premium)
                        # Trailing stop is updated above, now check if it was hit
                        if agent.trailing_stop_price is not None:
                            trailing_stop_premium = agent.trailing_stop_price
                            if trailing_sl_check(trailing_stop_premium):
                                # Trailing stop was hit during the candle
                                # We'll fetch actual premium from Kite API at exit, not use calculated level
                                trailing_stop_hit = True
                                logger.debug(
                                    f"PE Trailing Stop hit ({self.trade_regime} regime, Premium-based): Entry Premium=₹{entry_premium:.2f}, "
                                    f"Trailing SL Premium=₹{trailing_stop_premium:.2f}, "
                                    f"Current Premium=₹{current_premium:.2f}, Premium at High (spot high, premium low)=₹{premium_at_high:.2f}, Premium at Low (spot low, premium high)=₹{premium_at_low:.2f}"
                                )
                
                # All exit conditions are now handled above (stop loss and trailing stop based on premium)
                # We don't call agent.check_exit_conditions because it uses spot price logic and would interfere
                # with our premium-based trailing stop logic
                should_exit = stop_loss_hit or trailing_stop_hit
                
                # If no exit condition is met, continue to next candle (position stays open)
                # The trailing stop will be updated on the next candle if premium increases
                
                # Initialize exit_premium and exit_strike to None (will be set based on exit reason)
                exit_premium = None
                exit_premium_source = None
                exit_strike = None
                
                # If stop loss or trailing stop was hit, override exit reason with premium-based message
                if stop_loss_hit:
                    # When stop loss is hit, use the stop loss level as exit premium (not fetch from API)
                    # This ensures loss is exactly equal to stop loss points
                    # Calculate SL level based on trade regime
                    if self.trade_regime == "Buy":
                        # Buy: SL hit when premium drops → exit_premium = entry_premium - stop_loss
                        stop_loss_level_premium = entry_premium - agent.strategy.stop_loss
                        premium_change = entry_premium - stop_loss_level_premium  # Positive change (drop)
                        loss = premium_change * agent.lots
                        exit_reason = (
                            f"Stop Loss hit (Premium-based) - Loss: ₹{loss:.2f}, "
                            f"Entry Premium: ₹{entry_premium:.2f}, Exit Premium (SL Level): ₹{stop_loss_level_premium:.2f}, "
                            f"Premium Drop: ₹{premium_change:.2f} points (SL: {agent.strategy.stop_loss} points)"
                        )
                    else:  # Sell
                        # Sell: SL hit when premium rises → exit_premium = entry_premium + stop_loss
                        stop_loss_level_premium = entry_premium + agent.strategy.stop_loss
                        premium_change = stop_loss_level_premium - entry_premium  # Positive change (rise)
                        loss = premium_change * agent.lots
                        exit_reason = (
                            f"Stop Loss hit (Premium-based) - Loss: ₹{loss:.2f}, "
                            f"Entry Premium: ₹{entry_premium:.2f}, Exit Premium (SL Level): ₹{stop_loss_level_premium:.2f}, "
                            f"Premium Rise: ₹{premium_change:.2f} points (SL: {agent.strategy.stop_loss} points)"
                        )
                    exit_premium = stop_loss_level_premium  # Use SL level, not fetched premium
                    should_exit = True
                    exit_premium_source = "Stop Loss Level"  # Mark that we used SL level
                elif trailing_stop_hit:
                    # For trailing stop, use the trailing stop level as exit premium (similar to regular SL)
                    # This ensures we exit at the trailing stop level, not at current market price
                    trailing_stop_level_premium = agent.trailing_stop_price if agent.trailing_stop_price is not None else current_premium
                    exit_premium = trailing_stop_level_premium  # Use trailing stop level as exit premium
                    exit_premium_source = "Trailing Stop Level"  # Mark that we used trailing stop level
                    
                    # Calculate P&L based on trailing stop level
                    if self.trade_regime == "Buy":
                        # Buy: Profit when exit_premium > entry_premium
                        premium_change = exit_premium - entry_premium
                        pnl = premium_change * agent.lots
                    else:  # Sell
                        # Sell: Profit when exit_premium < entry_premium
                        premium_change = entry_premium - exit_premium
                        pnl = premium_change * agent.lots
                    
                    exit_reason = (
                        f"Trailing Stop Loss hit - "
                        f"Entry Premium: ₹{entry_premium:.2f}, Exit Premium (Trailing SL Level): ₹{exit_premium:.2f}, "
                        f"Current Premium: ₹{current_premium:.2f}, P&L: ₹{pnl:.2f}"
                    )
                    should_exit = True
                
                # Calculate exit spot price from exit premium (for capital calculations)
                # This is approximate - we use the current spot price as proxy
                exit_spot = current_price
                
                if should_exit:
                    # Store entry price, lots, strike, premium, and strength values before exit (they get reset in exit_trade)
                    entry_price_before_exit = agent.entry_price
                    lots_before_exit = agent.lots
                    entry_strike_before_exit = agent.entry_strike
                    entry_premium_before_exit = agent.entry_premium
                    entry_price_strength_val = agent.entry_price_strength if hasattr(agent, 'entry_price_strength') else None
                    entry_volume_strength_val = agent.entry_volume_strength if hasattr(agent, 'entry_volume_strength') else None
                    
                    # Calculate exit_strike first (needed for all exit scenarios)
                    exit_strike = entry_strike_before_exit if entry_strike_before_exit is not None else self._calculate_atm_strike(current_price, segment)
                    
                    # Fetch ACTUAL exit premium from Kite API (not estimated)
                    # For stop loss: we use SL level to ensure exact loss
                    # For trailing stop: fetch actual premium from Kite API at exit time
                    # For other exits (3:15 PM, etc.): fetch actual premium from Kite API
                    if exit_premium is None:
                        days_to_expiry_exit = self._calculate_days_to_expiry(timestamp, self.expiry)
                        actual_exit_premium, actual_exit_premium_source = self._estimate_option_premium(
                            current_price, 
                            exit_strike, 
                            agent.current_position.value, 
                            segment, 
                            days_to_expiry_exit,
                            timestamp=timestamp,  # Use actual timestamp to fetch from Kite API
                            expiry=self.expiry
                        )
                        exit_premium = actual_exit_premium
                        exit_premium_source = actual_exit_premium_source
                    # If exit_premium was already set (from stop loss only), use it and keep the source
                    # This ensures stop loss is exactly equal to stop loss points, not more
                    # For trailing stop, we fetch actual premium from Kite API above
                    
                    # Exit trade using the exit premium
                    # Note: exit_trade expects spot price, but we track premium separately
                    # Use current timestamp for exit (not entry timestamp)
                    exit_result = agent.exit_trade(
                        exit_price=exit_spot,  # Use current spot as proxy (premium is tracked separately)
                        exit_time=timestamp,  # Current candle timestamp (different from entry time)
                        reason=exit_reason
                    )
                    
                    # Override exit_result exit_time to ensure it's the current timestamp
                    exit_result['exit_time'] = timestamp
                    
                    if exit_result['success']:
                        # Get entry candle data for verification
                        entry_candle_idx = None
                        for i in range(len(df)):
                            if df.index[i] == exit_result['entry_time']:
                                entry_candle_idx = i
                                break
                        
                        entry_candle_data = {}
                        if entry_candle_idx is not None and entry_candle_idx < len(df):
                            entry_candle = df.iloc[entry_candle_idx]
                            entry_candle_data = {
                                "entry_candle_open": float(entry_candle.get('open', exit_result['entry_price'])),
                                "entry_candle_high": float(entry_candle.get('high', exit_result['entry_price'])),
                                "entry_candle_low": float(entry_candle.get('low', exit_result['entry_price'])),
                                "entry_candle_close": float(entry_candle.get('close', exit_result['entry_price']))
                            }
                        
                        # Use the exit premium we calculated earlier (premium-based exit)
                        # exit_premium was set in the exit condition checks above
                        exit_premium_val = exit_premium
                        # Get exit premium source - it was set in the exit condition checks above
                        exit_premium_source_val = exit_premium_source if 'exit_premium_source' in locals() else current_premium_source
                        
                        # Calculate P&L based on premium difference (not spot difference)
                        entry_premium_val = entry_premium_before_exit if entry_premium_before_exit is not None else 0.0
                        entry_premium_source_val = agent.entry_premium_source if hasattr(agent, 'entry_premium_source') else "Unknown"
                        # P&L calculation based on trade regime
                        # Buy: Profit when exit_premium > entry_premium → (exit - entry) * lots
                        # Sell: Profit when exit_premium < entry_premium → (entry - exit) * lots
                        if self.trade_regime == "Buy":
                            premium_pnl = (exit_premium_val - entry_premium_val) * exit_result['lots']
                            premium_return_pct = ((exit_premium_val - entry_premium_val) / entry_premium_val * 100) if entry_premium_val > 0 else 0.0
                        else:  # Sell
                            premium_pnl = (entry_premium_val - exit_premium_val) * exit_result['lots']
                            premium_return_pct = ((entry_premium_val - exit_premium_val) / entry_premium_val * 100) if entry_premium_val > 0 else 0.0
                        
                        # Update capital based on premium P&L
                        current_capital += premium_pnl
                        # Add back the initial capital/margin
                        if entry_price_before_exit is not None and lots_before_exit > 0:
                            current_capital += (entry_price_before_exit * lots_before_exit)
                        equity_curve.append(current_capital)
                        
                        # Update peak for drawdown calculation
                        if current_capital > peak_capital:
                            peak_capital = current_capital
                        
                        # Calculate Stop Loss level based on entry premium (not spot price)
                        # Buy: SL Level = Entry Premium - Stop Loss Points
                        # Sell: SL Level = Entry Premium + Stop Loss Points
                        option_type = exit_result['option_type']
                        stop_loss_points = agent.strategy.stop_loss
                        # Use entry premium for stop loss level calculation based on trade regime
                        if self.trade_regime == "Buy":
                            stop_loss_level = entry_premium_val - stop_loss_points
                        else:  # Sell
                            stop_loss_level = entry_premium_val + stop_loss_points
                        
                        # Get instrument details if available
                        entry_instrument_tradingsymbol = "N/A"
                        exit_instrument_tradingsymbol = "N/A"
                        entry_instrument_info = "N/A"
                        exit_instrument_info = "N/A"
                        remarks = "N/A"
                        
                        # Get entry instrument from agent if stored
                        if hasattr(agent, 'entry_instrument_details') and agent.entry_instrument_details:
                            entry_details = agent.entry_instrument_details
                            entry_instrument_tradingsymbol = entry_details.get('tradingsymbol', 'N/A')
                            entry_instrument_info = f"{entry_instrument_tradingsymbol} ({entry_details.get('instrument_type', 'N/A')})"
                        
                        # Format strike field using tradingsymbol format (e.g., BANKNIFTY25DEC59900PE)
                        strike_value = entry_strike_before_exit if entry_strike_before_exit is not None else exit_strike
                        if entry_instrument_tradingsymbol != "N/A":
                            # Use the actual tradingsymbol from Kite API
                            full_strike = entry_instrument_tradingsymbol
                        elif self.expiry:
                            # Build tradingsymbol using the format logic
                            from src.utils.premium_fetcher import build_tradingsymbol
                            expiry_config = self._load_expiry_config()
                            full_strike = build_tradingsymbol(segment, strike_value, option_type, self.expiry, expiry_config) or f"{option_type}{strike_value} {self.expiry}"
                        else:
                            # Fallback to old format if no expiry
                            full_strike = f"{option_type}{strike_value} N/A"
                        
                        # Get exit instrument from cache
                        if hasattr(self, '_last_instrument_details'):
                            exit_time_str = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)
                            exit_key = f"{exit_time_str}_{exit_strike}_{exit_result['option_type']}"
                            if exit_key in self._last_instrument_details:
                                exit_details = self._last_instrument_details[exit_key]
                                exit_instrument_tradingsymbol = exit_details.get('tradingsymbol', 'N/A')
                                exit_instrument_info = f"{exit_instrument_tradingsymbol} ({exit_details.get('instrument_type', 'N/A')})"
                        
                        # Build remarks with tradingsymbols used
                        remarks_parts = []
                        if entry_instrument_tradingsymbol != "N/A":
                            remarks_parts.append(f"Entry: {entry_instrument_tradingsymbol}")
                        if exit_instrument_tradingsymbol != "N/A":
                            remarks_parts.append(f"Exit: {exit_instrument_tradingsymbol}")
                        if remarks_parts:
                            remarks = " | ".join(remarks_parts)
                        
                        trade_record = {
                            "entry_time": exit_result['entry_time'].isoformat() if isinstance(exit_result['entry_time'], datetime) else str(exit_result['entry_time']),
                            "exit_time": timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),  # Use current candle timestamp (not entry time)
                            "option_type": exit_result['option_type'],  # CE or PE only
                            "strike": full_strike,  # Full strike description: OptionType+Strike+Expiry
                            "entry_premium": entry_premium_val,  # Entry option premium
                            "exit_premium": exit_premium_val,  # Exit option premium
                            "premium_source": f"{entry_premium_source_val} / {exit_premium_source_val}",  # Source of premiums
                            "entry_spot": agent.entry_spot if hasattr(agent, 'entry_spot') and agent.entry_spot is not None else entry_price_before_exit,  # Spot price at entry
                            "exit_spot": exit_spot,  # Spot price at exit
                            "remarks": remarks,  # Remarks showing tradingsymbols used
                            "lots": exit_result['lots'],
                            "pnl": premium_pnl,  # P&L based on premium
                            "return_pct": premium_return_pct,  # Return % based on premium
                            "reason": exit_result['reason'],
                            "stop_loss_points": stop_loss_points,  # Stop loss in points
                            "stop_loss_level": stop_loss_level,  # Stop loss price level
                            "trade_regime": self.trade_regime,  # Trade regime: Buy or Sell
                            "entry_price_strength": entry_price_strength_val,  # Price Strength at entry
                            "entry_volume_strength": entry_volume_strength_val,  # Volume Strength at entry
                            **entry_candle_data  # Include OHLC data for verification
                        }
                        
                        result.trades.append(trade_record)
                        result.total_trades += 1
                        
                        if premium_pnl > 0:
                            result.winning_trades += 1
                            result.total_profit += premium_pnl
                        else:
                            result.losing_trades += 1
                            result.total_loss += abs(premium_pnl)
                        
                        # Calculate drawdown
                        drawdown = ((peak_capital - current_capital) / peak_capital) * 100
                        if drawdown > result.max_drawdown:
                            result.max_drawdown = drawdown
                        
                        # Update max profit
                        if premium_pnl > result.max_profit:
                            result.max_profit = premium_pnl
                
                else:
                    # Check if should add lots
                    current_pnl = agent.calculate_pnl(current_price)
                    should_add, lots_to_add = strategy.should_add_lots(
                        current_pnl, agent.lots
                    )
                    
                    if should_add and current_capital >= (current_price * lots_to_add):
                        # Add lots
                        add_result = agent.add_lots(current_price, lots_to_add)
                        if add_result['success']:
                            current_capital -= (current_price * lots_to_add)
                            logger.debug(f"Added {lots_to_add} lots at ₹{current_price:.2f}")
            
            # Check entry signals if not in position
            if agent.current_position is None:
                # Check if we're in re-entry mode after SL hit
                allow_reentry = agent.waiting_for_reentry
                reentry_candle_type = agent.reentry_candle_type
                
                signal, option_type, reason, signal_details = strategy.generate_signal(
                    df, 
                    idx, 
                    allow_reentry=allow_reentry,
                    reentry_candle_type=reentry_candle_type
                )
                
                # Enhanced logging for debugging (especially for specific dates)
                if signal == TradeSignal.HOLD and "No entry signal" in reason:
                    # Log detailed checks for debugging
                    checks = signal_details.get("checks", [])
                    if idx % 20 == 0 or timestamp.date() == datetime(2024, 11, 27).date():  # Log every 20th candle or Nov 27
                        logger.debug(f"[{timestamp}] No signal - Reason: {reason}")
                        for check in checks[-3:]:  # Show last 3 checks
                            logger.debug(f"  - {check.get('label', 'N/A')}: {check.get('passed', False)}")
                
                # If re-entry signal is generated, clear re-entry mode
                if allow_reentry and signal in [TradeSignal.BUY_CE, TradeSignal.BUY_PE]:
                    agent.clear_reentry_mode()
                    logger.info(f"Re-entry executed: {signal.value} - {reason}")
                
                # Debug signal generation
                if signal == TradeSignal.BUY_PE:
                    pe_signals += 1
                    signal_count += 1
                    logger.info(f"PE Signal detected at {timestamp}: {reason}")
                elif signal == TradeSignal.BUY_CE:
                    ce_signals += 1
                    signal_count += 1
                    logger.info(f"CE Signal detected at {timestamp}: {reason}")
                elif "candle" in reason.lower():
                    no_candle_match += 1
                
                if signal in [TradeSignal.BUY_CE, TradeSignal.BUY_PE]:
                    # Entry timing: Enter immediately on CURRENT candle where crossover is detected
                    # Crossover is now detected on the current candle itself (no delay)
                    entry_price = current_price  # Use current candle close
                    entry_timestamp = timestamp  # Use current candle timestamp
                    
                    # Log signal detection details
                    candle_ohlc = signal_details.get('candle_ohlc', {})
                    candle_type = signal_details.get('candle_type', 'unknown')
                    logger.info(
                        f"Signal Details: Crossover detected on current candle, type={candle_type}, "
                        f"OHLC: O={candle_ohlc.get('open', 0):.2f}, H={candle_ohlc.get('high', 0):.2f}, "
                        f"L={candle_ohlc.get('low', 0):.2f}, C={candle_ohlc.get('close', 0):.2f}"
                    )
                    
                    # Entry on CURRENT candle where crossover is detected (immediate entry, no delay)
                    logger.info(f"Entering immediately on crossover candle: ₹{entry_price:.2f} at {entry_timestamp}")
                    
                    # Alternative: Use next candle open (commented out - user wants immediate entry)
                    # if idx + 1 < len(df):
                    #     next_candle = df.iloc[idx + 1]
                    #     next_candle_open = next_candle.get('open', current_price)
                    #     next_candle_timestamp = next_candle.name if hasattr(next_candle, 'name') else df.index[idx + 1]
                    #     entry_price = next_candle_open
                    #     entry_timestamp = next_candle_timestamp
                    #     logger.info(f"Using next candle open: ₹{entry_price:.2f} at {entry_timestamp}")
                    
                    # For both CE and PE (long options): need capital = price * lots
                    required_capital = entry_price * strategy.initial_lot_size
                    
                    if current_capital >= required_capital:
                        # Calculate strike price and entry premium for the option
                        strike = self._calculate_atm_strike(entry_price, segment)
                        # Calculate days to expiry for entry
                        days_to_expiry_entry = self._calculate_days_to_expiry(entry_timestamp, self.expiry)
                        entry_premium, entry_premium_source = self._estimate_option_premium(entry_price, strike, option_type.value, segment, days_to_expiry_entry, timestamp=entry_timestamp, expiry=self.expiry)
                        
                        # Store premium source in agent
                        agent.entry_premium_source = entry_premium_source
                        
                        # Get Price Strength and Volume Strength from signal details
                        entry_price_strength = signal_details.get('price_strength')
                        entry_volume_strength = signal_details.get('volume_strength')
                        
                        # Enter trade using entry price
                        entry_result = agent.enter_trade(
                            signal=signal,
                            option_type=option_type,
                            price=entry_price,  # Use entry price (next candle open or current close)
                            timestamp=entry_timestamp,  # Use entry timestamp
                            reason=reason,
                            price_strength=entry_price_strength,
                            volume_strength=entry_volume_strength
                        )
                        
                        if entry_result['success']:
                            # Store spot price, strike, and premium for reference
                            agent.entry_spot = entry_price
                            agent.entry_strike = strike
                            agent.entry_premium = entry_premium
                            
                            # Log detailed entry information for debugging
                            candle_open = candle.get('open', current_price)
                            candle_high = candle.get('high', current_price)
                            candle_low = candle.get('low', current_price)
                            logger.info(f"Signal Generated at: {timestamp} (Close: ₹{current_price:.2f})")
                            logger.info(f"Entry Executed at: {entry_timestamp} (Price: ₹{entry_price:.2f})")
                            logger.info(f"Candle OHLC - Open: ₹{candle_open:.2f}, High: ₹{candle_high:.2f}, Low: ₹{candle_low:.2f}, Close: ₹{current_price:.2f}")
                            
                            # Deduct capital used for the option buy
                            current_capital -= required_capital
                            equity_curve.append(current_capital)
                            
                            trade_action = "Bought"
                            logger.info(f"{trade_action} {option_type.value} at Spot: ₹{entry_price:.2f} - {reason}")
        
        # Close any open position at end
        if agent.current_position is not None:
            last_candle = df.iloc[-1]
            last_spot = last_candle['close']
            last_timestamp = df.index[-1]
            
            # Store entry price, lots, strike, premium, and strength values before exit (they get reset in exit_trade)
            entry_price_before_exit = agent.entry_price
            lots_before_exit = agent.lots
            entry_strike_before_exit = agent.entry_strike
            entry_premium_before_exit = agent.entry_premium
            entry_premium_source_val = agent.entry_premium_source if hasattr(agent, 'entry_premium_source') else "Unknown"
            entry_price_strength_val = agent.entry_price_strength if hasattr(agent, 'entry_price_strength') else None
            entry_volume_strength_val = agent.entry_volume_strength if hasattr(agent, 'entry_volume_strength') else None
            
            # Fetch ACTUAL exit premium from Kite API (not estimated) before exit_trade resets agent state
            exit_strike = entry_strike_before_exit if entry_strike_before_exit is not None else self._calculate_atm_strike(last_spot, segment)
            days_to_expiry_exit = self._calculate_days_to_expiry(last_timestamp, self.expiry)
            exit_premium, exit_premium_source = self._estimate_option_premium(
                last_spot, 
                exit_strike, 
                agent.current_position.value,  # Use agent.current_position before exit_trade resets it
                segment, 
                days_to_expiry_exit,
                timestamp=last_timestamp,  # Use actual timestamp to fetch from Kite API
                expiry=self.expiry
            )
            
            # Exit using spot price
            exit_result = agent.exit_trade(
                exit_price=last_spot,
                exit_time=last_timestamp,
                reason="Backtest end - forced exit"
            )
            
            if exit_result['success']:
                # Get entry candle data for verification
                entry_candle_idx = None
                for i in range(len(df)):
                    if df.index[i] == exit_result['entry_time']:
                        entry_candle_idx = i
                        break
                
                entry_candle_data = {}
                if entry_candle_idx is not None and entry_candle_idx < len(df):
                    entry_candle = df.iloc[entry_candle_idx]
                    entry_candle_data = {
                        "entry_candle_open": float(entry_candle.get('open', exit_result['entry_price'])),
                        "entry_candle_high": float(entry_candle.get('high', exit_result['entry_price'])),
                        "entry_candle_low": float(entry_candle.get('low', exit_result['entry_price'])),
                        "entry_candle_close": float(entry_candle.get('close', exit_result['entry_price']))
                    }
                
                # Calculate P&L based on premium difference (not spot difference)
                # exit_premium and exit_premium_source were already calculated above before exit_trade
                entry_premium_val = entry_premium_before_exit if entry_premium_before_exit is not None else 0.0
                exit_premium_val = exit_premium
                # P&L calculation based on trade regime
                # Buy: Profit when exit_premium > entry_premium → (exit - entry) * lots
                # Sell: Profit when exit_premium < entry_premium → (entry - exit) * lots
                if self.trade_regime == "Buy":
                    premium_pnl = (exit_premium_val - entry_premium_val) * exit_result['lots']
                    premium_return_pct = ((exit_premium_val - entry_premium_val) / entry_premium_val * 100) if entry_premium_val > 0 else 0.0
                else:  # Sell
                    premium_pnl = (entry_premium_val - exit_premium_val) * exit_result['lots']
                    premium_return_pct = ((entry_premium_val - exit_premium_val) / entry_premium_val * 100) if entry_premium_val > 0 else 0.0
                
                # Update capital based on premium P&L
                current_capital += premium_pnl
                # Return the capital that was locked (entry_price * lots)
                if entry_price_before_exit is not None and lots_before_exit > 0:
                    current_capital += (entry_price_before_exit * lots_before_exit)
                equity_curve.append(current_capital)
                
                # Calculate Stop Loss level based on entry premium (not spot price)
                # Buy: SL Level = Entry Premium - Stop Loss Points
                # Sell: SL Level = Entry Premium + Stop Loss Points
                option_type = exit_result['option_type']
                stop_loss_points = agent.strategy.stop_loss
                # Use entry premium for stop loss level calculation based on trade regime
                if self.trade_regime == "Buy":
                    stop_loss_level = entry_premium_val - stop_loss_points
                else:  # Sell
                    stop_loss_level = entry_premium_val + stop_loss_points
                
                # Get instrument details if available
                entry_instrument_tradingsymbol = "N/A"
                exit_instrument_tradingsymbol = "N/A"
                entry_instrument_info = "N/A"
                exit_instrument_info = "N/A"
                remarks = "N/A"
                
                # Get entry instrument from agent if stored
                if hasattr(agent, 'entry_instrument_details') and agent.entry_instrument_details:
                    entry_details = agent.entry_instrument_details
                    entry_instrument_tradingsymbol = entry_details.get('tradingsymbol', 'N/A')
                    entry_instrument_info = f"{entry_instrument_tradingsymbol} ({entry_details.get('instrument_type', 'N/A')})"
                
                # Format strike field using tradingsymbol format (e.g., BANKNIFTY25DEC59900PE)
                strike_value = entry_strike_before_exit if entry_strike_before_exit is not None else exit_strike
                if entry_instrument_tradingsymbol != "N/A":
                    # Use the actual tradingsymbol from Kite API
                    full_strike = entry_instrument_tradingsymbol
                elif self.expiry:
                    # Build tradingsymbol using the format logic
                    from src.utils.premium_fetcher import build_tradingsymbol
                    full_strike = build_tradingsymbol(segment, strike_value, option_type, self.expiry) or f"{option_type}{strike_value} {self.expiry}"
                else:
                    # Fallback to old format if no expiry
                    full_strike = f"{option_type}{strike_value} N/A"
                
                # Get exit instrument from cache
                if hasattr(self, '_last_instrument_details'):
                    exit_time_str = last_timestamp.isoformat() if isinstance(last_timestamp, datetime) else str(last_timestamp)
                    exit_key = f"{exit_time_str}_{exit_strike}_{exit_result['option_type']}"
                    if exit_key in self._last_instrument_details:
                        exit_details = self._last_instrument_details[exit_key]
                        exit_instrument_tradingsymbol = exit_details.get('tradingsymbol', 'N/A')
                        exit_instrument_info = f"{exit_instrument_tradingsymbol} ({exit_details.get('instrument_type', 'N/A')})"
                
                # Build remarks with tradingsymbols used
                remarks_parts = []
                if entry_instrument_tradingsymbol != "N/A":
                    remarks_parts.append(f"Entry: {entry_instrument_tradingsymbol}")
                if exit_instrument_tradingsymbol != "N/A":
                    remarks_parts.append(f"Exit: {exit_instrument_tradingsymbol}")
                if remarks_parts:
                    remarks = " | ".join(remarks_parts)
                
                trade_record = {
                    "entry_time": exit_result['entry_time'].isoformat() if isinstance(exit_result['entry_time'], datetime) else str(exit_result['entry_time']),
                    "exit_time": last_timestamp.isoformat() if isinstance(last_timestamp, datetime) else str(last_timestamp),  # Use last candle timestamp
                    "option_type": exit_result['option_type'],  # CE or PE only
                    "strike": full_strike,  # Full strike: OptionType+Strike+Expiry
                    "entry_premium": entry_premium_val,  # Entry option premium
                    "exit_premium": exit_premium_val,  # Exit option premium
                    "premium_source": f"{entry_premium_source_val} / {exit_premium_source}",  # Source of premiums
                    "entry_spot": agent.entry_spot if hasattr(agent, 'entry_spot') and agent.entry_spot is not None else last_spot,  # Spot price at entry
                    "exit_spot": last_spot,  # Spot price at exit
                    "remarks": remarks,  # Remarks showing tradingsymbols used
                    "lots": exit_result['lots'],
                    "pnl": premium_pnl,  # P&L based on premium
                    "return_pct": premium_return_pct,  # Return % based on premium
                    "reason": exit_result['reason'],
                    "stop_loss_points": stop_loss_points,  # Stop loss in points
                    "stop_loss_level": stop_loss_level,  # Stop loss price level
                    "trade_regime": self.trade_regime,  # Trade regime: Buy or Sell
                    "entry_price_strength": entry_price_strength_val,  # Price Strength at entry
                    "entry_volume_strength": entry_volume_strength_val,  # Volume Strength at entry
                    **entry_candle_data  # Include OHLC data for verification
                }
                
                result.trades.append(trade_record)
                result.total_trades += 1
                
                if premium_pnl > 0:
                    result.winning_trades += 1
                    result.total_profit += premium_pnl
                else:
                    result.losing_trades += 1
                    result.total_loss += abs(premium_pnl)
        
        # Calculate final metrics
        result.final_capital = current_capital
        result.net_pnl = result.total_profit - result.total_loss
        result.return_pct = ((result.final_capital - initial_capital) / initial_capital) * 100
        
        if result.total_trades > 0:
            result.win_rate = (result.winning_trades / result.total_trades) * 100
        
        if result.total_loss > 0:
            result.profit_factor = result.total_profit / result.total_loss
        elif result.total_profit > 0:
            result.profit_factor = None  # Use None instead of inf for JSON compatibility
        
        # Log debug information
        logger.info(f"Backtest completed: {result.total_trades} trades, Net P&L: ₹{result.net_pnl:.2f}")
        logger.info(f"Signal statistics: Total signals detected: {signal_count} (PE: {pe_signals}, CE: {ce_signals}), No candle match: {no_candle_match}")
        
        if result.total_trades == 0 and signal_count > 0:
            logger.warning(f"Signals detected but no trades taken. Possible reasons: insufficient capital or data issues")
        elif result.total_trades == 0:
            logger.warning(f"No signals detected. Check RSI calculation and data quality.")
        
        return result

