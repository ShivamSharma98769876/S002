"""
Signal Diagnostic Tool
Helps diagnose why trades are not being identified for specific dates
"""

import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
from src.trading.rsi_agent import RSIStrategy, Segment, TradeSignal
from src.utils.logger import get_logger

logger = get_logger("diagnostic")


def diagnose_signals_for_date(
    df: pd.DataFrame,
    strategy: RSIStrategy,
    target_date: Optional[datetime] = None,
    verbose: bool = True
) -> Dict:
    """
    Diagnose why signals are not being generated for a specific date or all dates
    
    Args:
        df: DataFrame with OHLCV data
        strategy: RSIStrategy instance
        target_date: Specific date to diagnose (if None, diagnoses all dates)
        verbose: If True, print detailed diagnostics
    
    Returns:
        Dictionary with diagnostic information
    """
    results = {
        "total_candles": len(df),
        "signals_found": 0,
        "pe_signals": 0,
        "ce_signals": 0,
        "no_signals_reasons": {},
        "crossover_events": [],
        "candle_type_distribution": {"bullish": 0, "bearish": 0, "neutral": 0},
        "data_quality_issues": []
    }
    
    # Calculate indicators
    price_strength = strategy.calculate_price_strength(df)
    volume_strength = strategy.calculate_volume_strength(df)
    
    # Check data quality
    if df['volume'].isna().any():
        results["data_quality_issues"].append("Missing volume data")
    if df['volume'].eq(0).any():
        results["data_quality_issues"].append("Zero volume in some candles")
    if price_strength.isna().any():
        results["data_quality_issues"].append("Price Strength has NaN values")
    if volume_strength.isna().any():
        results["data_quality_issues"].append("Volume Strength has NaN values")
    
    # Start from index 6 (minimum for Volume Strength WMA)
    start_idx = max(6, strategy.rsi_period)
    
    for idx in range(start_idx, len(df)):
        candle = df.iloc[idx]
        timestamp = candle.name if hasattr(candle, 'name') else df.index[idx]
        
        # Filter by target date if specified
        if target_date:
            if isinstance(timestamp, pd.Timestamp):
                candle_date = timestamp.date()
            elif isinstance(timestamp, datetime):
                candle_date = timestamp.date()
            else:
                try:
                    candle_date = pd.Timestamp(timestamp).date()
                except:
                    continue
            
            if candle_date != target_date.date():
                continue
        
        # Check candle type
        is_bearish = strategy.is_bearish_candle(candle)
        is_bullish = strategy.is_bullish_candle(candle)
        
        if is_bullish:
            results["candle_type_distribution"]["bullish"] += 1
        elif is_bearish:
            results["candle_type_distribution"]["bearish"] += 1
        else:
            results["candle_type_distribution"]["neutral"] += 1
        
        # Check crossover
        if idx < 1:
            continue
        
        curr_ps = price_strength.iloc[idx]
        prev_ps = price_strength.iloc[idx - 1]
        curr_vs = volume_strength.iloc[idx]
        prev_vs = volume_strength.iloc[idx - 1]
        
        # Skip if NaN
        if pd.isna(curr_ps) or pd.isna(prev_ps) or pd.isna(curr_vs) or pd.isna(prev_vs):
            continue
        
        # Check for crossover
        pe_crossover = (prev_ps > prev_vs and curr_ps <= curr_vs)
        ce_crossover = (prev_ps < prev_vs and curr_ps >= curr_vs)
        
        if pe_crossover or ce_crossover:
            crossover_info = {
                "timestamp": timestamp,
                "type": "PE" if pe_crossover else "CE",
                "price_strength_prev": float(prev_ps),
                "price_strength_curr": float(curr_ps),
                "volume_strength_prev": float(prev_vs),
                "volume_strength_curr": float(curr_vs),
                "candle_type": "bearish" if is_bearish else ("bullish" if is_bullish else "neutral"),
                "crossover_occurred": True,
                "signal_generated": False
            }
            
            # Check if signal would be generated
            if pe_crossover and is_bearish:
                crossover_info["signal_generated"] = True
                results["pe_signals"] += 1
                results["signals_found"] += 1
            elif ce_crossover and is_bullish:
                crossover_info["signal_generated"] = True
                results["ce_signals"] += 1
                results["signals_found"] += 1
            else:
                # Crossover happened but wrong candle type
                reason = f"Crossover occurred but candle is {crossover_info['candle_type']} (need {'bearish' if pe_crossover else 'bullish'})"
                results["no_signals_reasons"][reason] = results["no_signals_reasons"].get(reason, 0) + 1
            
            results["crossover_events"].append(crossover_info)
        
        # Check why signal wasn't generated (if no crossover)
        if not pe_crossover and not ce_crossover:
            # Check if Price Strength and Volume Strength are close (near crossover)
            ps_vs_diff = abs(curr_ps - curr_vs)
            if ps_vs_diff < (curr_ps * 0.01):  # Within 1% of each other
                reason = "Price Strength and Volume Strength very close but no crossover"
                results["no_signals_reasons"][reason] = results["no_signals_reasons"].get(reason, 0) + 1
    
    if verbose:
        print("\n" + "="*80)
        print("SIGNAL DIAGNOSTIC REPORT")
        print("="*80)
        print(f"Total Candles Analyzed: {results['total_candles']}")
        print(f"Starting Index: {start_idx}")
        print(f"\nSignals Found: {results['signals_found']}")
        print(f"  - PE Signals: {results['pe_signals']}")
        print(f"  - CE Signals: {results['ce_signals']}")
        
        print(f"\nCandle Type Distribution:")
        for candle_type, count in results["candle_type_distribution"].items():
            print(f"  - {candle_type.capitalize()}: {count}")
        
        print(f"\nCrossover Events: {len(results['crossover_events'])}")
        for event in results["crossover_events"][:10]:  # Show first 10
            print(f"  - {event['timestamp']}: {event['type']} crossover, "
                  f"PS: {event['price_strength_prev']:.2f}→{event['price_strength_curr']:.2f}, "
                  f"VS: {event['volume_strength_prev']:.2f}→{event['volume_strength_curr']:.2f}, "
                  f"Candle: {event['candle_type']}, Signal: {'YES' if event['signal_generated'] else 'NO'}")
        
        if results["no_signals_reasons"]:
            print(f"\nReasons No Signals Generated:")
            for reason, count in results["no_signals_reasons"].items():
                print(f"  - {reason}: {count} times")
        
        if results["data_quality_issues"]:
            print(f"\nData Quality Issues:")
            for issue in results["data_quality_issues"]:
                print(f"  - {issue}")
        
        print("="*80 + "\n")
    
    return results

