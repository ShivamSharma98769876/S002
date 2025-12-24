"""
Live Trader agents.

Each segment agent wraps RSIStrategy/RSITradingAgent and uses live prices
to simulate trades in Paper mode. For now, we use simple polling to get
index prices and treat each poll as a candle close.
"""

from __future__ import annotations

import threading
import time
import csv
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import Any, Dict, Optional, List, Tuple

import pandas as pd

from src.trading.rsi_agent import RSIStrategy, RSITradingAgent, Segment, TradeSignal, OptionType
from src.api.kite_client import KiteClient
from src.api.live_data import fetch_live_index_ltp, fetch_recent_index_candles
from src.live_trader.instruments import select_itm_strike, get_segment_config, SegmentConfig
from src.live_trader.execution import PaperExecutionClient, LiveExecutionClient, PaperTradeRecord, OpenPositionRecord, LOG_DIR
from src.utils.logger import get_logger, get_segment_logger
from src.utils.premium_fetcher import build_tradingsymbol
from src.database.models import DatabaseManager
from src.database.repository import CandleRepository
import json


INTERVAL_SECONDS = {
    "1minute": 1 * 60,
    "3minute": 3 * 60,
    "5minute": 5 * 60,
    "15minute": 15 * 60,
    "30minute": 30 * 60,
    "1hour": 60 * 60,
}

INTERVAL_MINUTES = {
    "1minute": 1,
    "3minute": 3,
    "5minute": 5,
    "15minute": 15,
    "30minute": 30,
    "1hour": 60,
}


@dataclass
class LiveAgentParams:
    segment: str
    time_interval: str  # Signal generation timeframe (e.g., "5minute" for PS/VS calculation)
    rsi_period: int
    stop_loss: float
    itm_offset: float
    initial_capital: float
    price_strength_ema: int = 3  # EMA period for Price Strength
    volume_strength_wma: int = 21  # WMA period for Volume Strength
    trade_regime: str = "Buy"  # "Buy" or "Sell" - Trade regime for option trading
    pyramiding_config: Optional[Dict] = None
    monitoring_interval: Optional[str] = None  # Monitoring/checking interval (defaults to "1minute" for better entry timing)


