"""
Script to explain why a specific trade entry was generated
Analyzes the entry at 2:35 PM on 11/27/2025 for BANKNIFTY CE
"""

import sys
from datetime import datetime
import pandas as pd
from src.backtesting.data_fetcher import HistoricalDataFetcher
from src.trading.rsi_agent import RSIStrategy, Segment
from src.api.kite_client import KiteClient
from src.config.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger("explain_entry")

def explain_entry(segment: str, entry_time: datetime, option_type: str = "CE"):
    """
    Explain why a specific entry was generated
    
    Args:
        segment: Trading segment (BANKNIFTY, NIFTY, SENSEX)
        entry_time: Entry timestamp
        option_type: CE or PE
    """
    print(f"\n{'='*80}")
    print(f"ANALYZING ENTRY: {segment} {option_type} at {entry_time}")
    print(f"{'='*80}\n")
    
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
    
    # Fetch data for the day using Kite API (same as backtest)
    from_date = entry_time.replace(hour=9, minute=15, second=0, microsecond=0)
    to_date = entry_time.replace(hour=15, minute=30, second=0, microsecond=0)
    
    print(f"Fetching data from {from_date} to {to_date} using Kite API...")
    df = data_fetcher.fetch_segment_data_from_kite(
        segment=segment,
        from_date=from_date,
        to_date=to_date,
        interval="5minute"
    )
    
    if df.empty:
        # Fallback to Yahoo Finance if Kite API fails
        print("Kite API data fetch failed, falling back to Yahoo Finance...")
        df = data_fetcher.fetch_segment_data(
            segment=segment,
            from_date=from_date,
            to_date=to_date,
            interval="5minute"
        )
    
    if df.empty:
        print(" No data fetched!")
        return
    
    print(f" Fetched {len(df)} candles\n")
    
    # Calculate indicators
    price_strength = strategy.calculate_price_strength(df)
    volume_strength = strategy.calculate_volume_strength(df)
    
    # Find the entry candle index - check around 2:30-2:40 PM
    entry_idx = None
    for idx, row in df.iterrows():
        if isinstance(idx, pd.Timestamp):
            candle_time = idx
        else:
            candle_time = pd.Timestamp(idx)
        
        # Check if this candle matches entry time (within 5 minutes)
        # Also check 2:30 PM and 2:35 PM specifically
        time_diff = abs((candle_time - entry_time).total_seconds())
        if time_diff <= 300:  # 5 minutes tolerance
            entry_idx = df.index.get_loc(idx)
            print(f"   Found candidate at {candle_time} (diff: {time_diff}s)")
            # Prefer exact match or closest
            if time_diff == 0:
                break
    
    if entry_idx is None:
        print(f" Could not find candle at {entry_time}")
        print(f"Available times around entry:")
        for idx in range(max(0, len(df)-10), len(df)):
            print(f"  - {df.index[idx]}")
        return
    
    print(f" Found entry candle at index {entry_idx}: {df.index[entry_idx]}\n")
    
    # Check if this could be a re-entry
    print(" Checking for re-entry scenario...")
    print("   (Re-entry happens when stop loss was hit and system waits for next green candle)\n")
    
    # Analyze the entry
    entry_candle = df.iloc[entry_idx]
    entry_time_actual = df.index[entry_idx]
    
    # Get previous candle (where crossover should have happened)
    if entry_idx < 1:
        print(" Not enough data to analyze (need at least 2 candles)")
        return
    
    prev_idx = entry_idx - 1
    prev_candle = df.iloc[prev_idx]
    prev_time = df.index[prev_idx]
    
    # Get values first
    entry_ps = price_strength.iloc[entry_idx]
    entry_vs = volume_strength.iloc[entry_idx]
    prev_ps = price_strength.iloc[prev_idx]
    prev_vs = volume_strength.iloc[prev_idx]
    
    # Also check the candle at the exact entry time (11:20 AM)
    # The entry should happen on the current candle if crossover was on previous
    print(f"\n{'='*80}")
    print(f"DETAILED ANALYSIS FOR {entry_time_actual}")
    print(f"{'='*80}\n")
    
    print(f"Current Candle (Entry Time): {entry_time_actual}")
    print(f"   Index: {entry_idx}")
    print(f"   OHLC: O={entry_candle['open']:.2f}, H={entry_candle['high']:.2f}, L={entry_candle['low']:.2f}, C={entry_candle['close']:.2f}")
    print(f"   Price Strength: {entry_ps:.2f}")
    print(f"   Volume Strength: {entry_vs:.2f}")
    print(f"   PS vs VS: {'PS > VS' if entry_ps > entry_vs else 'PS < VS' if entry_ps < entry_vs else 'PS = VS'}\n")
    
    print(f"Previous Candle (Where Crossover Should Be): {prev_time}")
    print(f"   Index: {prev_idx}")
    print(f"   OHLC: O={prev_candle['open']:.2f}, H={prev_candle['high']:.2f}, L={prev_candle['low']:.2f}, C={prev_candle['close']:.2f}")
    print(f"   Price Strength: {prev_ps:.2f}")
    print(f"   Volume Strength: {prev_vs:.2f}")
    print(f"   PS vs VS: {'PS > VS' if prev_ps > prev_vs else 'PS < VS' if prev_ps < prev_vs else 'PS = VS'}\n")
    
    # Get candle before previous (to check crossover)
    if prev_idx >= 1:
        before_prev_idx = prev_idx - 1
        before_prev_ps = price_strength.iloc[before_prev_idx]
        before_prev_vs = volume_strength.iloc[before_prev_idx]
    else:
        before_prev_ps = None
        before_prev_vs = None
    
    # Check candle types
    is_bullish_prev = strategy.is_bullish_candle(prev_candle)
    is_bearish_prev = strategy.is_bearish_candle(prev_candle)
    is_bullish_entry = strategy.is_bullish_candle(entry_candle)
    is_bearish_entry = strategy.is_bearish_candle(entry_candle)
    
    # Check crossover
    if before_prev_ps is not None and before_prev_vs is not None:
        ce_crossover = (before_prev_ps < before_prev_vs and prev_ps >= prev_vs)
        pe_crossover = (before_prev_ps > before_prev_vs and prev_ps <= prev_vs)
    else:
        ce_crossover = False
        pe_crossover = False
    
    # Print analysis
    print(f"{'='*80}")
    print("ENTRY ANALYSIS")
    print(f"{'='*80}\n")
    
    print(f" Entry Candle (where trade was taken):")
    print(f"   Time: {entry_time_actual}")
    print(f"   OHLC: O={entry_candle['open']:.2f}, H={entry_candle['high']:.2f}, "
          f"L={entry_candle['low']:.2f}, C={entry_candle['close']:.2f}")
    print(f"   Candle Type: {' Bullish (Green)' if is_bullish_entry else ' Bearish (Red)' if is_bearish_entry else ' Neutral'}")
    print(f"   Price Strength: {entry_ps:.2f}")
    print(f"   Volume Strength: {entry_vs:.2f}")
    print(f"   PS vs VS: {'PS > VS' if entry_ps > entry_vs else 'PS < VS' if entry_ps < entry_vs else 'PS = VS'}\n")
    
    print(f" Previous Candle (where crossover was detected):")
    print(f"   Time: {prev_time}")
    print(f"   OHLC: O={prev_candle['open']:.2f}, H={prev_candle['high']:.2f}, "
          f"L={prev_candle['low']:.2f}, C={prev_candle['close']:.2f}")
    print(f"   Candle Type: {' Bullish (Green)' if is_bullish_prev else ' Bearish (Red)' if is_bearish_prev else ' Neutral'}")
    print(f"   Price Strength: {prev_ps:.2f}")
    print(f"   Volume Strength: {prev_vs:.2f}")
    print(f"   PS vs VS: {'PS > VS' if prev_ps > prev_vs else 'PS < VS' if prev_ps < prev_vs else 'PS = VS'}\n")
    
    if before_prev_ps is not None:
        before_prev_idx = prev_idx - 1
        before_prev_candle = df.iloc[before_prev_idx]
        before_prev_time = df.index[before_prev_idx]
        print(f"Candle Before Previous (to show crossover): {before_prev_time}")
        print(f"   Index: {before_prev_idx}")
        print(f"   OHLC: O={before_prev_candle['open']:.2f}, H={before_prev_candle['high']:.2f}, L={before_prev_candle['low']:.2f}, C={before_prev_candle['close']:.2f}")
        print(f"   Price Strength: {before_prev_ps:.2f}")
        print(f"   Volume Strength: {before_prev_vs:.2f}")
        print(f"   PS vs VS: {'PS > VS' if before_prev_ps > before_prev_vs else 'PS < VS' if before_prev_ps < before_prev_vs else 'PS = VS'}\n")
        
        # Calculate RSI values for all three candles
        rsi_series = strategy.calculate_rsi(df['close'], period=9)
        if entry_idx < len(rsi_series) and not pd.isna(rsi_series.iloc[entry_idx]):
            print(f"RSI Values:")
            print(f"   {before_prev_time}: RSI = {rsi_series.iloc[before_prev_idx]:.2f}")
            print(f"   {prev_time}: RSI = {rsi_series.iloc[prev_idx]:.2f}")
            print(f"   {entry_time_actual}: RSI = {rsi_series.iloc[entry_idx]:.2f}\n")
    
    print(f"{'='*80}")
    print("SIGNAL GENERATION LOGIC")
    print(f"{'='*80}\n")
    
    if option_type == "CE":
        print(" CE Entry Conditions:")
        print("   1. Price Strength crosses UPWARD to Volume Strength (from below to above)")
        print("   2. This crossover happens on the PREVIOUS candle")
        print("   3. The PREVIOUS candle (where crossover happened) must be BULLISH (Green)")
        print("   4. Entry signal is generated on the CURRENT candle (next candle after crossover)\n")
        
        print(f"   Condition 1 (Crossover):")
        if before_prev_ps is not None:
            if ce_crossover:
                print(f"       DETECTED: PS {before_prev_ps:.2f} < VS {before_prev_vs:.2f}  PS {prev_ps:.2f} >= VS {prev_vs:.2f}")
            else:
                print(f"       NOT DETECTED: PS {before_prev_ps:.2f} {'<' if before_prev_ps < before_prev_vs else '>'} VS {before_prev_vs:.2f}  PS {prev_ps:.2f} {'<' if prev_ps < prev_vs else '>'} VS {prev_vs:.2f}")
        else:
            print(f"        Cannot check (insufficient data)")
        
        print(f"\n   Condition 2 (Candle Color on Previous Candle):")
        if is_bullish_prev:
            print(f"       PREVIOUS candle is BULLISH (Green) ")
        else:
            print(f"       PREVIOUS candle is NOT BULLISH (is {'Bearish' if is_bearish_prev else 'Neutral'}) ")
        
        print(f"\n   Result:")
        if ce_crossover and is_bullish_prev:
            print(f"       ALL CONDITIONS MET  CE ENTRY SIGNAL GENERATED")
            print(f"       Entry taken on: {entry_time_actual}")
        else:
            print(f"       CONDITIONS NOT MET:")
            if not ce_crossover:
                print(f"         - No bullish crossover detected")
                print(f"         - This might be a RE-ENTRY after stop loss")
                print(f"         - Re-entry allows entry on any green candle without crossover")
            if not is_bullish_prev:
                print(f"         - Previous candle is not bullish")
    
    # Check re-entry scenario
    print(f"\n{'='*80}")
    print("RE-ENTRY SCENARIO CHECK")
    print(f"{'='*80}\n")
    print("If this was a re-entry after stop loss:")
    print("   - System would wait for next green candle")
    print("   - Entry can happen on ANY green candle (no crossover needed)")
    print("   - Previous candle being green would trigger re-entry\n")
    
    if is_bullish_prev and not ce_crossover:
        print("    LIKELY RE-ENTRY:")
        print(f"      - Previous candle (2:25 PM) is green ")
        print(f"      - No crossover needed for re-entry ")
        print(f"      - Entry signal generated on next candle (2:30 PM)")
    elif is_bullish_entry and not ce_crossover:
        print("    POSSIBLE RE-ENTRY:")
        print(f"      - Entry candle itself is green ")
        print(f"      - Could be re-entry on current green candle")
    
    elif option_type == "PE":
        print(" PE Entry Conditions:")
        print("   1. Price Strength crosses DOWNWARD to Volume Strength (from above to below)")
        print("   2. This crossover happens on the PREVIOUS candle")
        print("   3. The PREVIOUS candle (where crossover happened) must be BEARISH (Red)")
        print("   4. Entry signal is generated on the CURRENT candle (next candle after crossover)\n")
        
        print(f"   Condition 1 (Crossover):")
        if before_prev_ps is not None:
            if pe_crossover:
                print(f"       DETECTED: PS {before_prev_ps:.2f} > VS {before_prev_vs:.2f}  PS {prev_ps:.2f} <= VS {prev_vs:.2f}")
            else:
                print(f"       NOT DETECTED: PS {before_prev_ps:.2f} {'<' if before_prev_ps < before_prev_vs else '>'} VS {before_prev_vs:.2f}  PS {prev_ps:.2f} {'<' if prev_ps < prev_vs else '>'} VS {prev_vs:.2f}")
        else:
            print(f"        Cannot check (insufficient data)")
        
        print(f"\n   Condition 2 (Candle Color on Previous Candle):")
        if is_bearish_prev:
            print(f"       PREVIOUS candle is BEARISH (Red) ")
        else:
            print(f"       PREVIOUS candle is NOT BEARISH (is {'Bullish' if is_bullish_prev else 'Neutral'}) ")
        
        print(f"\n   Result:")
        if pe_crossover and is_bearish_prev:
            print(f"       ALL CONDITIONS MET  PE ENTRY SIGNAL GENERATED")
            print(f"       Entry taken on: {entry_time_actual}")
        else:
            print(f"       CONDITIONS NOT MET:")
            if not pe_crossover:
                print(f"         - No bearish crossover detected")
            if not is_bearish_prev:
                print(f"         - Previous candle is not bearish")
    
    # Look further back to find if there was an earlier crossover
    print(f"\n{'='*80}")
    print("LOOKING BACK FOR EARLIER CROSSOVER (to find initial entry)")
    print(f"{'='*80}\n")
    
    # Check last 20 candles before entry
    lookback_start = max(0, entry_idx - 20)
    print(f"Checking candles from index {lookback_start} to {entry_idx}:\n")
    
    found_crossover = False
    for idx in range(lookback_start + 2, entry_idx + 1):
        if idx < 2:
            continue
        
        curr_ps = price_strength.iloc[idx]
        prev_ps = price_strength.iloc[idx - 1]
        before_prev_ps = price_strength.iloc[idx - 2]
        curr_vs = volume_strength.iloc[idx]
        prev_vs = volume_strength.iloc[idx - 1]
        before_prev_vs = volume_strength.iloc[idx - 2]
        
        if pd.isna(curr_ps) or pd.isna(prev_ps) or pd.isna(before_prev_ps) or \
           pd.isna(curr_vs) or pd.isna(prev_vs) or pd.isna(before_prev_vs):
            continue
        
        ce_cross = (before_prev_ps < before_prev_vs and prev_ps >= prev_vs)
        candle = df.iloc[idx - 1]  # Previous candle where crossover happened
        is_bull = strategy.is_bullish_candle(candle)
        
        if ce_cross and is_bull:
            candle_time = df.index[idx - 1]
            print(f"    Found CE crossover at {candle_time}:")
            print(f"      PS: {before_prev_ps:.2f} < VS: {before_prev_vs:.2f}  PS: {prev_ps:.2f} >= VS: {prev_vs:.2f}")
            print(f"      Candle: {' Green' if is_bull else ' Red'}")
            print(f"       This would have triggered initial CE entry at {df.index[idx]}\n")
            found_crossover = True
            break
    
    if not found_crossover:
        print("    No earlier CE crossover found")
        print("    This entry is likely a RE-ENTRY after stop loss\n")
    
    print(f"{'='*80}\n")

