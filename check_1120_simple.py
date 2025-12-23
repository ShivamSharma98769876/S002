"""
Check why entry was not taken at 11:20 AM on 27th Nov 2025
"""

from datetime import datetime
import pandas as pd
from src.backtesting.data_fetcher import HistoricalDataFetcher
from src.trading.rsi_agent import RSIStrategy, Segment
from src.api.kite_client import KiteClient
from src.config.config_manager import ConfigManager

# Target time
entry_time = datetime(2025, 11, 27, 11, 20, 0)
segment = "BANKNIFTY"

print("="*80)
print(f"CHECKING ENTRY AT 11:20 AM ON 27th NOV 2025")
print("="*80)

# Initialize with config.json and use access_token
print("Initializing Kite client from config.json...")
import sys
import json
sys.stdout.flush()

config = ConfigManager()
config_data = config.get_config()

# Check if access_token exists in config
if 'access_token' in config_data and config_data['access_token']:
    print(f"Found access_token in config.json: {config_data['access_token'][:10]}...")
    sys.stdout.flush()
else:
    print("WARNING: No access_token found in config.json")
    sys.stdout.flush()

# Initialize KiteClient - it should use access_token from config
kite_client = KiteClient(config)

# Check authentication status
print("Checking Kite authentication...")
sys.stdout.flush()

try:
    is_authenticated = kite_client.is_authenticated()
    print(f"Kite authentication status: {is_authenticated}")
    sys.stdout.flush()
    
    if not is_authenticated:
        print("WARNING: Kite client not authenticated")
        print("Attempting to use access_token directly...")
        sys.stdout.flush()
        
        # Try to set access token directly if available
        if 'access_token' in config_data and config_data['access_token']:
            try:
                from kiteconnect import KiteConnect
                api_key = config_data.get('api_key', '')
                access_token = config_data.get('access_token', '')
                
                if api_key and access_token:
                    kite = KiteConnect(api_key=api_key)
                    kite.set_access_token(access_token)
                    # Update the kite_client's kite object
                    if hasattr(kite_client, 'kite'):
                        kite_client.kite = kite
                    print("Access token set directly")
                    sys.stdout.flush()
            except Exception as e:
                print(f"Error setting access token: {e}")
                sys.stdout.flush()
except Exception as e:
    print(f"Error checking authentication: {e}")
    sys.stdout.flush()

data_fetcher = HistoricalDataFetcher(kite_client)
print("Data fetcher initialized\n")
sys.stdout.flush()

# Create strategy
strategy = RSIStrategy(
    segment=Segment.BANKNIFTY,
    rsi_period=9,
    price_strength_ema=3,
    volume_strength_wma=21
)

# Fetch data
from_date = entry_time.replace(hour=9, minute=15, second=0, microsecond=0)
to_date = entry_time.replace(hour=15, minute=30, second=0, microsecond=0)

print(f"\nFetching data from Kite API (using access_token from config)...")
print(f"Date range: {from_date} to {to_date}")
print(f"Segment: {segment}, Interval: 5minute")
print("Please wait...\n")
sys.stdout.flush()

# Force use Kite API - don't fallback to Yahoo Finance
df = None
try:
    df = data_fetcher.fetch_segment_data_from_kite(
        segment=segment,
        from_date=from_date,
        to_date=to_date,
        interval="5minute"
    )
    
    if df.empty:
        print("ERROR: Kite API returned no data!")
        print("Possible reasons:")
        print("  1. Access token expired or invalid")
        print("  2. Market was closed on 27th Nov 2025")
        print("  3. Network issue")
        print("\nTrying to verify Kite connection...")
        sys.stdout.flush()
        
        # Try to verify connection
        try:
            if hasattr(kite_client, 'kite') and kite_client.kite:
                # Try a simple API call
                profile = kite_client.kite.profile()
                print(f"Kite connection verified. User: {profile.get('user_name', 'N/A')}")
                sys.stdout.flush()
        except Exception as e:
            print(f"Kite connection error: {e}")
            print("Please check:")
            print("  1. Access token in config.json is valid")
            print("  2. Internet connection")
            sys.stdout.flush()
        
        exit(1)
    else:
        print(f"Successfully fetched {len(df)} candles from Kite API")
        print(f"Data range: {df.index.min()} to {df.index.max()}")
        sys.stdout.flush()
        
