"""
Export RSI, PS, VS indicators for TradingView comparison

This script exports calculated indicator values to CSV for easy comparison
with TradingView's "Hilega Milega" indicator.

Usage:
    python export_indicators.py --segment SENSEX --date 2025-12-05
    python export_indicators.py --segment NIFTY --date 2025-12-05 --interval 5minute
    python export_indicators.py --segment BANKNIFTY --date 2025-12-05 --output indicators.csv
"""

import sys
import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.trading.rsi_agent import RSIStrategy, Segment
from src.api.kite_client import KiteClient, get_kite_client
from src.api.live_data import fetch_recent_index_candles
from src.utils.logger import get_logger

logger = get_logger("export_indicators")

# Index instrument tokens from Zerodha
INDEX_INSTRUMENT_TOKENS = {
    "NIFTY": 256265,      # NSE:NIFTY 50
    "BANKNIFTY": 260105,  # NSE:NIFTY BANK
    "SENSEX": 265,        # BSE:SENSEX
}

INTERVAL_MAP = {
    "1minute": "minute",
    "3minute": "minute",
    "5minute": "minute",
    "15minute": "minute",
    "30minute": "minute",
    "1hour": "hour",
}


def fetch_data_for_date(segment: str, target_date: datetime, interval: str = "5minute"):
    """Fetch historical candle data for a specific date"""
    kite = get_kite_client()
    
    if not kite or not kite.is_authenticated():
        logger.error("❌ Kite API not authenticated. Please authenticate first.")
        return None
    
    instrument_token = INDEX_INSTRUMENT_TOKENS.get(segment.upper())
    if not instrument_token:
        logger.error(f"❌ Unknown segment: {segment}")
        return None
    
    # Calculate date range (target date + 1 day for safety)
    from_date = target_date.replace(hour=9, minute=15, second=0, microsecond=0)
    to_date = (target_date + timedelta(days=1)).replace(hour=15, minute=30, second=0, microsecond=0)
    
    logger.info(f"📊 Fetching data for {segment} from {from_date} to {to_date}")
    logger.info(f"   Interval: {interval}")
    
    try:
        # Map interval
        interval_type = INTERVAL_MAP.get(interval, "minute")
        interval_value = int(interval.replace("minute", "").replace("hour", ""))
        
        # Fetch candles
        candles = kite.kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
            continuous=False,
            oi=False
        )
        
        if not candles:
            logger.warning(f"⚠️ No candles returned from API")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(candles)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df.columns = [col.lower() for col in df.columns]
        
        # Filter to target date only
        df = df[df.index.date == target_date.date()]
        
        logger.info(f"✅ Fetched {len(df)} candles for {target_date.date()}")
        return df
        
    except Exception as e:
        logger.error(f"❌ Error fetching data: {e}", exc_info=True)
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Export RSI, PS, VS indicators for TradingView comparison"
    )
    parser.add_argument(
        "--segment",
        type=str,
        default="SENSEX",
        choices=["NIFTY", "BANKNIFTY", "SENSEX"],
        help="Trading segment (default: SENSEX)"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date in YYYY-MM-DD format (default: today)"
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="5minute",
        choices=["1minute", "3minute", "5minute", "15minute", "30minute", "1hour"],
        help="Candle interval (default: 5minute)"
    )
    parser.add_argument(
        "--rsi-period",
        type=int,
        default=9,
        help="RSI period (default: 9)"
    )
    parser.add_argument(
        "--ps-ema",
        type=int,
        default=3,
        help="Price Strength EMA period (default: 3)"
    )
    parser.add_argument(
        "--vs-wma",
        type=int,
        default=21,
        help="Volume Strength WMA period (default: 21)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV file path (default: indicators_<segment>_<date>.csv)"
    )
    
    args = parser.parse_args()
    
    # Parse date
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Fetch data
    df = fetch_data_for_date(args.segment, target_date, args.interval)
    if df is None or len(df) == 0:
        logger.error("❌ No data available. Exiting.")
        return 1
    
    # Initialize strategy
    segment_enum = Segment[args.segment.upper()]
    strategy = RSIStrategy(
        segment=segment_enum,
        rsi_period=args.rsi_period,
        price_strength_ema=args.ps_ema,
        volume_strength_wma=args.vs_wma,
        timeframe=args.interval
    )
    
    logger.info(f"✅ Strategy initialized: {args.segment}")
    logger.info(f"   RSI Period: {args.rsi_period}")
    logger.info(f"   PS EMA: {args.ps_ema}")
    logger.info(f"   VS WMA: {args.vs_wma}")
    
    # Determine output path
    if args.output:
        output_path = args.output
    else:
        date_str = target_date.strftime("%Y%m%d")
        output_path = f"indicators_{args.segment}_{date_str}.csv"
    
    # Export indicators
    logger.info(f"📊 Exporting indicators to {output_path}...")
    export_df = strategy.export_indicators_for_comparison(df, output_path=output_path)
    
    if len(export_df) > 0:
        logger.info(f"\n✅ Export complete!")
        logger.info(f"   Total rows: {len(export_df)}")
        logger.info(f"   Date range: {export_df['Timestamp'].min()} to {export_df['Timestamp'].max()}")
        logger.info(f"\n📋 Sample data (last 5 rows):")
        print(export_df[['Timestamp', 'Close', 'RSI', 'PS', 'VS', 'PS_VS_Diff', 'Crossover_Type']].tail().to_string(index=False))
        logger.info(f"\n💡 Next steps:")
        logger.info(f"   1. Open {output_path} in Excel/Google Sheets")
        logger.info(f"   2. Compare PS and VS values with TradingView")
        logger.info(f"   3. Verify RSI values match TradingView RSI(9)")
        logger.info(f"   4. Check crossover events match TradingView indicator")
        return 0
    else:
        logger.error("❌ No data exported. Check if there's enough historical data.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