def analyze_crossover_at_time(segment: str, crossover_time: datetime):
    """Analyze a specific crossover time to understand why entry wasn't taken"""
    print(f"\n{'='*80}")
    print(f"ANALYZING CROSSOVER AT: {crossover_time}")
    print(f"{'='*80}\n")
    
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
    
    # Fetch data for the day using Kite API (same as backtest)
    from_date = crossover_time.replace(hour=9, minute=15, second=0, microsecond=0)
    to_date = crossover_time.replace(hour=15, minute=30, second=0, microsecond=0)
    
    df = data_fetcher.fetch_segment_data_from_kite(
        segment=segment,
        from_date=from_date,
        to_date=to_date,
        interval="5minute"
    )
    
    if df.empty:
        # Fallback to Yahoo Finance if Kite API fails
        logger.warning("Kite API data fetch failed, falling back to Yahoo Finance")
        df = data_fetcher.fetch_segment_data(
            segment=segment,
            from_date=from_date,
            to_date=to_date,
            interval="5minute"
        )
    
    if df.empty:
        print(" No data fetched!")
        return
    
    # Calculate indicators
    price_strength = strategy.calculate_price_strength(df)
    volume_strength = strategy.calculate_volume_strength(df)
    
    # Find all candles around 1:50 PM and check for crossovers
    print("Scanning candles around 1:50 PM for crossovers:\n")
    
    # Show candles from 1:40 to 2:00 PM
    start_check = None
    end_check = None
    for idx, row in df.iterrows():
        if isinstance(idx, pd.Timestamp):
            candle_time = idx
        else:
            candle_time = pd.Timestamp(idx)
        
        if candle_time.hour == 13 and candle_time.minute >= 40:
            if start_check is None:
                start_check = df.index.get_loc(idx)
        if candle_time.hour == 14 and candle_time.minute <= 0:
            end_check = df.index.get_loc(idx)
            break
    
    if start_check is None or end_check is None:
        print(" Could not find candles around 1:50 PM")
        return
    
    print(f"Checking candles from index {start_check} to {end_check}:\n")
    
    for idx in range(start_check, end_check + 1):
        if idx < 2:
            continue
        
        candle = df.iloc[idx]
        candle_time = df.index[idx]
        
        # Get values
        curr_ps = price_strength.iloc[idx]
        prev_ps = price_strength.iloc[idx - 1]
        before_prev_ps = price_strength.iloc[idx - 2] if idx >= 2 else None
        curr_vs = volume_strength.iloc[idx]
        prev_vs = volume_strength.iloc[idx - 1]
        before_prev_vs = volume_strength.iloc[idx - 2] if idx >= 2 else None
        
        if pd.isna(curr_ps) or pd.isna(prev_ps) or pd.isna(curr_vs) or pd.isna(prev_vs):
            continue
        if before_prev_ps is None or pd.isna(before_prev_ps) or before_prev_vs is None or pd.isna(before_prev_vs):
            continue
        
        # Check crossover on PREVIOUS candle (idx-1) - this is how the code works
        # The crossover is detected between (idx-2) and (idx-1)
        # Entry happens at idx if crossover detected and color matches
        ce_crossover = (before_prev_ps < before_prev_vs and prev_ps >= prev_vs)
        pe_crossover = (before_prev_ps > before_prev_vs and prev_ps <= prev_vs)
        
        if ce_crossover or pe_crossover:
            prev_candle = df.iloc[idx - 1]  # Candle where crossover happened
            is_bullish_prev = strategy.is_bullish_candle(prev_candle)
            is_bearish_prev = strategy.is_bearish_candle(prev_candle)
            
            print(f"    Crossover detected on candle at {df.index[idx - 1]} (crossover candle):")
            print(f"      Entry would be at NEXT candle: {candle_time}")
            if ce_crossover:
                print(f"       CE Crossover: PS {before_prev_ps:.2f} < VS {before_prev_vs:.2f}  PS {prev_ps:.2f} >= VS {prev_vs:.2f}")
                print(f"      Crossover candle type: {' Green' if is_bullish_prev else ' Red'}")
                if is_bullish_prev:
                    print(f"       ALL CONDITIONS MET - Entry SHOULD be at: {candle_time}")
                else:
                    print(f"       No entry - crossover candle is not green (need green for CE)")
            if pe_crossover:
                print(f"       PE Crossover: PS {before_prev_ps:.2f} > VS {before_prev_vs:.2f}  PS {prev_ps:.2f} <= VS {prev_vs:.2f}")
                print(f"      Crossover candle type: {' Green' if is_bullish_prev else ' Red'}")
                if is_bearish_prev:
                    print(f"       ALL CONDITIONS MET - Entry SHOULD be at: {candle_time}")
                else:
                    print(f"       No entry - crossover candle is not red (need red for PE)")
            print()
    
    # Now find the specific crossover candle
    crossover_idx = None
    for idx, row in df.iterrows():
        if isinstance(idx, pd.Timestamp):
            candle_time = idx
        else:
            candle_time = pd.Timestamp(idx)
        
        time_diff = abs((candle_time - crossover_time).total_seconds())
        if time_diff <= 300:  # 5 minutes tolerance
            crossover_idx = df.index.get_loc(idx)
            break
    
    if crossover_idx is None:
        print(f" Could not find candle at {crossover_time}")
        return
    
    print(f" Found crossover candle at index {crossover_idx}: {df.index[crossover_idx]}\n")
    
    # Check the crossover
    if crossover_idx < 2:
        print(" Not enough data to check crossover")
        return
    
    # Get candles
    crossover_candle = df.iloc[crossover_idx]
    before_crossover_candle = df.iloc[crossover_idx - 1]
    
    # Get values
    crossover_ps = price_strength.iloc[crossover_idx]
    before_ps = price_strength.iloc[crossover_idx - 1]
    crossover_vs = volume_strength.iloc[crossover_idx]
    before_vs = volume_strength.iloc[crossover_idx - 1]
    
    # Check crossover
    ce_crossover = (before_ps < before_vs and crossover_ps >= crossover_vs)
    is_bullish = strategy.is_bullish_candle(crossover_candle)
    
    print(f" Crossover Candle (1:50 PM):")
    print(f"   Time: {df.index[crossover_idx]}")
    print(f"   OHLC: O={crossover_candle['open']:.2f}, H={crossover_candle['high']:.2f}, "
          f"L={crossover_candle['low']:.2f}, C={crossover_candle['close']:.2f}")
    print(f"   Candle Type: {' Bullish (Green)' if is_bullish else ' Bearish (Red)'}")
    print(f"   Price Strength: {crossover_ps:.2f}")
    print(f"   Volume Strength: {crossover_vs:.2f}\n")
    
    print(f" Candle Before Crossover:")
    print(f"   Time: {df.index[crossover_idx - 1]}")
    print(f"   Price Strength: {before_ps:.2f}")
    print(f"   Volume Strength: {before_vs:.2f}\n")
    
    print(f" Crossover Detected: {ce_crossover}")
    print(f" Candle is Bullish: {is_bullish}")
    
    if ce_crossover and is_bullish:
        print(f"\n CONDITIONS MET - Entry should be at NEXT candle (1:55 PM)")
        
        # Check next candle (1:55 PM)
        if crossover_idx + 1 < len(df):
            next_candle = df.iloc[crossover_idx + 1]
            next_time = df.index[crossover_idx + 1]
            print(f"\n Next Candle (where entry should happen - 1:55 PM):")
            print(f"   Time: {next_time}")
            print(f"   OHLC: O={next_candle['open']:.2f}, H={next_candle['high']:.2f}, "
                  f"L={next_candle['low']:.2f}, C={next_candle['close']:.2f}")
            print(f"   Candle Type: {' Bullish' if strategy.is_bullish_candle(next_candle) else ' Bearish'}")
    else:
        print(f"\n CONDITIONS NOT MET:")
        if not ce_crossover:
            print(f"   - No crossover detected")
        if not is_bullish:
            print(f"   - Candle is not bullish (is {'bearish' if strategy.is_bearish_candle(crossover_candle) else 'neutral'})")
    
    print(f"\n{'='*80}\n")
    
    # Now check what happened at 1:55 PM (where entry should have been)
    entry_should_be_at = datetime(2025, 11, 27, 13, 55, 0)
    entry_idx_expected = None
    for idx, row in df.iterrows():
        if isinstance(idx, pd.Timestamp):
            candle_time = idx
        else:
            candle_time = pd.Timestamp(idx)
        
        time_diff = abs((candle_time - entry_should_be_at).total_seconds())
        if time_diff <= 300:
            entry_idx_expected = df.index.get_loc(idx)
            break
    
    if entry_idx_expected:
        print(f" Checking why entry wasn't taken at 1:55 PM (index {entry_idx_expected}):\n")
        expected_candle = df.iloc[entry_idx_expected]
        expected_time = df.index[entry_idx_expected]
        
        # Check if there was a crossover on previous candle
        if entry_idx_expected >= 2:
            prev_idx = entry_idx_expected - 1
            before_prev_idx = entry_idx_expected - 2
            
            prev_ps = price_strength.iloc[prev_idx]
            before_prev_ps = price_strength.iloc[before_prev_idx]
            prev_vs = volume_strength.iloc[prev_idx]
            before_prev_vs = volume_strength.iloc[before_prev_idx]
            
            ce_cross = (before_prev_ps < before_prev_vs and prev_ps >= prev_vs)
            prev_candle = df.iloc[prev_idx]
            is_bull = strategy.is_bullish_candle(prev_candle)
            
            print(f"   Crossover candle (where crossover happened): {df.index[prev_idx]}")
            print(f"   Crossover check: PS {before_prev_ps:.2f} < VS {before_prev_vs:.2f}  PS {prev_ps:.2f} >= VS {prev_vs:.2f}")
            print(f"   CE Crossover detected: {ce_cross}")
            print(f"   Crossover candle is bullish: {is_bull}")
            print(f"   Entry candle (1:55 PM): {expected_time}")
            print(f"   Entry candle type: {' Green' if strategy.is_bullish_candle(expected_candle) else ' Red'}")
            
            if ce_cross and is_bull:
                print(f"\n    ALL CONDITIONS MET - Entry SHOULD have been taken at 1:55 PM!")
                print(f"    But entry was NOT taken!")
                print(f"   Possible reasons:")
                print(f"      1. Already in a position (system doesn't allow multiple positions)")
                print(f"      2. Insufficient data/indicators not ready")
                print(f"      3. Some other condition not met")
            else:
                print(f"\n    Conditions not met:")
                if not ce_cross:
                    print(f"      - No crossover detected (PS didn't cross above VS)")
                if not is_bull:
                    print(f"      - Crossover candle not bullish (need green candle for CE entry)")
        print(f"\n{'='*80}\n")

if __name__ == "__main__":
    # Analyze why entry was not taken at 11:20 AM
    entry_time_1120 = datetime(2025, 11, 27, 11, 20, 0)
    print("="*80)
    print("ANALYZING WHY ENTRY WAS NOT TAKEN AT 11:20 AM")
    print("="*80)
    explain_entry("BANKNIFTY", entry_time_1120, "CE")
    
    # First analyze the crossover at 1:50 PM
    crossover_time = datetime(2025, 11, 27, 13, 50, 0)
    analyze_crossover_at_time("BANKNIFTY", crossover_time)
    
    # Then analyze the actual entry at 2:35 PM
    entry_time = datetime(2025, 11, 27, 14, 35, 0)
    explain_entry("BANKNIFTY", entry_time, "CE")