except Exception as e:
    print(f"ERROR fetching from Kite API: {e}")
    import traceback
    traceback.print_exc()
    sys.stdout.flush()
    exit(1)

print(f"Fetched {len(df)} candles\n")

# Calculate indicators
print("Calculating RSI...")
rsi_series = strategy.calculate_rsi(df['close'], period=9)
print(f"RSI calculated: {len(rsi_series)} values, NaN count: {rsi_series.isna().sum()}")

print("Calculating Price Strength (EMA(3) of RSI)...")
price_strength = strategy.calculate_price_strength(df)
print(f"Price Strength calculated: {len(price_strength)} values, NaN count: {price_strength.isna().sum()}")

print("Calculating Volume Strength (WMA(21) of RSI)...")
volume_strength = strategy.calculate_volume_strength(df)
print(f"Volume Strength calculated: {len(volume_strength)} values, NaN count: {volume_strength.isna().sum()}")

# Check if we have enough data
min_required = 29  # RSI(9) needs 9, WMA(21) needs 21, so 9+21-1 = 29
if len(df) < min_required:
    print(f"WARNING: Only {len(df)} candles, need at least {min_required} for Volume Strength")
else:
    print(f"Data sufficient: {len(df)} candles >= {min_required} required")
    
# Show first few non-NaN values
print("\nFirst few Volume Strength values:")
for i in range(min(len(volume_strength), 35)):
    if not pd.isna(volume_strength.iloc[i]):
        print(f"  Index {i} ({df.index[i]}): VS = {volume_strength.iloc[i]:.2f}")
        if i >= 5:
            break

# Find 11:20 AM candle
entry_idx = None
for idx in range(len(df)):
    candle_time = df.index[idx]
    time_diff = abs((candle_time - entry_time).total_seconds())
    if time_diff <= 300:  # 5 min tolerance
        entry_idx = idx
        break

if entry_idx is None:
    print(f"ERROR: Could not find candle at {entry_time}")
    exit(1)

entry_candle = df.iloc[entry_idx]
entry_time_actual = df.index[entry_idx]

print(f"Found candle at: {entry_time_actual} (index {entry_idx})\n")

# Need at least 2 previous candles for crossover check
if entry_idx < 2:
    print(f"ERROR: Not enough data (need at least 2 previous candles, have {entry_idx})")
    exit(1)

# Get previous candles
prev_idx = entry_idx - 1
before_prev_idx = entry_idx - 2

prev_candle = df.iloc[prev_idx]
before_prev_candle = df.iloc[before_prev_idx]

prev_time = df.index[prev_idx]
before_prev_time = df.index[before_prev_idx]

# Get indicator values - check for NaN
entry_ps = price_strength.iloc[entry_idx]
entry_vs = volume_strength.iloc[entry_idx]
prev_ps = price_strength.iloc[prev_idx]
prev_vs = volume_strength.iloc[prev_idx]
before_prev_ps = price_strength.iloc[before_prev_idx]
before_prev_vs = volume_strength.iloc[before_prev_idx]

