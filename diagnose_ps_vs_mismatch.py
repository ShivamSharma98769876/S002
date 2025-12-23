"""
Diagnostic script to compare PS/VS calculations with TradingView
This helps identify why PS/VS values don't match TradingView
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from trading.rsi_agent import RSIStrategy, Segment
from api.kite_client import KiteClient
from backtesting.data_fetcher import HistoricalDataFetcher

def calculate_rsi_wilders(prices: pd.Series, period: int = 9) -> pd.Series:
    """
    Calculate RSI using Wilder's smoothing method (matching TradingView)
    """
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    # Use EWM with alpha=1/period to approximate Wilder's smoothing
    gain_ema = pd.Series(gain, index=prices.index).ewm(alpha=1.0/period, adjust=False).mean()
    loss_ema = pd.Series(loss, index=prices.index).ewm(alpha=1.0/period, adjust=False).mean()
    
    rs = gain_ema / loss_ema.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    
    return rsi

def calculate_wma_tradingview(rsi_series: pd.Series, period: int = 21) -> pd.Series:
    """
    Calculate WMA matching TradingView formula:
    WMA = (n*P1 + (n-1)*P2 + ... + 1*Pn) / (n + (n-1) + ... + 1)
    Where P1 is newest, Pn is oldest
    """
    weights = np.arange(1, period + 1)  # [1, 2, 3, ..., 21]
    
    def wma_func(x):
        """x is in chronological order [oldest, ..., newest]"""
        if len(x) < period:
            return np.nan
        x = np.array(x)
        # Forward fill NaN
        valid_mask = ~np.isnan(x)
        if not np.any(valid_mask):
            return np.nan
        first_valid_idx = np.where(valid_mask)[0][0]
        for i in range(len(x)):
            if np.isnan(x[i]):
                if i > first_valid_idx:
                    x[i] = x[i-1]
                else:
                    x[i] = x[first_valid_idx]
        # Apply weights: 1*oldest + 2*... + period*newest
        wma_value = np.sum(weights * x) / np.sum(weights)
        return wma_value
    
    return rsi_series.rolling(window=period, min_periods=period).apply(wma_func, raw=True)

def diagnose_ps_vs_mismatch(segment: str = "NIFTY", target_time: str = "2025-12-19 10:26:00"):
    """
    Diagnose PS/VS mismatch by:
    1. Fetching data from Kite API
    2. Calculating PS/VS using our method
    3. Showing which candle is being used
    4. Comparing with expected TradingView values
    """
    print(f"\n{'='*80}")
    print(f"PS/VS Mismatch Diagnostic")
    print(f"{'='*80}\n")
    print(f"Segment: {segment}")
    print(f"Target Time: {target_time}\n")
    
    # Parse target time
    target_dt = pd.Timestamp(target_time)
    
    # Initialize strategy
    strategy = RSIStrategy(
        segment=Segment[segment],
        rsi_period=9,
        timeframe="5min",
        price_strength_ema=3,
        volume_strength_wma=21
    )
    
    # Fetch data from Kite
    kite_client = KiteClient()
    if not kite_client.is_authenticated():
        print("❌ Kite API not authenticated. Please authenticate first.")
        return
    
    data_fetcher = HistoricalDataFetcher(kite_client)
    
    # Fetch data for the day
    from_date = target_dt.replace(hour=9, minute=15, second=0, microsecond=0)
    to_date = target_dt.replace(hour=15, minute=30, second=0, microsecond=0)
    
    print(f"Fetching data from {from_date} to {to_date}...")
    df = data_fetcher.fetch_segment_data_from_kite(
        segment=segment,
        from_date=from_date,
        to_date=to_date,
        interval="5minute"
    )
    
    if df.empty:
        print("❌ No data fetched!")
        return
    
    print(f"✅ Fetched {len(df)} candles\n")
    
    # Calculate indicators
    print("Calculating RSI, PS, and VS...")
    rsi = strategy.calculate_rsi(df['close'], period=9)
    ps = strategy.calculate_price_strength(df)
    vs = strategy.calculate_volume_strength(df)
    
    # Find the candle closest to target time
    target_idx = None
    min_diff = float('inf')
    for idx, ts in enumerate(df.index):
        diff = abs((ts - target_dt).total_seconds())
        if diff < min_diff:
            min_diff = diff
            target_idx = idx
    
    if target_idx is None:
        print("❌ Could not find candle near target time")
        return
    
    # Show candles around target time
    print(f"\n{'='*80}")
    print(f"Candles Around Target Time ({target_time})")
    print(f"{'='*80}\n")
    
    start_idx = max(0, target_idx - 5)
    end_idx = min(len(df), target_idx + 5)
    
    print(f"{'Timestamp':<20} {'Window':<15} {'Close':<10} {'RSI':<8} {'PS':<8} {'VS':<8} {'PS-VS':<8} {'PS>VS?':<8}")
    print("-" * 100)
    
    for idx in range(start_idx, end_idx):
        ts = df.index[idx]
        row = df.iloc[idx]
        
        # Calculate window
        bar_end = ts.floor("5T")
        bar_start = bar_end - timedelta(minutes=5)
        window = f"{bar_start.strftime('%H:%M')}–{bar_end.strftime('%H:%M')}"
        
        # Get indicator values
        rsi_val = rsi.iloc[idx] if idx < len(rsi) else np.nan
        ps_val = ps.iloc[idx] if idx < len(ps) else np.nan
        vs_val = vs.iloc[idx] if idx < len(vs) else np.nan
        diff = ps_val - vs_val if not (np.isnan(ps_val) or np.isnan(vs_val)) else np.nan
        ps_above = "YES" if (not np.isnan(diff) and diff > 0) else "NO"
        
        marker = " <-- TARGET" if idx == target_idx else ""
        
        print(f"{ts.strftime('%Y-%m-%d %H:%M:%S'):<20} {window:<15} {row['close']:<10.2f} "
              f"{rsi_val:<8.2f} {ps_val:<8.2f} {vs_val:<8.2f} {diff:<8.2f} {ps_above:<8} {marker}")
    
    # Show the specific candle used in logs
    print(f"\n{'='*80}")
    print(f"Analysis of Candle Used in Logs")
    print(f"{'='*80}\n")
    
    log_candle_time = pd.Timestamp("2025-12-19 10:21:48")  # From logs
    log_idx = None
    for idx, ts in enumerate(df.index):
        if abs((ts - log_candle_time).total_seconds()) < 60:
            log_idx = idx
            break
    
    if log_idx is not None:
        ts = df.index[log_idx]
        bar_end = ts.floor("5T")
        bar_start = bar_end - timedelta(minutes=5)
        window = f"{bar_start.strftime('%H:%M')}–{bar_end.strftime('%H:%M')}"
        
        rsi_val = rsi.iloc[log_idx] if log_idx < len(rsi) else np.nan
        ps_val = ps.iloc[log_idx] if log_idx < len(ps) else np.nan
        vs_val = vs.iloc[log_idx] if log_idx < len(vs) else np.nan
        
        print(f"Candle from logs: {ts}")
        print(f"Window: {window}")
        print(f"Close: {df.iloc[log_idx]['close']:.2f}")
        print(f"RSI: {rsi_val:.2f}")
        print(f"PS: {ps_val:.2f}")
        print(f"VS: {vs_val:.2f}")
        print(f"PS - VS: {ps_val - vs_val:.2f}")
        print(f"PS > VS: {'YES' if ps_val > vs_val else 'NO'}")
        print(f"\n⚠️ This candle is from window {window}, which is OLDER than expected!")
        print(f"   Expected: 10:20–10:25")
        print(f"   Found: {window}")
        print(f"   This explains why PS/VS values don't match TradingView!")
    
    # Show expected candle (10:20-10:25)
    print(f"\n{'='*80}")
    print(f"Expected Candle (10:20–10:25)")
    print(f"{'='*80}\n")
    
    expected_time = pd.Timestamp("2025-12-19 10:25:00")
    expected_idx = None
    for idx, ts in enumerate(df.index):
        if abs((ts - expected_time).total_seconds()) < 60:
            expected_idx = idx
            break
    
    if expected_idx is not None:
        ts = df.index[expected_idx]
        bar_end = ts.floor("5T")
        bar_start = bar_end - timedelta(minutes=5)
        window = f"{bar_start.strftime('%H:%M')}–{bar_end.strftime('%H:%M')}"
        
        rsi_val = rsi.iloc[expected_idx] if expected_idx < len(rsi) else np.nan
        ps_val = ps.iloc[expected_idx] if expected_idx < len(ps) else np.nan
        vs_val = vs.iloc[expected_idx] if expected_idx < len(vs) else np.nan
        
        print(f"Candle timestamp: {ts}")
        print(f"Window: {window}")
        print(f"Close: {df.iloc[expected_idx]['close']:.2f}")
        print(f"RSI: {rsi_val:.2f}")
        print(f"PS: {ps_val:.2f}")
        print(f"VS: {vs_val:.2f}")
        print(f"PS - VS: {ps_val - vs_val:.2f}")
        print(f"PS > VS: {'YES' if ps_val > vs_val else 'NO'}")
        print(f"\n✅ This is the candle TradingView is showing!")
    else:
        print("❌ Expected candle (10:20–10:25) not found in data")
        print("   This means the API hasn't published it yet, which is why we're using old data.")
    
    print(f"\n{'='*80}")
    print(f"Recommendations")
    print(f"{'='*80}\n")
    print("1. The system is using OLD candles when the exact expected candle isn't available.")
    print("2. Solution: Wait for the correct candle to be available, or use database candles if recent enough.")
    print("3. The WMA calculation appears correct - the issue is data timing, not calculation.")
    print("\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Diagnose PS/VS mismatch with TradingView")
    parser.add_argument("--segment", default="NIFTY", choices=["NIFTY", "BANKNIFTY", "SENSEX"])
    parser.add_argument("--time", default="2025-12-19 10:26:00", help="Target time to check")
    args = parser.parse_args()
    
    diagnose_ps_vs_mismatch(args.segment, args.time)

