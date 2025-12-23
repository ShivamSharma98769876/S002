"""
RSI Divergence + Trend Reversal Trading Agent
Implements the RSI-based intraday option buying strategy
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import pandas as pd
import numpy as np
from src.utils.logger import get_logger

logger = get_logger("trading")


class Segment(Enum):
    """Trading segments"""
    NIFTY = "NIFTY"
    SENSEX = "SENSEX"
    BANKNIFTY = "BANKNIFTY"


class OptionType(Enum):
    """Option types"""
    CE = "CE"  # Call Option
    PE = "PE"  # Put Option


class TradeSignal(Enum):
    """Trading signals"""
    BUY_CE = "BUY_CE"
    BUY_PE = "BUY_PE"
    EXIT = "EXIT"
    HOLD = "HOLD"


class RSIStrategy:
    """
    RSI Divergence + Trend Reversal Strategy
    Based on "Hilega Milega" indicator by NK Sir (TradingView)
    
    Indicator Settings (matching TradingView):
    - RSI Source: Close
    - RSI Length: 9
    - Price Strength Indicator (EMA): 3
    - Volume Strength Indicator (WMA): 21
    
    Revised Entry Conditions:
    - PE Buy (Bearish setup):
      * Price must be in a Bearish/Red candle (current timeframe must be red)
      * Price Strength (EMA(3) of RSI(9), blue line) crosses downwards to Volume Strength (WMA(21) of RSI(9), red line) from above
      * If SL hits → re-enter on every new red candle until trend confirms
    
    - CE Buy (Bullish setup):
      * Price must be in a Bullish/Green candle (current timeframe must be green)
      * Price Strength (EMA(3) of RSI(9), blue line) crosses upward to Volume Strength (WMA(21) of RSI(9), red line) from below
      * If SL hits → re-enter on every new green candle until trend confirms
    
    Exit Conditions:
    - Stop Loss hit
    - Trailing Stop Loss hit
    - Target reached
    """
    
    def __init__(
        self,
        segment: Segment,
        rsi_period: int = 9,
        timeframe: str = "15min",
        stop_loss: Optional[float] = None,
        trailing_stop: Optional[float] = None,
        price_strength_ema: int = 3,
        volume_strength_wma: int = 21,  # TradingView uses WMA(21), not 18
        trade_regime: str = "Buy"  # "Buy" or "Sell" - determines option selection logic
    ):
        self.segment = segment
        self.rsi_period = rsi_period
        self.timeframe = timeframe
        self.price_strength_ema = price_strength_ema
        self.volume_strength_wma = volume_strength_wma
        # Normalize trade_regime: capitalize first letter, ensure it's "Buy" or "Sell"
        if trade_regime:
            # Strip whitespace and capitalize
            normalized = str(trade_regime).strip().capitalize()
            if normalized in ["Buy", "Sell"]:
                self.trade_regime = normalized
            else:
                logger.warning(f"Invalid trade_regime '{trade_regime}' (normalized: '{normalized}'), defaulting to 'Buy'")
                self.trade_regime = "Buy"
        else:
            self.trade_regime = "Buy"
        logger.info(f"RSIStrategy initialized with trade_regime='{self.trade_regime}' (original: '{trade_regime}')")
        
        # Load VWAP entry conditions from config
        self._load_vwap_config()
        
        # Segment-specific parameters
        self._init_segment_params()
        
        # Override stop loss and trailing stop if provided
        if stop_loss is not None:
            self.stop_loss = stop_loss
        if trailing_stop is not None:
            self.trailing_stop = trailing_stop
    
    def _load_vwap_config(self):
        """Load VWAP entry conditions and PS/VS difference conditions from config.json"""
        try:
            from src.config.config_manager import ConfigManager
            import json
            config_manager = ConfigManager()
            config_path = config_manager.config_dir / "config.json"
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config_data = json.load(f)
                    vwap_config = config_data.get("vwap_entry_conditions", {})
                    self.vwap_enabled = vwap_config.get("enabled", True)
                    self.vwap_price_above = vwap_config.get("price_above_vwap", True)
                    self.vwap_max_diff_pct = vwap_config.get("max_price_vwap_diff_pct", 1.0)
                    self.vwap_tolerance_pct = vwap_config.get("vwap_tolerance_pct", 0.2)
                    
                    # Load PS/VS difference conditions
                    strength_diff_config = config_data.get("strength_diff_conditions", {})
                    self.strength_diff_enabled = strength_diff_config.get("enabled", True)
                    self.min_ps_vs_diff_pct = strength_diff_config.get("min_ps_vs_diff_pct", 2.0)
                    self.max_ps_vs_diff_pct = strength_diff_config.get("max_ps_vs_diff_pct", 5.0)
                    
                    # Load multi-timeframe confirmation settings
                    mtf_config = config_data.get("multi_timeframe_confirmation", {})
                    self.mtf_enabled = mtf_config.get("enabled", True)
                    self.mtf_require_alignment = mtf_config.get("require_alignment", True)
                    self.mtf_momentum_threshold = mtf_config.get("momentum_threshold", 0.5)
                    
                    # Load divergence detection settings
                    divergence_config = config_data.get("divergence_detection", {})
                    self.divergence_enabled = divergence_config.get("enabled", True)
                    self.divergence_threshold = divergence_config.get("threshold", 2.0)
                    
                    # Load volume confirmation settings
                    volume_config = config_data.get("volume_confirmation", {})
                    self.volume_confirmation_enabled = volume_config.get("enabled", True)
                    self.volume_spike_threshold = volume_config.get("spike_threshold", 1.5)
                    
                    # Load dynamic threshold settings
                    dynamic_config = config_data.get("dynamic_threshold", {})
                    self.dynamic_threshold_enabled = dynamic_config.get("enabled", True)
                    self.tight_range = dynamic_config.get("tight_range", [2.0, 3.0])
                    self.wide_range = dynamic_config.get("wide_range", [3.0, 20.0])
                    
                    # Load time session filter settings
                    time_config = config_data.get("time_session_filter", {})
                    self.time_filter_enabled = time_config.get("enabled", True)
                    self.avoid_first_minutes = time_config.get("avoid_first_minutes", 15)
                    self.avoid_last_minutes = time_config.get("avoid_last_minutes", 15)
                    buy_time_config = time_config.get("buy_regime", {})
                    self.buy_start_hour = buy_time_config.get("start_hour", 10)
                    self.buy_start_minute = buy_time_config.get("start_minute", 0)
                    self.buy_end_hour = buy_time_config.get("end_hour", 14)
                    self.buy_end_minute = buy_time_config.get("end_minute", 30)
                    sell_time_config = time_config.get("sell_regime", {})
                    self.sell_start_hour = sell_time_config.get("start_hour", 9)
                    self.sell_start_minute = sell_time_config.get("start_minute", 30)
                    self.sell_end_hour = sell_time_config.get("end_hour", 15)
                    self.sell_end_minute = sell_time_config.get("end_minute", 15)
                    
                    # Load ATR volatility filter settings
                    atr_config = config_data.get("atr_volatility_filter", {})
                    self.atr_filter_enabled = atr_config.get("enabled", True)
                    self.atr_period = atr_config.get("atr_period", 14)
                    buy_atr_config = atr_config.get("buy_regime", {})
                    buy_min = buy_atr_config.get("min_atr_multiplier")
                    self.buy_min_atr_multiplier = buy_min if buy_min is not None else 1.0
                    self.buy_max_atr_multiplier = buy_atr_config.get("max_atr_multiplier")  # Can be None (no upper limit)
                    sell_atr_config = atr_config.get("sell_regime", {})
                    sell_min = sell_atr_config.get("min_atr_multiplier")
                    self.sell_min_atr_multiplier = sell_min if sell_min is not None else 0.8
                    sell_max = sell_atr_config.get("max_atr_multiplier")
                    self.sell_max_atr_multiplier = sell_max if sell_max is not None else 1.5
                    
                    # Load RSI extreme filter settings
                    rsi_extreme_config = config_data.get("rsi_extreme_filter", {})
                    self.rsi_extreme_filter_enabled = rsi_extreme_config.get("enabled", True)
                    buy_rsi_config = rsi_extreme_config.get("buy_regime", {})
                    buy_ce_max = buy_rsi_config.get("ce_max_rsi")
                    self.buy_ce_max_rsi = buy_ce_max if buy_ce_max is not None else 75
                    buy_pe_min = buy_rsi_config.get("pe_min_rsi")
                    self.buy_pe_min_rsi = buy_pe_min if buy_pe_min is not None else 25
                    sell_rsi_config = rsi_extreme_config.get("sell_regime", {})
                    sell_ce_min = sell_rsi_config.get("ce_min_rsi")
                    self.sell_ce_min_rsi = sell_ce_min if sell_ce_min is not None else 60
                    sell_pe_max = sell_rsi_config.get("pe_max_rsi")
                    self.sell_pe_max_rsi = sell_pe_max if sell_pe_max is not None else 40
                    dynamic_config = config_data.get("dynamic_threshold", {})
                    self.dynamic_threshold_enabled = dynamic_config.get("enabled", True)
                    self.dynamic_tight_range = dynamic_config.get("tight_range", [2.0, 3.0])
                    self.dynamic_wide_range = dynamic_config.get("wide_range", [3.0, 5.0])
            else:
                # Default values
                self.vwap_enabled = True
                self.vwap_price_above = True
                self.vwap_max_diff_pct = 1.0
                self.vwap_tolerance_pct = 0.2
                self.strength_diff_enabled = True
                self.min_ps_vs_diff_pct = 2.0
                self.max_ps_vs_diff_pct = 5.0
                self.mtf_enabled = True
                self.mtf_require_alignment = True
                self.mtf_momentum_threshold = 0.5
                self.divergence_enabled = True
                self.divergence_threshold = 2.0
                self.volume_confirmation_enabled = True
                self.volume_spike_threshold = 1.5
                self.dynamic_threshold_enabled = True
                self.dynamic_tight_range = [2.0, 3.0]
                self.dynamic_wide_range = [3.0, 5.0]
                
                # Default filter values (if config loading fails)
                self.time_filter_enabled = True
                self.avoid_first_minutes = 15
                self.avoid_last_minutes = 15
                self.buy_start_hour = 10
                self.buy_start_minute = 0
                self.buy_end_hour = 14
                self.buy_end_minute = 30
                self.sell_start_hour = 9
                self.sell_start_minute = 30
                self.sell_end_hour = 15
                self.sell_end_minute = 15
                
                self.atr_filter_enabled = True
                self.atr_period = 14
                self.buy_min_atr_multiplier = 1.0
                self.buy_max_atr_multiplier = None
                self.sell_min_atr_multiplier = 0.8
                self.sell_max_atr_multiplier = 1.5
                
                self.rsi_extreme_filter_enabled = True
                self.buy_ce_max_rsi = 75
                self.buy_pe_min_rsi = 25
                self.sell_ce_min_rsi = 60
                self.sell_pe_max_rsi = 40
        except Exception as e:
            logger.warning(f"Could not load config: {e}, using defaults")
            # Set defaults here too
            self.time_filter_enabled = True
            self.avoid_first_minutes = 15
            self.avoid_last_minutes = 15
            self.buy_start_hour = 10
            self.buy_start_minute = 0
            self.buy_end_hour = 14
            self.buy_end_minute = 30
            self.sell_start_hour = 9
            self.sell_start_minute = 30
            self.sell_end_hour = 15
            self.sell_end_minute = 15
            
            self.atr_filter_enabled = True
            self.atr_period = 14
            self.buy_min_atr_multiplier = 1.0
            self.buy_max_atr_multiplier = None
            self.sell_min_atr_multiplier = 0.8
            self.sell_max_atr_multiplier = 1.5
            
            self.rsi_extreme_filter_enabled = True
            self.buy_ce_max_rsi = 75
            self.buy_pe_min_rsi = 25
            self.sell_ce_min_rsi = 60
            self.sell_pe_max_rsi = 40
            self.vwap_enabled = True
            self.vwap_price_above = True
            self.vwap_max_diff_pct = 1.0
            self.vwap_tolerance_pct = 0.2
            self.strength_diff_enabled = True
            self.min_ps_vs_diff_pct = 1.0
            self.mtf_enabled = True
            self.mtf_require_alignment = True
            self.mtf_momentum_threshold = 0.5
            self.divergence_enabled = True
            self.divergence_threshold = 2.0
            self.volume_confirmation_enabled = True
            self.volume_spike_threshold = 1.5
            self.dynamic_threshold_enabled = True
            self.dynamic_tight_range = [2.0, 3.0]
            self.dynamic_wide_range = [3.0, 5.0]
    
    def _init_segment_params(self):
        """Initialize segment-specific parameters"""
        if self.segment == Segment.NIFTY:
            self.initial_lot_size = 1
            self.stop_loss = 20
            self.trailing_stop = 20
            self.lot2_profit_threshold = 750
            self.lot2_lots = 5
            self.lot3_profit_threshold = 3750
            self.lot3_lots = 5
            self.lot4_profit_threshold = 5000
            self.lot4_lots = 5
        elif self.segment == Segment.SENSEX:
            self.initial_lot_size = 1
            self.stop_loss = 50
            self.trailing_stop = 50
            self.lot2_profit_threshold = 400
            self.lot2_lots = 10
            self.lot3_profit_threshold = 4000
            self.lot3_lots = 10
            self.lot4_profit_threshold = 10000
            self.lot4_lots = 10
        elif self.segment == Segment.BANKNIFTY:
            self.initial_lot_size = 1
            self.stop_loss = 50
            self.trailing_stop = 50
            self.lot2_profit_threshold = 400
            self.lot2_lots = 10
            self.lot3_profit_threshold = 4000
            self.lot3_lots = 10
            self.lot4_profit_threshold = 10000
            self.lot4_lots = 10
    
    def calculate_rsi(self, prices: pd.Series, period: int = None) -> pd.Series:
        """
        Calculate RSI indicator using Wilder's smoothing method (matching TradingView)
        RSI Source: Close (as per TradingView "Hilega Milega" indicator settings)
        RSI Length: 9 (default, configurable via self.rsi_period)
        
        Wilder's Smoothing Method:
        - First period: Simple average of gains and losses
        - Subsequent periods: avg_gain = (prev_avg_gain * (period - 1) + current_gain) / period
        - Same for losses
        
        Args:
            prices: Price series (typically close prices)
            period: RSI period (defaults to self.rsi_period = 9)
        
        Returns:
            RSI series
        """
        if period is None:
            period = self.rsi_period
        
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        
        # Use EWM with alpha=1/period to approximate Wilder's smoothing
        # This matches TradingView's RSI calculation
        # alpha = 1/period gives the same smoothing factor as Wilder's method
        gain_ema = pd.Series(gain, index=prices.index).ewm(alpha=1.0/period, adjust=False).mean()
        loss_ema = pd.Series(loss, index=prices.index).ewm(alpha=1.0/period, adjust=False).mean()
        
        # Avoid division by zero
        rs = gain_ema / loss_ema.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_price_strength(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate Price Strength (Blue line)
        Price Strength = EMA(price_strength_ema) of RSI(9)
        Matching TradingView "Hilega Milega" indicator: Price Strength Indicator (EMA) = 3
        
        TradingView EMA formula: EMA = (Price - Previous EMA) * (2 / (Period + 1)) + Previous EMA
        This is equivalent to pandas ewm(span=period, adjust=False).mean()
        
        Steps:
        1. Calculate RSI(9) from close prices
        2. Apply EMA(price_strength_ema) on RSI to get Price Strength
        
        Returns:
            Price Strength EMA series (price_strength_ema-period EMA of RSI)
        """
        # First calculate RSI(9)
        rsi_series = self.calculate_rsi(df['close'], period=self.rsi_period)
        
        # Apply EMA(price_strength_ema) on RSI
        # TradingView EMA uses smoothing factor = 2 / (period + 1)
        # pandas ewm(span=period) uses alpha = 2 / (span + 1), which matches TradingView
        # adjust=False ensures we use the exact formula without bias adjustment
        ema_result = rsi_series.ewm(span=self.price_strength_ema, adjust=False).mean()
        
        # Ensure no NaN values propagate (forward fill if needed)
        # First valid value should be the first RSI value (after RSI calculation is valid)
        return ema_result
    
    def calculate_volume_strength(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate Volume Strength (Red line)
        Volume Strength = WMA(volume_strength_wma) of RSI(9)
        Matching TradingView "Hilega Milega" indicator: Volume Strength Indicator (WMA) = 21
        
        TradingView WMA formula: WMA = (n*P1 + (n-1)*P2 + ... + 1*Pn) / (n + (n-1) + ... + 1)
        Where P1 is most recent value, Pn is oldest value
        This matches the standard WMA implementation
        
        Steps:
        1. Calculate RSI(9) from close prices
        2. Apply WMA(volume_strength_wma) on RSI to get Volume Strength
        
        Returns:
            Volume Strength WMA series (volume_strength_wma-period WMA of RSI)
        """
        period = self.volume_strength_wma
        
        # First calculate RSI(9)
        rsi_series = self.calculate_rsi(df['close'], period=self.rsi_period)
        
        # WMA weights: most recent gets highest weight (period), oldest gets weight (1)
        # pandas rolling() gives values in chronological order [oldest, ..., newest]
        # So we need weights [1, 2, 3, ..., period] to apply to [oldest, ..., newest]
        # This gives: 1*oldest + 2*second_oldest + ... + period*newest
        # Which matches TradingView's WMA where newest value gets highest weight
        weights = np.arange(1, period + 1)  # [1, 2, 3, ..., 21] for period=21
        
        def wma_func(x):
            """
            Calculate WMA for a window of values.
            x is array in chronological order [oldest, ..., newest]
            weights are [1, 2, 3, ..., period] applied to [oldest, ..., newest]
            """
            if len(x) < period:
                return np.nan
            
            # Convert to numpy array
            x = np.array(x)
            
            # Check if all values are NaN
            if np.all(np.isnan(x)):
                return np.nan
            
            # Handle NaN values: forward fill from first valid value
            # This ensures we don't get NaN in the middle of valid data
            valid_mask = ~np.isnan(x)
            if not np.any(valid_mask):
                return np.nan
            
            # Forward fill NaN values (use last valid value)
            first_valid_idx = np.where(valid_mask)[0][0]
            for i in range(len(x)):
                if np.isnan(x[i]):
                    if i > first_valid_idx:
                        x[i] = x[i-1]  # Use previous value
                    else:
                        x[i] = x[first_valid_idx]  # Use first valid value
            
            # Calculate WMA: weights applied to chronological order
            # x[0] = oldest (weight 1), x[period-1] = newest (weight period)
            # TradingView WMA: (n*P1 + (n-1)*P2 + ... + 1*Pn) / sum
            # Where P1 is newest, Pn is oldest
            # Our x is [oldest, ..., newest], so we apply weights [1, 2, ..., period]
            # This gives: 1*oldest + 2*... + period*newest = period*newest + ... + 1*oldest ✓
            wma_value = np.sum(weights * x) / np.sum(weights)
            return wma_value
        
        # Apply WMA using rolling window
        wma_result = rsi_series.rolling(window=period, min_periods=period).apply(wma_func, raw=True)
        
        return wma_result
    
    def is_bearish_candle(self, row: pd.Series) -> bool:
        """Check if candle is bearish (red)"""
        return row['close'] < row['open']
    
    def is_bullish_candle(self, row: pd.Series) -> bool:
        """Check if candle is bullish (green)"""
        return row['close'] > row['open']
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Calculate Average True Range (ATR) for volatility measurement.
        
        ATR = Moving Average of True Range
        True Range = max(High - Low, abs(High - Previous Close), abs(Low - Previous Close))
        
        Args:
            df: DataFrame with OHLC data
            period: Period for ATR calculation (default: 14)
            
        Returns:
            Series with ATR values
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Calculate True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Calculate ATR as SMA of True Range
        atr = true_range.rolling(window=period).mean()
        
        return atr
    
    def check_time_session_filter(self, current_time: datetime, signal_type: str) -> Tuple[bool, str]:
        """
        Check if current time is within optimal trading session.
        
        Args:
            current_time: Current datetime
            signal_type: "CE" or "PE"
            
        Returns:
            Tuple of (passed, reason)
        """
        if not self.time_filter_enabled:
            return True, "Time filter disabled"
        
        from src.utils.date_utils import get_market_hours
        
        current_hour = current_time.hour
        current_minute = current_time.minute
        current_time_minutes = current_hour * 60 + current_minute
        
        # Get market hours from config.json
        market_open_time, market_close_time = get_market_hours()
        market_open_minutes = market_open_time.hour * 60 + market_open_time.minute
        market_close_minutes = market_close_time.hour * 60 + market_close_time.minute
        
        # Avoid first N minutes after market open
        avoid_first_end_minutes = market_open_minutes + self.avoid_first_minutes
        # Avoid last N minutes before market close
        avoid_last_start_minutes = market_close_minutes - self.avoid_last_minutes
        
        if current_time_minutes < avoid_first_end_minutes:
            return False, f"Too early: Within first {self.avoid_first_minutes} minutes after market open"
        
        if current_time_minutes >= avoid_last_start_minutes:
            return False, f"Too late: Within last {self.avoid_last_minutes} minutes before market close"
        
        if self.trade_regime == "Buy":
            # Buy regime: Single optimal window
            start_minutes = self.buy_start_hour * 60 + self.buy_start_minute
            end_minutes = self.buy_end_hour * 60 + self.buy_end_minute
            
            if start_minutes <= current_time_minutes < end_minutes:
                return True, f"Optimal session: {self.buy_start_hour:02d}:{self.buy_start_minute:02d}-{self.buy_end_hour:02d}:{self.buy_end_minute:02d}"
            else:
                return False, f"Outside optimal session: {self.buy_start_hour:02d}:{self.buy_start_minute:02d}-{self.buy_end_hour:02d}:{self.buy_end_minute:02d}"
        
        else:  # Sell regime
            # Sell regime: Single continuous window (no lunch break)
            start_minutes = self.sell_start_hour * 60 + self.sell_start_minute
            end_minutes = self.sell_end_hour * 60 + self.sell_end_minute
            
            if start_minutes <= current_time_minutes < end_minutes:
                return True, f"Optimal session: {self.sell_start_hour:02d}:{self.sell_start_minute:02d}-{self.sell_end_hour:02d}:{self.sell_end_minute:02d}"
            else:
                return False, f"Outside optimal session: {self.sell_start_hour:02d}:{self.sell_start_minute:02d}-{self.sell_end_hour:02d}:{self.sell_end_minute:02d}"
    
    def check_atr_volatility_filter(self, df: pd.DataFrame, current_idx: int) -> Tuple[bool, str, Optional[float], Optional[float]]:
        """
        Check if ATR volatility meets requirements for entry.
        
        Args:
            df: DataFrame with OHLC data
            current_idx: Current index in DataFrame
            
        Returns:
            Tuple of (passed, reason, current_atr, avg_atr)
        """
        if not self.atr_filter_enabled:
            return True, "ATR filter disabled", None, None
        
        if current_idx < self.atr_period:
            return True, f"Insufficient data for ATR (need {self.atr_period} candles)", None, None
        
        # Calculate ATR
        atr_series = self.calculate_atr(df, self.atr_period)
        current_atr = atr_series.iloc[current_idx]
        
        # Calculate average ATR (using last 20 periods for smoother average)
        lookback = min(20, current_idx)
        avg_atr = atr_series.iloc[current_idx - lookback:current_idx + 1].mean()
        
        if pd.isna(current_atr) or pd.isna(avg_atr) or avg_atr == 0:
            return True, "ATR calculation unavailable", current_atr, avg_atr
        
        atr_ratio = current_atr / avg_atr
        
        if self.trade_regime == "Buy":
            min_multiplier = getattr(self, 'buy_min_atr_multiplier', None)
            max_multiplier = getattr(self, 'buy_max_atr_multiplier', None)
            
            # Ensure multipliers are not None (defensive check)
            if min_multiplier is None:
                min_multiplier = 1.0  # Default fallback
            # max_multiplier can be None (no upper limit for Buy regime)
            
            # Safe comparison - ensure min_multiplier is not None before comparing
            if min_multiplier is not None and atr_ratio < min_multiplier:
                return False, f"ATR too low: {atr_ratio:.2f}x (min: {min_multiplier:.2f}x)", current_atr, avg_atr
            if max_multiplier is not None and atr_ratio > max_multiplier:
                return False, f"ATR too high: {atr_ratio:.2f}x (max: {max_multiplier:.2f}x)", current_atr, avg_atr
            
            return True, f"ATR acceptable: {atr_ratio:.2f}x (range: {min_multiplier:.2f}-{max_multiplier if max_multiplier else '∞'}x)", current_atr, avg_atr
        
        else:  # Sell regime
            min_multiplier = getattr(self, 'sell_min_atr_multiplier', None)
            max_multiplier = getattr(self, 'sell_max_atr_multiplier', None)
            
            # Ensure multipliers are not None (defensive check)
            if min_multiplier is None:
                min_multiplier = 0.8  # Default fallback
            if max_multiplier is None:
                max_multiplier = 1.5  # Default fallback
            
            # Safe comparison - ensure multipliers are not None before comparing
            if min_multiplier is not None and atr_ratio < min_multiplier:
                return False, f"ATR too low: {atr_ratio:.2f}x (min: {min_multiplier:.2f}x)", current_atr, avg_atr
            if max_multiplier is not None and atr_ratio > max_multiplier:
                return False, f"ATR too high: {atr_ratio:.2f}x (max: {max_multiplier:.2f}x)", current_atr, avg_atr
            
            return True, f"ATR acceptable: {atr_ratio:.2f}x (range: {min_multiplier:.2f}-{max_multiplier:.2f}x)", current_atr, avg_atr
    
    def check_rsi_extreme_filter(self, rsi_value: Optional[float], signal_type: str) -> Tuple[bool, str]:
        """
        Check if RSI is at acceptable levels for entry.
        
        Args:
            rsi_value: Current RSI value
            signal_type: "CE" or "PE"
            
        Returns:
            Tuple of (passed, reason)
        """
        if not self.rsi_extreme_filter_enabled:
            return True, "RSI extreme filter disabled"
        
        if rsi_value is None or pd.isna(rsi_value):
            return True, "RSI unavailable"
        
        if self.trade_regime == "Buy":
            if signal_type == "CE":
                max_rsi = getattr(self, 'buy_ce_max_rsi', None)
                if max_rsi is None:
                    max_rsi = 75  # Default fallback
                if rsi_value > max_rsi:
                    return False, f"RSI overbought: {rsi_value:.2f} > {max_rsi} (CE entry)"
                return True, f"RSI acceptable: {rsi_value:.2f} <= {max_rsi} (CE entry)"
            else:  # PE
                min_rsi = getattr(self, 'buy_pe_min_rsi', None)
                if min_rsi is None:
                    min_rsi = 25  # Default fallback
                if rsi_value < min_rsi:
                    return False, f"RSI oversold: {rsi_value:.2f} < {min_rsi} (PE entry)"
                return True, f"RSI acceptable: {rsi_value:.2f} >= {min_rsi} (PE entry)"
        
        else:  # Sell regime
            if signal_type == "CE":
                min_rsi = getattr(self, 'sell_ce_min_rsi', None)
                if min_rsi is None:
                    min_rsi = 60  # Default fallback
                if rsi_value < min_rsi:
                    return False, f"RSI too low: {rsi_value:.2f} < {min_rsi} (Sell CE - need overbought for decay)"
                return True, f"RSI acceptable: {rsi_value:.2f} >= {min_rsi} (Sell CE - overbought for decay)"
            else:  # PE
                max_rsi = getattr(self, 'sell_pe_max_rsi', None)
                if max_rsi is None:
                    max_rsi = 40  # Default fallback
                if rsi_value > max_rsi:
                    return False, f"RSI too high: {rsi_value:.2f} > {max_rsi} (Sell PE - need oversold for decay)"
                return True, f"RSI acceptable: {rsi_value:.2f} <= {max_rsi} (Sell PE - oversold for decay)"
    
    def calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate VWAP (Volume Weighted Average Price)
        
        VWAP = Σ(Price × Volume) / Σ(Volume)
        Where Price = (High + Low + Close) / 3 (typical price)
        
        For indices or when volume is missing/zero, falls back to simple moving average
        of typical price (since indices don't have volume like stocks).
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            VWAP series (cumulative VWAP from start of day, or SMA fallback if no volume)
        """
        # Calculate typical price for each candle
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        
        # Get volume (use 0 if volume column doesn't exist)
        volume = df.get('volume', pd.Series(0, index=df.index))
        
        # Check if we have valid volume data (non-zero values)
        total_volume = volume.sum()
        has_valid_volume = total_volume > 0 and not volume.isna().all()
        
        if not has_valid_volume:
            # Fallback: Use simple moving average of typical price (for indices without volume)
            # This provides a similar reference point as VWAP
            logger.debug("No valid volume data available, using SMA of typical price as VWAP fallback")
            # Use cumulative average (expanding window) to simulate VWAP behavior
            vwap = typical_price.expanding(min_periods=1).mean()
            return vwap
        
        # Calculate cumulative price × volume and cumulative volume
        cumulative_price_volume = (typical_price * volume).cumsum()
        cumulative_volume = volume.cumsum()
        
        # Calculate VWAP (avoid division by zero)
        # Replace zeros with NaN to avoid division by zero, but keep valid values
        vwap = cumulative_price_volume / cumulative_volume.replace(0, np.nan)
        
        # Forward fill NaN values (for initial candles where cumulative volume is 0)
        # This happens when first few candles have zero volume
        vwap = vwap.ffill()
        
        # If still NaN at the start, use typical price for first candle
        if len(vwap) > 0 and pd.isna(vwap.iloc[0]):
            vwap.iloc[0] = typical_price.iloc[0]
            vwap = vwap.ffill()
        
        return vwap
    
    def check_strength_crossover(
        self, 
        price_strength: pd.Series, 
        volume_strength: pd.Series, 
        current_idx: int
    ) -> Tuple[bool, bool]:
        """
        Check Price Strength vs Volume Strength crossover conditions
        
        Args:
            price_strength: Price Strength EMA series (3 EMA of price, blue line)
            volume_strength: Volume Strength WMA series (21 WMA of RSI, red line)
            current_idx: Current index in dataframe
        
        Returns:
            (pe_signal, ce_signal)
            - pe_signal: True if Price Strength crosses DOWNWARDS to Volume Strength from above
            - ce_signal: True if Price Strength crosses UPWARD to Volume Strength from below
        """
        if current_idx < 1:
            return False, False
        
        # Get current and previous values
        curr_price_strength = price_strength.iloc[current_idx]
        prev_price_strength = price_strength.iloc[current_idx - 1]
        curr_volume_strength = volume_strength.iloc[current_idx]
        prev_volume_strength = volume_strength.iloc[current_idx - 1]
        
        # Skip if any values are NaN
        if (pd.isna(curr_price_strength) or pd.isna(prev_price_strength) or 
            pd.isna(curr_volume_strength) or pd.isna(prev_volume_strength)):
            return False, False
        
        # PE Signal: Price Strength (blue) crosses DOWNWARDS to Volume Strength (red) from above
        # Previous: Price Strength > Volume Strength
        # Current: Price Strength < Volume Strength (crossed down - strict)
        pe_signal = (prev_price_strength > prev_volume_strength and 
                    curr_price_strength < curr_volume_strength)
        
        # CE Signal: Price Strength (blue) crosses UPWARD to Volume Strength (red) from below
        # Previous: Price Strength < Volume Strength
        # Current: Price Strength > Volume Strength (crossed up - strict)
        ce_signal = (prev_price_strength < prev_volume_strength and 
                    curr_price_strength > curr_volume_strength)
        
        return pe_signal, ce_signal
    
    def calculate_1min_ps_vs(self, df_1min: pd.DataFrame) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
        """
        Calculate 1-minute Price Strength and Volume Strength for multi-timeframe confirmation.
        
        Args:
            df_1min: DataFrame with 1-minute OHLCV data
            
        Returns:
            (price_strength_1min, volume_strength_1min) or (None, None) if insufficient data
        """
        try:
            if len(df_1min) < max(self.rsi_period, self.volume_strength_wma):
                return None, None
            
            price_strength_1min = self.calculate_price_strength(df_1min)
            volume_strength_1min = self.calculate_volume_strength(df_1min)
            
            return price_strength_1min, volume_strength_1min
        except Exception as e:
            logger.warning(f"Error calculating 1-minute PS/VS: {e}")
            return None, None
    
    def check_multi_timeframe_alignment(
        self,
        ps_5min: float,
        vs_5min: float,
        ps_1min: Optional[float],
        vs_1min: Optional[float],
        signal_type: str  # "PE" or "CE"
    ) -> Tuple[bool, str]:
        """
        Check if 1-minute PS/VS aligns with 5-minute signal direction.
        
        Args:
            ps_5min: 5-minute Price Strength
            vs_5min: 5-minute Volume Strength
            ps_1min: 1-minute Price Strength (None if unavailable)
            vs_1min: 1-minute Volume Strength (None if unavailable)
            signal_type: "PE" (bearish) or "CE" (bullish)
            
        Returns:
            (aligned, reason)
        """
        if not self.mtf_enabled or not self.mtf_require_alignment:
            return True, "Multi-timeframe confirmation disabled"
        
        if ps_1min is None or vs_1min is None:
            return True, "1-minute PS/VS unavailable (proceeding with 5-min only)"
        
        if signal_type == "PE":
            # PE signal: PS crosses DOWN to VS (bearish)
            # 1-min should confirm: PS < VS or PS declining
            aligned = ps_1min <= vs_1min
            reason = f"1-min PS={ps_1min:.2f} {'<=' if aligned else '>'} VS={vs_1min:.2f}"
        else:  # CE
            # CE signal: PS crosses UP to VS (bullish)
            # 1-min should confirm: PS > VS or PS rising
            aligned = ps_1min >= vs_1min
            reason = f"1-min PS={ps_1min:.2f} {'>=' if aligned else '<'} VS={vs_1min:.2f}"
        
        return aligned, reason
    
    def calculate_momentum(
        self,
        ps_series: pd.Series,
        vs_series: pd.Series,
        lookback: int = 3
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate PS and VS momentum (rate of change).
        
        Args:
            ps_series: Price Strength series
            vs_series: Volume Strength series
            lookback: Number of periods to look back
            
        Returns:
            (ps_momentum, vs_momentum) in points per period
        """
        try:
            if len(ps_series) < lookback + 1:
                return None, None
            
            current_ps = ps_series.iloc[-1]
            past_ps = ps_series.iloc[-(lookback + 1)]
            ps_momentum = (current_ps - past_ps) / lookback
            
            current_vs = vs_series.iloc[-1]
            past_vs = vs_series.iloc[-(lookback + 1)]
            vs_momentum = (current_vs - past_vs) / lookback
            
            return ps_momentum, vs_momentum
        except Exception as e:
            logger.warning(f"Error calculating momentum: {e}")
            return None, None
    
    def check_momentum_filter(
        self,
        ps_momentum: Optional[float],
        vs_momentum: Optional[float],
        signal_type: str  # "PE" or "CE"
    ) -> Tuple[bool, str]:
        """
        Check if momentum confirms signal direction.
        
        Args:
            ps_momentum: PS momentum (points per period)
            vs_momentum: VS momentum (points per period)
            signal_type: "PE" (bearish) or "CE" (bullish)
            
        Returns:
            (passed, reason)
        """
        if not self.mtf_enabled or ps_momentum is None:
            return True, "Momentum filter disabled or unavailable"
        
        threshold = self.mtf_momentum_threshold
        
        if signal_type == "PE":
            # PE signal: PS should be declining (negative momentum)
            passed = ps_momentum <= -threshold
            reason = f"PS momentum={ps_momentum:.2f} {'<=' if passed else '>'} -{threshold} (declining)"
        else:  # CE
            # CE signal: PS should be rising (positive momentum)
            passed = ps_momentum >= threshold
            reason = f"PS momentum={ps_momentum:.2f} {'>=' if passed else '<'} {threshold} (rising)"
        
        return passed, reason
    
    def check_divergence(
        self,
        ps_5min: float,
        vs_5min: float,
        ps_1min: Optional[float],
        vs_1min: Optional[float],
        signal_type: str  # "PE" or "CE"
    ) -> Tuple[bool, str]:
        """
        Detect divergence between 5-minute and 1-minute PS/VS.
        
        Args:
            ps_5min: 5-minute Price Strength
            vs_5min: 5-minute Volume Strength
            ps_1min: 1-minute Price Strength (None if unavailable)
            vs_1min: 1-minute Volume Strength (None if unavailable)
            signal_type: "PE" or "CE"
            
        Returns:
            (no_divergence, reason) - True if no significant divergence
        """
        if not self.divergence_enabled or ps_1min is None or vs_1min is None:
            return True, "Divergence detection disabled or 1-min data unavailable"
        
        # Calculate PS/VS difference for both timeframes
        diff_5min = ps_5min - vs_5min
        diff_1min = ps_1min - vs_1min
        
        # Check for divergence
        if signal_type == "PE":
            # PE signal: 5-min PS < VS (negative diff), but 1-min PS > VS (positive diff) = divergence
            divergence = (diff_5min < 0 and diff_1min > 0) or (diff_5min > 0 and diff_1min < 0)
        else:  # CE
            # CE signal: 5-min PS > VS (positive diff), but 1-min PS < VS (negative diff) = divergence
            divergence = (diff_5min > 0 and diff_1min < 0) or (diff_5min < 0 and diff_1min > 0)
        
        # Check if divergence is significant
        if divergence:
            divergence_magnitude = abs(diff_5min - diff_1min)
            significant = divergence_magnitude >= self.divergence_threshold
            if significant:
                return False, f"Significant divergence: 5-min diff={diff_5min:.2f}, 1-min diff={diff_1min:.2f}, magnitude={divergence_magnitude:.2f}"
            else:
                return True, f"Minor divergence (within threshold): 5-min diff={diff_5min:.2f}, 1-min diff={diff_1min:.2f}"
        
        return True, f"No divergence: 5-min diff={diff_5min:.2f}, 1-min diff={diff_1min:.2f}"
    
    def check_volume_confirmation(
        self,
        df_1min: pd.DataFrame,
        lookback: int = 5
    ) -> Tuple[bool, str]:
        """
        Check if volume confirms the signal (volume spike on 1-minute).
        
        Args:
            df_1min: 1-minute DataFrame
            lookback: Number of periods to look back for average volume
            
        Returns:
            (confirmed, reason)
        """
        if not self.volume_confirmation_enabled or len(df_1min) < lookback + 1:
            return True, "Volume confirmation disabled or insufficient data"
        
        try:
            current_volume = df_1min['volume'].iloc[-1]
            avg_volume = df_1min['volume'].iloc[-(lookback + 1):-1].mean()
            
            if avg_volume == 0:
                return True, "Average volume is zero (cannot confirm)"
            
            volume_ratio = current_volume / avg_volume
            confirmed = volume_ratio >= self.volume_spike_threshold
            
            reason = f"Volume ratio={volume_ratio:.2f} ({'>= ' if confirmed else '< '}{self.volume_spike_threshold})"
            return confirmed, reason
        except Exception as e:
            logger.warning(f"Error checking volume confirmation: {e}")
            return True, f"Volume check error: {e}"
    
    def get_dynamic_threshold(
        self,
        ps_1min: Optional[float],
        vs_1min: Optional[float],
        ps_5min: float,
        vs_5min: float
    ) -> Tuple[float, float]:
        """
        Get dynamic PS/VS difference thresholds based on 1-minute alignment.
        
        Args:
            ps_1min: 1-minute Price Strength
            vs_1min: 1-minute Volume Strength
            ps_5min: 5-minute Price Strength
            vs_5min: 5-minute Volume Strength
            
        Returns:
            (min_threshold, max_threshold)
        """
        if not self.dynamic_threshold_enabled:
            return self.min_ps_vs_diff_pct, self.max_ps_vs_diff_pct
        
        # Check if 1-minute aligns with 5-minute
        if ps_1min is not None and vs_1min is not None:
            diff_5min = ps_5min - vs_5min
            diff_1min = ps_1min - vs_1min
            
            # If both have same sign (aligned), use tight range
            if (diff_5min > 0 and diff_1min > 0) or (diff_5min < 0 and diff_1min < 0):
                return self.dynamic_tight_range[0], self.dynamic_tight_range[1]
        
        # Otherwise use wide range
        return self.dynamic_wide_range[0], self.dynamic_wide_range[1]
    
    def generate_signal(
        self,
        df: pd.DataFrame,
        current_idx: int,
        allow_reentry: bool = False,
        reentry_candle_type: Optional[str] = None,
        df_1min: Optional[pd.DataFrame] = None
    ) -> Tuple[TradeSignal, Optional[OptionType], str, Dict[str, Any]]:
        """
        Generate trading signal based on revised RSI strategy with Price Strength vs Volume Strength
        
        Args:
            df: DataFrame with OHLCV data
            current_idx: Current index in dataframe
            allow_reentry: If True, allow re-entry on matching candle type after SL hit
            reentry_candle_type: 'bearish' or 'bullish' - required candle type for re-entry
            
        Returns:
            (signal, option_type, reason, details)
        """
        details: Dict[str, Any] = {
            "price_strength": None,
            "volume_strength": None,
            "candle_type": "unavailable",
            "checks": []
        }

        def add_check(label: str, passed: bool, value: Any = None) -> None:
            entry = {"label": label, "passed": bool(passed)}
            if value is not None:
                entry["value"] = value
            details["checks"].append(entry)

        # Check if we have enough data for RSI (needs at least rsi_period candles), EMA (needs at least price_strength_ema), and WMA (needs at least volume_strength_wma)
        # Since we need RSI first, then apply EMA and WMA, we need at least max(rsi_period, volume_strength_wma) candles
        if current_idx < self.rsi_period:
            add_check("RSI samples available", False, f"{current_idx}/9")
            details["rsi_value"] = None
            details["rsi_status"] = f"Insufficient data: need 9 candles, have {current_idx}"
            return TradeSignal.HOLD, None, "Insufficient data for RSI calculation", details
        
        # Calculate RSI first to get the value for logging
        rsi_series = self.calculate_rsi(df['close'], period=self.rsi_period)
        
        # Get RSI value for current candle
        current_rsi = rsi_series.iloc[current_idx] if current_idx < len(rsi_series) else None
        if current_rsi is None or pd.isna(current_rsi):
            details["rsi_value"] = None
            details["rsi_status"] = "RSI calculation returned NaN (insufficient price movement or division by zero)"
        else:
            details["rsi_value"] = float(current_rsi)
            details["rsi_status"] = "RSI calculated successfully"
        
        # Calculate Price Strength (EMA(price_strength_ema) of RSI(rsi_period)) and Volume Strength (WMA(volume_strength_wma) of RSI(rsi_period))
        # These methods internally calculate RSI again, but that's okay for now
        price_strength = self.calculate_price_strength(df)
        volume_strength = self.calculate_volume_strength(df)
        
        # VWAP is now checked at the strike level in execution layer, not here
        # Keeping VWAP calculation disabled for signal generation
        vwap_series = None
        details["vwap"] = None
        
        if current_idx < self.volume_strength_wma:
            add_check("Volume Strength samples available", False, f"{current_idx}/{self.volume_strength_wma}")
            return TradeSignal.HOLD, None, "Insufficient data for Volume Strength WMA", details
        
        # Check if Price Strength and Volume Strength are valid
        if pd.isna(price_strength.iloc[current_idx]) or pd.isna(volume_strength.iloc[current_idx]):
            ps_val = price_strength.iloc[current_idx] if current_idx < len(price_strength) else None
            vs_val = volume_strength.iloc[current_idx] if current_idx < len(volume_strength) else None
            add_check("Strength indicators valid", False, f"PS={ps_val}, VS={vs_val}")
            logger.warning(
                f"Price/Volume Strength not calculated at index {current_idx}: "
                f"PS={ps_val}, VS={vs_val}, RSI={details.get('rsi_value', 'N/A')}"
            )
            return TradeSignal.HOLD, None, "Price/Volume Strength not calculated", details
        
        curr_price_strength = float(price_strength.iloc[current_idx])
        curr_volume_strength = float(volume_strength.iloc[current_idx])
        details["price_strength"] = curr_price_strength
        details["volume_strength"] = curr_volume_strength
        
        # Log calculated values for debugging with more detail
        rsi_val = details.get("rsi_value", current_rsi)
        if rsi_val is not None and not pd.isna(rsi_val):
            # Get previous values for comparison
            prev_ps = float(price_strength.iloc[current_idx - 1]) if current_idx > 0 else None
            prev_vs = float(volume_strength.iloc[current_idx - 1]) if current_idx > 0 else None
            prev_rsi = float(self.calculate_rsi(df['close'], period=self.rsi_period).iloc[current_idx - 1]) if current_idx > 0 else None
            
            logger.info(
                f"📊 Indicator Values at index {current_idx}: "
                f"RSI={float(rsi_val):.2f}, PS={curr_price_strength:.2f}, VS={curr_volume_strength:.2f}"
            )
            if prev_ps is not None and prev_vs is not None:
                prev_rsi_str = f"{prev_rsi:.2f}" if prev_rsi is not None else "N/A"
                logger.info(
                    f"📊 Previous Values (index {current_idx - 1}): "
                    f"RSI={prev_rsi_str}, PS={prev_ps:.2f}, VS={prev_vs:.2f}"
                )
                logger.info(
                    f"📊 Crossover Analysis: "
                    f"PS change: {prev_ps:.2f} → {curr_price_strength:.2f} ({curr_price_strength - prev_ps:+.2f}), "
                    f"VS change: {prev_vs:.2f} → {curr_volume_strength:.2f} ({curr_volume_strength - prev_vs:+.2f}), "
                    f"PS-VS diff: {prev_ps - prev_vs:.2f} → {curr_price_strength - curr_volume_strength:.2f}"
                )
        else:
            logger.debug(
                f"Calculated indicators at index {current_idx}: "
                f"RSI=N/A, PS={curr_price_strength:.2f}, VS={curr_volume_strength:.2f}"
            )
        
        # UPDATED LOGIC: Detect crossover on PREVIOUS candle, enter on CURRENT candle
        # This ensures crossover candle completes before entry (waits for real crossover)
        if current_idx < 2:
            add_check("Previous candles available", False, f"Need at least 2 previous candles, have {current_idx + 1}")
            details["candle_type"] = "unavailable"
            details["candle_ohlc"] = None
            return TradeSignal.HOLD, None, "Need at least 2 previous candles for crossover detection", details
        
        # Check if crossover happened on the PREVIOUS candle (current_idx - 1)
        # Crossover is detected between candle (current_idx - 2) and (current_idx - 1)
        # Entry happens on CURRENT candle (current_idx) after crossover candle completes

        # Before running crossover logic, make sure Strength values are valid (not NaN)
        # We need values for: current_idx (entry candle), current_idx-1 (crossover candle), current_idx-2 (before crossover)
        curr_ps_raw = price_strength.iloc[current_idx]
        curr_vs_raw = volume_strength.iloc[current_idx]
        crossover_ps_raw = price_strength.iloc[current_idx - 1]  # Crossover candle
        crossover_vs_raw = volume_strength.iloc[current_idx - 1]  # Crossover candle
        before_crossover_ps_raw = price_strength.iloc[current_idx - 2]  # Before crossover
        before_crossover_vs_raw = volume_strength.iloc[current_idx - 2]  # Before crossover

        if (
            pd.isna(curr_ps_raw)
            or pd.isna(curr_vs_raw)
            or pd.isna(crossover_ps_raw)
            or pd.isna(crossover_vs_raw)
            or pd.isna(before_crossover_ps_raw)
            or pd.isna(before_crossover_vs_raw)
        ):
            # Strength indicators are not fully ready – do not try to detect crossover yet
            add_check(
                "Candles Strength available",
                False,
                f"Curr PS={curr_ps_raw}, VS={curr_vs_raw}, "
                f"Crossover PS={crossover_ps_raw}, VS={crossover_vs_raw}, "
                f"Before PS={before_crossover_ps_raw}, VS={before_crossover_vs_raw}",
            )
            return (
                TradeSignal.HOLD,
                None,
                "Price/Volume Strength not ready for crossover detection",
                details,
            )

        # Now Strength values are valid – run crossover detection on PREVIOUS candle (current_idx - 1)
        # This checks for crossover between (current_idx - 2) and (current_idx - 1)
        pe_crossover_detected, ce_crossover_detected = self.check_strength_crossover(
            price_strength, volume_strength, current_idx - 1
        )
        
        # Get Price Strength and Volume Strength values
        # Entry candle (current_idx) - where we will enter
        entry_price_strength = float(curr_ps_raw)
        entry_volume_strength = float(curr_vs_raw)
        # Crossover candle (current_idx - 1) - where crossover happened
        crossover_price_strength = float(crossover_ps_raw)
        crossover_volume_strength = float(crossover_vs_raw)
        # Before crossover candle (current_idx - 2) - before crossover
        before_crossover_price_strength = float(before_crossover_ps_raw)
        before_crossover_volume_strength = float(before_crossover_vs_raw)
        
        # Log crossover status for debugging
        if pe_crossover_detected or ce_crossover_detected:
            logger.info(
                f"[CROSSOVER DETECTION] Crossover on idx {current_idx - 1}, Entry on idx {current_idx} | Trade Regime: {self.trade_regime} | "
                f"Before: PS={before_crossover_price_strength:.2f} VS={before_crossover_volume_strength:.2f} | "
                f"Crossover: PS={crossover_price_strength:.2f} VS={crossover_volume_strength:.2f} | "
                f"Entry: PS={entry_price_strength:.2f} VS={entry_volume_strength:.2f} | "
                f"PE_cross={pe_crossover_detected} (PS crosses DOWN) | CE_cross={ce_crossover_detected} (PS crosses UP)"
            )
        
        # Check the CROSSOVER candle (current_idx - 1) for the correct color
        # Entry happens on CURRENT candle (current_idx) after crossover candle completes
        crossover_candle = df.iloc[current_idx - 1]  # Crossover candle
        entry_candle = df.iloc[current_idx]  # Entry candle
        is_bearish = self.is_bearish_candle(crossover_candle)  # Check crossover candle color
        is_bullish = self.is_bullish_candle(crossover_candle)  # Check crossover candle color
        
        # Store OHLC data for logging (from crossover candle - where crossover happened)
        crossover_open = float(crossover_candle.get('open', 0))
        crossover_high = float(crossover_candle.get('high', 0))
        crossover_low = float(crossover_candle.get('low', 0))
        crossover_close = float(crossover_candle.get('close', 0))
        
        details["candle_ohlc"] = {
            "open": crossover_open,
            "high": crossover_high,
            "low": crossover_low,
            "close": crossover_close
        }
        details["candle_timestamp"] = crossover_candle.name if hasattr(crossover_candle, 'name') else None
        
        if is_bullish:
            details["candle_type"] = "bullish"
        elif is_bearish:
            details["candle_type"] = "bearish"
        else:
            details["candle_type"] = "neutral"
        
        # Log detailed candle information for debugging
        if pe_crossover_detected or ce_crossover_detected:
            candle_time_str = str(details["candle_timestamp"]) if details["candle_timestamp"] else "N/A"
            logger.info(
                f"Crossover Candle Details (idx {current_idx - 1}): "
                f"Time={candle_time_str}, "
                f"Type={details['candle_type']}, "
                f"O={crossover_open:.2f}, H={crossover_high:.2f}, L={crossover_low:.2f}, C={crossover_close:.2f}, "
                f"Close-Open={crossover_close - crossover_open:.2f}"
            )
            entry_candle_time = entry_candle.name if hasattr(entry_candle, 'name') else None
            entry_candle_time_str = str(entry_candle_time) if entry_candle_time else "N/A"
            before_candle_time = df.index[current_idx - 2] if current_idx >= 2 and hasattr(df.index, '__getitem__') else None
            before_candle_time_str = str(before_candle_time) if before_candle_time is not None else "N/A"
            logger.info(
                f"Entry Candle (idx {current_idx}): Time={entry_candle_time_str}, "
                f"Entry after crossover candle completes"
            )
            logger.info(
                f"Candle Timing: Before Crossover (idx {current_idx - 2})={before_candle_time_str}, "
                f"Crossover Candle (idx {current_idx - 1})={candle_time_str}, "
                f"Entry Candle (idx {current_idx})={entry_candle_time_str}"
            )
        
        # PE Buy Condition: Crossover detected on previous candle (current_idx - 1) + red candle on crossover candle
        # PE requires: PS crosses DOWN to VS (bearish crossover)
        pe_crossover_reason = ""
        if pe_crossover_detected:
            pe_crossover_reason = (
                f"✅ BEARISH CROSSOVER DETECTED: PS crossed DOWN to VS | "
                f"Before: PS={before_crossover_price_strength:.2f} > VS={before_crossover_volume_strength:.2f} → "
                f"Crossover: PS={crossover_price_strength:.2f} ≤ VS={crossover_volume_strength:.2f}"
            )
        else:
            # Explain why no crossover
            if before_crossover_price_strength > before_crossover_volume_strength:
                # PS was above VS, check if it's still above or crossed
                if crossover_price_strength > crossover_volume_strength:
                    pe_crossover_reason = (
                        f"❌ NO BEARISH CROSSOVER: PS still above VS | "
                        f"Before: PS={before_crossover_price_strength:.2f} > VS={before_crossover_volume_strength:.2f} → "
                        f"Current: PS={crossover_price_strength:.2f} > VS={crossover_volume_strength:.2f} "
                        f"(PS needs to cross DOWN to VS for PE signal)"
                    )
                else:
                    pe_crossover_reason = (
                        f"❌ NO BEARISH CROSSOVER: PS already below VS (no crossover event) | "
                        f"Before: PS={before_crossover_price_strength:.2f} > VS={before_crossover_volume_strength:.2f} → "
                        f"Current: PS={crossover_price_strength:.2f} ≤ VS={crossover_volume_strength:.2f} "
                        f"(PS was already below, no crossing occurred)"
                    )
            else:
                # PS was below VS, so no bearish crossover possible
                pe_crossover_reason = (
                    f"❌ NO BEARISH CROSSOVER: PS was already below VS | "
                    f"Before: PS={before_crossover_price_strength:.2f} ≤ VS={before_crossover_volume_strength:.2f} → "
                    f"Current: PS={crossover_price_strength:.2f} vs VS={crossover_volume_strength:.2f} "
                    f"(Bearish crossover requires PS to start above VS and cross down)"
                )
        # Format crossover candle timestamp for check messages
        crossover_candle_time_str = str(crossover_candle.name) if hasattr(crossover_candle, 'name') else "N/A"
        before_candle_time_str = str(df.index[current_idx - 2]) if current_idx >= 2 and hasattr(df.index, '__getitem__') else "N/A"
        
        add_check(
            f"PE: Bearish crossover (PS crosses DOWN to VS) detected on previous candle (Crossover: {crossover_candle_time_str}, Before: {before_candle_time_str})", 
            pe_crossover_detected, 
            pe_crossover_reason
        )
        # Bearish/Bullish candle check removed - entry now only requires crossover
        
        # For re-entry: require crossover (candle color check removed)
        # Re-entry should follow the same logic as normal entry: crossover + candle confirmation
        # Note: current_candle and is_bearish/is_bullish are already set above for current candle
        
        # PE Re-entry: Require crossover (candle color check removed)
        if allow_reentry and reentry_candle_type == 'bearish':
            add_check("PE: Re-entry mode active", True)
            add_check("PE: Re-entry requires crossover", pe_crossover_detected)
            if pe_crossover_detected:
                # VWAP check removed - now checked at strike level in execution layer
                
                # Check PS/VS difference threshold for re-entry too (must be within range)
                if self.strength_diff_enabled:
                    max_strength = max(abs(crossover_price_strength), abs(crossover_volume_strength))
                    if max_strength > 0:
                        ps_vs_diff_pct = abs(crossover_price_strength - crossover_volume_strength) / max_strength * 100
                        strength_diff_passed = (self.min_ps_vs_diff_pct <= ps_vs_diff_pct <= self.max_ps_vs_diff_pct)
                        add_check("PE: Re-entry PS/VS difference threshold", strength_diff_passed, 
                                 f"Diff: {ps_vs_diff_pct:.2f}% (Range: {self.min_ps_vs_diff_pct}%-{self.max_ps_vs_diff_pct}%, PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})")
                        if not strength_diff_passed:
                            if ps_vs_diff_pct < self.min_ps_vs_diff_pct:
                                logger.debug(f"PE re-entry blocked by PS/VS difference: {ps_vs_diff_pct:.2f}% < {self.min_ps_vs_diff_pct}% (below minimum)")
                                return TradeSignal.HOLD, None, f"Re-entry PS/VS difference ({ps_vs_diff_pct:.2f}%) below minimum ({self.min_ps_vs_diff_pct}%)", details
                            else:
                                logger.debug(f"PE re-entry blocked by PS/VS difference: {ps_vs_diff_pct:.2f}% > {self.max_ps_vs_diff_pct}% (above maximum)")
                                return TradeSignal.HOLD, None, f"Re-entry PS/VS difference ({ps_vs_diff_pct:.2f}%) above maximum ({self.max_ps_vs_diff_pct}%)", details
                    else:
                        add_check("PE: Re-entry PS/VS difference threshold", False, "Cannot calculate difference (both PS and VS are zero)")
                        return TradeSignal.HOLD, None, "Re-entry: Cannot calculate PS/VS difference (both are zero)", details
                
                add_check("PE: Re-entry conditions met", True)
                # For "Sell" regime: PS crosses DOWN to VS (price getting weak) → Sell CE (CE loses value when price weakens)
                trade_regime_check = str(self.trade_regime).strip().capitalize()
                if trade_regime_check == "Sell":
                    return (
                        TradeSignal.BUY_CE,
                        OptionType.CE,
                        f"[SELL] Re-entry: PS crosses DOWN to VS: Sell CE (price weak, CE loses value) (PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})",
                        details,
                    )
                else:
                    return (
                        TradeSignal.BUY_PE,
                        OptionType.PE,
                        f"Re-entry: Crossover after SL hit (PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})",
                        details,
                    )
            else:
                add_check("PE: Re-entry waiting for crossover", False)
        
        # Summary check for PE entry
        pe_all_criteria_met = pe_crossover_detected
        pe_summary = ""
        if pe_all_criteria_met:
            pe_summary = "✅ All PE entry criteria met: Bearish crossover (PS↓VS)"
        else:
            pe_summary = "❌ PE entry criteria NOT met: Missing Bearish crossover (PS↓VS)"
        add_check("PE: All entry criteria", pe_all_criteria_met, pe_summary)
        
        # Log filter summary for PE if crossover detected
        if pe_crossover_detected:
            filter_summary = []
            for check in details.get("checks", []):
                label = check.get("label", "")
                if "filter" in label.lower():
                    passed = check.get("passed", False)
                    value = check.get("value", "")
                    status = "✅ PASS" if passed else "❌ FAIL"
                    filter_summary.append(f"{status}: {label} - {value}")
            
            if filter_summary:
                logger.info(f"📊 PE Entry Filters Summary:\n" + "\n".join(f"  {f}" for f in filter_summary))
        
        # CE Buy Condition: Crossover detected on previous candle (current_idx - 1) + green candle on crossover candle
        # CE requires: PS crosses UP to VS (bullish crossover)
        ce_crossover_reason = ""
        if ce_crossover_detected:
            ce_crossover_reason = (
                f"✅ BULLISH CROSSOVER DETECTED: PS crossed UP to VS | "
                f"Before: PS={before_crossover_price_strength:.2f} < VS={before_crossover_volume_strength:.2f} → "
                f"Crossover: PS={crossover_price_strength:.2f} ≥ VS={crossover_volume_strength:.2f}"
            )
        else:
            # Explain why no crossover
            if before_crossover_price_strength < before_crossover_volume_strength:
                # PS was below VS, check if it's still below or crossed
                if crossover_price_strength < crossover_volume_strength:
                    ce_crossover_reason = (
                        f"❌ NO BULLISH CROSSOVER: PS still below VS | "
                        f"Before: PS={before_crossover_price_strength:.2f} < VS={before_crossover_volume_strength:.2f} → "
                        f"Current: PS={crossover_price_strength:.2f} < VS={crossover_volume_strength:.2f} "
                        f"(PS needs to cross UP to VS for CE signal)"
                    )
                else:
                    ce_crossover_reason = (
                        f"❌ NO BULLISH CROSSOVER: PS already above VS (no crossover event) | "
                        f"Before: PS={before_crossover_price_strength:.2f} < VS={before_crossover_volume_strength:.2f} → "
                        f"Current: PS={crossover_price_strength:.2f} ≥ VS={crossover_volume_strength:.2f} "
                        f"(PS was already above, no crossing occurred)"
                    )
            else:
                # PS was above VS, so no bullish crossover possible
                ce_crossover_reason = (
                    f"❌ NO BULLISH CROSSOVER: PS was already above VS | "
                    f"Before: PS={before_crossover_price_strength:.2f} ≥ VS={before_crossover_volume_strength:.2f} → "
                    f"Current: PS={crossover_price_strength:.2f} vs VS={crossover_volume_strength:.2f} "
                    f"(Bullish crossover requires PS to start below VS and cross up)"
                )
        add_check(
            f"CE: Bullish crossover (PS crosses UP to VS) detected on previous candle (Crossover: {crossover_candle_time_str}, Before: {before_candle_time_str})", 
            ce_crossover_detected, 
            ce_crossover_reason
        )
        # Bullish/Bearish candle check removed - entry now only requires crossover
        
        # CE Re-entry: Require crossover (candle color check removed)
        if allow_reentry and reentry_candle_type == 'bullish':
            add_check("CE: Re-entry mode active", True)
            add_check("CE: Re-entry requires crossover", ce_crossover_detected)
            if ce_crossover_detected:
                # VWAP check removed - now checked at strike level in execution layer
                
                # Check PS/VS difference threshold for re-entry too (must be within range)
                if self.strength_diff_enabled:
                    max_strength = max(abs(crossover_price_strength), abs(crossover_volume_strength))
                    if max_strength > 0:
                        ps_vs_diff_pct = abs(crossover_price_strength - crossover_volume_strength) / max_strength * 100
                        strength_diff_passed = (self.min_ps_vs_diff_pct <= ps_vs_diff_pct <= self.max_ps_vs_diff_pct)
                        add_check("CE: Re-entry PS/VS difference threshold", strength_diff_passed, 
                                 f"Diff: {ps_vs_diff_pct:.2f}% (Range: {self.min_ps_vs_diff_pct}%-{self.max_ps_vs_diff_pct}%, PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})")
                        if not strength_diff_passed:
                            if ps_vs_diff_pct < self.min_ps_vs_diff_pct:
                                logger.debug(f"CE re-entry blocked by PS/VS difference: {ps_vs_diff_pct:.2f}% < {self.min_ps_vs_diff_pct}% (below minimum)")
                                return TradeSignal.HOLD, None, f"Re-entry PS/VS difference ({ps_vs_diff_pct:.2f}%) below minimum ({self.min_ps_vs_diff_pct}%)", details
                            else:
                                logger.debug(f"CE re-entry blocked by PS/VS difference: {ps_vs_diff_pct:.2f}% > {self.max_ps_vs_diff_pct}% (above maximum)")
                                return TradeSignal.HOLD, None, f"Re-entry PS/VS difference ({ps_vs_diff_pct:.2f}%) above maximum ({self.max_ps_vs_diff_pct}%)", details
                    else:
                        add_check("CE: Re-entry PS/VS difference threshold", False, "Cannot calculate difference (both PS and VS are zero)")
                        return TradeSignal.HOLD, None, "Re-entry: Cannot calculate PS/VS difference (both are zero)", details
                
                add_check("CE: Re-entry conditions met", True)
                # For "Sell" regime: PS crosses UP to VS (price getting strong) → Sell PE (PE loses value when price strengthens)
                trade_regime_check = str(self.trade_regime).strip().capitalize()
                if trade_regime_check == "Sell":
                    return (
                        TradeSignal.BUY_PE,
                        OptionType.PE,
                        f"[SELL] Re-entry: PS crosses UP to VS: Sell PE (price strong, PE loses value) (PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})",
                        details,
                    )
                else:
                    return (
                        TradeSignal.BUY_CE,
                        OptionType.CE,
                        f"Re-entry: Crossover after SL hit (PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})",
                        details,
                    )
            else:
                add_check("CE: Re-entry waiting for crossover", False)
        
        # Summary check for CE entry
        ce_all_criteria_met = ce_crossover_detected
        ce_summary = ""
        if ce_all_criteria_met:
            ce_summary = "✅ All CE entry criteria met: Bullish crossover (PS↑VS)"
        else:
            ce_summary = "❌ CE entry criteria NOT met: Missing Bullish crossover (PS↑VS)"
        add_check("CE: All entry criteria", ce_all_criteria_met, ce_summary)
        
        # Log filter summary for CE if crossover detected
        if ce_crossover_detected:
            filter_summary = []
            for check in details.get("checks", []):
                label = check.get("label", "")
                if "filter" in label.lower():
                    passed = check.get("passed", False)
                    value = check.get("value", "")
                    status = "✅ PASS" if passed else "❌ FAIL"
                    filter_summary.append(f"{status}: {label} - {value}")
            
            if filter_summary:
                logger.info(f"📊 CE Entry Filters Summary:\n" + "\n".join(f"  {f}" for f in filter_summary))
        
        # Safety check: Both crossovers should not be true simultaneously
        if pe_crossover_detected and ce_crossover_detected:
            logger.error(
                f"ERROR: Both PE and CE crossovers detected simultaneously at crossover idx {current_idx - 1}! "
                f"Before: PS={before_crossover_price_strength:.2f} VS={before_crossover_volume_strength:.2f}, "
                f"Crossover: PS={crossover_price_strength:.2f} VS={crossover_volume_strength:.2f}, "
                f"Trade_Regime={self.trade_regime}"
            )
            # This should not happen, but if it does, prioritize CE crossover
            logger.warning("Both crossovers detected, prioritizing CE crossover")
            pe_crossover_detected = False
        
        # Calculate 1-minute PS/VS if available
        ps_1min_series = None
        vs_1min_series = None
        ps_1min_current = None
        vs_1min_current = None
        
        if df_1min is not None and len(df_1min) > 0:
            ps_1min_series, vs_1min_series = self.calculate_1min_ps_vs(df_1min)
            if ps_1min_series is not None and vs_1min_series is not None and len(ps_1min_series) > 0:
                ps_1min_current = float(ps_1min_series.iloc[-1]) if not pd.isna(ps_1min_series.iloc[-1]) else None
                vs_1min_current = float(vs_1min_series.iloc[-1]) if not pd.isna(vs_1min_series.iloc[-1]) else None
        
        # PE Buy Condition: Crossover on previous candle (candle color check removed)
        if pe_crossover_detected:
            # VWAP check removed - now checked at strike level in execution layer
            
            # Apply entry filters
            # 1. Time Session Filter
            current_time = df.index[current_idx] if hasattr(df.index[current_idx], 'to_pydatetime') else datetime.now()
            if isinstance(current_time, pd.Timestamp):
                current_time = current_time.to_pydatetime()
            time_passed, time_reason = self.check_time_session_filter(current_time, "PE")
            add_check("PE: Time session filter", time_passed, time_reason)
            if not time_passed:
                logger.info(f"PE entry blocked by time filter: {time_reason}")
                return TradeSignal.HOLD, None, f"Time filter failed: {time_reason}", details
            
            # 2. ATR Volatility Filter
            atr_passed, atr_reason, current_atr, avg_atr = self.check_atr_volatility_filter(df, current_idx)
            add_check("PE: ATR volatility filter", atr_passed, atr_reason)
            if not atr_passed:
                logger.info(f"PE entry blocked by ATR filter: {atr_reason}")
                return TradeSignal.HOLD, None, f"ATR filter failed: {atr_reason}", details
            
            # 3. RSI Extreme Filter
            # In Sell Regime: PE crossover (PS↓VS) → Sell CE, so check CE RSI conditions
            # In Buy Regime: PE crossover (PS↓VS) → Buy PE, so check PE RSI conditions
            entry_rsi = details.get("rsi_value")
            if self.trade_regime == "Sell":
                # PE crossover in Sell Regime → Sell CE, check CE RSI conditions
                rsi_passed, rsi_reason = self.check_rsi_extreme_filter(entry_rsi, "CE")
                add_check("PE: RSI extreme filter (Sell CE)", rsi_passed, rsi_reason)
            else:
                # PE crossover in Buy Regime → Buy PE, check PE RSI conditions
                rsi_passed, rsi_reason = self.check_rsi_extreme_filter(entry_rsi, "PE")
                add_check("PE: RSI extreme filter", rsi_passed, rsi_reason)
            if not rsi_passed:
                logger.info(f"PE entry blocked by RSI filter: {rsi_reason}")
                return TradeSignal.HOLD, None, f"RSI filter failed: {rsi_reason}", details
            
            # Store filter status in details for chart visualization
            details["filters"] = {
                "time": {"passed": time_passed, "reason": time_reason},
                "atr": {"passed": atr_passed, "reason": atr_reason, "current_atr": float(current_atr) if current_atr is not None else None, "avg_atr": float(avg_atr) if avg_atr is not None else None},
                "rsi": {"passed": rsi_passed, "reason": rsi_reason, "rsi_value": float(entry_rsi) if entry_rsi is not None else None}
            }
            
            # Multi-timeframe confirmation checks
            if self.mtf_enabled:
                # Check 1-minute alignment
                aligned, alignment_reason = self.check_multi_timeframe_alignment(
                    entry_price_strength, entry_volume_strength,
                    ps_1min_current, vs_1min_current, "PE"
                )
                add_check("PE: 1-minute PS/VS alignment", aligned, alignment_reason)
                if not aligned:
                    logger.debug(f"PE entry blocked: {alignment_reason}")
                    return TradeSignal.HOLD, None, f"1-minute alignment failed: {alignment_reason}", details
                
                # Check momentum if 1-minute data available
                if ps_1min_series is not None and vs_1min_series is not None:
                    ps_momentum, vs_momentum = self.calculate_momentum(ps_1min_series, vs_1min_series)
                    momentum_passed, momentum_reason = self.check_momentum_filter(ps_momentum, vs_momentum, "PE")
                    add_check("PE: 1-minute momentum filter", momentum_passed, momentum_reason)
                    if not momentum_passed:
                        logger.debug(f"PE entry blocked: {momentum_reason}")
                        return TradeSignal.HOLD, None, f"Momentum filter failed: {momentum_reason}", details
                
                # Check divergence
                no_divergence, divergence_reason = self.check_divergence(
                    entry_price_strength, entry_volume_strength,
                    ps_1min_current, vs_1min_current, "PE"
                )
                add_check("PE: Divergence check", no_divergence, divergence_reason)
                if not no_divergence:
                    logger.debug(f"PE entry blocked: {divergence_reason}")
                    return TradeSignal.HOLD, None, f"Divergence detected: {divergence_reason}", details
                
                # Check volume confirmation
                if df_1min is not None:
                    volume_confirmed, volume_reason = self.check_volume_confirmation(df_1min)
                    add_check("PE: Volume confirmation", volume_confirmed, volume_reason)
                    if not volume_confirmed:
                        logger.debug(f"PE entry blocked: {volume_reason}")
                        return TradeSignal.HOLD, None, f"Volume confirmation failed: {volume_reason}", details
            
            # Check PS/VS difference threshold if enabled (must be within range)
            # Use dynamic thresholds if enabled
            if self.strength_diff_enabled:
                min_threshold, max_threshold = self.get_dynamic_threshold(
                    ps_1min_current, vs_1min_current,
                    entry_price_strength, entry_volume_strength
                )
                if self.dynamic_threshold_enabled:
                    add_check("PE: Using dynamic thresholds", True, f"Min={min_threshold}%, Max={max_threshold}%")
                else:
                    min_threshold = self.min_ps_vs_diff_pct
                    max_threshold = self.max_ps_vs_diff_pct
                
                # Calculate percentage difference: abs(PS - VS) / max(PS, VS) * 100
                max_strength = max(abs(entry_price_strength), abs(entry_volume_strength))
                if max_strength > 0:
                    ps_vs_diff_pct = abs(entry_price_strength - entry_volume_strength) / max_strength * 100
                    strength_diff_passed = (min_threshold <= ps_vs_diff_pct <= max_threshold)
                    add_check("PE: PS/VS difference threshold", strength_diff_passed, 
                             f"Diff: {ps_vs_diff_pct:.2f}% (Range: {min_threshold}%-{max_threshold}%, PS: {entry_price_strength:.2f}, VS: {entry_volume_strength:.2f})")
                    if not strength_diff_passed:
                        if ps_vs_diff_pct < min_threshold:
                            logger.debug(f"PE entry blocked by PS/VS difference: {ps_vs_diff_pct:.2f}% < {min_threshold}% (below minimum)")
                            return TradeSignal.HOLD, None, f"PS/VS difference ({ps_vs_diff_pct:.2f}%) below minimum ({min_threshold}%)", details
                        else:
                            logger.debug(f"PE entry blocked by PS/VS difference: {ps_vs_diff_pct:.2f}% > {max_threshold}% (above maximum)")
                            return TradeSignal.HOLD, None, f"PS/VS difference ({ps_vs_diff_pct:.2f}%) above maximum ({max_threshold}%)", details
                else:
                    add_check("PE: PS/VS difference threshold", False, "Cannot calculate difference (both PS and VS are zero)")
                    logger.debug("PE entry blocked: Cannot calculate PS/VS difference (both are zero)")
                    return TradeSignal.HOLD, None, "Cannot calculate PS/VS difference (both are zero)", details
            
            # Log crossover details
            logger.debug(
                f"PE Crossover: PS {before_crossover_price_strength:.2f} > VS {before_crossover_volume_strength:.2f} → "
                f"PS {crossover_price_strength:.2f} <= VS {crossover_volume_strength:.2f} (entry on next candle)"
            )
            # VWAP check removed - now checked at strike level in execution layer
            
            # For "Sell" regime: PS crosses DOWN to VS (price getting weak) → Sell CE (CE loses value when price weakens)
            # For "Buy" regime: PS crosses DOWN to VS → Buy PE (normal)
            logger.info(f"[TRADE_REGIME_CHECK] PE Crossover: trade_regime='{self.trade_regime}' (repr: {repr(self.trade_regime)}, type: {type(self.trade_regime).__name__})")
            # Use case-insensitive comparison for robustness
            trade_regime_check = str(self.trade_regime).strip().capitalize()
            if trade_regime_check == "Sell":
                logger.info(
                    f"[SELL REGIME] PE Crossover detected (PS crosses DOWN - price getting weak): "
                    f"Returning SELL_CE signal (OptionType.CE) - CE loses value when price weakens"
                )
                return (
                    TradeSignal.BUY_CE,
                    OptionType.CE,
                    f"[SELL] PS crosses DOWN to VS: Sell CE (price weak, CE loses value) (Crossover PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})",
                    details,
                )
            else:
                logger.debug(f"PE Crossover: Using Buy regime (trade_regime='{self.trade_regime}')")
                return (
                    TradeSignal.BUY_PE,
                    OptionType.PE,
                    f"Crossover detected on previous candle + bearish candle on crossover candle (PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})",
                    details,
                )
        
        # CE Buy Condition: Crossover on previous candle (candle color check removed)
        if ce_crossover_detected:
            # VWAP check removed - now checked at strike level in execution layer
            
            # Apply entry filters
            # 1. Time Session Filter
            current_time = df.index[current_idx] if hasattr(df.index[current_idx], 'to_pydatetime') else datetime.now()
            if isinstance(current_time, pd.Timestamp):
                current_time = current_time.to_pydatetime()
            time_passed, time_reason = self.check_time_session_filter(current_time, "CE")
            add_check("CE: Time session filter", time_passed, time_reason)
            if not time_passed:
                logger.info(f"CE entry blocked by time filter: {time_reason}")
                return TradeSignal.HOLD, None, f"Time filter failed: {time_reason}", details
            
            # 2. ATR Volatility Filter
            atr_passed, atr_reason, current_atr, avg_atr = self.check_atr_volatility_filter(df, current_idx)
            add_check("CE: ATR volatility filter", atr_passed, atr_reason)
            if not atr_passed:
                logger.info(f"CE entry blocked by ATR filter: {atr_reason}")
                return TradeSignal.HOLD, None, f"ATR filter failed: {atr_reason}", details
            
            # 3. RSI Extreme Filter
            # In Sell Regime: CE crossover (PS↑VS) → Sell PE, so check PE RSI conditions
            # In Buy Regime: CE crossover (PS↑VS) → Buy CE, so check CE RSI conditions
            entry_rsi = details.get("rsi_value")
            if self.trade_regime == "Sell":
                # CE crossover in Sell Regime → Sell PE, check PE RSI conditions
                rsi_passed, rsi_reason = self.check_rsi_extreme_filter(entry_rsi, "PE")
                add_check("CE: RSI extreme filter (Sell PE)", rsi_passed, rsi_reason)
            else:
                # CE crossover in Buy Regime → Buy CE, check CE RSI conditions
                rsi_passed, rsi_reason = self.check_rsi_extreme_filter(entry_rsi, "CE")
                add_check("CE: RSI extreme filter", rsi_passed, rsi_reason)
            if not rsi_passed:
                logger.info(f"CE entry blocked by RSI filter: {rsi_reason}")
                return TradeSignal.HOLD, None, f"RSI filter failed: {rsi_reason}", details
            
            # Store filter status in details for chart visualization
            details["filters"] = {
                "time": {"passed": time_passed, "reason": time_reason},
                "atr": {"passed": atr_passed, "reason": atr_reason, "current_atr": float(current_atr) if current_atr is not None else None, "avg_atr": float(avg_atr) if avg_atr is not None else None},
                "rsi": {"passed": rsi_passed, "reason": rsi_reason, "rsi_value": float(entry_rsi) if entry_rsi is not None else None}
            }
            
            # Multi-timeframe confirmation checks
            if self.mtf_enabled:
                # Check 1-minute alignment
                aligned, alignment_reason = self.check_multi_timeframe_alignment(
                    entry_price_strength, entry_volume_strength,
                    ps_1min_current, vs_1min_current, "CE"
                )
                add_check("CE: 1-minute PS/VS alignment", aligned, alignment_reason)
                if not aligned:
                    logger.debug(f"CE entry blocked: {alignment_reason}")
                    return TradeSignal.HOLD, None, f"1-minute alignment failed: {alignment_reason}", details
                
                # Check momentum if 1-minute data available
                if ps_1min_series is not None and vs_1min_series is not None:
                    ps_momentum, vs_momentum = self.calculate_momentum(ps_1min_series, vs_1min_series)
                    momentum_passed, momentum_reason = self.check_momentum_filter(ps_momentum, vs_momentum, "CE")
                    add_check("CE: 1-minute momentum filter", momentum_passed, momentum_reason)
                    if not momentum_passed:
                        logger.debug(f"CE entry blocked: {momentum_reason}")
                        return TradeSignal.HOLD, None, f"Momentum filter failed: {momentum_reason}", details
                
                # Check divergence
                no_divergence, divergence_reason = self.check_divergence(
                    entry_price_strength, entry_volume_strength,
                    ps_1min_current, vs_1min_current, "CE"
                )
                add_check("CE: Divergence check", no_divergence, divergence_reason)
                if not no_divergence:
                    logger.debug(f"CE entry blocked: {divergence_reason}")
                    return TradeSignal.HOLD, None, f"Divergence detected: {divergence_reason}", details
                
                # Check volume confirmation
                if df_1min is not None:
                    volume_confirmed, volume_reason = self.check_volume_confirmation(df_1min)
                    add_check("CE: Volume confirmation", volume_confirmed, volume_reason)
                    if not volume_confirmed:
                        logger.debug(f"CE entry blocked: {volume_reason}")
                        return TradeSignal.HOLD, None, f"Volume confirmation failed: {volume_reason}", details
            
            # Check PS/VS difference threshold with dynamic thresholds
            if self.strength_diff_enabled:
                min_threshold, max_threshold = self.get_dynamic_threshold(
                    ps_1min_current, vs_1min_current,
                    entry_price_strength, entry_volume_strength
                )
                if self.dynamic_threshold_enabled:
                    add_check("CE: Using dynamic thresholds", True, f"Min={min_threshold}%, Max={max_threshold}%")
                else:
                    min_threshold = self.min_ps_vs_diff_pct
                    max_threshold = self.max_ps_vs_diff_pct
                
                # Calculate percentage difference: abs(PS - VS) / max(PS, VS) * 100
                max_strength = max(abs(entry_price_strength), abs(entry_volume_strength))
                if max_strength > 0:
                    ps_vs_diff_pct = abs(entry_price_strength - entry_volume_strength) / max_strength * 100
                    strength_diff_passed = (min_threshold <= ps_vs_diff_pct <= max_threshold)
                    add_check("CE: PS/VS difference threshold", strength_diff_passed, 
                             f"Diff: {ps_vs_diff_pct:.2f}% (Range: {min_threshold}%-{max_threshold}%, PS: {entry_price_strength:.2f}, VS: {entry_volume_strength:.2f})")
                    if not strength_diff_passed:
                        if ps_vs_diff_pct < min_threshold:
                            logger.debug(f"CE entry blocked by PS/VS difference: {ps_vs_diff_pct:.2f}% < {min_threshold}% (below minimum)")
                            return TradeSignal.HOLD, None, f"PS/VS difference ({ps_vs_diff_pct:.2f}%) below minimum ({min_threshold}%)", details
                        else:
                            logger.debug(f"CE entry blocked by PS/VS difference: {ps_vs_diff_pct:.2f}% > {max_threshold}% (above maximum)")
                            return TradeSignal.HOLD, None, f"PS/VS difference ({ps_vs_diff_pct:.2f}%) above maximum ({max_threshold}%)", details
                else:
                    add_check("CE: PS/VS difference threshold", False, "Cannot calculate difference (both PS and VS are zero)")
                    logger.debug("CE entry blocked: Cannot calculate PS/VS difference (both are zero)")
                    return TradeSignal.HOLD, None, "Cannot calculate PS/VS difference (both are zero)", details
            
            # Log crossover details
            logger.debug(
                f"CE Crossover: PS {before_crossover_price_strength:.2f} < VS {before_crossover_volume_strength:.2f} → "
                f"PS {crossover_price_strength:.2f} >= VS {crossover_volume_strength:.2f} (entry on next candle)"
            )
            # VWAP check removed - now checked at strike level in execution layer
            
            # For "Sell" regime: PS crosses UP to VS (price getting strong) → Sell PE (PE loses value when price strengthens)
            # For "Buy" regime: PS crosses UP to VS → Buy CE (normal)
            logger.info(f"[TRADE_REGIME_CHECK] CE Crossover: trade_regime='{self.trade_regime}' (repr: {repr(self.trade_regime)}, type: {type(self.trade_regime).__name__})")
            # Use case-insensitive comparison for robustness
            trade_regime_check = str(self.trade_regime).strip().capitalize()
            if trade_regime_check == "Sell":
                logger.info(
                    f"[SELL REGIME] CE Crossover detected (PS crosses UP - price getting strong): "
                    f"Returning SELL_PE signal (OptionType.PE) - PE loses value when price strengthens"
                )
                return (
                    TradeSignal.BUY_PE,
                    OptionType.PE,
                    f"[SELL] PS crosses UP to VS: Sell PE (price strong, PE loses value) (Crossover PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})",
                    details,
                )
            else:
                logger.debug(f"CE Crossover: Using Buy regime (trade_regime='{self.trade_regime}')")
                return (
                    TradeSignal.BUY_CE,
                    OptionType.CE,
                    f"Crossover detected on previous candle + bullish candle on crossover candle (PS: {crossover_price_strength:.2f}, VS: {crossover_volume_strength:.2f})",
                    details,
                )
        
        return TradeSignal.HOLD, None, "No entry signal", details
    
    def should_add_lots(self, total_profit: float, current_lots: int) -> Tuple[bool, int]:
        """
        Check if should add lots based on profit milestones
        
        Returns:
            (should_add, lots_to_add)
        """
        if current_lots == self.initial_lot_size:
            # Check for lot 2
            if total_profit >= self.lot2_profit_threshold:
                return True, self.lot2_lots
        elif current_lots == self.initial_lot_size + self.lot2_lots:
            # Check for lot 3
            if total_profit >= self.lot3_profit_threshold:
                return True, self.lot3_lots
        elif current_lots == self.initial_lot_size + self.lot2_lots + self.lot3_lots:
            # Check for lot 4
            if total_profit >= self.lot4_profit_threshold:
                return True, self.lot4_lots
        elif current_lots >= self.initial_lot_size + self.lot2_lots + self.lot3_lots + self.lot4_lots:
            # Continue adding lots using same trailing logic
            # Add more lots when profit increases by lot4_profit_threshold
            profit_since_last_add = total_profit - (self.lot4_profit_threshold * 
                                                   ((current_lots - self.initial_lot_size - 
                                                     self.lot2_lots - self.lot3_lots) // self.lot4_lots))
            if profit_since_last_add >= self.lot4_profit_threshold:
                return True, self.lot4_lots
        
        return False, 0


class RSITradingAgent:
    """
    RSI Trading Agent that executes the strategy
    """
    
    def __init__(self, strategy: RSIStrategy):
        self.strategy = strategy
        # Track positions separately by option type (CE and PE can be open simultaneously)
        # Structure: {OptionType.CE: {...position details...}, OptionType.PE: {...position details...}}
        self.positions: Dict[OptionType, Optional[Dict]] = {
            OptionType.CE: None,
            OptionType.PE: None
        }
        # Legacy support: current_position points to the most recently opened position
        # This is maintained for backward compatibility but should be phased out
        self.current_position = None
        # Re-entry tracking after SL hit (per option type)
        self.reentry_mode: Dict[OptionType, Dict] = {
            OptionType.CE: {"waiting": False, "candle_type": None},
            OptionType.PE: {"waiting": False, "candle_type": None}
        }
        # Trailing stop price tracking (for backtesting)
        self.trailing_stop_price: Optional[float] = None
        # Entry premium tracking (for backtesting)
        self.entry_premium: Optional[float] = None
        self.entry_premium_source: Optional[str] = None
        self.entry_strike: Optional[int] = None
        self.entry_spot: Optional[float] = None
        self.entry_instrument_details: Optional[Dict] = None
        
    def _get_position(self, option_type: OptionType) -> Optional[Dict]:
        """Get position details for a specific option type"""
        return self.positions.get(option_type)
    
    def _has_position(self, option_type: OptionType) -> bool:
        """Check if a position of the specified option type is open"""
        return self.positions.get(option_type) is not None
    
    def _get_any_position(self) -> Optional[Tuple[OptionType, Dict]]:
        """Get any open position (for backward compatibility)"""
        for opt_type, pos in self.positions.items():
            if pos is not None:
                return (opt_type, pos)
        return None
    
    @property
    def current_position(self) -> Optional[OptionType]:
        """Legacy property: returns the most recently opened position type (for backward compatibility)"""
        any_pos = self._get_any_position()
        return any_pos[0] if any_pos else None
    
    @current_position.setter
    def current_position(self, value: Optional[OptionType]):
        """Legacy setter: maintains backward compatibility but doesn't affect positions dict"""
        # This setter is for backward compatibility only
        # The actual positions are managed via self.positions dict
        pass
    
    def enter_trade(
        self,
        signal: TradeSignal,
        option_type: OptionType,
        price: float,
        timestamp: datetime,
        reason: str,
        price_strength: Optional[float] = None,
        volume_strength: Optional[float] = None
    ) -> Dict:
        """Enter a new trade - prevents duplicate option types but allows CE and PE simultaneously"""
        # Check if this specific option type is already open
        if self._has_position(option_type):
            existing_pos = self._get_position(option_type)
            current_strike = existing_pos.get('entry_strike', 'N/A') if existing_pos else 'N/A'
            entry_time = existing_pos.get('entry_time', 'N/A') if existing_pos else 'N/A'
            logger.warning(
                f"⛔ Cannot enter {option_type.value} trade: {option_type.value} position already open "
                f"(strike={current_strike}, entry_time={entry_time})"
            )
            return {"success": False, "reason": f"{option_type.value} position already open: strike={current_strike}"}
        
        # Create new position entry
        position_data = {
            "entry_price": price,
            "entry_time": timestamp,
            "lots": self.strategy.initial_lot_size,
            "total_investment": price * self.strategy.initial_lot_size,
            "highest_profit": 0,
            "trailing_stop_price": None,
            "entry_price_strength": price_strength,
            "entry_volume_strength": volume_strength,
            "entry_strike": None,  # Will be set by LiveSegmentAgent
            "entry_spot": None,
            "entry_premium": None,
            "entry_premium_source": None
        }
        
        self.positions[option_type] = position_data
        
        trade_action = "Bought" if option_type == OptionType.CE else "Sold"
        logger.info(f"{trade_action} {option_type.value} trade at ₹{price:.2f} - {reason}")
        if price_strength is not None and volume_strength is not None:
            logger.info(f"Entry Price Strength: {price_strength:.2f}, Volume Strength: {volume_strength:.2f}")
        
        return {
            "success": True,
            "option_type": option_type.value,
            "entry_price": price,
            "entry_time": timestamp,
            "lots": position_data["lots"],
            "reason": reason,
            "price_strength": price_strength,
            "volume_strength": volume_strength
        }
    
    def add_lots(self, price: float, lots_to_add: int, option_type: Optional[OptionType] = None) -> Dict:
        """Add more lots to existing position (for specific option type or current position)"""
        if option_type is None:
            option_type = self.current_position
        
        if option_type is None or not self._has_position(option_type):
            return {"success": False, "reason": f"No active {option_type.value if option_type else ''} position"}
        
        pos = self._get_position(option_type)
        pos["lots"] += lots_to_add
        additional_investment = price * lots_to_add
        # Initialize total_investment if not present (for positions recovered from Kite/CSV)
        if "total_investment" not in pos:
            pos["total_investment"] = pos.get("entry_price", price) * pos.get("lots", 1)
        pos["total_investment"] += additional_investment
        
        logger.info(f"Added {lots_to_add} lots to {option_type.value} at ₹{price:.2f}. Total lots: {pos['lots']}")
        
        return {
            "success": True,
            "lots_added": lots_to_add,
            "total_lots": pos["lots"],
            "price": price,
            "option_type": option_type.value
        }
    
    def calculate_pnl(self, current_price: float, option_type: Optional[OptionType] = None) -> float:
        """
        Calculate current P&L for a specific position or all positions
        
        For CE (Call Options): Profit when price goes UP
        P&L = (current_price - entry_price) * lots
        
        For PE (Put Options): Profit when price goes DOWN
        P&L = (entry_price - current_price) * lots
        """
        if option_type is not None:
            # Calculate P&L for specific position
            if not self._has_position(option_type):
                return 0.0
            pos = self._get_position(option_type)
            if option_type == OptionType.CE:
                return (current_price - pos["entry_price"]) * pos["lots"]
            else:  # PE
                return (pos["entry_price"] - current_price) * pos["lots"]
        else:
            # Calculate total P&L for all open positions (backward compatibility)
            total_pnl = 0.0
            for opt_type, pos in self.positions.items():
                if pos is not None:
                    if opt_type == OptionType.CE:
                        total_pnl += (current_price - pos["entry_price"]) * pos["lots"]
                    else:  # PE
                        total_pnl += (pos["entry_price"] - current_price) * pos["lots"]
            return total_pnl
    
    def check_exit_conditions(
        self,
        current_price: float,
        timestamp: datetime,
        option_type: Optional[OptionType] = None
    ) -> Tuple[bool, Optional[str], Optional[OptionType]]:
        """
        Check if exit conditions are met for a specific position or all positions
        
        Returns:
            (should_exit, exit_reason, option_type_to_exit)
        """
        # If option_type specified, check only that position
        if option_type is not None:
            if not self._has_position(option_type):
                return False, None, None
            return self._check_exit_for_position(option_type, current_price, timestamp)
        
        # Otherwise check all open positions
        for opt_type, pos in self.positions.items():
            if pos is not None:
                should_exit, exit_reason, _ = self._check_exit_for_position(opt_type, current_price, timestamp)
                if should_exit:
                    return True, exit_reason, opt_type
        
        return False, None, None
    
    def _check_exit_for_position(
        self,
        option_type: OptionType,
        current_price: float,
        timestamp: datetime
    ) -> Tuple[bool, Optional[str], Optional[OptionType]]:
        """Check exit conditions for a specific position"""
        if not self._has_position(option_type):
            return False, None, None
        
        pos = self._get_position(option_type)
        pnl = self.calculate_pnl(current_price, option_type)
        
        # Initialize highest_profit if not present (for positions recovered from Kite/CSV)
        if "highest_profit" not in pos:
            pos["highest_profit"] = 0
        
        # Update highest profit for tracking
        if pnl > pos["highest_profit"]:
            pos["highest_profit"] = pnl
        
        # Update trailing stop on every candle (but only move in favorable direction)
        # For every 100 points profit, move trailing SL by 100 points (1:1 ratio)
        if option_type == OptionType.CE:
            # CE: Profit when price goes UP
            # Calculate price movement from entry (positive when price goes up)
            price_movement = current_price - pos["entry_price"]
            
            # For every 100 points price movement UP, move trailing SL 100 points UP (1:1 ratio)
            # Trailing SL = entry_price + price_movement - trailing_stop
            # Example: Entry ₹24,000, Price ₹24,100 (100 pts up) → Trailing SL = ₹24,000 + 100 - 50 = ₹24,050
            #          Entry ₹24,000, Price ₹24,200 (200 pts up) → Trailing SL = ₹24,000 + 200 - 50 = ₹24,150
            if price_movement > 0:
                new_trailing_stop_price = pos["entry_price"] + price_movement - self.strategy.trailing_stop
            else:
                # If price hasn't moved up, use initial trailing SL
                new_trailing_stop_price = pos["entry_price"] - self.strategy.trailing_stop
            
            # Only update if it's higher than previous (can't move backward)
            if pos["trailing_stop_price"] is None or new_trailing_stop_price > pos["trailing_stop_price"]:
                pos["trailing_stop_price"] = new_trailing_stop_price
                logger.debug(f"CE Trailing SL updated: {pos['trailing_stop_price']:.2f} (Current Price: {current_price:.2f}, Movement: {price_movement:.2f} pts, Ratio: 1:1)")
            
            # CE Stop Loss: Exit when price drops by stop_loss points from entry
            # SL Level = entry_price - stop_loss
            price_drop = pos["entry_price"] - current_price
            if price_drop >= self.strategy.stop_loss:
                loss = price_drop * pos["lots"]
                return True, f"Stop Loss hit (Loss: ₹{loss:.2f}, Price drop: {price_drop:.2f} points)", option_type
            
            # CE Trailing Stop: lock profit when price falls back to trailing stop
            if pos["trailing_stop_price"] is not None and current_price <= pos["trailing_stop_price"]:
                price_drop_from_peak = pos["trailing_stop_price"] + self.strategy.trailing_stop - current_price
                return True, (
                    f"Trailing Stop Loss hit (Profit: ₹{pnl:.2f}, Entry: ₹{pos['entry_price']:.2f}, "
                    f"Trailing SL: ₹{pos['trailing_stop_price']:.2f}, Current: ₹{current_price:.2f}, "
                    f"Drop: {price_drop_from_peak:.2f} points)"
                ), option_type
        
        elif option_type == OptionType.PE:
            # PE: Profit when price goes DOWN
            # Calculate price movement from entry (positive when price goes down)
            price_movement = pos["entry_price"] - current_price  # Positive when price goes down
            
            # For every 100 points price movement DOWN, move trailing SL 100 points DOWN (1:1 ratio)
            # Initial trailing SL: entry_price + trailing_stop (above entry)
            # As price moves down, trailing SL moves down: entry_price + trailing_stop - price_movement
            # Example: Entry ₹85,953.83, Trailing Stop: 50
            #          Initial: Trailing SL = ₹85,953.83 + 50 = ₹86,003.83
            #          Price ₹85,853.83 (100 pts down) → Trailing SL = ₹85,953.83 + 50 - 100 = ₹85,903.83
            #          Price ₹85,753.83 (200 pts down) → Trailing SL = ₹85,953.83 + 50 - 200 = ₹85,803.83
            if price_movement > 0:
                new_trailing_stop_price = pos["entry_price"] + self.strategy.trailing_stop - price_movement
            else:
                # If price hasn't moved down, use initial trailing SL
                new_trailing_stop_price = pos["entry_price"] + self.strategy.trailing_stop
            
            # Only update if it's lower than previous (can't move backward)
            # For PE, lower trailing SL means it moved down (closer to entry or below)
            if pos["trailing_stop_price"] is None or new_trailing_stop_price < pos["trailing_stop_price"]:
                pos["trailing_stop_price"] = new_trailing_stop_price
                logger.debug(f"PE Trailing SL updated: {pos['trailing_stop_price']:.2f} (Current Price: {current_price:.2f}, Movement: {price_movement:.2f} pts, Ratio: 1:1)")
            
            # PE Stop Loss: Exit when price goes UP by stop_loss points from entry
            # SL Level = entry_price + stop_loss
            price_rise = current_price - pos["entry_price"]
            if price_rise >= self.strategy.stop_loss:
                loss = price_rise * pos["lots"]
                return True, f"Stop Loss hit (Loss: ₹{loss:.2f}, Price rise: {price_rise:.2f} points)", option_type
            
            # PE Trailing Stop: lock profit when price rises back to trailing stop
            if pos["trailing_stop_price"] is not None and current_price >= pos["trailing_stop_price"]:
                price_rise_from_trough = current_price - (pos["trailing_stop_price"] - self.strategy.trailing_stop)
                return True, (
                    f"Trailing Stop Loss hit (Profit: ₹{pnl:.2f}, Entry: ₹{pos['entry_price']:.2f}, "
                    f"Trailing SL: ₹{pos['trailing_stop_price']:.2f}, Current: ₹{current_price:.2f}, "
                    f"Rise: {price_rise_from_trough:.2f} points)"
                ), option_type
        
        return False, None, None
    
    def exit_trade(
        self,
        exit_price: float,
        exit_time: datetime,
        reason: str,
        option_type: Optional[OptionType] = None
    ) -> Dict:
        """
        Exit a specific trade (or current position if option_type not specified)
        
        If exit is due to Stop Loss, enable re-entry mode:
        - For PE: wait for next red candle
        - For CE: wait for next green candle
        """
        if option_type is None:
            option_type = self.current_position
        
        if option_type is None or not self._has_position(option_type):
            return {"success": False, "reason": f"No active {option_type.value if option_type else ''} position"}
        
        pos = self._get_position(option_type)
        pnl = self.calculate_pnl(exit_price, option_type)
        # Initialize total_investment if not present (for positions recovered from Kite/CSV)
        if "total_investment" not in pos:
            pos["total_investment"] = pos.get("entry_price", exit_price) * pos.get("lots", 1)
        return_pct = (pnl / pos["total_investment"]) * 100 if pos["total_investment"] > 0 else 0
        
        # Check if exit is due to Stop Loss - enable re-entry mode
        is_sl_exit = "Stop Loss" in reason
        
        result = {
            "success": True,
            "exit_price": exit_price,
            "exit_time": exit_time,
            "entry_price": pos["entry_price"],
            "entry_time": pos["entry_time"],
            "lots": pos["lots"],
            "pnl": pnl,
            "return_pct": return_pct,
            "reason": reason,
            "option_type": option_type.value,
            "enable_reentry": is_sl_exit
        }
        
        # If SL hit, enable re-entry mode for this option type
        if is_sl_exit:
            self.reentry_mode[option_type]["waiting"] = True
            # Set re-entry candle type based on option type
            if option_type == OptionType.PE:
                self.reentry_mode[option_type]["candle_type"] = 'bearish'  # Wait for red candle
            elif option_type == OptionType.CE:
                self.reentry_mode[option_type]["candle_type"] = 'bullish'  # Wait for green candle
            logger.info(f"Stop Loss hit for {option_type.value}. Re-entry enabled: waiting for {self.reentry_mode[option_type]['candle_type']} candle")
        else:
            # Reset re-entry mode for other exit reasons
            self.reentry_mode[option_type]["waiting"] = False
            self.reentry_mode[option_type]["candle_type"] = None
        
        # Clear position
        self.positions[option_type] = None
        
        # Clear current_position if it was pointing to this option type
        if self.current_position == option_type:
            self.current_position = None
        
        return result
    
    @property
    def waiting_for_reentry(self) -> bool:
        """Legacy property: returns True if any position is waiting for re-entry"""
        return any(mode["waiting"] for mode in self.reentry_mode.values())
    
    @waiting_for_reentry.setter
    def waiting_for_reentry(self, value: bool):
        """Legacy setter: sets re-entry for current position (if any)"""
        if self.current_position is not None:
            self.reentry_mode[self.current_position]["waiting"] = value
    
    @property
    def reentry_candle_type(self) -> Optional[str]:
        """Legacy property: returns re-entry candle type for current position"""
        if self.current_position is not None:
            return self.reentry_mode[self.current_position]["candle_type"]
        return None
    
    @reentry_candle_type.setter
    def reentry_candle_type(self, value: Optional[str]):
        """Legacy setter: sets re-entry candle type for current position"""
        if self.current_position is not None:
            self.reentry_mode[self.current_position]["candle_type"] = value
    
    def clear_reentry_mode(self, option_type: Optional[OptionType] = None):
        """Clear re-entry mode for a specific option type or current position"""
        if option_type is None:
            option_type = self.current_position
        if option_type is not None:
            self.reentry_mode[option_type]["waiting"] = False
            self.reentry_mode[option_type]["candle_type"] = None
        self.entry_spot = None
        self.entry_premium = None
        
        logger.info(f"Exited trade at ₹{exit_price:.2f} - {reason}. P&L: ₹{pnl:.2f}")
        
        return result
    
    def clear_reentry_mode(self, option_type: Optional[OptionType] = None):
        """Clear re-entry mode for a specific option type or current position"""
        if option_type is None:
            option_type = self.current_position
        if option_type is not None:
            self.reentry_mode[option_type]["waiting"] = False
            self.reentry_mode[option_type]["candle_type"] = None
            logger.debug(f"Re-entry mode cleared for {option_type.value}")
    
    # Backward compatibility properties for LiveSegmentAgent
    @property
    def entry_price(self) -> Optional[float]:
        """Legacy property: returns entry price of current position"""
        if self.current_position is not None:
            pos = self._get_position(self.current_position)
            return pos["entry_price"] if pos else None
        return None
    
    @property
    def entry_time(self) -> Optional[datetime]:
        """Legacy property: returns entry time of current position"""
        if self.current_position is not None:
            pos = self._get_position(self.current_position)
            return pos["entry_time"] if pos else None
        return None
    
    @property
    def lots(self) -> int:
        """Legacy property: returns lots of current position"""
        if self.current_position is not None:
            pos = self._get_position(self.current_position)
            return pos["lots"] if pos else 0
        return 0
    
    @property
    def entry_strike(self) -> Optional[int]:
        """Legacy property: returns entry strike of current position"""
        if self.current_position is not None:
            pos = self._get_position(self.current_position)
            return pos.get("entry_strike") if pos else None
        return None
    
    @entry_strike.setter
    def entry_strike(self, value: Optional[int]):
        """Legacy setter: sets entry strike for current position"""
        if self.current_position is not None:
            pos = self._get_position(self.current_position)
            if pos:
                pos["entry_strike"] = value
    
    @property
    def entry_premium(self) -> Optional[float]:
        """Legacy property: returns entry premium of current position"""
        if self.current_position is not None:
            pos = self._get_position(self.current_position)
            return pos.get("entry_premium") if pos else None
        return None
    
    @entry_premium.setter
    def entry_premium(self, value: Optional[float]):
        """Legacy setter: sets entry premium for current position"""
        if self.current_position is not None:
            pos = self._get_position(self.current_position)
            if pos:
                pos["entry_premium"] = value
    
    def set_position_metadata(self, option_type: OptionType, **kwargs):
        """Set metadata for a specific position (strike, premium, etc.)"""
        if self._has_position(option_type):
            pos = self._get_position(option_type)
            for key, value in kwargs.items():
                pos[key] = value

    def export_indicators_for_comparison(
        self,
        df: pd.DataFrame,
        output_path: Optional[str] = None,
        start_idx: Optional[int] = None,
        end_idx: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Export calculated RSI, PS, and VS values for comparison with TradingView.
        
        This function calculates all indicators and exports them to a CSV file
        that can be easily compared with TradingView's "Hilega Milega" indicator.
        
        Args:
            df: DataFrame with OHLCV data (must have datetime index)
            output_path: Path to save CSV file (if None, returns DataFrame only)
            start_idx: Start index for export (if None, starts from first valid index)
            end_idx: End index for export (if None, exports to end)
        
        Returns:
            DataFrame with columns: Timestamp, Open, High, Low, Close, Volume, 
            RSI, PS, VS, PS_VS_Diff, Candle_Type, Crossover_Type
        """
        # Calculate indicators
        rsi_series = self.calculate_rsi(df['close'], period=self.rsi_period)
        price_strength = self.calculate_price_strength(df)
        volume_strength = self.calculate_volume_strength(df)
        
        # Determine valid range (skip NaN values)
        min_valid_idx = max(self.rsi_period, self.volume_strength_wma)
        if start_idx is None:
            start_idx = min_valid_idx
        if end_idx is None:
            end_idx = len(df)
        
        # Ensure valid range
        start_idx = max(start_idx, min_valid_idx)
        end_idx = min(end_idx, len(df))
        
        # Prepare export data
        export_data = []
        
        for idx in range(start_idx, end_idx):
            timestamp = df.index[idx] if hasattr(df.index, '__getitem__') else idx
            candle = df.iloc[idx]
            
            # Get indicator values
            rsi_val = rsi_series.iloc[idx] if idx < len(rsi_series) else None
            ps_val = price_strength.iloc[idx] if idx < len(price_strength) else None
            vs_val = volume_strength.iloc[idx] if idx < len(volume_strength) else None
            
            # Skip if indicators are not valid
            if pd.isna(rsi_val) or pd.isna(ps_val) or pd.isna(vs_val):
                continue
            
            # Calculate PS-VS difference
            ps_vs_diff = float(ps_val) - float(vs_val)
            
            # Determine candle type
            is_bullish = self.is_bullish_candle(candle)
            is_bearish = self.is_bearish_candle(candle)
            if is_bullish:
                candle_type = "Bullish"
            elif is_bearish:
                candle_type = "Bearish"
            else:
                candle_type = "Neutral"
            
            # Detect crossover type
            crossover_type = "None"
            if idx > 0:
                prev_ps = price_strength.iloc[idx - 1] if idx - 1 < len(price_strength) else None
                prev_vs = volume_strength.iloc[idx - 1] if idx - 1 < len(volume_strength) else None
                
                if not pd.isna(prev_ps) and not pd.isna(prev_vs):
                    prev_ps = float(prev_ps)
                    prev_vs = float(prev_vs)
                    curr_ps = float(ps_val)
                    curr_vs = float(vs_val)
                    
                    # PE crossover: PS crosses DOWN to VS (from above to below)
                    if prev_ps > prev_vs and curr_ps < curr_vs:
                        crossover_type = "PE (PS↓VS)"
                    # CE crossover: PS crosses UP to VS (from below to above)
                    elif prev_ps < prev_vs and curr_ps > curr_vs:
                        crossover_type = "CE (PS↑VS)"
            
            # Build row data
            row = {
                "Timestamp": timestamp,
                "Open": float(candle['open']),
                "High": float(candle['high']),
                "Low": float(candle['low']),
                "Close": float(candle['close']),
                "Volume": float(candle['volume']) if 'volume' in candle else 0.0,
                "RSI": float(rsi_val),
                "PS": float(ps_val),
                "VS": float(vs_val),
                "PS_VS_Diff": ps_vs_diff,
                "Candle_Type": candle_type,
                "Crossover_Type": crossover_type
            }
            
            export_data.append(row)
        
        # Create DataFrame
        export_df = pd.DataFrame(export_data)
        
        # Save to CSV if path provided
        if output_path:
            export_df.to_csv(output_path, index=False)
            logger.info(f"✅ Exported {len(export_df)} rows to {output_path}")
            logger.info(f"   Columns: Timestamp, Open, High, Low, Close, Volume, RSI, PS, VS, PS_VS_Diff, Candle_Type, Crossover_Type")
            logger.info(f"   Date range: {export_df['Timestamp'].min()} to {export_df['Timestamp'].max()}")
        
        return export_df