# Check for NaN values
if pd.isna(entry_vs) or pd.isna(prev_vs) or pd.isna(before_prev_vs):
    print("\n" + "="*80)
    print("WARNING: Volume Strength contains NaN values!")
    print("="*80)
    print(f"Entry VS (index {entry_idx}): {entry_vs}")
    print(f"Previous VS (index {prev_idx}): {prev_vs}")
    print(f"Before Previous VS (index {before_prev_idx}): {before_prev_vs}")
    print(f"\nChecking Volume Strength calculation...")
    
    # Check RSI values
    print(f"\nRSI values around entry:")
    for i in range(max(0, before_prev_idx-5), min(len(rsi_series), entry_idx+3)):
        rsi_val = rsi_series.iloc[i] if i < len(rsi_series) else None
        vs_val = volume_strength.iloc[i] if i < len(volume_strength) else None
        print(f"  Index {i} ({df.index[i]}): RSI={rsi_val:.2f if rsi_val is not None and not pd.isna(rsi_val) else 'NaN'}, VS={vs_val:.2f if vs_val is not None and not pd.isna(vs_val) else 'NaN'}")
    
    # Check if we have enough data
    min_required = 29  # RSI(9) + WMA(21) - 1
    print(f"\nData check:")
    print(f"  Total candles: {len(df)}")
    print(f"  Minimum required: {min_required}")
    print(f"  Entry index: {entry_idx}")
    print(f"  Sufficient data: {entry_idx >= min_required - 1}")
    
    if entry_idx < min_required - 1:
        print(f"\nERROR: Not enough data! Need at least {min_required} candles, have {entry_idx + 1}")
        print(f"Volume Strength will be NaN until index {min_required - 1}")
        exit(1)
    
    # Try to recalculate Volume Strength manually for debugging
    print(f"\nAttempting to recalculate Volume Strength...")
    import numpy as np
    period = 21
    weights = np.arange(period, 0, -1)
    
    # Check RSI values for the window
    if entry_idx >= period - 1:
        rsi_window = rsi_series.iloc[entry_idx - period + 1:entry_idx + 1]
        print(f"  RSI window (last {period} values):")
        for i, val in enumerate(rsi_window):
            print(f"    [{i}] {val:.2f if not pd.isna(val) else 'NaN'}")
        
        # Manual WMA calculation
        rsi_array = np.array(rsi_window)
        nan_count = np.sum(np.isnan(rsi_array))
        print(f"  NaN count in window: {nan_count}")
        
        if nan_count == 0:
            wma_manual = np.sum(weights * rsi_array) / np.sum(weights)
            print(f"  Manual WMA calculation: {wma_manual:.2f}")
            print(f"  Actual VS value: {entry_vs:.2f if not pd.isna(entry_vs) else 'NaN'}")
        else:
            print(f"  ERROR: RSI window contains NaN values, cannot calculate WMA")
    
    print("\n" + "="*80 + "\n")

# Convert to float (will fail if NaN, but we've checked above)
entry_ps = float(entry_ps) if not pd.isna(entry_ps) else None
entry_vs = float(entry_vs) if not pd.isna(entry_vs) else None
prev_ps = float(prev_ps) if not pd.isna(prev_ps) else None
prev_vs = float(prev_vs) if not pd.isna(prev_vs) else None
before_prev_ps = float(before_prev_ps) if not pd.isna(before_prev_ps) else None
before_prev_vs = float(before_prev_vs) if not pd.isna(before_prev_vs) else None

if entry_vs is None or prev_vs is None or before_prev_vs is None:
    print("ERROR: Cannot proceed - Volume Strength is NaN")
    exit(1)

# Get RSI
entry_rsi = float(rsi_series.iloc[entry_idx]) if entry_idx < len(rsi_series) and not pd.isna(rsi_series.iloc[entry_idx]) else None
prev_rsi = float(rsi_series.iloc[prev_idx]) if prev_idx < len(rsi_series) and not pd.isna(rsi_series.iloc[prev_idx]) else None
before_prev_rsi = float(rsi_series.iloc[before_prev_idx]) if before_prev_idx < len(rsi_series) and not pd.isna(rsi_series.iloc[before_prev_idx]) else None

# Check candle types
is_bullish_entry = strategy.is_bullish_candle(entry_candle)
is_bullish_prev = strategy.is_bullish_candle(prev_candle)
is_bullish_before_prev = strategy.is_bullish_candle(before_prev_candle)

# Check crossover - handle None values
if before_prev_ps is None or before_prev_vs is None or prev_ps is None or prev_vs is None:
    print("ERROR: Cannot check crossover - missing values")
    ce_crossover = False