class LiveSegmentAgent(threading.Thread):
    """
    Per-segment live trading agent running in its own thread.

    Simplifications:
      - Uses LTP polling; each poll is treated as a candle close (OHLC equal).
      - Only supports PAPER mode; uses PaperExecutionClient.
    """

    def __init__(
        self,
        kite_client: KiteClient,
        params: LiveAgentParams,
        execution,  # Can be PaperExecutionClient or LiveExecutionClient
        risk_limits: Optional[Dict] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        # Include mode in thread name for better identification
        mode_name = "LIVE" if isinstance(execution, LiveExecutionClient) else "PAPER"
        super().__init__(daemon=True, name=f"LiveAgent-{params.segment}-{mode_name}")
        self.kite_client = kite_client
        self.params = params
        self.execution = execution
        self.risk_limits = risk_limits or {}
        
        self._stop_flag = threading.Event()
        self._lock = threading.Lock()

        # Initialize segment-specific logger (Paper/Live + Segment) - must be done early
        self.logger = get_segment_logger(segment=params.segment, mode=mode_name)
        self.logger.info(f"Initialized {mode_name} trading agent for {params.segment}")
        
        # Use monitoring_interval for tick frequency (defaults to 1 minute for better entry timing)
        # time_interval is still used for signal generation (candle timeframe)
        monitoring_interval = params.monitoring_interval or "1minute"
        self._tick_interval_seconds = INTERVAL_SECONDS.get(
            monitoring_interval.lower(), 1 * 60  # Default to 1 minute
        )
        
        # Log the hybrid approach
        self.logger.info(
            f"Hybrid Monitoring: Signal timeframe={params.time_interval} (for PS/VS calculation), "
            f"Monitoring interval={monitoring_interval} (for entry/exit checks)"
        )

        # Validate and normalize trade_regime (must be set before use)
        self.trade_regime = params.trade_regime.capitalize() if params.trade_regime else "Buy"
        if self.trade_regime not in ["Buy", "Sell"]:
            self.logger.warning(f"Invalid trade_regime '{self.trade_regime}', defaulting to 'Buy'")
            self.trade_regime = "Buy"
        self.logger.info(f"Trade Regime: {self.trade_regime}")

        # Initialize database for candle storage
        self.db_manager = db_manager or DatabaseManager()
        self.candle_repo = CandleRepository(self.db_manager)

        self.segment_enum = Segment[params.segment.upper()]
        self.strategy = RSIStrategy(
            self.segment_enum,
            rsi_period=params.rsi_period,
            stop_loss=params.stop_loss,
            trailing_stop=params.stop_loss,
            price_strength_ema=params.price_strength_ema,
            volume_strength_wma=params.volume_strength_wma,
            trade_regime=self.trade_regime,
        )
        self.agent = RSITradingAgent(self.strategy)
        
        # Initialize premium tracking for trailing stops
        # For Buy: track highest_premium (already in agent)
        # For Sell: track lowest_premium (need to add)
        if self.trade_regime == "Sell":
            self.agent.lowest_premium = None  # Will be set on entry
        
        # Initialize premium fetching (similar to backtesting)
        self._expiry_config = None
        self._kite_authenticated = None
        self._current_expiry = None  # Cache current expiry date
        
        # Use custom pyramiding config if provided, otherwise use defaults
        if params.pyramiding_config and params.segment in params.pyramiding_config:
            cfg_dict = params.pyramiding_config[params.segment]
            # Get default config first to use as fallback
            default_cfg = get_segment_config(params.segment)
            self.segment_cfg = SegmentConfig(
                lot_size=cfg_dict.get("lot_size", default_cfg.lot_size),
                pyramid_points=cfg_dict.get("pyramid_points", default_cfg.pyramid_points),
                lot_addition=cfg_dict.get("lot_addition", default_cfg.lot_addition),
                max_quantity=cfg_dict.get("max_quantity", default_cfg.max_quantity),
                itm_offset=cfg_dict.get("itm_offset", default_cfg.itm_offset),  # Per-segment ITM offset
                stop_loss=cfg_dict.get("stop_loss", default_cfg.stop_loss),  # Per-segment stop loss
            )
            self.logger.info(
                f"Segment config loaded from params for {params.segment}: "
                f"lot_size={self.segment_cfg.lot_size}, itm_offset={self.segment_cfg.itm_offset}, "
                f"stop_loss={self.segment_cfg.stop_loss}, "
                f"pyramid_points={self.segment_cfg.pyramid_points}, "
                f"lot_addition={self.segment_cfg.lot_addition}, max_quantity={self.segment_cfg.max_quantity}"
            )
        else:
            self.segment_cfg = get_segment_config(params.segment)
            self.logger.info(
                f"Segment config using defaults for {params.segment}: "
                f"lot_size={self.segment_cfg.lot_size}, itm_offset={self.segment_cfg.itm_offset}, "
                f"pyramid_points={self.segment_cfg.pyramid_points}, "
                f"lot_addition={self.segment_cfg.lot_addition}, max_quantity={self.segment_cfg.max_quantity}"
            )

        self.df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        # Store last trading day's candles for fallback use
        self._last_trading_day_candles = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        self._bootstrap_history()
        self.trades_taken_today = 0
        self._position_key: Optional[str] = None  # For tracking live positions
        
        # Track position updates for CSV logging
        self._last_position_update_time = None
        self._position_update_interval = timedelta(minutes=5)  # Update every 5 minutes
        self._pyramiding_count = 0  # Track pyramiding events
        
        # Recover positions from Kite API on startup (LIVE mode only)
        if isinstance(self.execution, LiveExecutionClient):
            self._recover_positions_from_kite()

    def stop(self) -> None:
        self._stop_flag.set()

    def _bootstrap_history(self) -> None:
        """
        Preload historical candles from database (preferred) or fetch from API.
        Fetches data starting from market open (9:15 AM from config) to ensure indicators are ready.
        Similar to backtesting, fetches 3 days of data if needed for proper bootstrapping.
        """
        interval_key = self.params.time_interval.lower()
        interval_minutes = INTERVAL_MINUTES.get(interval_key, 5)
        
        # Calculate minimum candles needed for calculations (same as backtesting)
        # WMA(21) is the limiting factor - needs 21 RSI values
        # RSI(9) needs 9 candles, so WMA(21) needs 21 RSI values = 9 + 20 = 29 candles total
        candles_needed_for_bootstrap = max(29, self.strategy.rsi_period + self.strategy.volume_strength_wma - 1)
        min_candles_needed = candles_needed_for_bootstrap
        
        # Try to load from database first (preferred method on restart)
        try:
            from datetime import timedelta, time as dt_time
            from src.utils.date_utils import get_current_ist_time
            
            # Load candles from today's market open (from config) or last 2 days if today is early
            from src.utils.date_utils import get_market_hours
            market_open_time, _ = get_market_hours()
            ist_time = get_current_ist_time()
            today_start = ist_time.replace(hour=market_open_time.hour, minute=market_open_time.minute, second=0, microsecond=0)
            
            # If it's before market open today, load from yesterday
            if ist_time.time() < market_open_time:
                today_start = today_start - timedelta(days=1)
            
            # Ensure today_start is timezone-naive for comparison with database timestamps
            # Database stores timestamps as naive datetimes
            if today_start.tzinfo is not None:
                today_start = today_start.replace(tzinfo=None)
            
            # Try to get latest candles (up to 200 candles, which should cover full trading day + buffer)
            db_candles = self.candle_repo.get_latest_candles(
                segment=self.params.segment,
                interval=self.params.time_interval,
                limit=200  # Enough for full day + historical context
            )
            
            if db_candles and len(db_candles) >= min_candles_needed:
                # Filter to only include candles from today's market open onwards
                # Ensure both timestamps are timezone-naive for comparison
                filtered_candles = []
                for c in db_candles:
                    candle_timestamp = c.timestamp
                    # Remove timezone if present
                    if hasattr(candle_timestamp, 'tzinfo') and candle_timestamp.tzinfo is not None:
                        candle_timestamp = candle_timestamp.replace(tzinfo=None)
                    if candle_timestamp >= today_start:
                        filtered_candles.append(c)
                
                # If we have enough filtered candles, use them; otherwise use all
                if len(filtered_candles) >= min_candles_needed:
                    db_candles = filtered_candles
                
                # Convert database candles to DataFrame
                candles_data = []
                for candle in db_candles:
                    candles_data.append({
                        'open': candle.open,
                        'high': candle.high,
                        'low': candle.low,
                        'close': candle.close,
                        'volume': candle.volume
                    })
                
                if candles_data:
                    self.df = pd.DataFrame(candles_data, index=[c.timestamp for c in db_candles])
                    # Sort by timestamp to ensure chronological order
                    self.df = self.df.sort_index()
                    
                    self.logger.info(
                        f" ✅ Loaded {len(self.df)} candles from database "
                        f"({self.params.time_interval}) from {self.df.index[0]} to {self.df.index[-1]}"
                    )
                    
                    # Check if we have enough candles for calculations
                    if len(self.df) < min_candles_needed:
                        self.logger.warning(
                            f" ⚠️ Only {len(self.df)} candles loaded, need {min_candles_needed} for calculations. "
                            f"Will fetch more from API if needed."
                        )
                    else:
                        self.logger.info(
                            f" ✅ Sufficient candles ({len(self.df)}) loaded for calculations"
                        )
                    
                    # Fetch and store last trading day's candles for fallback use
                    self._fetch_and_store_last_trading_day_candles()
                    return
            elif db_candles and len(db_candles) > 0:
                self.logger.info(
                    f" Loaded {len(db_candles)} candles from database, but need {min_candles_needed}. "
                    f"Will fetch more from API."
                )
                # Use what we have and fetch more
                candles_data = []
                for candle in db_candles:
                    candles_data.append({
                        'open': candle.open,
                        'high': candle.high,
                        'low': candle.low,
                        'close': candle.close,
                        'volume': candle.volume
                    })
                if candles_data:
                    self.df = pd.DataFrame(candles_data, index=[c.timestamp for c in db_candles])
                    self.df = self.df.sort_index()
        except Exception as e:
            self.logger.warning(f" Error loading candles from database: {e}", exc_info=True)

        # If database doesn't have enough data or doesn't exist, fetch from API
        try:
            from src.utils.date_utils import get_current_ist_time, get_market_hours
            from datetime import timedelta
            
            existing_count = len(self.df) if hasattr(self, 'df') and not self.df.empty else 0
            needed_count = max(0, min_candles_needed - existing_count)
            
            # If we need more data, fetch from market open (9:15 AM from config) onwards
            if needed_count > 0:
                market_open_time, _ = get_market_hours()
                ist_time = get_current_ist_time()
                today = ist_time.date()
                
                # Calculate today's market open datetime
                today_market_open = datetime.combine(today, market_open_time).replace(tzinfo=None)
                
                # If current time is before market open, use yesterday's market open
                if ist_time.time() < market_open_time:
                    today_market_open = datetime.combine(today - timedelta(days=1), market_open_time).replace(tzinfo=None)
                
                # Calculate how many days we need to fetch (similar to backtesting)
                # For 5-minute candles: 29 candles = 145 minutes = ~2.4 hours
                # We'll fetch up to 3 days of data to ensure enough bootstrap candles
                bootstrap_days = 3
                fetch_from_date = today_market_open - timedelta(days=bootstrap_days)
                
                # Fetch historical data from market open using Kite API
                self.logger.info(
                    f"Fetching historical data from {fetch_from_date.date()} {market_open_time.strftime('%H:%M')} "
                    f"to {today_market_open.date()} {market_open_time.strftime('%H:%M')} "
                    f"(need {needed_count} more candles for bootstrapping)"
                )
                
                # Use Kite API to fetch historical data
                seg = self.params.segment.upper()
                from src.api.live_data import INDEX_INSTRUMENT_TOKENS
                instrument_token = INDEX_INSTRUMENT_TOKENS.get(seg)
                
                if instrument_token is None:
                    self.logger.warning(f"Unsupported segment for historical data: {seg}, falling back to recent candles")
                    # Fallback to recent candles method
                    lookback_minutes = max(
                        needed_count * interval_minutes,
                        interval_minutes * 12,
                    )
                    history = fetch_recent_index_candles(
                        self.kite_client,
                        self.params.segment,
                        self.params.time_interval,
                        lookback_minutes=lookback_minutes,
                    )
                else:
                    # Fetch data from fetch_from_date to today_market_open (or current time if after market open)
                    end_time = ist_time.replace(tzinfo=None) if ist_time.time() >= market_open_time else today_market_open
                    
                    try:
                        candles = self.kite_client.kite.historical_data(
                            instrument_token,
                            fetch_from_date,
                            end_time,
                            self.params.time_interval,
                            continuous=False,
                            oi=False,
                        )
                        
                        if not candles:
                            self.logger.warning(f"No historical candles returned from Kite API for {seg}, falling back to recent candles")
                            # Fallback to recent candles method
                            lookback_minutes = max(
                                needed_count * interval_minutes,
                                interval_minutes * 12,
                            )
                            history = fetch_recent_index_candles(
                                self.kite_client,
                                self.params.segment,
                                self.params.time_interval,
                                lookback_minutes=lookback_minutes,
                            )
                        else:
                            # Convert Kite candles to DataFrame
                            history_data = []
                            timestamps = []
                            for candle in candles:
                                history_data.append({
                                    'open': candle['open'],
                                    'high': candle['high'],
                                    'low': candle['low'],
                                    'close': candle['close'],
                                    'volume': candle.get('volume', 0)
                                })
                                timestamps.append(candle['date'])
                            
                            # Create DataFrame with timestamps as index
                            history = pd.DataFrame(history_data, index=timestamps)
                            history.index = pd.to_datetime(history.index)
                            
                            # Normalize timezone: convert to IST then remove timezone
                            if history.index.tz is not None:
                                history.index = history.index.tz_convert("Asia/Kolkata").tz_localize(None)
                            else:
                                # If no timezone, assume IST and localize
                                history.index = history.index.tz_localize("Asia/Kolkata").tz_localize(None)
                            
                            # Keep all candles for bootstrapping (we need historical data for indicators)
                            # We'll filter to market open when we start trading
                            if not history.empty:
                                self.logger.info(
                                    f"Fetched {len(history)} candles from Kite API "
                                    f"from {history.index[0]} to {history.index[-1]} "
                                    f"(includes {bootstrap_days} days before market open for bootstrapping)"
                                )
                            else:
                                self.logger.warning("Empty history from Kite API, falling back to recent candles")
                                # Fallback to recent candles method
                                lookback_minutes = max(
                                    needed_count * interval_minutes,
                                    interval_minutes * 12,
                                )
                                history = fetch_recent_index_candles(
                                    self.kite_client,
                                    self.params.segment,
                                    self.params.time_interval,
                                    lookback_minutes=lookback_minutes,
                                )
                    except Exception as e:
                        self.logger.warning(f"Error fetching historical data from Kite API: {e}, falling back to recent candles")
                        # Fallback to recent candles method
                        lookback_minutes = max(
                            needed_count * interval_minutes,
                            interval_minutes * 12,
                        )
                        history = fetch_recent_index_candles(
                            self.kite_client,
                            self.params.segment,
                            self.params.time_interval,
                            lookback_minutes=lookback_minutes,
                        )
            else:
                # We have enough data from database
                history = None
                if existing_count >= min_candles_needed:
                    self.logger.info(f" ✅ Sufficient candles ({existing_count}) from database for calculations")
                    # Fetch and store last trading day's candles for fallback use
                    self._fetch_and_store_last_trading_day_candles()
                    return
            
            if history is None or history.empty:
                if existing_count > 0:
                    self.logger.info(
                        f" Using {existing_count} candles from database. "
                        f"API fetch returned no new data."
                    )
                    # Check if we have enough candles
                    if existing_count >= min_candles_needed:
                        self.logger.info(f" ✅ Sufficient candles ({existing_count}) from database for calculations")
                    else:
                        self.logger.warning(
                            f" ⚠️ Only {existing_count} candles from database, need {min_candles_needed}. "
                            f"Indicators may not be accurate initially."
                        )
                    # Fetch and store last trading day's candles for fallback use
                    self._fetch_and_store_last_trading_day_candles()
                    return
                else:
                    self.logger.warning(
                        f" Unable to bootstrap candles; will build history live. "
                        f"Indicators may not be accurate until enough candles are collected."
                    )
                    # Still fetch last trading day's candles for fallback use
                    self._fetch_and_store_last_trading_day_candles()
                    return

            # Keep OHLCV columns and drop timezone info
            required_cols = ["open", "high", "low", "close"]
            if "volume" in history.columns:
                required_cols.append("volume")
            history = history[required_cols].copy()
            if getattr(history.index, "tz", None) is not None:
                history.index = history.index.tz_convert("Asia/Kolkata").tz_localize(None)
            
            # Merge with existing DataFrame if we have one
            if hasattr(self, 'df') and not self.df.empty:
                # Combine existing and new candles, removing duplicates
                combined = pd.concat([self.df, history])
                combined = combined[~combined.index.duplicated(keep='last')]  # Keep latest if duplicate
                combined = combined.sort_index()
                self.df = combined
                self.logger.info(
                    f" Merged {len(history)} new candles with {existing_count} existing. "
                    f"Total: {len(self.df)} candles"
                )
            else:
                self.df = history

            # Store fetched candles in database
            try:
                candles_to_save = []
                for timestamp, row in history.iterrows():
                    candles_to_save.append({
                        'segment': self.params.segment,
                        'timestamp': timestamp,
                        'interval': self.params.time_interval,
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row.get('volume', 0.0)),
                        'is_synthetic': False
                    })
                
                if candles_to_save:
                    saved_count = self.candle_repo.save_candles_batch(candles_to_save)
                    self.logger.info(f" Saved {saved_count} new candles to database")
            except Exception as e:
                self.logger.warning(f" Error saving candles to database: {e}")

            self.logger.info(
                f" ✅ Bootstrapped {len(self.df)} candles total "
                f"({self.params.time_interval}) from {self.df.index[0]} to {self.df.index[-1]}"
            )
        except Exception as e:
            self.logger.warning(
                f" Failed to fetch additional candles from API: {e}"
            )
            if hasattr(self, 'df') and not self.df.empty:
                self.logger.info(
                    f" Continuing with {len(self.df)} candles from database"
                )
        
        # Always fetch and store last trading day's candles for fallback use
        self._fetch_and_store_last_trading_day_candles()

    def _fetch_and_store_last_trading_day_candles(self) -> None:
        """
        Fetch complete last trading day's candles and store them for fallback use.
        This ensures we have historical data available when recent candles aren't available.
        """
        try:
            from src.api.live_data import fetch_last_trading_day_candles
            
            self.logger.info("📅 Fetching complete last trading day's candles for fallback use...")
            
            fetched_last_day = fetch_last_trading_day_candles(
                self.kite_client,
                self.params.segment,
                self.params.time_interval
            )
            
            if fetched_last_day is not None and not fetched_last_day.empty:
                # Normalize timezone: convert fetched index to timezone-naive if needed
                fetched_last_day_index = fetched_last_day.index
                if getattr(fetched_last_day_index, "tz", None) is not None:
                    # Convert to IST then remove timezone
                    fetched_last_day.index = fetched_last_day_index.tz_convert("Asia/Kolkata").tz_localize(None)
                
                # Store in instance variable for quick access
                self._last_trading_day_candles = fetched_last_day
                
                # Also save to database for persistence
                try:
                    for ts, row in fetched_last_day.iterrows():
                        is_synthetic = (row['open'] == row['high'] == row['low'] == row['close'])
                        self.candle_repo.save_candle(
                            segment=self.params.segment,
                            timestamp=ts,
                            interval=self.params.time_interval,
                            open=float(row['open']),
                            high=float(row['high']),
                            low=float(row['low']),
                            close=float(row['close']),
                            volume=float(row.get('volume', 0.0)),
                            is_synthetic=is_synthetic
                        )
                except Exception as e:
                    self.logger.warning(f"Failed to save last trading day candles to database: {e}")
                
                self.logger.info(
                    f" ✅ Stored {len(fetched_last_day)} candles from last trading day "
                    f"({fetched_last_day.index[0]} to {fetched_last_day.index[-1]}) for fallback use"
                )
            else:
                self.logger.warning("⚠️ Could not fetch last trading day's candles. Fallback may not work.")
        except Exception as e:
            self.logger.warning(
                f"⚠️ Error fetching last trading day's candles: {e}. "
                f"Fallback may not work.",
                exc_info=True
            )

    def run(self) -> None:
        # Use monitoring_interval for loop frequency; time_interval remains the candle timeframe
        monitoring_key = (self.params.monitoring_interval or "1minute").lower()
        self._tick_interval_seconds = INTERVAL_SECONDS.get(monitoring_key, 60)
        self.logger.info(
            f"LiveSegmentAgent started for {self.params.segment} "
            f"interval={self.params.time_interval}, rsi={self.params.rsi_period}, "
            f"tick_interval={self._tick_interval_seconds}s (monitoring interval={monitoring_key})"
        )

        # Wait until market opens (from config.json)
        from src.utils.date_utils import is_market_open, get_current_ist_time, get_market_hours
        
        market_open_time, _ = get_market_hours()
        market_open_str = market_open_time.strftime("%H:%M")
        
        self.logger.info(f" Waiting for market to open ({market_open_str} IST)...")
        while not self._stop_flag.is_set():
            ist_time = get_current_ist_time()
            current_time = ist_time.time()
            
            # Check if it's a weekday
            if ist_time.weekday() >= 5:  # Saturday or Sunday
                self.logger.info(f" Weekend - market closed. Waiting for next trading day...")
                time.sleep(3600)  # Sleep for 1 hour and check again
                continue
            
            # Check if market is open (from config)
            if current_time >= market_open_time:
                self.logger.info(f" ✅ Market is open! Starting trading at {current_time.strftime('%H:%M:%S')} IST")
                break
            
            # Wait until market opens
            wait_seconds = ((market_open_time.hour * 3600 + market_open_time.minute * 60) - 
                          (current_time.hour * 3600 + current_time.minute * 60))
            if wait_seconds > 0:
                wait_minutes = wait_seconds / 60
                self.logger.info(f" Market opens at {market_open_str} IST. Current time: {current_time.strftime('%H:%M:%S')} IST. Waiting {wait_minutes:.1f} minutes...")
                time.sleep(min(wait_seconds, 60))  # Sleep in 1-minute increments
            else:
                time.sleep(1)

        next_tick_at = datetime.now()

        while not self._stop_flag.is_set():
            now = datetime.now()
            if now >= next_tick_at:
                try:
                    self._tick()
                except Exception as e:
                    self.logger.error(
                        f"Error in LiveSegmentAgent[{self.params.segment}]: {e}",
                        exc_info=True,
                    )
                next_tick_at = now + timedelta(seconds=self._tick_interval_seconds)
            else:
                remaining = (next_tick_at - now).total_seconds()
                sleep_for = 0.5 if remaining <= 0 else min(remaining, 1.0)
                time.sleep(sleep_for)

        self.logger.info(f"LiveSegmentAgent stopped for {self.params.segment}")

    # === Core loop helpers ===

    def _tick(self) -> None:
        """One iteration: fetch price, update candle, run strategy/agent."""
        try:
            # Check if market is open (from config.json)
            from src.utils.date_utils import is_market_open, get_current_ist_time, get_market_hours
            
            if not is_market_open():
                ist_time = get_current_ist_time()
                current_time = ist_time.time()
                _, market_close = get_market_hours()
                
                # If market is closed, log and skip this tick
                if current_time > market_close:
                    market_close_str = market_close.strftime("%H:%M")
                    self.logger.info(f" Market closed (after {market_close_str} IST). Waiting for next trading day...")
                    time.sleep(3600)  # Sleep for 1 hour
                    return
                else:
                    # Before market opens, wait
                    self.logger.debug(f" Market not yet open. Current time: {current_time.strftime('%H:%M:%S')} IST")
                    return
            
            # Fetch live price from Kite
            price = fetch_live_index_ltp(self.kite_client, self.params.segment)
            # Use IST time for all calculations (critical for Azure which runs in GMT)
            from src.utils.date_utils import get_current_ist_time
            ist_now = get_current_ist_time()
            now = ist_now.replace(second=0, microsecond=0).replace(tzinfo=None)  # Convert to naive for compatibility
            self.logger.info(f"Fetched LTP from Kite: ₹{price:.2f} at {now.strftime('%H:%M:%S')} IST")

            with self._lock:
                # HYBRID APPROACH: 
                # - Signal generation uses time_interval (e.g., 5-minute candles for PS/VS calculation)
                # - Monitoring/checking happens every monitoring_interval (e.g., 1 minute)
                # - This allows earlier entry detection while maintaining signal quality
                
                # Round timestamp to signal generation interval boundary (round DOWN to get current interval start)
                interval_minutes = INTERVAL_MINUTES.get(self.params.time_interval.lower(), 5)
                rounded_time = now.replace(second=0, microsecond=0)
                rounded_time = rounded_time.replace(minute=(rounded_time.minute // interval_minutes) * interval_minutes)
                
                # For signal generation, we need the MOST RECENT COMPLETED candle from signal timeframe
                # A candle is usable if it's at least 1 minute old (to avoid current forming candle)
                # Strategy: Try to use the current interval's candle first, then fall back to N-1 if needed
                # Example with 5-min candles, checking every 1 min:
                #   At 10:02 AM: rounded_time = 10:00:00 (2 min old) → Use 10:00:00 ✅
                #   At 10:01 AM: rounded_time = 10:00:00 (1 min old) → Use 10:00:00 ✅
                #   At 10:00:30 AM: rounded_time = 10:00:00 (30 sec old) → Use 09:55:00 (N-1) ✅
                
                # First, try to use the current interval's candle if it's old enough
                time_since_rounded = (now - rounded_time).total_seconds()
                if time_since_rounded >= 60:  # At least 1 minute old
                    # Current interval candle is usable
                    signal_candle_time = rounded_time
                    self.logger.debug(
                        f"📊 Signal Generation: Using {self.params.time_interval} candle {signal_candle_time} "
                        f"(age: {time_since_rounded:.0f}s, current: {now.strftime('%H:%M:%S')})"
                    )
                else:
                    # Current interval candle is too recent, use N-1 (previous interval)
                    signal_candle_time = rounded_time - timedelta(minutes=interval_minutes)
                    self.logger.debug(
                        f"📊 Signal Generation: Current {self.params.time_interval} candle too recent "
                        f"({time_since_rounded:.0f}s), using N-1: {signal_candle_time}"
                    )
                
                # Check if signal_candle_time is actually completed (enough time has passed)
                time_since_signal_candle = (now - signal_candle_time).total_seconds()
                candle_completion_time = interval_minutes * 60  # Time needed for candle to complete
                signal_candle_completed = time_since_signal_candle >= candle_completion_time
                
                # Log the candle time being used for debugging
                self.logger.debug(
                    f" Current time: {now}, Rounded: {rounded_time}, "
                    f"Signal candle time: {signal_candle_time}, Time since: {time_since_signal_candle/60:.1f} min"
                )
                
                # Initialize candle variable
                candle = None
                
                # PRIORITY 1: Check DataFrame first (candles collected during the day)
                # This should have all today's candles that were already fetched and processed
                if hasattr(self, 'df') and not self.df.empty and signal_candle_time in self.df.index:
                    df_row = self.df.loc[signal_candle_time]
                    time_since_candle = (now - signal_candle_time).total_seconds()
                    
                    # Check if candle is old enough and not synthetic
                    if time_since_candle >= 60:  # At least 1 minute old
                        is_synthetic = (df_row['open'] == df_row['high'] == df_row['low'] == df_row['close'])
                        if not is_synthetic:
                            candle = {
                                "open": float(df_row['open']),
                                "high": float(df_row['high']),
                                "low": float(df_row['low']),
                                "close": float(df_row['close']),
                                "volume": float(df_row.get('volume', 0.0))
                            }
                            self.logger.debug(
                                f" ✅ Using candle from DataFrame (collected today): {signal_candle_time} "
                                f"(O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f})"
                            )
                
                # PRIORITY 2: If not in DataFrame, check database (candles saved earlier)
                db_candle = None
                most_recent_candle = None  # Initialize outside the if block to avoid UnboundLocalError
                if candle is None:
                    latest_db_candles = self.candle_repo.get_latest_candles(
                        segment=self.params.segment,
                        interval=self.params.time_interval,
                        limit=20  # Get last 20 candles to find the most recent completed one
                    )
                    
                    # Require an exact candle for signal_candle_time (no older fallback)
                    # A candle is usable if it's at least 1 minute old (to avoid using current forming candle)
                    min_age_seconds = 60  # 1 minute minimum to ensure it's not the current forming candle
                    max_age_seconds = interval_minutes * 60 * 2  # 2 intervals - max age before forcing API fetch
                    
                    # First, try to find the exact candle for signal_candle_time
                    for latest_candle in reversed(latest_db_candles):
                        if latest_candle.timestamp == signal_candle_time:
                            time_since_candle = (now - latest_candle.timestamp).total_seconds()
                            if time_since_candle >= min_age_seconds:
                                is_synthetic = latest_candle.is_synthetic or (latest_candle.open == latest_candle.high == latest_candle.low == latest_candle.close)
                                if not is_synthetic:
                                    most_recent_candle = latest_candle
                                    self.logger.debug(f" Found exact match for signal_candle_time: {signal_candle_time}")
                                    break  # Found exact match, use it
                
                    # Now check if the most recent candle is too old or not the one we need
                    if most_recent_candle:
                        # If we found a candle but it's not the exact one we need, fetch from API
                        if most_recent_candle.timestamp < signal_candle_time:
                            self.logger.info(
                                f" Database has candle {most_recent_candle.timestamp}, but need {signal_candle_time}. "
                                f"Fetching fresh data from API to get the latest completed candles..."
                            )
                            most_recent_candle = None  # Force API fetch
                        else:
                            # We have the exact candle we need, check if it's too old
                            time_since_candle = (now - most_recent_candle.timestamp).total_seconds()
                            if time_since_candle > max_age_seconds:
                                self.logger.info(
                                    f" ⚠️ Database candle is {time_since_candle/60:.1f} minutes old (max: {max_age_seconds/60:.1f} min). "
                                    f"Fetching fresh data from API to get newer completed candles..."
                                )
                                most_recent_candle = None  # Force API fetch
                    
                    # If we found a good candle in database, use it
                    if most_recent_candle:
                        db_candle = most_recent_candle
                
                # PRIORITY 3: Only fetch from API if we don't have the candle in DataFrame or database
                if candle is None and db_candle is None:
                    # Fetch fresh candles from API
                        try:
                            fetched = fetch_recent_index_candles(
                                self.kite_client,
                                self.params.segment,
                                self.params.time_interval,
                                lookback_minutes=interval_minutes * 10  # Fetch 10 intervals
                            )
                            
                            if fetched is not None and not fetched.empty:
                                # Normalize timezone
                                if getattr(fetched.index, "tz", None) is not None:
                                    fetched.index = fetched.index.tz_convert("Asia/Kolkata").tz_localize(None)
                                
                                # Find the most recent usable candle from fetched data (N-1 logic)
                                # A candle is usable if it's at least 1 minute old (to avoid current forming candle)
                                usable_candles = []
                                for ts, row in fetched.iterrows():
                                    time_since_ts = (now - ts).total_seconds()
                                    if time_since_ts >= 60:  # At least 1 minute old
                                        # Check if it's not synthetic
                                        is_syn = (row['open'] == row['high'] == row['low'] == row['close'])
                                        if not is_syn:
                                            usable_candles.append((ts, row))
                                
                                if usable_candles:
                                    # Require exact candle for signal_candle_time
                                    exact_match = None
                                    for ts, row in usable_candles:
                                        if ts == signal_candle_time:
                                            exact_match = (ts, row)
                                            break
                                    
                                    if exact_match:
                                        newest_ts, newest_row = exact_match
                                        signal_candle_time = newest_ts
                                        db_candle = None  # Will be fetched below
                                        
                                        # Compute bar window based on 5-minute intervals (always use 5 minutes)
                                        candle_interval_minutes = 5  # Always use 5-minute candles
                                        if isinstance(newest_ts, pd.Timestamp):
                                            bar_end = newest_ts.floor(f"{candle_interval_minutes}min")
                                        else:
                                            bar_end = pd.Timestamp(newest_ts).floor(f"{candle_interval_minutes}min")
                                        bar_start = bar_end - timedelta(minutes=candle_interval_minutes)
                                        window_str = f"{bar_start.strftime('%H:%M')}–{bar_end.strftime('%H:%M')}"
                                        self.logger.info(
                                            f" ✅ Found candle from API (exact): {newest_ts} "
                                            f"[Window {window_str}] "
                                            f"(O:{newest_row['open']:.2f} H:{newest_row['high']:.2f} "
                                            f"L:{newest_row['low']:.2f} C:{newest_row['close']:.2f})"
                                        )
                                        
                                        # Save the new candles to database AND add to DataFrame immediately
                                        candles_to_save = []
                                        for ts, row in usable_candles:
                                            # Save all usable candles that are at least 1 minute old
                                            candles_to_save.append({
                                                'segment': self.params.segment,
                                                'timestamp': ts,
                                                'interval': self.params.time_interval,
                                                'open': float(row['open']),
                                                'high': float(row['high']),
                                                'low': float(row['low']),
                                                'close': float(row['close']),
                                                'volume': float(row.get('volume', 0.0)),
                                                'is_synthetic': False
                                            })
                                            
                                            # Add to DataFrame immediately so it's available for next tick
                                            if ts not in self.df.index:
                                                self.df.loc[ts] = {
                                                    'open': float(row['open']),
                                                    'high': float(row['high']),
                                                    'low': float(row['low']),
                                                    'close': float(row['close']),
                                                    'volume': float(row.get('volume', 0.0))
                                                }
                                        
                                        if candles_to_save:
                                            saved_count = self.candle_repo.save_candles_batch(candles_to_save)
                                            self.logger.info(f" Saved {saved_count} new candles to database and DataFrame")
                                            # Sort DataFrame after adding new candles
                                            self.df = self.df.sort_index()
                                    else:
                                        # No exact candle available from API
                                        # CRITICAL: Only use candles from the SAME WINDOW to avoid PS/VS mismatch
                                        # Calculate expected window first
                                        if isinstance(signal_candle_time, pd.Timestamp):
                                            expected_bar_end = signal_candle_time.floor(f"{interval_minutes}min")
                                        else:
                                            expected_bar_end = pd.Timestamp(signal_candle_time).floor(f"{interval_minutes}min")
                                        expected_bar_start = expected_bar_end - timedelta(minutes=interval_minutes)
                                        expected_window_str = f"{expected_bar_start.strftime('%H:%M')}–{expected_bar_end.strftime('%H:%M')}"
                                        
                                        # Find candles from the SAME window (not just closest)
                                        same_window_candles = []
                                        for ts, row in usable_candles:
                                            if isinstance(ts, pd.Timestamp):
                                                actual_bar_end = ts.floor(f"{interval_minutes}min")
                                            else:
                                                actual_bar_end = pd.Timestamp(ts).floor(f"{interval_minutes}min")
                                            actual_bar_start = actual_bar_end - timedelta(minutes=interval_minutes)
                                            actual_window_str = f"{actual_bar_start.strftime('%H:%M')}–{actual_bar_end.strftime('%H:%M')}"
                                            
                                            if actual_window_str == expected_window_str:
                                                same_window_candles.append((ts, row))
                                        
                                        if same_window_candles:
                                            # Found a candle from the same window - use it
                                            newest_ts, newest_row = max(same_window_candles, key=lambda x: x[0])
                                            signal_candle_time = newest_ts
                                            db_candle = None
                                            
                                            self.logger.info(
                                                f" ✅ Found candle from API (same window): {newest_ts} "
                                                f"[Window {expected_window_str}] "
                                                f"(O:{newest_row['open']:.2f} H:{newest_row['high']:.2f} "
                                                f"L:{newest_row['low']:.2f} C:{newest_row['close']:.2f})"
                                            )
                                            
                                            # Save candles to database
                                            candles_to_save = []
                                            for ts, row in usable_candles:
                                                candles_to_save.append({
                                                    'segment': self.params.segment,
                                                    'timestamp': ts,
                                                    'interval': self.params.time_interval,
                                                    'open': float(row['open']),
                                                    'high': float(row['high']),
                                                    'low': float(row['low']),
                                                    'close': float(row['close']),
                                                    'volume': float(row.get('volume', 0.0)),
                                                    'is_synthetic': False
                                                })
                                            
                                            if candles_to_save:
                                                saved_count = self.candle_repo.save_candles_batch(candles_to_save)
                                                self.logger.info(f" Saved {saved_count} new candles to database")
                                        else:
                                            # No candle from same window - implement fallback strategy
                                            # Try previous windows one by one until we find an available candle
                                            time_since_expected = (now - signal_candle_time).total_seconds()
                                            is_very_recent = time_since_expected < 180  # Less than 3 minutes old
                                            
                                            # First, check database for the exact expected candle
                                            db_has_expected = False
                                            if db_candle:
                                                db_ts = db_candle.timestamp
                                                if db_ts == signal_candle_time:
                                                    # Database has the exact expected candle - use it!
                                                    signal_candle_time = db_ts
                                                    self.logger.info(
                                                        f" ✅ Using database candle (exact match): {db_ts} "
                                                        f"[Window {expected_window_str}]"
                                                    )
                                                    db_has_expected = True
                                                else:
                                                    # Check if database candle is from the expected window
                                                    if isinstance(db_ts, pd.Timestamp):
                                                        db_bar_end = db_ts.floor(f"{interval_minutes}min")
                                                    else:
                                                        db_bar_end = pd.Timestamp(db_ts).floor(f"{interval_minutes}min")
                                                    db_bar_start = db_bar_end - timedelta(minutes=interval_minutes)
                                                    db_window_str = f"{db_bar_start.strftime('%H:%M')}–{db_bar_end.strftime('%H:%M')}"
                                                    
                                                    if db_window_str == expected_window_str:
                                                        # Database has the correct window candle - use it
                                                        signal_candle_time = db_ts
                                                        self.logger.info(
                                                            f" ✅ Using database candle (same window): {db_ts} "
                                                            f"[Window {expected_window_str}]"
                                                        )
                                                        db_has_expected = True
                                            
                                            if not db_has_expected:
                                                # Database doesn't have the expected candle
                                                # If very recent, check database more thoroughly first
                                                if is_very_recent:
                                                    for db_c in latest_db_candles:
                                                        if db_c.timestamp == signal_candle_time:
                                                            signal_candle_time = db_c.timestamp
                                                            db_candle = db_c
                                                            self.logger.info(
                                                                f" ✅ Found expected candle in database (deep search): {db_c.timestamp} "
                                                                f"[Window {expected_window_str}]"
                                                            )
                                                            db_has_expected = True
                                                            break
                                                
                                                if not db_has_expected:
                                                    # Fallback: Try previous windows (-1, -2, -3, etc.) until we find an available candle
                                                    found_fallback = False
                                                    max_fallback_attempts = 5  # Try up to 5 previous windows
                                                    
                                                    for attempt in range(1, max_fallback_attempts + 1):
                                                        # Calculate previous window
                                                        fallback_candle_time = signal_candle_time - timedelta(minutes=interval_minutes * attempt)
                                                        if isinstance(fallback_candle_time, pd.Timestamp):
                                                            fallback_bar_end = fallback_candle_time.floor(f"{interval_minutes}min")
                                                        else:
                                                            fallback_bar_end = pd.Timestamp(fallback_candle_time).floor(f"{interval_minutes}min")
                                                        fallback_bar_start = fallback_bar_end - timedelta(minutes=interval_minutes)
                                                        fallback_window_str = f"{fallback_bar_start.strftime('%H:%M')}–{fallback_bar_end.strftime('%H:%M')}"
                                                        
                                                        # Check API candles for this window
                                                        fallback_candles = []
                                                        for ts, row in usable_candles:
                                                            if isinstance(ts, pd.Timestamp):
                                                                actual_bar_end = ts.floor(f"{interval_minutes}min")
                                                            else:
                                                                actual_bar_end = pd.Timestamp(ts).floor(f"{interval_minutes}min")
                                                            actual_bar_start = actual_bar_end - timedelta(minutes=interval_minutes)
                                                            actual_window_str = f"{actual_bar_start.strftime('%H:%M')}–{actual_bar_end.strftime('%H:%M')}"
                                                            
                                                            if actual_window_str == fallback_window_str:
                                                                fallback_candles.append((ts, row))
                                                        
                                                        if fallback_candles:
                                                            # Found a candle in this fallback window - use it
                                                            newest_ts, newest_row = max(fallback_candles, key=lambda x: x[0])
                                                            signal_candle_time = newest_ts
                                                            db_candle = None
                                                            
                                                            self.logger.info(
                                                                f" ✅ Using fallback candle (window -{attempt}): {newest_ts} "
                                                                f"[Window {fallback_window_str}] "
                                                                f"(Expected: {expected_window_str}) "
                                                                f"(O:{newest_row['open']:.2f} H:{newest_row['high']:.2f} "
                                                                f"L:{newest_row['low']:.2f} C:{newest_row['close']:.2f})"
                                                            )
                                                            
                                                            # Save candles to database AND add to DataFrame immediately
                                                            candles_to_save = []
                                                            for ts, row in usable_candles:
                                                                candles_to_save.append({
                                                                    'segment': self.params.segment,
                                                                    'timestamp': ts,
                                                                    'interval': self.params.time_interval,
                                                                    'open': float(row['open']),
                                                                    'high': float(row['high']),
                                                                    'low': float(row['low']),
                                                                    'close': float(row['close']),
                                                                    'volume': float(row.get('volume', 0.0)),
                                                                    'is_synthetic': False
                                                                })
                                                                
                                                                # Add to DataFrame immediately
                                                                if ts not in self.df.index:
                                                                    self.df.loc[ts] = {
                                                                        'open': float(row['open']),
                                                                        'high': float(row['high']),
                                                                        'low': float(row['low']),
                                                                        'close': float(row['close']),
                                                                        'volume': float(row.get('volume', 0.0))
                                                                    }
                                                            
                                                            if candles_to_save:
                                                                saved_count = self.candle_repo.save_candles_batch(candles_to_save)
                                                                self.logger.info(f" Saved {saved_count} new candles to database and DataFrame")
                                                                # Sort DataFrame after adding
                                                                self.df = self.df.sort_index()
                                                            
                                                            found_fallback = True
                                                            break
                                                        
                                                        # Also check database for this fallback window
                                                        for db_c in latest_db_candles:
                                                            if db_c.timestamp == fallback_candle_time:
                                                                signal_candle_time = db_c.timestamp
                                                                db_candle = db_c
                                                                self.logger.info(
                                                                    f" ✅ Using database fallback candle (window -{attempt}): {db_c.timestamp} "
                                                                    f"[Window {fallback_window_str}] "
                                                                    f"(Expected: {expected_window_str})"
                                                                )
                                                                found_fallback = True
                                                                break
                                                        
                                                        if found_fallback:
                                                            break
                                                    
                                                    if not found_fallback:
                                                        # No candle found even after trying fallbacks
                                                        if is_very_recent:
                                                            # Very recent candle - API delay is normal
                                                            self.logger.info(
                                                                f"⏳ Expected candle window {expected_window_str} just completed "
                                                                f"({time_since_expected/60:.1f} min ago). API may need 1-2 more minutes to publish it. "
                                                                f"Skipping this tick - will retry on next tick."
                                                            )
                                                        else:
                                                            # Older candle - should be available
                                                            if usable_candles:
                                                                newest_ts, newest_row = max(usable_candles, key=lambda x: x[0])
                                                                if isinstance(newest_ts, pd.Timestamp):
                                                                    actual_bar_end = newest_ts.floor(f"{interval_minutes}min")
                                                                else:
                                                                    actual_bar_end = pd.Timestamp(newest_ts).floor(f"{interval_minutes}min")
                                                                actual_bar_start = actual_bar_end - timedelta(minutes=interval_minutes)
                                                                actual_window_str = f"{actual_bar_start.strftime('%H:%M')}–{actual_bar_end.strftime('%H:%M')}"
                                                                
                                                                self.logger.warning(
                                                                    f"⛔ Skipping signal: Expected candle window {expected_window_str} not available.\n"
                                                                    f"   Tried {max_fallback_attempts} previous windows, none found.\n"
                                                                    f"   API returned window {actual_window_str}.\n"
                                                                    f"   Database also doesn't have expected window."
                                                                )
                                                            else:
                                                                self.logger.warning(
                                                                    f"⛔ Skipping signal: Expected candle window {expected_window_str} not available.\n"
                                                                    f"   Tried {max_fallback_attempts} previous windows, none found.\n"
                                                                    f"   No usable candles from API."
                                                                )
                                                        return
                                else:
                                    # No usable candles from API - skip
                                    self.logger.warning(
                                        f"⛔ Skipping signal: No usable candles returned from API for {self.params.segment} at {signal_candle_time}"
                                    )
                                    return
                        except Exception as e:
                            self.logger.warning(f" Error fetching fresh candles from API: {e}")
                            # Fall back to using database candle if available
                            if db_candle:
                                signal_candle_time = db_candle.timestamp
                            else:
                                # No candle available, skip this tick
                                self.logger.warning(" No candle available from DataFrame, database, or API. Skipping this tick.")
                                return
                elif db_candle:
                    # Database candle is recent enough, use it
                    signal_candle_time = db_candle.timestamp
                
                # Log the candle being used
                if db_candle:
                    # Compute bar window based on interval for the database candle,
                    # snapping to exact minute multiples (3/5/15/etc)
                    if isinstance(signal_candle_time, pd.Timestamp):
                        bar_end = signal_candle_time.floor(f"{interval_minutes}min")
                    else:
                        bar_end = pd.Timestamp(signal_candle_time).floor(f"{interval_minutes}min")
                    bar_start = bar_end - timedelta(minutes=interval_minutes)
                    window_str = f"{bar_start.strftime('%H:%M')}–{bar_end.strftime('%H:%M')}"
                    self.logger.info(
                        f" ✅ Using most recent completed candle from database: {signal_candle_time} "
                        f"[Window {window_str}] "
                        f"(O:{db_candle.open:.2f} H:{db_candle.high:.2f} L:{db_candle.low:.2f} C:{db_candle.close:.2f})"
                    )
                
                # If we didn't find a good candle in database, try exact timestamp match
                if not db_candle:
                    db_candle = self.candle_repo.get_candle(
                        segment=self.params.segment,
                        timestamp=signal_candle_time,
                        interval=self.params.time_interval
                    )
                
                # Check if candle is synthetic (all OHLC same) or marked as synthetic
                # If synthetic and enough time has passed, re-fetch real candle from API
                if db_candle:
                    is_synthetic_by_marker = db_candle.is_synthetic
                    is_synthetic_by_ohlc = (db_candle.open == db_candle.high == db_candle.low == db_candle.close)
                    is_synthetic = is_synthetic_by_marker or is_synthetic_by_ohlc
                    
                    # signal_candle_time should always be completed (it's the previous interval)
                    # Check if enough time has passed for candle to be completed
                    time_since_signal_candle = (now - signal_candle_time).total_seconds()
                    candle_completion_time = interval_minutes * 60  # Time needed for candle to complete
                    signal_candle_completed = time_since_signal_candle >= candle_completion_time
                    
                    # IMPORTANT: For completed candles, we should NEVER use synthetic candles
                    # Real market candles CANNOT have all OHLC the same (price must move during the interval)
                    if is_synthetic and signal_candle_completed:
                        self.logger.warning(
                            f" ⚠️ Found synthetic candle for COMPLETED interval {signal_candle_time} "
                            f"(O:{db_candle.open:.2f} H:{db_candle.high:.2f} L:{db_candle.low:.2f} C:{db_candle.close:.2f}). "
                            f"Candle completed {time_since_signal_candle/60:.1f} min ago. "
                            f"❌ REAL CANDLES CANNOT HAVE ALL OHLC SAME - fetching real data from API..."
                        )
                        db_candle = None  # Force re-fetch
                    elif not is_synthetic:
                        # Use real database candle
                        candle = {
                            "open": db_candle.open,
                            "high": db_candle.high,
                            "low": db_candle.low,
                            "close": db_candle.close,
                            "volume": db_candle.volume
                        }
                        self.logger.debug(f" Using real candle from database for {signal_candle_time}")
                    else:
                        # Synthetic candle but not enough time passed - this shouldn't happen for completed candles
                        # If it's a completed candle (time_passed=True), we should have re-fetched above
                        # This branch is only for candles that are still forming (shouldn't happen for signal_candle_time)
                        self.logger.warning(
                            f" ⚠️ Synthetic candle found for {signal_candle_time} but time check failed. "
                            f"Re-fetching from API to ensure real data..."
                        )
                        db_candle = None  # Force re-fetch to be safe
                
                if not candle:
                    # Candle not in database or is synthetic, try to fetch from historical data
                    # Use progressive lookback strategy: try multiple lookback periods
                    try:
                        # Progressive lookback multipliers: try 10, 20, 30, 60 intervals
                        lookback_multipliers = [10, 20, 30, 60]
                        original_signal_candle_time = signal_candle_time
                        found_candle = False
                        
                        for multiplier in lookback_multipliers:
                            if found_candle:
                                break
                                
                            lookback_minutes = interval_minutes * multiplier
                            self.logger.info(
                                f" 🔍 Fetching historical candles with {multiplier}x lookback ({lookback_minutes} minutes) "
                                f"to find candle for {signal_candle_time}..."
                            )
                            
                            fetched = fetch_recent_index_candles(
                                self.kite_client,
                                self.params.segment,
                                self.params.time_interval,
                                lookback_minutes=lookback_minutes
                            )
                            
                            if fetched is not None and not fetched.empty:
                                # Normalize timezone: convert fetched index to timezone-naive if needed
                                fetched_index = fetched.index
                                if getattr(fetched_index, "tz", None) is not None:
                                    # Convert to IST then remove timezone
                                    fetched.index = fetched_index.tz_convert("Asia/Kolkata").tz_localize(None)
                                
                                # Find usable candles: at least interval_minutes old and not synthetic
                                min_age_seconds = interval_minutes * 60  # Candle must be at least one interval old
                                usable_candles = []
                                for ts, row_data in fetched.iterrows():
                                    # ts is the timestamp from the DataFrame index
                                    time_since_ts = (now - ts).total_seconds()
                                    if time_since_ts >= min_age_seconds:  # At least one interval old
                                        # Check if it's not synthetic
                                        is_syn = (row_data['open'] == row_data['high'] == row_data['low'] == row_data['close'])
                                        if not is_syn:
                                            usable_candles.append((ts, row_data))
                                
                                if usable_candles:
                                    # Try to find exact match first
                                    exact_match = None
                                    for ts, row_data in usable_candles:
                                        if ts == signal_candle_time:
                                            exact_match = (ts, row_data)
                                            break
                                    
                                    if exact_match:
                                        # Found exact match
                                        found_ts, row = exact_match
                                        self.logger.info(f" ✅ Found exact candle match: {found_ts}")
                                    else:
                                        # No exact match, use the most recent usable candle
                                        # Prefer candles <= signal_candle_time, but if none, use most recent
                                        available_before = [(ts, row) for ts, row in usable_candles if ts <= signal_candle_time]
                                        if available_before:
                                            found_ts, row = max(available_before, key=lambda x: x[0])
                                            self.logger.info(
                                                f" ✅ Using closest available candle before/at {signal_candle_time}: {found_ts} "
                                                f"(requested: {original_signal_candle_time})"
                                            )
                                        else:
                                            # All usable candles are after signal_candle_time, use most recent one
                                            found_ts, row = max(usable_candles, key=lambda x: x[0])
                                            self.logger.warning(
                                                f" ⚠️ No candles found before {signal_candle_time}, using most recent available: {found_ts} "
                                                f"(requested: {original_signal_candle_time})"
                                            )
                                    
                                    # Update signal_candle_time to use the found candle
                                    signal_candle_time = found_ts
                                    
                                    candle = {
                                        "open": float(row['open']),
                                        "high": float(row['high']),
                                        "low": float(row['low']),
                                        "close": float(row['close']),
                                        "volume": float(row.get('volume', 0.0))
                                    }
                                    
                                    # Check if this is a real candle (OHLC not all same)
                                    is_real_candle = not (candle['open'] == candle['high'] == candle['low'] == candle['close'])
                                    
                                    # For completed candles, if API returns all OHLC same, this might be a data quality issue
                                    # But we should still try to use it if it's the best we have
                                    if not is_real_candle and signal_candle_completed:
                                        self.logger.warning(
                                            f" ⚠️ WARNING: API returned candle with all OHLC same for interval {signal_candle_time}! "
                                            f"This might indicate low volatility or data quality issue. "
                                            f"Candle: O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}. "
                                            f"Will use this candle but signal generation may be limited."
                                        )
                                    
                                    # Save to database and add to DataFrame immediately
                                    self.candle_repo.save_candle(
                                        segment=self.params.segment,
                                        timestamp=signal_candle_time,
                                        interval=self.params.time_interval,
                                        open=candle['open'],
                                        high=candle['high'],
                                        low=candle['low'],
                                        close=candle['close'],
                                        volume=candle['volume'],
                                        is_synthetic=not is_real_candle
                                    )
                                    
                                    # Add to DataFrame immediately so it's available for next tick
                                    if signal_candle_time not in self.df.index:
                                        self.df.loc[signal_candle_time] = candle
                                        self.df = self.df.sort_index()
                                    
                                    if is_real_candle:
                                        self.logger.info(
                                            f" ✅ Fetched and saved REAL candle from API for {signal_candle_time} (added to DataFrame): "
                                            f"O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}"
                                        )
                                    else:
                                        self.logger.warning(
                                            f" ⚠️ Fetched candle from API but all OHLC are same (synthetic-like): {signal_candle_time}"
                                        )
                                    
                                    found_candle = True
                                    break  # Successfully found candle, exit lookback loop
                                else:
                                    # No usable candles found with this lookback, try next multiplier
                                    self.logger.warning(
                                        f" ⚠️ No usable candles found with {multiplier}x lookback. "
                                        f"Trying next lookback period..."
                                    )
                            else:
                                # Fetch returned None or empty, try next multiplier
                                self.logger.warning(
                                    f" ⚠️ Historical fetch returned empty with {multiplier}x lookback. "
                                    f"Trying next lookback period..."
                                )
                        
                        # If we exhausted all lookback attempts without finding a candle,
                        # use the stored last trading day's candles (fetched at startup)
                        if not found_candle:
                            self.logger.warning(
                                f" ⚠️ Could not find any usable candle after trying all lookback periods "
                                f"(up to {interval_minutes * 60} minutes) for {original_signal_candle_time}. "
                                f"Using stored last trading day's candles..."
                            )
                            
                            # Use stored last trading day candles (fetched at startup)
                            if hasattr(self, '_last_trading_day_candles') and not self._last_trading_day_candles.empty:
                                fetched_last_day = self._last_trading_day_candles
                                self.logger.info(
                                    f" ✅ Using {len(fetched_last_day)} pre-fetched candles from last trading day "
                                    f"({fetched_last_day.index[0]} to {fetched_last_day.index[-1]})"
                                )
                            else:
                                # Fallback: try to fetch now if not stored (shouldn't happen if startup worked)
                                self.logger.warning("⚠️ Last trading day candles not stored, fetching now...")
                                from src.api.live_data import fetch_last_trading_day_candles
                                fetched_last_day = fetch_last_trading_day_candles(
                                    self.kite_client,
                                    self.params.segment,
                                    self.params.time_interval
                                )
                            
                            if fetched_last_day is not None and not fetched_last_day.empty:
                                # Normalize timezone: convert fetched index to timezone-naive if needed
                                fetched_last_day_index = fetched_last_day.index
                                if getattr(fetched_last_day_index, "tz", None) is not None:
                                    # Convert to IST then remove timezone
                                    fetched_last_day.index = fetched_last_day_index.tz_convert("Asia/Kolkata").tz_localize(None)
                                
                                # Find usable candles: not synthetic (all candles from last trading day are already completed)
                                usable_candles = []
                                for ts, row_data in fetched_last_day.iterrows():
                                    # Check if it's not synthetic
                                    is_syn = (row_data['open'] == row_data['high'] == row_data['low'] == row_data['close'])
                                    if not is_syn:
                                        usable_candles.append((ts, row_data))
                                
                                if usable_candles:
                                    # Use the most recent usable candle from last trading day (last candle of the day)
                                    found_ts, row = max(usable_candles, key=lambda x: x[0])
                                    
                                    # CRITICAL FIX: Do NOT update signal_candle_time to yesterday's timestamp!
                                    # We only use yesterday's candle DATA, but keep signal_candle_time as TODAY's time
                                    # This ensures signal generation uses today's timestamp, not yesterday's
                                    # The candle data will be used for calculations, but timestamp remains today
                                    
                                    self.logger.warning(
                                        f" ⚠️ Using last trading day candle DATA (from {found_ts}) for TODAY's signal candle time ({original_signal_candle_time}). "
                                        f"This is a fallback - signal timestamp remains {original_signal_candle_time} (today)."
                                    )
                                    
                                    # Keep signal_candle_time as original (today), don't change it to yesterday
                                    # signal_candle_time remains as original_signal_candle_time
                                    
                                    candle = {
                                        "open": float(row['open']),
                                        "high": float(row['high']),
                                        "low": float(row['low']),
                                        "close": float(row['close']),
                                        "volume": float(row.get('volume', 0.0))
                                    }
                                    
                                    # Check if this is a real candle (OHLC not all same)
                                    is_real_candle = not (candle['open'] == candle['high'] == candle['low'] == candle['close'])
                                    
                                    if not is_real_candle:
                                        self.logger.warning(
                                            f" ⚠️ WARNING: Last trading day candle has all OHLC same for interval {found_ts}! "
                                            f"This might indicate low volatility or data quality issue."
                                        )
                                    
                                    # Save the candle with TODAY's timestamp (not yesterday's)
                                    # This ensures the DataFrame uses today's timestamp for signal generation
                                    # Save with TODAY's timestamp and add to DataFrame immediately
                                    self.candle_repo.save_candle(
                                        segment=self.params.segment,
                                        timestamp=original_signal_candle_time,  # Use TODAY's timestamp, not yesterday's
                                        interval=self.params.time_interval,
                                        open=candle['open'],
                                        high=candle['high'],
                                        low=candle['low'],
                                        close=candle['close'],
                                        volume=candle['volume'],
                                        is_synthetic=not is_real_candle
                                    )
                                    
                                    # Add to DataFrame immediately so it's available for next tick
                                    if original_signal_candle_time not in self.df.index:
                                        self.df.loc[original_signal_candle_time] = candle
                                        self.df = self.df.sort_index()
                                    
                                    if is_real_candle:
                                        self.logger.info(
                                            f" ✅ Using last trading day candle DATA (from {found_ts}) for TODAY's signal candle ({original_signal_candle_time}): "
                                            f"O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}"
                                        )
                                    else:
                                        self.logger.warning(
                                            f" ⚠️ Fetched candle from last trading day but all OHLC are same (synthetic-like): {signal_candle_time}"
                                        )
                                    
                                    found_candle = True
                                else:
                                    self.logger.error(
                                        f" ❌ No usable candles found in last trading day data for {original_signal_candle_time}!"
                                    )
                            else:
                                self.logger.error(
                                    f" ❌ Failed to fetch last trading day candles for {original_signal_candle_time}!"
                                )
                        
                        # Final check: if still no candle found, we must skip this tick
                        if not found_candle:
                            self.logger.error(
                                f" ❌ CRITICAL: Could not find any usable candle after trying all lookback periods "
                                f"and last trading day for {original_signal_candle_time}! "
                                f"Cannot generate signals without real candle data. Skipping this tick."
                            )
                            return  # Skip this tick - we can't proceed without real candle data
                            
                    except Exception as e:
                        # This is a critical error - we can't proceed without real candle data
                        self.logger.error(
                            f" ❌ CRITICAL: Error fetching historical candle for {signal_candle_time}: {e}. "
                            f"Cannot generate signals without real candle data. Skipping this tick.",
                            exc_info=True
                        )
                        return  # Skip this tick - we can't proceed without real candle data
                
                # At this point, we should have a candle for signal_candle_time
                # If we don't have a candle, we can't proceed
                if not candle:
                    self.logger.error(
                        f" ❌ CRITICAL: No candle available for {signal_candle_time}! "
                        f"Cannot generate signals without candle data. Skipping this tick."
                    )
                    return  # Skip this tick - we can't proceed without candle data
                
                # Check if candle is synthetic (all OHLC same)
                is_synthetic_candle = (candle['open'] == candle['high'] == candle['low'] == candle['close'])
                
                # For completed candles, if it's synthetic, we'll still use it but with a warning
                # This handles cases where API returns low-volatility candles (all OHLC same)
                # The signal generation logic will handle this appropriately
                if is_synthetic_candle and signal_candle_completed:
                    self.logger.warning(
                        f" ⚠️ Using synthetic candle for COMPLETED interval {signal_candle_time} "
                        f"(O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}). "
                        f"This might indicate low volatility period. Signal generation may be limited."
                    )
                    # Continue anyway - let the signal generation logic handle it
                elif is_synthetic_candle:
                    self.logger.warning(
                        f" ⚠️ Using synthetic candle for {signal_candle_time} (not completed yet). "
                        f"This shouldn't happen for signal generation."
                    )
                
                # Add the completed candle to DataFrame for signal generation
                # Use signal_candle_time (last completed) instead of rounded_time (current forming)
                if signal_candle_time not in self.df.index:
                    self.df.loc[signal_candle_time] = candle
                    self.logger.debug(f" ✅ Added completed candle to DataFrame: {signal_candle_time} (O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f})")
                
                # Sort DataFrame by index to ensure chronological order
                self.df = self.df.sort_index()
                
                # Find index of signal_candle_time (the last completed candle we're using for signals)
                if signal_candle_time in self.df.index:
                    idx = self.df.index.get_loc(signal_candle_time)
                else:
                    # Fallback: use last index
                    idx = len(self.df) - 1
                    self.logger.warning(f" ⚠️ signal_candle_time {signal_candle_time} not in DataFrame, using last index {idx}")
                
                # Store the latest candle time being used for signal generation (for logging)
                self._last_signal_candle_time = signal_candle_time
                
                # Need at least max(rsi_period, volume_strength_wma) candles for Price Strength and Volume Strength
                # RSI needs rsi_period candles, then EMA needs price_strength_ema more, WMA needs volume_strength_wma more
                # The limiting factor is volume_strength_wma since it needs the most candles
                min_candles_needed = max(self.strategy.volume_strength_wma, self.strategy.rsi_period + self.strategy.price_strength_ema)
                if idx < min_candles_needed:
                    self.logger.info(f" Building data history: {idx + 1}/{min_candles_needed} candles collected (need {min_candles_needed} for Price Strength and Volume Strength calculation)")
                    return

                # Calculate RSI for logging
                try:
                    rsi_values = self.strategy.calculate_rsi(self.df['close'], self.strategy.rsi_period)
                    current_rsi = rsi_values.iloc[idx] if not pd.isna(rsi_values.iloc[idx]) else None
                    if current_rsi is not None:
                        self.logger.info(f" 📊 Strategy Analysis - RSI: {current_rsi:.2f}, Price: ₹{price:.2f}, Candles: {idx + 1}")
                except Exception as e:
                    self.logger.warning(f" Could not calculate RSI: {e}")

                # Exit / pyramiding management - Check all open positions
                # In LIVE mode, check Kite API first (source of truth), then sync with internal state
                open_positions = []
                mode_name = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
                
                if isinstance(self.execution, LiveExecutionClient):
                    # LIVE mode: Check Kite API for actual positions
                    try:
                        for opt_type in [OptionType.CE, OptionType.PE]:
                            kite_pos = self.execution.check_kite_position_by_option_type(
                                self.params.segment,
                                opt_type.value
                            )
                            if kite_pos:
                                # Position exists in Kite - ensure it's tracked internally
                                if not self.agent._has_position(opt_type):
                                    # Position in Kite but not in internal state - log warning
                                    self.logger.warning(
                                        f"⚠️ Position mismatch: {opt_type.value} exists in Kite but not in internal state. "
                                        f"Syncing..."
                                    )
                                open_positions.append(opt_type)
                            else:
                                # No position in Kite - clear from internal state if exists
                                if self.agent._has_position(opt_type):
                                    self.logger.warning(
                                        f"⚠️ Position mismatch: {opt_type.value} in internal state but not in Kite. "
                                        f"Clearing stale position..."
                                    )
                                    self.agent.positions[opt_type] = None
                                    if self.agent.current_position == opt_type:
                                        self.agent.current_position = None
                    except Exception as e:
                        # If Kite check fails, fall back to internal state
                        self.logger.warning(
                            f"⚠️ Error checking Kite positions, using internal state: {e}"
                        )
                        for opt_type in [OptionType.CE, OptionType.PE]:
                            if self.agent._has_position(opt_type):
                                open_positions.append(opt_type)
                else:
                    # PAPER mode: Use internal state only
                    for opt_type in [OptionType.CE, OptionType.PE]:
                        if self.agent._has_position(opt_type):
                            open_positions.append(opt_type)
                
                if open_positions:
                    mode_name = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
                    for opt_type in open_positions:
                        pos = self.agent._get_position(opt_type)
                        entry_strike = pos.get('entry_strike', 'N/A') if pos else 'N/A'
                        self.logger.debug(
                            f" 🔍 Monitoring: Checking exit conditions for {mode_name} {opt_type.value} position: "
                            f"strike={entry_strike} (checking every {self._tick_interval_seconds//60} min)"
                        )
                        # Check exit for this specific position
                        should_exit, exit_reason, exit_option_type = self.agent.check_exit_conditions(price, now, opt_type)
                        if should_exit:
                            self._handle_exit(price, now, exit_option_type)
                        else:
                            # Check pyramiding for this position (only if no exit)
                            self._check_pyramiding(price, opt_type)
                            # Update position in CSV (every 5 minutes or on events)
                            # Note: Trailing SL update happens here, but monitoring checks every monitoring_interval
                            self._update_open_position_in_csv(price, now, opt_type)

                # Entry management - Always scan for entry signals (will be blocked if same option type is open)
                mode_name = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
                if open_positions:
                    open_types_str = ", ".join([opt.value for opt in open_positions])
                    self.logger.info(f" 🔍 Scanning for entry signals in {mode_name} mode (Open positions: {open_types_str})...")
                else:
                    self.logger.info(f" 🔍 Scanning for entry signals in {mode_name} mode (No open positions)...")
                self._handle_entry(price, now, idx)
        except Exception as e:
            # Log error gracefully with context
            error_msg = str(e)
            error_type = type(e).__name__
            segment_name = getattr(self.params, 'segment', 'UNKNOWN')
            self.logger.error(
                f" ❌ Error in _tick for {segment_name}: {error_type}: {error_msg}",
                exc_info=False  # Set to True for full traceback if needed for debugging
            )
            # Log additional context if available
            try:
                if hasattr(self, 'agent') and self.agent:
                    open_positions = []
                    for opt_type in [OptionType.CE, OptionType.PE]:
                        if self.agent._has_position(opt_type):
                            open_positions.append(opt_type.value)
                    if open_positions:
                        self.logger.debug(f"   Context: Open positions: {', '.join(open_positions)}")
            except:
                pass  # Don't fail on context logging
    
    def _load_expiry_config(self) -> Optional[Dict]:
        """Load expiry configuration from config.json (same as backtesting)"""
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
                self.logger.warning(f"Could not load expiry config: {e}, using defaults")
                self._expiry_config = {
                    "BANKNIFTY": {"duration": "Monthly", "day_of_week": "Thursday"},
                    "NIFTY": {"duration": "Weekly", "day_of_week": "Tuesday"},
                    "SENSEX": {"duration": "Weekly", "day_of_week": "Thursday"}
                }
        return self._expiry_config
    
    def _get_expiry_date(self, timestamp: datetime) -> Optional[str]:
        """
        Get expiry date for current segment with threshold-based switching.
        
        For all segments (NIFTY, SENSEX, BANKNIFTY):
        - If days to current expiry <= min_days_to_expiry threshold, switch to next expiry
        - Weekly expiries (NIFTY, SENSEX): switch to next week's expiry (7 days later)
        - Monthly expiries (BANKNIFTY): switch to next month's expiry (last weekday of next month)
        - Otherwise, use current expiry
        """
        try:
            from src.utils.premium_fetcher import get_expiry_date
            from datetime import timedelta
            import calendar
            
            expiry_config = self._load_expiry_config()
            segment_config = expiry_config.get(self.params.segment.upper(), {})
            segment_upper = self.params.segment.upper()
            
            # Get the current expiry date
            expiry_date = get_expiry_date(
                timestamp,
                segment_config.get("duration", "Weekly"),
                segment_config.get("day_of_week", "Thursday")
            )
            
            if not expiry_date:
                return None
            
            # Check if threshold is configured for this segment
            duration = segment_config.get("duration", "Weekly")
            min_days = segment_config.get("min_days_to_expiry")
            
            if min_days is not None:
                # Calculate days to current expiry
                days_to_expiry = self._calculate_days_to_expiry(timestamp, expiry_date.strftime("%Y-%m-%d"))
                
                # If days <= threshold, switch to next expiry
                if days_to_expiry <= min_days:
                    if duration == "Weekly":
                        # For weekly expiries, next expiry is simply 7 days after current expiry
                        next_expiry_date = expiry_date.date() + timedelta(days=7)
                        next_expiry_datetime = datetime.combine(next_expiry_date, datetime.min.time())
                    else:
                        # For monthly expiries, get next month's last weekday
                        day_of_week = segment_config.get("day_of_week", "Thursday")
                        day_map = {
                            "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
                            "Friday": 4, "Saturday": 5, "Sunday": 6
                        }
                        target_wd = day_map.get(day_of_week.capitalize(), 3)
                        
                        # Calculate next month
                        current_date = expiry_date.date()
                        if current_date.month == 12:
                            next_year, next_month = current_date.year + 1, 1
                        else:
                            next_year, next_month = current_date.year, current_date.month + 1
                        
                        # Get last weekday of next month
                        last_day = calendar.monthrange(next_year, next_month)[1]
                        d = date(next_year, next_month, last_day)
                        while d.weekday() != target_wd:
                            d -= timedelta(days=1)
                        next_expiry_date = d
                        next_expiry_datetime = datetime.combine(next_expiry_date, datetime.min.time())
                    
                    self.logger.info(
                        f"⏭️  Expiry switch: {segment_upper} current expiry {expiry_date.strftime('%Y-%m-%d')} "
                        f"has {days_to_expiry} days remaining (threshold: {min_days}). "
                        f"Switching to next expiry: {next_expiry_datetime.strftime('%Y-%m-%d')}"
                    )
                    return next_expiry_datetime.strftime("%Y-%m-%d")
            
            # Return current expiry (either no threshold check needed, or threshold not met)
            return expiry_date.strftime("%Y-%m-%d")
        except Exception as e:
            self.logger.warning(f"Could not calculate expiry date: {e}")
        return None
    
    def _calculate_days_to_expiry(self, timestamp: datetime, expiry: Optional[str]) -> int:
        """Calculate days to expiry (same as backtesting)"""
        if not expiry:
            return 0
        try:
            expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            current_date = timestamp.date()
            days = (expiry_date - current_date).days
            return max(0, days)
        except Exception as e:
            self.logger.warning(f"Could not calculate days to expiry: {e}")
            return 0
    
    def _fetch_option_premium_from_kite(
        self,
        strike: int,
        option_type: str,
        timestamp: datetime,
        expiry_override: Optional[str] = None
    ) -> Optional[Tuple[float, Dict]]:
        """Fetch actual option premium from Kite API (same as backtesting)"""
        try:
            if not self.kite_client:
                return None
            
            # Check authentication status
            if self._kite_authenticated is None:
                self._kite_authenticated = self.kite_client.is_authenticated()
            
            if not self._kite_authenticated:
                return None
            
            # Get expiry date (use override if provided)
            expiry = expiry_override or self._get_expiry_date(timestamp)
            if not expiry:
                return None
            
            # Use the premium fetcher utility (same as backtesting)
            from src.utils.premium_fetcher import fetch_premium_by_params
            
            result = fetch_premium_by_params(
                self.kite_client,
                self.params.segment,
                strike,
                option_type,
                expiry,
                timestamp,
                exchange="NFO",  # Will be auto-detected in fetch_premium_by_params
                window_minutes=10,
                interval="5minute",
                expiry_config=self._load_expiry_config()
            )
            
            if result:
                premium, instrument_details = result
                return (premium, instrument_details)
        except Exception as e:
            self.logger.debug(f"Error fetching option premium from Kite: {e}")
        return None
    
    def _estimate_option_premium(
        self,
        spot_price: float,
        strike: int,
        option_type: str,
        timestamp: datetime,
        expiry_override: Optional[str] = None
    ) -> Tuple[float, str]:
        """Get option premium - tries Kite API first, falls back to estimation (same as backtesting)"""
        # Try Kite API first
        kite_result = self._fetch_option_premium_from_kite(strike, option_type, timestamp, expiry_override)
        if kite_result is not None:
            premium, instrument_details = kite_result
            return (premium, "Kite API")
        
        # Fallback to estimation (same formula as backtesting)
        expiry = self._get_expiry_date(timestamp)
        days_to_expiry = self._calculate_days_to_expiry(timestamp, expiry)
        
        # Intrinsic value
        if option_type.upper() == "CE":
            intrinsic = max(0, spot_price - strike)
        else:  # PE
            intrinsic = max(0, strike - spot_price)
        
        # Time value estimation (simplified)
        # Use segment-specific volatility estimates
        volatility_multiplier = {
            "NIFTY": 0.5,
            "BANKNIFTY": 0.8,
            "SENSEX": 0.6
        }.get(self.params.segment.upper(), 0.5)
        
        time_value = intrinsic * 0.1 * volatility_multiplier * (1 + days_to_expiry / 7)
        premium = intrinsic + time_value
        
        return (premium, "Estimated")

    def _handle_entry(self, price: float, timestamp: datetime, idx: int) -> None:
        max_trades = int(self.risk_limits.get("max_trades_per_day", 100))
        if self.trades_taken_today >= max_trades:
            self.logger.info(f" ⚠️ Max trades limit reached ({self.trades_taken_today}/{max_trades}) - skipping signal check")
            return

        # Note: SL order status check for opposite option type will be done after we know which option_type we're entering

        # Check if we're in re-entry mode after SL hit (initial check - will be updated after signal generation)
        allow_reentry = self.agent.waiting_for_reentry
        reentry_candle_type = self.agent.reentry_candle_type
        
        if allow_reentry:
            self.logger.info(f" 🔄 Re-entry mode active: waiting for {reentry_candle_type} candle")

        # Fetch 1-minute candles for multi-timeframe confirmation
        df_1min = None
        try:
            from src.api.live_data import fetch_recent_index_candles
            df_1min = fetch_recent_index_candles(
                self.kite_client,
                self.params.segment,
                interval="1minute",
                lookback_minutes=30  # Get last 30 minutes of 1-minute candles
            )
            if df_1min is not None and len(df_1min) > 0:
                self.logger.debug(f"Fetched {len(df_1min)} 1-minute candles for multi-timeframe confirmation")
            else:
                self.logger.debug("No 1-minute candles available (will proceed with 5-minute only)")
        except Exception as e:
            self.logger.warning(f"Error fetching 1-minute candles for multi-timeframe confirmation: {e}. Proceeding with 5-minute only.")
        
        # Generate signal with re-entry support and multi-timeframe confirmation
        signal, option_type, reason, eval_details = self.strategy.generate_signal(
            self.df, 
            idx,
            allow_reentry=allow_reentry,
            reentry_candle_type=reentry_candle_type,
            df_1min=df_1min
        )
        
        # Check for strangle position (both CE and PE open) - check after we know option_type
        has_ce_position = self.agent._has_position(OptionType.CE)
        has_pe_position = self.agent._has_position(OptionType.PE)
        is_strangle = has_ce_position and has_pe_position
        
        # For strangle: Update re-entry mode check based on the specific option type signal
        if is_strangle and option_type is not None:
            # Check re-entry mode for the specific option type being entered
            option_reentry_mode = self.agent.reentry_mode.get(option_type, {})
            allow_reentry = option_reentry_mode.get("waiting", False)
            reentry_candle_type = option_reentry_mode.get("candle_type")
            
            if allow_reentry:
                self.logger.info(
                    f" 🔄 Re-entry mode active for {option_type.value}: waiting for {reentry_candle_type} candle "
                    f"(strangle exists, other side still open)"
                )
        
        # Get the latest candle time being used (from signal_candle_time in _tick)
        # We need to pass this to ensure we log the correct candle timestamp
        latest_candle_time = None
        if hasattr(self, '_last_signal_candle_time'):
            latest_candle_time = self._last_signal_candle_time
        elif idx < len(self.df):
            latest_candle_time = self.df.index[idx]
        
        self._log_entry_checks(eval_details, signal, current_price=price, latest_candle_time=latest_candle_time)
        
        # Log signal generation result with trade regime context
        if signal in (TradeSignal.BUY_CE, TradeSignal.BUY_PE):
            # Determine actual trade action based on trade regime
            if signal == TradeSignal.BUY_CE:
                trade_action = "SELL_CE" if self.trade_regime == "Sell" else "BUY_CE"
            else:  # BUY_PE
                trade_action = "SELL_PE" if self.trade_regime == "Sell" else "BUY_PE"
            
            if allow_reentry:
                self.logger.info(f" ✅ RE-ENTRY SIGNAL: {trade_action} ({option_type.value}) [Trade Regime: {self.trade_regime}] - {reason}")
            else:
                self.logger.info(f" ✅ SIGNAL GENERATED: {trade_action} ({option_type.value}) [Trade Regime: {self.trade_regime}] - {reason}")
        else:
            self.logger.info(f" ⏸️ No entry signal: {signal.value} [Trade Regime: {self.trade_regime}] - {reason}")
            return

        if option_type is None:
            self.logger.warning(f" Signal generated but option_type is None")
            return
        
        # Check if this specific option type is already open (prevent duplicate option types)
        # First check internal state
        if self.agent._has_position(option_type):
            mode_name = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
            existing_pos = self.agent._get_position(option_type)
            existing_strike = existing_pos.get('entry_strike', 'N/A') if existing_pos else 'N/A'
            self.logger.info(
                f" ⚠️ {option_type.value} position already open in {mode_name} mode "
                f"(strike={existing_strike}). Skipping new {option_type.value} entry signal. "
                f"(Note: CE and PE can be open simultaneously)"
            )
            return
        
        # In LIVE mode, also check Kite API to verify actual positions
        if isinstance(self.execution, LiveExecutionClient):
            try:
                # Use configured segment string from params (e.g. "NIFTY", "BANKNIFTY")
                kite_position = self.execution.check_kite_position_by_option_type(
                    self.params.segment,
                    option_type.value
                )
                if kite_position:
                    tradingsymbol = kite_position.get('tradingsymbol', 'N/A')
                    quantity = int(kite_position.get('quantity', 0))
                    exchange = kite_position.get('exchange', 'N/A')
                    self.logger.warning(
                        f" ⛔ BLOCKING ENTRY: {option_type.value} position already exists in Kite! "
                        f"{exchange}:{tradingsymbol} with quantity={quantity}. "
                        f"Skipping new {option_type.value} entry signal to prevent duplicate position."
                    )
                    return
            except Exception as e:
                # Log error gracefully but don't block entry if check fails
                self.logger.error(
                    f" ⚠️ Error checking Kite positions for {option_type.value} before entry: {e}. "
                    f"Proceeding with entry check based on internal state only.",
                    exc_info=False  # Don't log full traceback for API errors
                )
                # Continue with entry - internal state check already passed
        
        # In Sell Regime, check for open trades with tag="S0002" and product="MIS" on the same side
        if self.trade_regime == "Sell" and isinstance(self.execution, LiveExecutionClient):
            try:
                has_open_trade = self.execution.check_open_trade_with_tag_and_product(
                    segment=self.params.segment,
                    option_type=option_type.value,
                    tag="S0002",
                    product="MIS"
                )
                if has_open_trade:
                    self.logger.warning(
                        f" ⛔ BLOCKING ENTRY (Sell Regime): {option_type.value} trade already open in Kite "
                        f"with tag='S0002' and product='MIS' for {self.segment_cfg.segment}. "
                        f"Skipping new {option_type.value} entry signal to prevent duplicate trade on same side."
                    )
                    return
            except Exception as e:
                # Log error gracefully but don't block entry if check fails
                self.logger.error(
                    f" ⚠️ Error checking open trades with tag='S0002' for {option_type.value} before entry: {e}. "
                    f"Proceeding with entry check.",
                    exc_info=False  # Don't log full traceback for API errors
                )
                # Continue with entry - fail open
        
        # Check for strangle position (both CE and PE open simultaneously)
        # In Sell regime: If strangle exists, block all new entries until one side closes
        opposite_option_type = OptionType.PE if option_type == OptionType.CE else OptionType.CE
        has_ce_position = self.agent._has_position(OptionType.CE)
        has_pe_position = self.agent._has_position(OptionType.PE)
        is_strangle = has_ce_position and has_pe_position
        
        if is_strangle and self.trade_regime == "Sell":
            # Strangle exists in Sell regime - block all new entries
            # Only allow re-entry on the side where SL hit
            if allow_reentry:
                # Check if re-entry is for the correct side (where SL hit)
                # reentry_candle_type indicates which side: 'bearish' = PE, 'bullish' = CE
                if reentry_candle_type == 'bearish' and option_type == OptionType.PE:
                    # PE re-entry allowed (PE SL hit)
                    self.logger.info(
                        f"✅ Allowing PE re-entry - strangle exists but PE SL hit, "
                        f"CE position still open (strike={self.agent._get_position(OptionType.CE).get('entry_strike', 'N/A')})"
                    )
                elif reentry_candle_type == 'bullish' and option_type == OptionType.CE:
                    # CE re-entry allowed (CE SL hit)
                    self.logger.info(
                        f"✅ Allowing CE re-entry - strangle exists but CE SL hit, "
                        f"PE position still open (strike={self.agent._get_position(OptionType.PE).get('entry_strike', 'N/A')})"
                    )
                else:
                    # Re-entry signal for wrong side - block it
                    self.logger.warning(
                        f"⛔ BLOCKED: Strangle exists (CE and PE both open). "
                        f"Re-entry signal for {option_type.value} but waiting for {reentry_candle_type} candle "
                        f"(mismatch). Only re-entry on the side where SL hit is allowed."
                    )
                    return
            else:
                # Normal entry attempt while strangle exists - block it
                ce_strike = self.agent._get_position(OptionType.CE).get('entry_strike', 'N/A') if has_ce_position else 'N/A'
                pe_strike = self.agent._get_position(OptionType.PE).get('entry_strike', 'N/A') if has_pe_position else 'N/A'
                self.logger.warning(
                    f"⛔ BLOCKED: Cannot take new {option_type.value} entry - strangle exists "
                    f"(CE strike={ce_strike}, PE strike={pe_strike}). "
                    f"System will monitor both positions and their SL status. "
                    f"New entry will only be allowed after one side's SL hits."
                )
                return
        elif isinstance(self.execution, LiveExecutionClient) and self.agent._has_position(opposite_option_type):
            # Only one side open - allow strangle creation (normal case)
            opposite_pos = self.agent._get_position(opposite_option_type)
            if opposite_pos:
                opposite_strike = opposite_pos.get('entry_strike', 'N/A')
                self.logger.info(
                    f"✅ Allowing {option_type.value} entry to create strangle - "
                    f"opposite {opposite_option_type.value} position is open (strike={opposite_strike})"
                )
        
        # If re-entry signal is generated, clear re-entry mode
        if allow_reentry and signal in [TradeSignal.BUY_CE, TradeSignal.BUY_PE]:
            self.agent.clear_reentry_mode()
            self.logger.info(f" ✅ Re-entry executed: {signal.value} - {reason}")

        # Determine ITM option and lot size (use segment config ITM offset)
        strike = select_itm_strike(price, self.params.segment, self.segment_cfg.itm_offset, option_type.value)
        lots = 1  # For now always 1 lot; quantity is handled via segment config
        quantity = self.segment_cfg.lot_size * lots

        # Compute expiry using config and build proper trading symbol
        expiry_str = self._get_expiry_date(timestamp)
        expiry_cfg = self._load_expiry_config()
        trading_symbol = None
        if expiry_str:
            try:
                trading_symbol = build_tradingsymbol(
                    self.params.segment,
                    strike,
                    option_type.value,
                    expiry_str,
                    expiry_cfg,
                )
            except Exception as e:
                self.logger.debug(f"Could not build trading symbol: {e}")

        # Fetch option premium from Kite API (like backtesting)
        entry_premium, entry_premium_source = self._estimate_option_premium(
            price,  # spot price
            strike,
            option_type.value,
            timestamp,
            expiry_override=expiry_str
        )
        
        self.logger.info(
            f" 📊 Option Premium: Strike={strike} {option_type.value}, "
            f"Premium=₹{entry_premium:.2f} (Source: {entry_premium_source}), "
            f"Spot=₹{price:.2f}"
        )

        # Final safety check: Ensure this specific option type is not already open
        if self.agent._has_position(option_type):
            mode_name = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
            existing_pos = self.agent._get_position(option_type)
            existing_strike = existing_pos.get('entry_strike', 'N/A') if existing_pos else 'N/A'
            self.logger.error(
                f" ⛔ CRITICAL: Attempted {option_type.value} entry while {option_type.value} position is open! "
                f"({mode_name} mode - strike={existing_strike}) - Entry blocked"
            )
            return

        # Enter trade logically using OPTION PREMIUM (not spot price)
        # Agent tracks premium internally for P&L calculation
        entry_result = self.agent.enter_trade(
            signal=signal, 
            option_type=option_type, 
            price=entry_premium,  # Use premium instead of spot
            timestamp=timestamp, 
            reason=reason
        )
        if not entry_result.get("success"):
            failure_reason = entry_result.get("reason", "Unknown")
            mode_name = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
            self.logger.warning(f" ⛔ Entry failed in {mode_name} mode: {failure_reason}")
            return
        
        # Store premium information
        self.agent.entry_premium = entry_premium
        self.agent.entry_premium_source = entry_premium_source
        # Initialize lowest_premium for Sell regime trailing stops
        if self.trade_regime == "Sell":
            self.agent.lowest_premium = entry_premium
        # Initialize lowest_premium for Sell regime trailing stops
        if self.trade_regime == "Sell":
            self.agent.lowest_premium = entry_premium

        # Place actual order if in LIVE mode
        sl_order_id = None
        if isinstance(self.execution, LiveExecutionClient):
            try:
                order_result = self.execution.place_entry_order(
                    segment=self.params.segment,
                    strike=strike,
                    option_type=option_type.value,
                    quantity=quantity,
                    expiry=expiry_str,  # Use calculated expiry (with threshold-based switching)
                    trade_regime=self.trade_regime,  # Pass trade regime for order type
                    time_interval=self.params.time_interval
                )
                # Check if order was successful
                if not order_result.get("success", True):  # Default to True for backward compatibility
                    failure_reason = order_result.get("reason", "Unknown error")
                    self.logger.error(
                        f"⛔ Entry order failed: {failure_reason}. Skipping trade entry."
                    )
                    return
                
                # Update entry price from actual order execution
                if order_result.get("entry_price", 0) > 0:
                    entry_result["entry_price"] = order_result["entry_price"]
                self._position_key = f"{self.params.segment}_{strike}_{option_type.value}"
                
                # Determine actual trade action for logging
                if signal == TradeSignal.BUY_CE:
                    trade_action = "SELL_CE" if self.trade_regime == "Sell" else "BUY_CE"
                else:  # BUY_PE
                    trade_action = "SELL_PE" if self.trade_regime == "Sell" else "BUY_PE"
                
                # Safely format entry_price (handle None case)
                entry_price_val = order_result.get('entry_price')
                entry_price_str = f"₹{entry_price_val:.2f}" if entry_price_val is not None else "N/A"
                
                self.logger.warning(
                    f"✅ LIVE ENTRY ORDER PLACED: {trade_action} ({order_result.get('tradingsymbol', 'N/A')}) "
                    f"@ {entry_price_str} | Order ID: {order_result.get('order_id', 'N/A')}"
                )
                
                # Calculate initial SL price based on PREMIUM (not spot) and trade regime
                # Use segment-specific stop_loss from segment_cfg
                entry_premium_val = entry_result.get('entry_price', entry_premium)
                segment_stop_loss = self.segment_cfg.stop_loss
                # Buy: SL = entry_premium - stop_loss (premium drops below entry - SL)
                # Sell: SL = entry_premium + (stop_loss% / 100 * entry_premium) (percentage-based)
                if self.trade_regime == "Buy":
                    initial_sl_price = entry_premium_val - segment_stop_loss
                else:  # Sell - percentage-based SL
                    sl_amount = (segment_stop_loss / 100.0) * entry_premium_val
                    initial_sl_price = entry_premium_val + sl_amount
                    self.logger.info(
                        f"📊 Sell Regime SL Calculation: Premium=₹{entry_premium_val:.2f}, "
                        f"SL%={segment_stop_loss:.1f}%, SL Amount=₹{sl_amount:.2f}, "
                        f"Initial SL=₹{initial_sl_price:.2f}"
                    )
                
                # Place SL order IMMEDIATELY after entry order
                sl_order_id = self.execution.place_stop_loss_order(
                    position_key=self._position_key,
                    stop_loss_price=initial_sl_price,
                    trade_regime=self.trade_regime
                )
                
                if sl_order_id:
                    self.logger.warning(
                        f"🛡️ STOP LOSS ORDER PLACED: SL Trigger @ ₹{initial_sl_price:.2f} "
                        f"| Order ID: {sl_order_id}"
                    )
                else:
                    self.logger.error(f"❌ FAILED TO PLACE STOP LOSS ORDER for {self._position_key}")
                    
            except Exception as e:
                self.logger.error(f"Failed to place LIVE entry order: {e}", exc_info=True)
                # Exit the logical trade if order placement fails
                self.agent.exit_trade(exit_price=price, exit_time=timestamp, reason=f"Order placement failed: {str(e)}")
                return

        self.trades_taken_today += 1
        
        # Log entry with clear indication that position is OPEN (using premium)
        entry_premium_val = entry_result.get('entry_price', entry_premium)
        
        # Determine actual trade action for logging
        if signal == TradeSignal.BUY_CE:
            trade_action = "SELL_CE" if self.trade_regime == "Sell" else "BUY_CE"
        else:  # BUY_PE
            trade_action = "SELL_PE" if self.trade_regime == "Sell" else "BUY_PE"
        
        self.logger.info(
            f" ✅ POSITION OPENED: {trade_action} ({option_type.value}) strike={strike} "
            f"Premium=₹{entry_premium_val:.2f} (Source: {entry_premium_source}), "
            f"Spot=₹{price:.2f}, qty={quantity}, lots={lots}, reason={reason}"
        )
        
        # Reset pyramiding counter for new position
        self._pyramiding_count = 0
        self._last_position_update_time = timestamp
        
        # Calculate initial SL price based on PREMIUM (not spot) and trade regime
        # Buy: SL = entry_premium - stop_loss (premium drops below entry - SL)
        # Sell: SL = entry_premium + (stop_loss% / 100 * entry_premium) (percentage-based)
        if self.trade_regime == "Buy":
            initial_sl_price = entry_premium_val - self.params.stop_loss
        else:  # Sell - percentage-based SL
            sl_amount = (self.params.stop_loss / 100.0) * entry_premium_val
            initial_sl_price = entry_premium_val + sl_amount
        current_sl_price = initial_sl_price
        
        # Log open position to CSV immediately
        mode = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
        option_symbol = (
            trading_symbol
            or f"{self.params.segment}{strike}{option_type.value}"
        )
        position_record = OpenPositionRecord(
            segment=self.params.segment,
            mode=mode,
            status="OPEN",
            signal_type=f"{self.trade_regime.upper()}_{option_type.value}",
            option_symbol=option_symbol,
            option_type=option_type.value,
            strike_price=float(strike),
            expiry=expiry_str or "",
            entry_time=timestamp,
            entry_price=float(entry_premium_val),  # Use premium, not spot
            current_price=float(entry_premium_val),  # Use premium for current price tracking
            current_lots=int(lots),
            current_quantity=int(quantity),
            stop_loss_points=self.params.stop_loss,
            initial_sl_price=float(initial_sl_price),
            current_sl_price=float(current_sl_price),
            trailing_stop_points=self.params.stop_loss,
            current_pnl_points=0.0,
            current_pnl_value=0.0,
            current_return_pct=0.0,
            pyramiding_count=0,
            update_time=timestamp
        )
        self.execution.log_open_position(position_record)
        self.logger.info(
            f" 📝 Position logged to CSV: data/live_trader/open_positions_{datetime.now().strftime('%Y-%m-%d')}.csv"
        )

        # Store extra metadata on agent for later use (directly on position dict)
        self.agent.set_position_metadata(
            option_type,
            entry_strike=strike,
            entry_spot=price,  # Store spot for reference
            entry_premium=entry_premium_val,  # Store premium (this is what we trade)
            entry_premium_source=entry_premium_source,
            entry_expiry=expiry_str,
            tradingsymbol=option_symbol,
            highest_premium=entry_premium_val,  # Initialize highest premium tracker for trailing stop
            lowest_premium=entry_premium_val if self.trade_regime == "Sell" else None
        )
        # Also set legacy properties for backward compatibility
        self.agent.entry_strike = strike
        self.agent.entry_premium = entry_premium_val

    def _handle_exit(self, price: float, timestamp: datetime, option_type: Optional[OptionType] = None) -> None:
        # If option_type not provided, use current_position (backward compatibility)
        if option_type is None:
            option_type = self.agent.current_position
        
        if option_type is None or not self.agent._has_position(option_type):
            return

        # Get entry strike and option type from position data
        pos = self.agent._get_position(option_type)
        entry_strike = pos.get('entry_strike') if pos else None
        entry_option_type = option_type.value if option_type else None
        
        if not entry_strike or not entry_option_type:
            self.logger.warning(f"Cannot exit {option_type.value if option_type else ''}: missing entry strike or option type")
            return
        
        # In LIVE mode, check SL order status instead of spot-based exit conditions
        should_exit = False
        exit_reason = None
        
        if isinstance(self.execution, LiveExecutionClient) and self._position_key:
            # Check SL order status - this is the source of truth for exits
            sl_status = self.execution.get_sl_order_status(self._position_key)
            
            if sl_status == 'COMPLETE':
                # SL order executed - log it but don't automatically square off
                # Keep monitoring the position
                self.logger.warning(f"🛡️ STOP LOSS ORDER EXECUTED: SL triggered but position remains open (monitoring continues)")
                # Don't set should_exit = True - keep position open and continue monitoring
                return
            elif sl_status == 'CANCELLED':
                # SL was cancelled, allow new trades
                self.logger.info(f"ℹ️ Stop Loss order CANCELLED - position still open, new trades allowed")
            elif sl_status == 'TRIGGER PENDING':
                # SL is pending, don't exit yet
                self.logger.debug(f"⏳ Stop Loss order TRIGGER PENDING - monitoring...")
            elif sl_status == 'REJECTED':
                should_exit = True
                exit_reason = "Stop Loss order REJECTED - manual exit required"
                self.logger.error(f"❌ Stop Loss order REJECTED - exiting position")
            else:
                # Unknown status or None - fall back to premium-based check
                self.logger.debug(f"SL order status: {sl_status} - falling back to premium-based exit check")
                expiry_for_calc = getattr(self.agent, 'entry_expiry', None)
                current_premium, _ = self._estimate_option_premium(
                    price, entry_strike, entry_option_type, timestamp, expiry_override=expiry_for_calc
                )
                should_exit, exit_reason, _ = self.agent.check_exit_conditions(
                    current_premium, timestamp, option_type
                )
        else:
            # PAPER mode or no SL order - use premium-based exit check
            expiry_for_calc = getattr(self.agent, 'entry_expiry', None)
            current_premium, _ = self._estimate_option_premium(
                price, entry_strike, entry_option_type, timestamp, expiry_override=expiry_for_calc
            )
            should_exit, exit_reason, _ = self.agent.check_exit_conditions(
                current_premium, timestamp, option_type
            )
        
        if not should_exit:
            return
        
        # Fetch exit option premium from Kite API (like backtesting)
        expiry_for_calc = getattr(self.agent, 'entry_expiry', None)
        exit_premium, exit_premium_source = self._estimate_option_premium(
            price,  # spot price
            entry_strike,
            entry_option_type,
            timestamp,
            expiry_override=expiry_for_calc
        )
        
        self.logger.info(
            f" 📊 Exit Option Premium: Strike={entry_strike} {entry_option_type}, "
            f"Premium=₹{exit_premium:.2f} (Source: {exit_premium_source}), "
            f"Spot=₹{price:.2f}"
        )

        # Exit trade using OPTION PREMIUM (not spot price)
        exit_result = self.agent.exit_trade(
            exit_price=exit_premium,  # Use premium instead of spot
            exit_time=timestamp, 
            reason=exit_reason or "Exit",
            option_type=option_type
        )
        if not exit_result.get("success"):
            return

        # Determine mode from execution client
        mode = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
        
        # Prepare trade record - calculate quantity first
        quantity = self.segment_cfg.lot_size * exit_result["lots"]
        
        # Square off position if in LIVE mode
        exit_premium_val = exit_premium
        if isinstance(self.execution, LiveExecutionClient) and self._position_key:
            try:
                square_off_result = self.execution.square_off_position(
                    position_key=self._position_key,
                    reason=exit_reason or "Exit",
                    trade_regime=self.trade_regime  # Pass trade regime for correct exit order type
                )
                # If live order executed, use actual exit premium from order
                if square_off_result.get("exit_price", 0) > 0:
                    exit_premium_val = square_off_result.get("exit_price")
                    exit_premium_source = "Live Order"
                exit_result["exit_price"] = exit_premium_val
                # P&L is calculated based on premium difference
                # Try to get entry_premium from position metadata first, then fallback to agent property, then exit_result
                pos = self.agent._get_position(option_type)
                entry_premium_for_pnl = pos.get('entry_premium') if pos else None
                if entry_premium_for_pnl is None:
                    entry_premium_for_pnl = getattr(self.agent, 'entry_premium', None)
                if entry_premium_for_pnl is None:
                    entry_premium_for_pnl = exit_result.get("entry_price")
                
                # Only calculate P&L if we have both entry and exit premiums
                if entry_premium_for_pnl is not None and exit_premium_val is not None:
                    # P&L calculation based on trade regime
                    if self.trade_regime == "Buy":
                        exit_result["pnl_points"] = exit_premium_val - entry_premium_for_pnl
                    else:  # Sell
                        exit_result["pnl_points"] = entry_premium_for_pnl - exit_premium_val
                    exit_result["pnl_value"] = exit_result["pnl_points"] * quantity
                else:
                    self.logger.warning(f"Cannot calculate P&L: entry_premium={entry_premium_for_pnl}, exit_premium={exit_premium_val}")
                    exit_result["pnl_points"] = 0.0
                    exit_result["pnl_value"] = 0.0
                exit_result["pnl_value"] = exit_result["pnl_points"] * quantity
                self.logger.warning(f"LIVE ORDER CLOSED: Exit Premium=₹{exit_premium_val:.2f}, P&L ₹{exit_result['pnl_value']:.2f}")
            except Exception as e:
                self.logger.error(f"Failed to square off LIVE position: {e}", exc_info=True)
                # Continue with logical exit even if order fails
        
        # Calculate P&L based on PREMIUM difference (not spot difference)
        # Try to get entry_premium from position metadata first, then fallback to agent property, then exit_result
        pos = self.agent._get_position(option_type)
        entry_premium_val = pos.get('entry_premium') if pos else None
        if entry_premium_val is None:
            entry_premium_val = getattr(self.agent, 'entry_premium', None)
        if entry_premium_val is None:
            entry_premium_val = exit_result.get("entry_price")
        
        if entry_premium_val is None or exit_premium_val is None:
            self.logger.warning(
                f"Cannot calculate premium P&L because entry or exit premium is None "
                f"(entry={entry_premium_val}, exit={exit_premium_val}). "
                f"Setting P&L to 0 for this trade."
            )
            premium_pnl_points = 0.0
            entry_premium_val = entry_premium_val or 0.0
            exit_premium_val = exit_premium_val or 0.0
        else:
            # P&L calculation based on trade regime
            # Buy: Profit when exit_premium > entry_premium → (exit - entry) * quantity
            # Sell: Profit when exit_premium < entry_premium → (entry - exit) * quantity
            if self.trade_regime == "Buy":
                premium_pnl_points = exit_premium_val - entry_premium_val
            else:  # Sell
                premium_pnl_points = entry_premium_val - exit_premium_val
        premium_pnl_value = premium_pnl_points * quantity
        premium_return_pct = ((premium_pnl_points / entry_premium_val) * 100) if entry_premium_val > 0 else 0.0
        
        strike = getattr(self.agent, "entry_strike", 0) or 0
        option_type = exit_result.get("option_type", "")

        # Calculate stop loss based on premium and trade regime
        # Buy: SL = entry_premium - stop_loss
        # Sell: SL = entry_premium + (stop_loss% / 100 * entry_premium) (percentage-based)
        entry_premium_for_sl = entry_premium_val or 0.0
        if self.trade_regime == "Buy":
            initial_sl_premium = entry_premium_for_sl - self.params.stop_loss
        else:  # Sell - percentage-based SL
            sl_amount = (self.params.stop_loss / 100.0) * entry_premium_for_sl
            initial_sl_premium = entry_premium_for_sl + sl_amount
        
        option_symbol = getattr(
            self.agent,
            "tradingsymbol",
            f"{self.params.segment}{strike}{option_type}",
        )

        record = PaperTradeRecord(
            segment=self.params.segment,
            mode=mode,
            signal_type=f"BUY_{option_type}",
            option_symbol=option_symbol,
            option_type=option_type,
            strike_price=float(strike),
            expiry=getattr(self.agent, 'entry_expiry', "") or "",
            lots=int(exit_result["lots"]),
            quantity=int(quantity),
            entry_time=exit_result["entry_time"],
            entry_price=float(entry_premium_val),  # Entry premium
            stop_loss_points=self.params.stop_loss,
            initial_sl_price=float(initial_sl_premium),  # SL based on premium
            trailing_stop_points=self.params.stop_loss,
            exit_time=exit_result["exit_time"],
            exit_price=float(exit_premium_val),  # Exit premium
            exit_reason=exit_result["reason"],
            pnl_points=float(premium_pnl_points),  # Premium P&L points
            pnl_value=float(premium_pnl_value),  # Premium P&L value
            return_pct=float(premium_return_pct),  # Premium return %
        )

        # Update open position record to CLOSED status before logging final trade
        mode = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
        closed_position_record = OpenPositionRecord(
            segment=self.params.segment,
            mode=mode,
            status="CLOSED",
            signal_type=f"BUY_{option_type}",
            option_symbol=option_symbol,
            option_type=option_type,
            strike_price=float(strike),
            expiry=getattr(self.agent, 'entry_expiry', "") or "",
            entry_time=exit_result["entry_time"],
            entry_price=float(entry_premium_val),  # Entry premium
            current_price=float(exit_premium_val),  # Exit premium
            current_lots=int(exit_result["lots"]),
            current_quantity=int(quantity),
            stop_loss_points=self.params.stop_loss,
            initial_sl_price=float(initial_sl_premium),  # SL based on premium
            current_sl_price=float(initial_sl_premium),  # SL based on premium
            trailing_stop_points=self.params.stop_loss,
            current_pnl_points=float(premium_pnl_points),  # Premium P&L points
            current_pnl_value=float(premium_pnl_value),  # Premium P&L value
            current_return_pct=float(premium_return_pct),  # Premium return %
            pyramiding_count=self._pyramiding_count,
            update_time=exit_result["exit_time"],
            exit_time=exit_result["exit_time"],
            exit_price=float(exit_premium_val),  # Exit premium
            exit_reason=exit_result["reason"],
            final_pnl_points=float(premium_pnl_points),  # Premium P&L points
            final_pnl_value=float(premium_pnl_value)  # Premium P&L value
        )
        self.execution.log_open_position(closed_position_record)
        
        # Also log to completed trades CSV (using premiums)
        self.logger.info(
            f" 💾 SAVING TRADE TO CSV: {option_type} strike={strike} "
            f"Entry Premium=₹{entry_premium_val:.2f} @ {exit_result['entry_time'].strftime('%H:%M:%S')}, "
            f"Exit Premium=₹{exit_premium_val:.2f} (Source: {exit_premium_source}) @ {exit_result['exit_time'].strftime('%H:%M:%S')}, "
            f"Premium P&L=₹{premium_pnl_value:.2f} ({premium_pnl_points:.2f} pts, {premium_return_pct:.2f}%), Reason={exit_result['reason']}"
        )
        self.execution.log_trade(record)
        self.logger.info(
            f" ✅ Trade saved to: data/live_trader/live_trades_{datetime.now().strftime('%Y-%m-%d')}.csv"
        )
        self.logger.info(
            f" ✅ Position marked as CLOSED in: data/live_trader/open_positions_{datetime.now().strftime('%Y-%m-%d')}.csv"
        )
        self._position_key = None  # Clear position key after exit
        self._pyramiding_count = 0  # Reset pyramiding counter

    def _update_open_position_in_csv(self, price: float, timestamp: datetime, option_type: Optional[OptionType] = None, is_pyramiding: bool = False) -> None:
        """Update open position in CSV file with current status."""
        if option_type is None:
            option_type = self.agent.current_position
        
        if option_type is None or not self.agent._has_position(option_type):
            return
        
        # Check if we should update (every 5 minutes or on pyramiding event)
        should_update = False
        if is_pyramiding:
            should_update = True
        elif self._last_position_update_time is None:
            should_update = True
        else:
            time_since_update = timestamp - self._last_position_update_time
            if time_since_update >= self._position_update_interval:
                should_update = True
        
        if not should_update:
            return
        
        # Get position data
        pos = self.agent._get_position(option_type)
        if not pos:
            return
        
        strike = pos.get("entry_strike", 0) or 0
        opt_type_value = option_type.value
        
        # Fetch current option premium (not spot price)
        expiry_for_calc = pos.get('entry_expiry')
        current_premium, premium_source = self._estimate_option_premium(
            price,  # spot price
            strike,
            opt_type_value,
            timestamp,
            expiry_override=expiry_for_calc
        )
        
        # Calculate current P&L based on PREMIUM difference
        entry_premium_val = pos.get('entry_premium', pos.get('entry_price', 0))
        current_lots = pos["lots"]
        current_qty = self.segment_cfg.lot_size * current_lots
        # P&L calculation based on trade regime
        if self.trade_regime == "Buy":
            premium_pnl_points = current_premium - entry_premium_val
        else:  # Sell
            premium_pnl_points = entry_premium_val - current_premium
        current_pnl_points = premium_pnl_points
        current_pnl_value = premium_pnl_points * current_qty
        
        # Calculate return percentage based on premium
        total_investment = entry_premium_val * current_lots * self.segment_cfg.lot_size
        current_return_pct = (current_pnl_value / total_investment * 100) if total_investment > 0 else 0.0
        
        # Calculate trailing stop price based on PREMIUM (not spot price)
        # Track highest premium reached for trailing stop calculation
        highest_premium = getattr(self.agent, 'highest_premium', entry_premium_val)
        if current_premium > highest_premium:
            highest_premium = current_premium
            self.agent.highest_premium = highest_premium
        
        # Calculate trailing stop based on trade regime
        # Buy: trailing stop = highest_premium - stop_loss_points (SL moves up as premium increases)
        # Sell: trailing stop = lowest_premium + (stop_loss% / 100 * lowest_premium) (percentage-based, SL moves down as premium decreases)
        if self.trade_regime == "Buy":
            # For Buy: SL trails up when premium increases
            current_sl_price = highest_premium - self.params.stop_loss
            # Ensure trailing stop never goes below initial SL
            initial_sl_price = entry_premium_val - self.params.stop_loss
            if current_sl_price < initial_sl_price:
                current_sl_price = initial_sl_price
        else:  # Sell - percentage-based trailing SL
            # For Sell: SL trails down when premium decreases
            # Track lowest premium for Sell (premium decrease is good)
            lowest_premium = getattr(self.agent, 'lowest_premium', entry_premium_val)
            if current_premium < lowest_premium:
                self.agent.lowest_premium = current_premium
                lowest_premium = current_premium
            # Calculate trailing SL as percentage of lowest premium
            sl_amount = (self.params.stop_loss / 100.0) * lowest_premium
            current_sl_price = lowest_premium + sl_amount
            # Ensure trailing stop never goes above initial SL
            initial_sl_amount = (self.params.stop_loss / 100.0) * entry_premium_val
            initial_sl_price = entry_premium_val + initial_sl_amount
            if current_sl_price > initial_sl_price:
                current_sl_price = initial_sl_price
        
        # MODIFY SL ORDER IN KITE if trailing SL has changed (LIVE mode only)
        if isinstance(self.execution, LiveExecutionClient) and self._position_key:
            try:
                # Get previous SL trigger price by checking SL order status (which updates position)
                sl_status = self.execution.get_sl_order_status(self._position_key)
                
                # Get position to check previous SL trigger price
                # Access via the execution client's internal position tracking
                if hasattr(self.execution, '_open_positions') and self._position_key in self.execution._open_positions:
                    pos = self.execution._open_positions[self._position_key]
                    previous_sl_trigger = pos.get('sl_trigger_price')
                    
                    # Only modify if SL price has changed significantly (avoid micro-adjustments)
                    # Minimum change: 0.5 points to avoid excessive API calls
                    # For Buy: SL should only move UP (current_sl_price > previous_sl_trigger)
                    # For Sell: SL should only move DOWN (current_sl_price < previous_sl_trigger)
                    sl_should_update = False
                    if previous_sl_trigger is None:
                        sl_should_update = True
                    elif self.trade_regime == "Buy":
                        # Buy: only update if SL moves up and change >= 0.5
                        if current_sl_price > previous_sl_trigger and (current_sl_price - previous_sl_trigger) >= 0.5:
                            sl_should_update = True
                    else:  # Sell
                        # Sell: only update if SL moves down and change >= 0.5
                        if current_sl_price < previous_sl_trigger and (previous_sl_trigger - current_sl_price) >= 0.5:
                            sl_should_update = True
                    
                    if sl_should_update:
                        # Also check if SL order is still pending (can't modify if executed/cancelled)
                        if sl_status in [None, 'TRIGGER PENDING', 'OPEN', '']:
                            modified_order_id = self.execution.modify_sl_order(
                                position_key=self._position_key,
                                new_trigger_price=current_sl_price,
                                trade_regime=self.trade_regime
                            )
                            if modified_order_id:
                                self.logger.info(
                                    f"🛡️ TRAILING SL UPDATED: SL order modified | "
                                    f"Previous: ₹{previous_sl_trigger:.2f if previous_sl_trigger else 'N/A'} → "
                                    f"New: ₹{current_sl_price:.2f} | Order ID: {modified_order_id}"
                                )
                            else:
                                self.logger.debug(
                                    f"SL order modification skipped (order may be executed/cancelled) | "
                                    f"Status: {sl_status}, Calculated SL: ₹{current_sl_price:.2f}"
                                )
                        else:
                            self.logger.debug(
                                f"SL order modification skipped (order status: {sl_status}) | "
                                f"Calculated SL: ₹{current_sl_price:.2f}"
                            )
                    else:
                        if previous_sl_trigger is not None:
                            direction = "UP" if self.trade_regime == "Buy" else "DOWN"
                            if self.trade_regime == "Buy":
                                moved = current_sl_price > previous_sl_trigger
                                diff = current_sl_price - previous_sl_trigger if moved else 0
                            else:  # Sell
                                moved = current_sl_price < previous_sl_trigger
                                diff = previous_sl_trigger - current_sl_price if moved else 0
                            
                            if not moved:
                                self.logger.debug(
                                    f"SL trigger price cannot move {direction} (Sell regime): "
                                    f"₹{previous_sl_trigger:.2f} → ₹{current_sl_price:.2f}"
                                )
                            else:
                                self.logger.debug(
                                    f"SL trigger price change too small ({direction}): "
                                    f"₹{previous_sl_trigger:.2f} → ₹{current_sl_price:.2f} "
                                    f"(diff: {diff:.2f} < 0.5)"
                                )
            except Exception as e:
                self.logger.error(f"Error modifying SL order for trailing stop: {e}", exc_info=True)
        
        # Determine mode
        mode = "LIVE" if isinstance(self.execution, LiveExecutionClient) else "PAPER"
        
        # Create update record (using premiums)
        option_symbol = getattr(
            self.agent,
            "tradingsymbol",
            f"{self.params.segment}{strike}{option_type.value}",
        )

        position_record = OpenPositionRecord(
            segment=self.params.segment,
            mode=mode,
            status="OPEN",
            signal_type=f"{self.trade_regime.upper()}_{option_type.value}",
            option_symbol=option_symbol,
            option_type=option_type.value,
            strike_price=float(strike),
            expiry=getattr(self.agent, 'entry_expiry', "") or "",
            entry_time=self.agent.entry_time,
            entry_price=float(entry_premium_val),  # Entry premium
            current_price=float(current_premium),  # Current premium (not spot)
            current_lots=int(current_lots),
            current_quantity=int(current_qty),
            stop_loss_points=self.params.stop_loss,
            initial_sl_price=float(
                # Calculate SL based on trade regime
                entry_premium_val - self.params.stop_loss if self.trade_regime == "Buy" 
                else entry_premium_val + ((self.params.stop_loss / 100.0) * entry_premium_val)
            ),
            current_sl_price=float(current_sl_price),
            trailing_stop_points=self.params.stop_loss,
            current_pnl_points=float(current_pnl_points),
            current_pnl_value=float(current_pnl_value),
            current_return_pct=float(current_return_pct),
            pyramiding_count=self._pyramiding_count,
            last_pyramiding_time=timestamp if is_pyramiding and self._pyramiding_count > 0 else None,
            update_time=timestamp
        )
        
        self.execution.log_open_position(position_record)
        self._last_position_update_time = timestamp
        
        if is_pyramiding:
            self.logger.info(
                f" 📝 Position updated in CSV after pyramiding: "
                f"lots={current_lots}, P&L=₹{current_pnl_value:.2f}"
            )
        else:
            self.logger.debug(
                f" 📝 Position updated in CSV: "
                f"P&L=₹{current_pnl_value:.2f} ({current_pnl_points:.2f} pts), "
                f"SL=₹{current_sl_price:.2f}"
            )

    def _check_pyramiding(self, price: float, option_type: Optional[OptionType] = None) -> None:
        """Check if we should add quantity according to pyramiding rules."""
        if self.agent.current_position is None:
            return

        cfg = self.segment_cfg
        
        # Early exit if pyramiding is disabled (lot_addition = 0)
        if cfg.lot_addition <= 0:
            self.logger.debug(
                f" Pyramiding disabled: lot_addition={cfg.lot_addition} "
                f"(Config: lot_size={cfg.lot_size}, pyramid_points={cfg.pyramid_points}, "
                f"lot_addition={cfg.lot_addition}, max_quantity={cfg.max_quantity})"
            )
            return

        # If option_type not provided, use current_position (backward compatibility)
        if option_type is None:
            option_type = self.agent.current_position
        
        if option_type is None or not self.agent._has_position(option_type):
            return
        
        # Compute unrealized profit for this specific position (per option)
        pnl_per_lot = self.agent.calculate_pnl(price, option_type)
        pos = self.agent._get_position(option_type)
        current_qty = self.segment_cfg.lot_size * pos["lots"]
        threshold = current_qty * cfg.pyramid_points
        unrealized_value = pnl_per_lot * self.segment_cfg.lot_size
        pass_threshold = unrealized_value >= threshold
        remaining_capacity = cfg.max_quantity - current_qty

        self.logger.info(
            f" Pyramiding criteria -> "
            f"Profit ₹{unrealized_value:.2f} vs Threshold ₹{threshold:.2f} "
            f"({'PASS' if pass_threshold else 'FAIL'}), "
            f"Remaining Qty Capacity={remaining_capacity}, "
            f"Config: lot_addition={cfg.lot_addition}, lot_size={cfg.lot_size}"
        )

        if (not pass_threshold) or remaining_capacity <= 0:
            return

        qty_to_add = min(cfg.lot_addition * cfg.lot_size, remaining_capacity)
        lots_to_add = qty_to_add // self.segment_cfg.lot_size
        if lots_to_add <= 0:
            self.logger.info(
                f" Pyramiding criteria -> Lot addition blocked (qty_to_add={qty_to_add}, "
                f"lot_addition={cfg.lot_addition}, lot_size={cfg.lot_size})"
            )
            return

        add_result = self.agent.add_lots(price, lots_to_add, option_type)
        if add_result.get("success"):
            self._pyramiding_count += 1
            self.logger.info(
                f" Pyramiding: added {lots_to_add} lots "
                f"at price={price:.2f}, total_lots={self.agent.lots}"
            )
            # Immediately update CSV after pyramiding
            self._update_open_position_in_csv(price, datetime.now(), option_type, is_pyramiding=True)

    def _log_entry_checks(self, eval_details: Optional[Dict[str, Any]], signal: TradeSignal, current_price: float = None, latest_candle_time: Optional[datetime] = None) -> None:
        """Enhanced logging with all segment details in structured format."""
        if not eval_details:
            return

        rsi_val = eval_details.get("rsi_value")
        rsi_status = eval_details.get("rsi_status", "Not calculated")
        candle_type = eval_details.get("candle_type", "unknown")
        candle_ohlc = eval_details.get("candle_ohlc")
        price_strength = eval_details.get("price_strength")
        volume_strength = eval_details.get("volume_strength")
        vwap_value = eval_details.get("vwap")
        checks = eval_details.get("checks", [])
        # Use latest_candle_time if provided (the actual candle being used), otherwise fall back to eval_details timestamp
        candle_timestamp = latest_candle_time if latest_candle_time is not None else eval_details.get("candle_timestamp")

        # Log current price
        if current_price is not None:
            self.logger.info(f"📊 Strategy Analysis - Current Price: ₹{current_price:.2f}")
        
        # Log RSI information
        if rsi_val is not None:
            rsi_display = f"{rsi_val:.2f}"
            self.logger.info(f"📈 RSI: {rsi_display}")
        else:
            rsi_display = f"N/A ({rsi_status})"
            self.logger.info(f"📈 RSI: {rsi_display}")
        
        # Log Price Strength, Volume Strength, and VWAP
        indicators_str = ""
        if price_strength is not None and volume_strength is not None:
            indicators_str = f"PS={price_strength:.2f}, VS={volume_strength:.2f}"
            if vwap_value is not None:
                indicators_str += f", VWAP={vwap_value:.2f}"
            self.logger.info(f"Indicators :: {indicators_str}")
            
            # Save PS/VS data for time series chart
            # Extract crossover information from checks to use correct timestamp
            crossover_timestamp = None
            crossover_type = None
            
            # Check if any crossover was detected and passed
            for check in checks:
                label = check.get("label", "")
                passed = check.get("passed", False)
                
                # Look for crossover checks that passed
                if "crossover" in label.lower() and passed:
                    # Use the candle_timestamp from eval_details (which is the crossover candle timestamp)
                    crossover_timestamp = eval_details.get("candle_timestamp")
                    
                    # Determine crossover type from check label
                    if "PE" in label or "Bearish" in label or "DOWN" in label:
                        crossover_type = "PE"
                    elif "CE" in label or "Bullish" in label or "UP" in label:
                        crossover_type = "CE"
                    
                    # Found a crossover, break
                    if crossover_timestamp and crossover_type:
                        break
            
            # Extract filter information from eval_details if available
            filter_info = eval_details.get("filters", {})
            
            # Only save if we have a valid timestamp
            if candle_timestamp is not None:
                self._save_ps_vs_data(
                    price_strength, 
                    volume_strength, 
                    candle_timestamp, 
                    current_price, 
                    rsi_val,
                    crossover_timestamp=crossover_timestamp,
                    crossover_type=crossover_type,
                    filter_info=filter_info
                )
            else:
                self.logger.warning(
                    f"⚠️ Cannot save PS/VS data: candle_timestamp is None. "
                    f"PS={price_strength:.2f}, VS={volume_strength:.2f}"
                )
        
        # Format candle display with OHLC details
        if candle_timestamp:
            candle_time_str = candle_timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            candle_time_str = "N/A"
        
        # Build entry criteria string with PS, VS, and VWAP
        entry_criteria_parts = [f"RSI={rsi_display}", f"Candle={candle_type}"]
        if indicators_str:
            entry_criteria_parts.append(indicators_str)
        entry_criteria_str = ", ".join(entry_criteria_parts)
        
        # Include trade regime in entry criteria log
        trade_regime_str = f" [Trade Regime: {self.trade_regime}]"
        
        if candle_type == "neutral" and candle_ohlc:
            o, h, l, c = candle_ohlc.get('open'), candle_ohlc.get('high'), candle_ohlc.get('low'), candle_ohlc.get('close')
            self.logger.info(f"Entry Criteria :: {entry_criteria_str} (O:{o:.2f} H:{h:.2f} L:{l:.2f} C:{c:.2f}) @ {candle_time_str}{trade_regime_str} ::")
        else:
            self.logger.info(f"Entry Criteria :: {entry_criteria_str} @ {candle_time_str}{trade_regime_str} ::")
        
        # Log all checks in structured format
        self.logger.info(f"Checks:")
        
        # Process and log checks
        # Note: Color coding is handled in the web UI via HTML, not in log files
        # This prevents ANSI escape sequences from appearing in log files
        for check in checks:
            label = check.get("label", "criterion")
            passed = check.get("passed", False)
            value = check.get("value")
            
            # Plain text status (colors are added in web UI via HTML)
            status = "PASS" if passed else "FAIL"
            
            check_line = f"  {label}: {status}"
            if value is not None:
                check_line += f" ({value})"
            
            self.logger.info(f"{check_line}")
        
        # Log outcome with trade regime context
        # In Sell regime: BUY_CE → SELL_CE, BUY_PE → SELL_PE
        if signal == TradeSignal.BUY_CE:
            if self.trade_regime == "Sell":
                outcome_str = "SELL_CE"
                option_type_str = "CE"
            else:
                outcome_str = "BUY_CE"
                option_type_str = "CE"
        elif signal == TradeSignal.BUY_PE:
            if self.trade_regime == "Sell":
                outcome_str = "SELL_PE"
                option_type_str = "PE"
            else:
                outcome_str = "BUY_PE"
                option_type_str = "PE"
        else:
            outcome_str = signal.value
            option_type_str = ""
        
        self.logger.info(f"Outcome={outcome_str} (Trade Regime: {self.trade_regime})")
        
        # Log signal details - show only the actual trade action (outcome_str), not the internal signal
        reason = eval_details.get("reason", "")
        if signal in (TradeSignal.BUY_CE, TradeSignal.BUY_PE):
            self.logger.info(f"✅ SIGNAL GENERATED: {outcome_str} ({option_type_str}) [Trade Regime: {self.trade_regime}] - {reason}")
        else:
            self.logger.info(f"⏸️ No entry signal: {signal.value} - {reason}")
        
        # Log current position status if open - validate position actually exists
        if self.agent.current_position is not None:
            # Check if position actually exists and has valid data
            pos = self.agent._get_position(self.agent.current_position)
            
            # Validate position exists and has required data
            if pos is None:
                # Position was cleared but current_position wasn't - clear it now
                self.logger.debug(
                    f"⚠️ Clearing stale current_position reference: {self.agent.current_position.value} "
                    f"(position data is None)"
                )
                self.agent.current_position = None
            elif not pos.get("entry_strike"):
                # Position exists but missing critical data - might be stale
                # In LIVE mode, verify with Kite
                if isinstance(self.execution, LiveExecutionClient):
                    try:
                        kite_pos = self.execution.check_kite_position_by_option_type(
                            self.params.segment,
                            self.agent.current_position.value
                        )
                        if not kite_pos:
                            # No position in Kite - clear stale reference
                            self.logger.debug(
                                f"⚠️ Clearing stale position: {self.agent.current_position.value} "
                                f"(not found in Kite, entry_strike missing)"
                            )
                            self.agent.positions[self.agent.current_position] = None
                            self.agent.current_position = None
                    except Exception as e:
                        self.logger.debug(f"Error verifying position in Kite: {e}")
                else:
                    # PAPER mode - clear if missing critical data
                    self.logger.debug(
                        f"⚠️ Clearing incomplete position: {self.agent.current_position.value} "
                        f"(missing entry_strike)"
                    )
                    self.agent.positions[self.agent.current_position] = None
                    self.agent.current_position = None
            
            # Only log if position is valid
            if self.agent.current_position is not None and pos and pos.get("entry_strike"):
                entry_strike = pos.get("entry_strike")
                entry_premium = pos.get("entry_premium", getattr(self.agent, "entry_price", None)) if pos else getattr(self.agent, "entry_price", None)
                tradingsymbol = pos.get("tradingsymbol", "N/A") if pos else "N/A"
                entry_expiry = pos.get("entry_expiry", "N/A") if pos else "N/A"
                lots = pos.get("lots", self.agent.lots) if pos else self.agent.lots
                current_premium = None
                premium_source = "N/A"
                
                expiry_for_calc = pos.get("entry_expiry") if pos else getattr(self.agent, "entry_expiry", None)
                current_premium, premium_source = self._estimate_option_premium(
                    current_price,
                    entry_strike,
                    self.agent.current_position.value,
                    datetime.now(),
                    expiry_override=expiry_for_calc
                )
                # Fallback to zero if premium not available
                if current_premium is None:
                    current_premium = 0.0
                if entry_premium is None:
                    entry_premium = 0.0

                # P&L based on premium difference
                if self.trade_regime == "Buy":
                    current_pnl = current_premium - entry_premium
                else:  # Sell regime
                    current_pnl = entry_premium - current_premium
                current_pnl_value = current_pnl * self.segment_cfg.lot_size * lots
                current_price_str = f"₹{current_premium:.2f}" if current_premium is not None else "N/A"
                self.logger.info(
                    f"📍 Current Position: {self.agent.current_position.value} "
                    f"Symbol={tradingsymbol}, Expiry={entry_expiry}, "
                    f"Strike={entry_strike}, "
                    f"Entry=₹{entry_premium:.2f}, "
                    f"Current={current_price_str}, "
                    f"Lots={lots}, "
                    f"P&L=₹{current_pnl_value:.2f} ({current_pnl:.2f} pts, Source: {premium_source})"
                )

    def _save_ps_vs_data(
        self, 
        price_strength: float, 
        volume_strength: float, 
        timestamp: Optional[datetime], 
        current_price: Optional[float], 
        rsi: Optional[float],
        crossover_timestamp: Optional[datetime] = None,
        crossover_type: Optional[str] = None,
        filter_info: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Save PS/VS data to JSON file for time series chart visualization.
        Stores data per segment per day, preserving ALL historical data across restarts.
        Data is appended to existing files, never deleted.
        
        Args:
            price_strength: Current PS value
            volume_strength: Current VS value
            timestamp: Current timestamp (for regular data points)
            current_price: Current price
            rsi: Current RSI value
            crossover_timestamp: Timestamp when crossover actually happened (if detected)
            crossover_type: Type of crossover ("CE" or "PE") if detected
        """
        if timestamp is None:
            return
        
        try:
            # Create data directory if it doesn't exist
            ps_vs_dir = LOG_DIR / "ps_vs_data"
            ps_vs_dir.mkdir(parents=True, exist_ok=True)
            
            # File name: ps_vs_{segment}_{date}.json
            date_str = timestamp.strftime("%Y-%m-%d")
            file_path = ps_vs_dir / f"ps_vs_{self.params.segment}_{date_str}.json"
            
            # Load existing data or create new (preserves all historical data)
            data = []
            existing_timestamps = set()  # Track existing timestamps to avoid duplicates
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # Build set of existing timestamps to avoid duplicates
                        existing_timestamps = {d.get("timestamp") for d in data if d.get("timestamp")}
                        self.logger.debug(f" Loaded {len(data)} existing PS/VS data points from {file_path.name}")
                except (json.JSONDecodeError, IOError) as e:
                    self.logger.warning(f" Error loading existing PS/VS data: {e}, starting fresh")
                    data = []
                    existing_timestamps = set()
            
            # If crossover was detected, save it with the crossover timestamp
            if crossover_timestamp is not None and crossover_type is not None:
                # Check if crossover point already exists (avoid duplicates)
                crossover_iso = crossover_timestamp.isoformat()
                existing_crossover = any(
                    d.get("timestamp") == crossover_iso and d.get("crossover") == crossover_type
                    for d in data
                )
                
                if not existing_crossover:
                    # Find PS/VS values at crossover time (use previous data point's values)
                    crossover_ps = price_strength
                    crossover_vs = volume_strength
                    
                    # Try to find the actual PS/VS values at crossover time from previous data
                    if len(data) > 0:
                        # Look for data point closest to crossover timestamp
                        for d in reversed(data):
                            d_timestamp = datetime.fromisoformat(d["timestamp"])
                            if d_timestamp <= crossover_timestamp:
                                crossover_ps = d.get("price_strength", price_strength)
                                crossover_vs = d.get("volume_strength", volume_strength)
                                break
                    
                    # Create crossover data point with crossover timestamp
                    crossover_point = {
                        "timestamp": crossover_iso,
                        "price_strength": round(crossover_ps, 2),
                        "volume_strength": round(crossover_vs, 2),
                        "price": round(current_price, 2) if current_price is not None else None,
                        "rsi": round(rsi, 2) if rsi is not None else None,
                        "crossover": crossover_type,
                        "filters": filter_info if filter_info else None
                    }
                    data.append(crossover_point)
            
            # Create new data point for current timestamp
            data_point = {
                "timestamp": timestamp.isoformat(),
                "price_strength": round(price_strength, 2),
                "volume_strength": round(volume_strength, 2),
                "price": round(current_price, 2) if current_price is not None else None,
                "rsi": round(rsi, 2) if rsi is not None else None,
                "crossover": None,  # Regular data point, no crossover
                "filters": filter_info if filter_info else None
            }
            
            # Detect crossover from previous point (fallback if not explicitly provided)
            if crossover_type is None and len(data) > 0:
                prev_point = data[-1]
                prev_ps = prev_point.get("price_strength")
                prev_vs = prev_point.get("volume_strength")
                
                if prev_ps is not None and prev_vs is not None:
                    # PE crossover: PS crosses DOWN to VS (from above to below)
                    if prev_ps > prev_vs and price_strength < volume_strength:
                        data_point["crossover"] = "PE"
                    # CE crossover: PS crosses UP to VS (from below to above)
                    elif prev_ps < prev_vs and price_strength > volume_strength:
                        data_point["crossover"] = "CE"
            
            # Add new data point only if it doesn't already exist (avoid duplicates on restart)
            timestamp_iso = timestamp.isoformat()
            if timestamp_iso not in existing_timestamps:
                data.append(data_point)
            else:
                # Update existing data point if it exists (in case of restart with same timestamp)
                for i, d in enumerate(data):
                    if d.get("timestamp") == timestamp_iso:
                        # Update with latest values
                        data[i] = data_point
                        self.logger.debug(f" Updated existing PS/VS data point for {timestamp_iso}")
                        break
            
            # PRESERVE ALL DATA - Do not filter/delete old data
            # Historical data is preserved across restarts for complete time series visualization
            # The UI can filter by hours if needed, but we keep all data in the file
            
            # Sort data by timestamp to maintain chronological order
            data.sort(key=lambda x: datetime.fromisoformat(x["timestamp"]) if x.get("timestamp") else datetime.min)
            
            # Save to file (preserves all historical data)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Log successful save (at debug level to avoid spam, but can be enabled for troubleshooting)
            self.logger.debug(
                f"✅ Saved PS/VS data to {file_path.name}: PS={price_strength:.2f}, VS={volume_strength:.2f}, "
                f"timestamp={timestamp}, total_points={len(data)}"
            )
            
        except Exception as e:
            # Don't fail the main process if PS/VS saving fails, but log at INFO level for visibility
            self.logger.warning(
                f"⚠️ Failed to save PS/VS data for timestamp {timestamp}: {e}. "
                f"This may prevent the PS/VS chart from displaying data.",
                exc_info=True
            )

    def _recover_positions_from_kite(self) -> None:
        """
        Recover open positions from Kite API on system startup.
        This ensures the system can resume monitoring positions after a restart.
        """
        if not isinstance(self.execution, LiveExecutionClient):
            return  # Only for LIVE mode
        
        try:
            self.logger.info("🔄 Recovering positions from Kite API on startup...")
            
            # Check for positions in Kite API
            for opt_type in [OptionType.CE, OptionType.PE]:
                kite_pos = self.execution.check_kite_position_by_option_type(
                    self.params.segment,
                    opt_type.value
                )
                
                if kite_pos:
                    tradingsymbol = kite_pos.get('tradingsymbol', '')
                    quantity = int(kite_pos.get('quantity', 0))
                    average_price = float(kite_pos.get('average_price', 0))
                    
                    self.logger.info(
                        f"📋 Found {opt_type.value} position in Kite: {tradingsymbol} "
                        f"(Qty: {quantity}, Avg Price: ₹{average_price:.2f})"
                    )
                    
                    # Try to restore from CSV first (has more details)
                    restored_from_csv = self._restore_position_from_csv(opt_type, tradingsymbol)
                    
                    if restored_from_csv:
                        self.logger.info(
                            f"✅ Restored {opt_type.value} position from CSV: "
                            f"Strike={restored_from_csv.get('entry_strike', 'N/A')}, "
                            f"Entry=₹{restored_from_csv.get('entry_price', 'N/A'):.2f}"
                        )
                    else:
                        # Restore from Kite API data (limited info)
                        self._restore_position_from_kite(opt_type, kite_pos)
                        self.logger.warning(
                            f"⚠️ Restored {opt_type.value} position from Kite API (limited details). "
                            f"CSV backup not found. Position will be monitored but some details may be missing."
                        )
                else:
                    # No position in Kite - clear from internal state if exists
                    if self.agent._has_position(opt_type):
                        self.logger.warning(
                            f"⚠️ Clearing stale {opt_type.value} position: "
                            f"Exists in internal state but not in Kite API"
                        )
                        self.agent.positions[opt_type] = None
                        if self.agent.current_position == opt_type:
                            self.agent.current_position = None
            
            self.logger.info("✅ Position recovery completed")
            
        except Exception as e:
            self.logger.error(f"❌ Error recovering positions from Kite: {e}", exc_info=True)
            # Don't fail startup - continue with empty state
    
    def _restore_position_from_csv(self, option_type: OptionType, tradingsymbol: str) -> Optional[Dict[str, Any]]:
        """
        Try to restore position details from CSV file.
        
        Returns:
            Position dict if found and restored, None otherwise
        """
        try:
            csv_file = LOG_DIR / f"open_positions_{datetime.now().strftime('%Y-%m-%d')}.csv"
            
            if not csv_file.exists():
                # Try yesterday's file as fallback
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                csv_file = LOG_DIR / f"open_positions_{yesterday}.csv"
            
            if not csv_file.exists():
                return None
            
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Match by segment, option_type, and tradingsymbol
                    if (row.get('segment', '').upper() == self.params.segment.upper() and
                        row.get('option_type', '').upper() == option_type.value.upper() and
                        row.get('status', '').upper() == 'OPEN' and
                        tradingsymbol.upper() in row.get('option_symbol', '').upper()):
                        
                        # Parse position data
                        try:
                            entry_strike = float(row.get('strike_price', 0))
                            entry_price = float(row.get('entry_price', 0))
                            entry_time_str = row.get('entry_time', '')
                            expiry = row.get('expiry', '')
                            lots = int(row.get('current_lots', 1))
                            quantity = int(row.get('current_quantity', 0))
                            
                            # Parse entry time
                            entry_time = datetime.now()
                            if entry_time_str:
                                try:
                                    entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
                                    if entry_time.tzinfo:
                                        entry_time = entry_time.replace(tzinfo=None)
                                except:
                                    pass
                            
                            # Restore position in agent
                            # Calculate total_investment from entry_price and lots
                            total_investment = entry_price * lots if entry_price > 0 and lots > 0 else 0
                            position_data = {
                                'entry_strike': entry_strike,
                                'entry_price': entry_price,
                                'entry_time': entry_time,
                                'lots': lots,
                                'quantity': quantity,
                                'expiry': expiry,
                                'tradingsymbol': tradingsymbol,
                                'highest_profit': 0,  # Initialize for tracking
                                'trailing_stop_price': None,  # Initialize for tracking
                                'total_investment': total_investment  # Initialize for tracking
                            }
                            
                            self.agent.positions[option_type] = position_data
                            self.agent.current_position = option_type
                            
                            # Set position metadata
                            self.agent.set_position_metadata(
                                option_type,
                                entry_expiry=expiry,
                                tradingsymbol=tradingsymbol
                            )
                            
                            # Set position key for tracking
                            self._position_key = f"{self.params.segment}_{entry_strike}_{option_type.value}"
                            
                            return position_data
                        except Exception as e:
                            self.logger.warning(f"Error parsing CSV position data: {e}")
                            continue
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error reading CSV for position recovery: {e}")
            return None
    
    def _restore_position_from_kite(self, option_type: OptionType, kite_pos: Dict[str, Any]) -> None:
        """
        Restore position from Kite API data (limited details available).
        This is a fallback when CSV is not available.
        """
        try:
            tradingsymbol = kite_pos.get('tradingsymbol', '')
            quantity = int(kite_pos.get('quantity', 0))
            average_price = float(kite_pos.get('average_price', 0))
            
            # Extract strike from tradingsymbol (e.g., NIFTY25DEC2325800CE -> 25800)
            strike = None
            try:
                # Tradingsymbol format: SEGMENT+EXPIRY+STRIKE+OPTIONTYPE
                # Example: NIFTY25DEC2325800CE
                match = re.search(r'(\d{5,6})(CE|PE)$', tradingsymbol)
                if match:
                    strike = int(match.group(1))
            except:
                pass
            
            if strike is None:
                self.logger.warning(f"Could not extract strike from tradingsymbol: {tradingsymbol}")
                strike = 0  # Use placeholder
            
            # Extract expiry from tradingsymbol
            expiry = ''
            try:
                # Format: NIFTY25DEC23 -> 2025-12-23
                match = re.search(r'(\d{2})([A-Z]{3})(\d{2})', tradingsymbol)
                if match:
                    year = int('20' + match.group(1))
                    month_map = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                                'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
                    month = month_map.get(match.group(2), 1)
                    day = int(match.group(3))
                    expiry = f"{year}-{month:02d}-{day:02d}"
            except:
                pass
            
            # Calculate lots (assuming standard lot sizes)
            lot_size = self.segment_cfg.lot_size
            lots = abs(quantity) // lot_size if lot_size > 0 else 1
            
            # Restore position
            # Calculate total_investment from average_price and lots
            total_investment = average_price * lots if average_price > 0 and lots > 0 else 0
            position_data = {
                'entry_strike': strike,
                'entry_price': average_price,
                'entry_time': datetime.now(),  # Approximate - don't have exact entry time
                'lots': lots,
                'quantity': quantity,
                'expiry': expiry,
                'tradingsymbol': tradingsymbol,
                'highest_profit': 0,  # Initialize for tracking
                'trailing_stop_price': None,  # Initialize for tracking
                'total_investment': total_investment  # Initialize for tracking
            }
            
            self.agent.positions[option_type] = position_data
            self.agent.current_position = option_type
            
            # Set position metadata
            if expiry:
                self.agent.set_position_metadata(
                    option_type,
                    entry_expiry=expiry,
                    tradingsymbol=tradingsymbol
                )
            
            # Set position key
            self._position_key = f"{self.params.segment}_{strike}_{option_type.value}"
            
            self.logger.info(
                f"✅ Restored {option_type.value} position from Kite: "
                f"Strike={strike}, Entry≈₹{average_price:.2f}, Lots={lots}, Qty={quantity}"
            )
            
        except Exception as e:
            self.logger.error(f"Error restoring position from Kite: {e}", exc_info=True)


