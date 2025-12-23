"""
Quick script to check why entry was not taken at 11:20 AM
"""

import sys
from datetime import datetime
import pandas as pd
from src.backtesting.data_fetcher import HistoricalDataFetcher
from src.trading.rsi_agent import RSIStrategy, Segment
from src.api.kite_client import KiteClient
from src.config.config_manager import ConfigManager

def check_1120_entry():
    segment = "BANKNIFTY"
    entry_time = datetime(2025, 11, 27, 11, 20, 0)
    
    print("="*80)
    print(f"ANALYZING WHY ENTRY WAS NOT TAKEN AT 11:20 AM")
    print("="*80)
    
    # Initialize
    config = ConfigManager()
    kite_client = KiteClient(config)
    data_fetcher = HistoricalDataFetcher(kite_client)
    
    # Get segment enum
    segment_enum = Segment[segment.upper()]
    
    # Create strategy
    strategy = RSIStrategy(
        segment=segment_enum,
        rsi_period=9,
        price_strength_ema=3,
        volume_strength_wma=21
    )
    
    # Fetch data
    from_date = entry_time.replace(hour=9, minute=15, second=0, microsecond=0)
    to_date = entry_time.replace(hour=15, minute=30, second=0, microsecond=0)
    
    print(f"\nFetching data from {from_date} to {to_date}...")
    df = data_fetcher.fetch_segment_data_from_kite(
        segment=segment,
        from_date=from_date,
        to_date=to_date,
        interval="5minute"
    )
    
    if df.empty:
        print("Kite API failed, using Yahoo Finance...")
        df = data_fetcher.fetch_segment_data(
            segment=segment,
            from_date=from_date,
            to_date=to_date,
            interval="5minute"
        )
    
    if df.empty:
        print("No data fetched!")
        return
    
    print(f"Fetched {len(df)} candles\n")
    
    # Calculate indicators
    price_strength = strategy.calculate_price_strength(df)
    volume_strength = strategy.calculate_volume_strength(df)
    rsi_series = strategy.calculate_rsi(df['close'], period=9)
    
    # Find 11:20 AM candle
    entry_idx = None
    for idx, row in df.iterrows():
        if isinstance(idx, pd.Timestamp):
            candle_time = idx
        else:
            candle_time = pd.Timestamp(idx)
        
        time_diff = abs((candle_time - entry_time).total_seconds())
        if time_diff <= 300:
            entry_idx = df.index.get_loc(idx)
            break
    
    if entry_idx is None:
        print(f"Could not find candle at {entry_time}")
        return
    
    entry_candle = df.iloc[entry_idx]
    entry_time_actual = df.index[entry_idx]
    
    print(f"Found candle at index {entry_idx}: {entry_time_actual}\n")
    
    # Check if we have enough data
    if entry_idx < 2:
        print(f"Not enough data (need at least 2 previous candles, have {entry_idx})")
        return
    
    # Get previous candles
    prev_idx = entry_idx - 1
    before_prev_idx = entry_idx - 2
    
    prev_candle = df.iloc[prev_idx]
    before_prev_candle = df.iloc[before_prev_idx]
    
    prev_time = df.index[prev_idx]
    before_prev_time = df.index[before_prev_idx]
    
    # Get values
    entry_ps = price_strength.iloc[entry_idx]
    entry_vs = volume_strength.iloc[entry_idx]
    prev_ps = price_strength.iloc[prev_idx]
    prev_vs = volume_strength.iloc[prev_idx]
    before_prev_ps = price_strength.iloc[before_prev_idx]
    before_prev_vs = volume_strength.iloc[before_prev_idx]
    
    # Get RSI values
    entry_rsi = rsi_series.iloc[entry_idx] if entry_idx < len(rsi_series) else None
    prev_rsi = rsi_series.iloc[prev_idx] if prev_idx < len(rsi_series) else None
    before_prev_rsi = rsi_series.iloc[before_prev_idx] if before_prev_idx < len(rsi_series) else None
    
    # Check candle types
    is_bullish_entry = strategy.is_bullish_candle(entry_candle)
    is_bullish_prev = strategy.is_bullish_candle(prev_candle)
    is_bullish_before_prev = strategy.is_bullish_candle(before_prev_candle)
    
    # Check crossover
    ce_crossover = (before_prev_ps < before_prev_vs and prev_ps >= prev_vs)
    
    # Print detailed values
    print("="*80)
    print("DETAILED VALUES AT 11:20 AM")
    print("="*80)
    
    print(f"\nCandle Before Previous ({before_prev_time}):")
    print(f"   OHLC: O={before_prev_candle['open']:.2f}, H={before_prev_candle['high']:.2f}, L={before_prev_candle['low']:.2f}, C={before_prev_candle['close']:.2f}")
    print(f"   Candle Type: {'Bullish (Green)' if is_bullish_before_prev else 'Bearish (Red)'}")
    print(f"   RSI: {before_prev_rsi:.2f}" if before_prev_rsi is not None and not pd.isna(before_prev_rsi) else "   RSI: N/A")
    print(f"   Price Strength: {before_prev_ps:.2f}")
    print(f"   Volume Strength: {before_prev_vs:.2f}")
    print(f"   PS vs VS: {'PS > VS' if before_prev_ps > before_prev_vs else 'PS < VS' if before_prev_ps < before_prev_vs else 'PS = VS'}")
    
    print(f"\nPrevious Candle ({prev_time}) - WHERE CROSSOVER SHOULD BE:")
    print(f"   OHLC: O={prev_candle['open']:.2f}, H={prev_candle['high']:.2f}, L={prev_candle['low']:.2f}, C={prev_candle['close']:.2f}")
    print(f"   Candle Type: {'Bullish (Green)' if is_bullish_prev else 'Bearish (Red)'}")
    print(f"   RSI: {prev_rsi:.2f}" if prev_rsi is not None and not pd.isna(prev_rsi) else "   RSI: N/A")
    print(f"   Price Strength: {prev_ps:.2f}")
    print(f"   Volume Strength: {prev_vs:.2f}")
    print(f"   PS vs VS: {'PS > VS' if prev_ps > prev_vs else 'PS < VS' if prev_ps < prev_vs else 'PS = VS'}")
    
    print(f"\nEntry Candle ({entry_time_actual}) - WHERE ENTRY SHOULD HAPPEN:")
    print(f"   OHLC: O={entry_candle['open']:.2f}, H={entry_candle['high']:.2f}, L={entry_candle['low']:.2f}, C={entry_candle['close']:.2f}")
    print(f"   Candle Type: {'Bullish (Green)' if is_bullish_entry else 'Bearish (Red)'}")
    print(f"   RSI: {entry_rsi:.2f}" if entry_rsi is not None and not pd.isna(entry_rsi) else "   RSI: N/A")
    print(f"   Price Strength: {entry_ps:.2f}")
    print(f"   Volume Strength: {entry_vs:.2f}")
    print(f"   PS vs VS: {'PS > VS' if entry_ps > entry_vs else 'PS < VS' if entry_ps < entry_vs else 'PS = VS'}")
    
    print("\n" + "="*80)
    print("CROSSOVER ANALYSIS")
    print("="*80)
    
    print(f"\nCE Crossover Check:")
    print(f"   Before Previous: PS {before_prev_ps:.2f} < VS {before_prev_vs:.2f} = {before_prev_ps < before_prev_vs}")
    print(f"   Previous: PS {prev_ps:.2f} >= VS {prev_vs:.2f} = {prev_ps >= prev_vs}")
    print(f"   Crossover Detected: {ce_crossover}")
    
    print(f"\nCandle Color Check:")
    print(f"   Previous candle is Bullish (Green): {is_bullish_prev}")
    
    print(f"\nEntry Conditions:")
    print(f"   1. Crossover detected: {ce_crossover}")
    print(f"   2. Previous candle is bullish: {is_bullish_prev}")
    print(f"   Both conditions met: {ce_crossover and is_bullish_prev}")
    
    if ce_crossover and is_bullish_prev:
        print(f"\n*** ALL CONDITIONS MET - Entry SHOULD have been taken at {entry_time_actual} ***")
        print(f"Possible reasons why it wasn't:")
        print(f"   1. Already in a position")
        print(f"   2. Insufficient data for indicators")
        print(f"   3. System not ready (index < minimum required)")
    else:
        print(f"\n*** CONDITIONS NOT MET - Entry was correctly NOT taken ***")
        if not ce_crossover:
            print(f"   Reason: No crossover detected")
            print(f"   (PS didn't cross from below VS to above VS)")
        if not is_bullish_prev:
            print(f"   Reason: Previous candle is not bullish")
            print(f"   (Need green candle for CE entry)")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    check_1120_entry()