else:
    ce_crossover = (before_prev_ps < before_prev_vs and prev_ps >= prev_vs)

# Print values
print("="*80)
print("VALUES AT 11:20 AM")
print("="*80)

print(f"\n1. Candle Before Previous ({before_prev_time}):")
print(f"   OHLC: O={before_prev_candle['open']:.2f}, H={before_prev_candle['high']:.2f}, L={before_prev_candle['low']:.2f}, C={before_prev_candle['close']:.2f}")
print(f"   Type: {'Bullish (Green)' if is_bullish_before_prev else 'Bearish (Red)'}")
if before_prev_rsi is not None:
    print(f"   RSI: {before_prev_rsi:.2f}")
print(f"   Price Strength: {before_prev_ps:.2f}")
print(f"   Volume Strength: {before_prev_vs:.2f}")
print(f"   PS vs VS: {'PS > VS' if before_prev_ps > before_prev_vs else 'PS < VS'}")

print(f"\n2. Previous Candle ({prev_time}) - WHERE CROSSOVER SHOULD BE:")
print(f"   OHLC: O={prev_candle['open']:.2f}, H={prev_candle['high']:.2f}, L={prev_candle['low']:.2f}, C={prev_candle['close']:.2f}")
print(f"   Type: {'Bullish (Green)' if is_bullish_prev else 'Bearish (Red)'}")
if prev_rsi is not None:
    print(f"   RSI: {prev_rsi:.2f}")
print(f"   Price Strength: {prev_ps:.2f}")
print(f"   Volume Strength: {prev_vs:.2f}")
print(f"   PS vs VS: {'PS > VS' if prev_ps > prev_vs else 'PS < VS'}")

print(f"\n3. Entry Candle ({entry_time_actual}) - WHERE ENTRY SHOULD HAPPEN:")
print(f"   OHLC: O={entry_candle['open']:.2f}, H={entry_candle['high']:.2f}, L={entry_candle['low']:.2f}, C={entry_candle['close']:.2f}")
print(f"   Type: {'Bullish (Green)' if is_bullish_entry else 'Bearish (Red)'}")
if entry_rsi is not None:
    print(f"   RSI: {entry_rsi:.2f}")
print(f"   Price Strength: {entry_ps:.2f}")
print(f"   Volume Strength: {entry_vs:.2f}")
print(f"   PS vs VS: {'PS > VS' if entry_ps > entry_vs else 'PS < VS'}")

print("\n" + "="*80)
print("CROSSOVER CHECK")
print("="*80)
print(f"\nCE Crossover Condition:")
print(f"   Before Previous: PS {before_prev_ps:.2f} < VS {before_prev_vs:.2f} ? {before_prev_ps < before_prev_vs}")
print(f"   Previous: PS {prev_ps:.2f} >= VS {prev_vs:.2f} ? {prev_ps >= prev_vs}")
print(f"   Crossover Detected: {ce_crossover}")

print(f"\nCandle Color Check:")
print(f"   Previous candle is Bullish (Green): {is_bullish_prev}")

print(f"\n" + "="*80)
print("RESULT")
print("="*80)
print(f"\nEntry Conditions:")
print(f"   1. Crossover detected: {ce_crossover}")
print(f"   2. Previous candle is bullish: {is_bullish_prev}")
print(f"   Both met: {ce_crossover and is_bullish_prev}")

if ce_crossover and is_bullish_prev:
    print(f"\n*** ALL CONDITIONS MET - Entry SHOULD have been taken! ***")
    print(f"Possible reasons why it wasn't:")
    print(f"   - Already in a position")
    print(f"   - System not ready (index < 29 for WMA(21))")
    print(f"   - Other system condition")
else:
    print(f"\n*** CONDITIONS NOT MET - Entry correctly NOT taken ***")
    if not ce_crossover:
        print(f"   Reason: No crossover (PS didn't cross from below to above VS)")
    if not is_bullish_prev:
        print(f"   Reason: Previous candle is not bullish (need green for CE)")

print("\n" + "="*80)

