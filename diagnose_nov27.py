"""
Diagnostic Script for Trading Signals
Run this script to diagnose why trades were not identified for a specific date

Usage:
    python diagnose_nov27.py
    python diagnose_nov27.py --date 2024-11-27 --segment NIFTY --interval 5minute
    python diagnose_nov27.py --date 2024-11-27 --segment BANKNIFTY
"""

import sys
import argparse
import json
import os
from datetime import datetime, timedelta
import pandas as pd
from kiteconnect import KiteConnect
from src.trading.rsi_agent import RSIStrategy, Segment
from src.utils.signal_diagnostic import diagnose_signals_for_date
from src.utils.logger import get_logger
from src.HLML import compute_pvs

# Try to import yfinance for Yahoo Finance data
try:
    import yfinance as yf
except ImportError:
    yf = None

logger = get_logger("diagnostic_script")

# Index instrument tokens from Zerodha
INDEX_INSTRUMENT_TOKENS = {
    "NIFTY": 256265,      # NSE:NIFTY 50
    "BANKNIFTY": 260105,  # NSE:NIFTY BANK
    "SENSEX": 265,        # BSE:SENSEX
}

# Map segments to Yahoo Finance symbols
YAHOO_SYMBOLS = {
    "NIFTY": "^NSEI",      # NIFTY 50
    "BANKNIFTY": "^NSEBANK",  # NIFTY BANK
    "SENSEX": "^BSESN",    # SENSEX
}


def get_futures_instrument_token(kite, segment, from_date, to_date):
    """
    Get instrument token for futures contract of the given segment
    
    Args:
        kite: KiteConnect instance
        segment: NIFTY, BANKNIFTY, or SENSEX
        from_date: Start date (to find relevant expiry)
        to_date: End date (to find relevant expiry)
    
    Returns:
        Instrument token for futures contract or None
    """
    try:
        # Get instruments list from NFO exchange
        instruments = kite.instruments("NFO")
        
        # Map segment to base name
        segment_map = {
            "NIFTY": "NIFTY",
            "BANKNIFTY": "BANKNIFTY",
            "SENSEX": "SENSEX"
        }
        base_name = segment_map.get(segment.upper())
        if not base_name:
            logger.warning(f"Unknown segment for futures: {segment}")
            return None
        
        # Filter for futures contracts (instrument_type == 'FUT')
        futures = [
            inst for inst in instruments
            if inst['name'] == base_name and
            inst['instrument_type'] == 'FUT' and
            inst['segment'] == 'NFO'
        ]
        
        if not futures:
            logger.warning(f"No futures contracts found for {base_name}")
            return None
        
        # Filter by expiry - find contracts that were active during the date range
        # Use contracts that expire after from_date and ideally cover the date range
        # Calculate middle date properly (avoid timedelta division issue)
        days_diff = (to_date - from_date).days
        if days_diff > 0:
            target_date = from_date + timedelta(days=int(days_diff / 2))  # Middle of date range
        else:
            target_date = from_date
        
        # Sort by expiry and find the contract that was most active during the period
        futures.sort(key=lambda x: x['expiry'])
        
        # Find the contract that covers the date range
        active_futures = [
            inst for inst in futures
            if inst['expiry'].date() >= from_date.date()
        ]
        
        if active_futures:
            # Use the nearest expiry that covers the date range
            instrument = active_futures[0]
            token = instrument['instrument_token']
            logger.info(f"Found futures contract for {base_name}: {instrument['tradingsymbol']}, "
                       f"expiry: {instrument['expiry'].date()}, token: {token}")
            return token
        else:
            # If no future covers the range, use nearest expiry
            if futures:
                instrument = futures[0]
                token = instrument['instrument_token']
                logger.warning(f"Using nearest futures contract for {base_name}: "
                             f"{instrument['tradingsymbol']}, expiry: {instrument['expiry'].date()}")
                return token
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting futures instrument token: {e}")
        return None


def fetch_volume_from_yahoo(segment, from_date, to_date, interval):
    """
    Fetch volume data from Yahoo Finance for the given segment
    
    Args:
        segment: NIFTY, BANKNIFTY, or SENSEX
        from_date: Start date
        to_date: End date
        interval: Time interval
    
    Returns:
        pandas Series with volume data indexed by timestamp, or None if failed
    """
    if yf is None:
        logger.warning("yfinance library not installed. Please install: pip install yfinance")
        return None
    
    try:
        # Get Yahoo Finance symbol for the segment
        yahoo_symbol = YAHOO_SYMBOLS.get(segment.upper())
        if not yahoo_symbol:
            logger.warning(f"Unknown segment for Yahoo Finance: {segment}")
            return None
        
        logger.info(f"Fetching volume data from Yahoo Finance for {segment} (symbol: {yahoo_symbol})")
        
        # Convert interval to yfinance format
        interval_map = {
            "1minute": "1m",
            "3minute": "3m",
            "5minute": "5m",
            "15minute": "15m",
            "30minute": "30m",
            "1hour": "1h",
            "1day": "1d",
        }
        
        yf_interval = interval_map.get(interval.lower(), "5m")
        
        # For intraday data, yfinance requires period instead of start/end
        is_intraday = yf_interval in ["1m", "3m", "5m", "15m", "30m", "1h"]
        
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
            
            logger.info(f"Fetching intraday volume data with period: {period}, interval: {yf_interval}")
            df_volume = ticker.history(period=period, interval=yf_interval)
            
            # Filter by date range
            if not df_volume.empty:
                # Remove timezone from index if present
                if df_volume.index.tz is not None:
                    df_volume.index = df_volume.index.tz_localize(None)
                
                # Build inclusive date range
                range_start = from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
                range_end = to_date + timedelta(days=1)
                range_end = range_end.replace(tzinfo=None) if range_end.tzinfo else range_end
                df_volume = df_volume[(df_volume.index >= range_start) & (df_volume.index < range_end)]
        else:
            # For daily data, use start and end
            from_date_naive = from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
            to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date
            end_inclusive = to_date_naive + timedelta(days=1)
            df_volume = ticker.history(start=from_date_naive, end=end_inclusive, interval=yf_interval)
            
            # Remove timezone from index if present
            if not df_volume.empty and df_volume.index.tz is not None:
                df_volume.index = df_volume.index.tz_localize(None)
        
        if df_volume.empty:
            logger.warning(f"No volume data returned from Yahoo Finance for {yahoo_symbol}")
            return None
        
        # Get volume column (handle both capitalized and lowercase)
        if "Volume" in df_volume.columns:
            volume_series = df_volume["Volume"]
        elif "volume" in df_volume.columns:
            volume_series = df_volume["volume"]
        else:
            logger.warning("Volume column not found in Yahoo Finance data")
            return None
        
        # Ensure volume is a Series with datetime index
        if not isinstance(volume_series, pd.Series):
            volume_series = pd.Series(volume_series.values, index=df_volume.index)
        
        logger.info(f"✅ Fetched volume data from Yahoo Finance: {len(volume_series)} candles")
        return volume_series
        
    except Exception as e:
        logger.error(f"Error fetching volume from Yahoo Finance: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_volume_from_futures(kite, segment, from_date, to_date, interval):
    """
    Fetch volume data from futures contract for the given segment
    
    Args:
        kite: KiteConnect instance
        segment: NIFTY, BANKNIFTY, or SENSEX
        from_date: Start date
        to_date: End date
        interval: Time interval
    
    Returns:
        pandas Series with volume data indexed by timestamp, or None if failed
    """
    try:
        # Get futures instrument token
        futures_token = get_futures_instrument_token(kite, segment, from_date, to_date)
        
        if not futures_token:
            logger.warning(f"Could not find futures contract for {segment}")
            return None
        
        # Fetch historical data from futures contract
        candles = kite.historical_data(
            instrument_token=futures_token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
            continuous=False,
            oi=False
        )
        
        if not candles:
            logger.warning(f"No volume data returned from futures contract for {segment}")
            return None
        
        # Convert to DataFrame
        df_volume = pd.DataFrame(candles)
        
        if df_volume.empty or "date" not in df_volume.columns:
            return None
        
        # Convert date to datetime and set as index
        df_volume["date"] = pd.to_datetime(df_volume["date"])
        df_volume.set_index("date", inplace=True)
        
        # Get volume column (handle both capitalized and lowercase)
        if "Volume" in df_volume.columns:
            volume_series = df_volume["Volume"]
        elif "volume" in df_volume.columns:
            volume_series = df_volume["volume"]
        else:
            logger.warning("Volume column not found in futures data")
            return None
        
        logger.info(f"✅ Fetched volume data from futures: {len(volume_series)} candles")
        return volume_series
        
    except Exception as e:
        logger.error(f"Error fetching volume from futures: {e}")
        return None


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Diagnose why trades were not identified for a specific date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python diagnose_nov27.py
  python diagnose_nov27.py --date 2024-11-27
  python diagnose_nov27.py --date 2024-11-27 --segment BANKNIFTY --interval 5minute
        """
    )
    
    parser.add_argument(
        "--date",
        type=str,
        default="2024-11-27",
        help="Target date to diagnose (YYYY-MM-DD). Default: 2024-11-27"
    )
    
    parser.add_argument(
        "--segment",
        type=str,
        choices=["NIFTY", "BANKNIFTY", "SENSEX"],
        default="NIFTY",
        help="Trading segment. Default: NIFTY"
    )
    
    parser.add_argument(
        "--interval",
        type=str,
        choices=["3minute", "5minute", "15minute", "30minute", "1hour"],
        default="5minute",
        help="Time interval for candles. Default: 5minute"
    )
    
    parser.add_argument(
        "--rsi-period",
        type=int,
        default=9,
        help="RSI period. Default: 9"
    )
    
    return parser.parse_args()


def main():
    """Main diagnostic function"""
    
    # Parse arguments
    args = parse_arguments()
    
    # Parse target date
    try:
        TARGET_DATE = datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"❌ ERROR: Invalid date format: {args.date}")
        print("Please use format: YYYY-MM-DD (e.g., 2024-11-27)")
        return
    
    SEGMENT = args.segment
    TIME_INTERVAL = args.interval
    RSI_PERIOD = args.rsi_period
    
    print("="*80)
    print("TRADING SIGNAL DIAGNOSTIC TOOL")
    print("="*80)
    print(f"Target Date: {TARGET_DATE.date()}")
    print(f"Segment: {SEGMENT}")
    print(f"Time Interval: {TIME_INTERVAL}")
    print(f"RSI Period: {RSI_PERIOD}")
    print("="*80)
    print()
    
    # Load config from config.json
    config_path = os.path.join(os.path.dirname(__file__), "config", "config.json")
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        api_key = config.get("api_key")
        access_token = config.get("access_token")
        
        if not api_key:
            print("❌ ERROR: api_key not found in config.json")
            return
        
        if not access_token:
            print("❌ ERROR: access_token not found in config.json")
            print("Please add your access_token to config/config.json")
            return
        
        print("✅ Config loaded from config.json")
        print(f"   API Key: {api_key[:8]}...")
        print(f"   Access Token: {access_token[:8]}...")
        print()
    except FileNotFoundError:
        print(f"❌ ERROR: config.json not found at {config_path}")
        print("Please ensure config/config.json exists with api_key and access_token")
        return
    except json.JSONDecodeError as e:
        print(f"❌ ERROR: Invalid JSON in config.json: {e}")
        return
    except Exception as e:
        print(f"❌ ERROR: Failed to load config: {e}")
        return
    
    # Initialize Kite Connect directly
    try:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        
        # Verify authentication by making a lightweight API call
        try:
            profile = kite.profile()
            print("✅ Kite Connect authenticated successfully")
            print(f"   User: {profile.get('user_name', 'N/A')}")
            print()
        except Exception as e:
            print(f"❌ ERROR: Access token validation failed: {e}")
            print("Please check if your access_token in config.json is valid and not expired")
            print("You may need to generate a new access token through the web interface")
            return
        
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize Kite Connect: {e}")
        return
    
    # Fetch data from Kite Connect
    # We need some historical data before target date for indicators to calculate
    # Use target date to calculate date range dynamically
    from_date = TARGET_DATE - timedelta(days=2)  # Start 2 days before target
    to_date = TARGET_DATE + timedelta(days=1)   # End 1 day after target
    
    print(f"📊 Fetching historical data from Kite Connect...")
    print(f"   Date range: {from_date.date()} to {to_date.date()}")
    print(f"   Segment: {SEGMENT}")
    print(f"   Interval: {TIME_INTERVAL}")
    print()
    
    try:
        # Get instrument token for the segment
        seg = SEGMENT.upper()
        instrument_token = INDEX_INSTRUMENT_TOKENS.get(seg)
        
        if instrument_token is None:
            print(f"❌ ERROR: Unsupported segment: {SEGMENT}")
            print(f"   Supported segments: {list(INDEX_INSTRUMENT_TOKENS.keys())}")
            return
        
        print(f"   Instrument Token: {instrument_token}")
        
        # Fetch historical data from Kite Connect
        # Note: Kite Connect historical_data API has limitations:
        # - For intraday data: max 60 days lookback
        # - For daily data: max 365 days lookback
        candles = kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=TIME_INTERVAL,
            continuous=False,
            oi=False
        )
        
        if not candles:
            print("❌ ERROR: No data returned from Kite Connect!")
            print("Please check:")
            print("  1. The date range is valid (not too far in the past)")
            print("  2. The segment name is correct")
            print("  3. Historical data is available for this period")
            print("  4. Your access token has permission to access historical data")
            return
        
        # Convert to DataFrame
        df = pd.DataFrame(candles)
        
        if df.empty:
            print("❌ ERROR: Empty DataFrame returned!")
            return
        
        # Check if 'date' column exists
        if "date" not in df.columns:
            print("❌ ERROR: 'date' column not found in response!")
            print(f"   Available columns: {df.columns.tolist()}")
            return
        
        # Convert date to datetime and set as index
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        
        # Rename columns to lowercase (Kite returns capitalized)
        column_mapping = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        }
        df.rename(columns=column_mapping, inplace=True)
        
        # Ensure we have required columns
        required_columns = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_columns):
            print(f"❌ ERROR: Missing required columns!")
            print(f"   Required: {required_columns}")
            print(f"   Available: {df.columns.tolist()}")
            return
        
        # Handle missing or zero volume data
        # Check configuration for volume indicator source
        volume_config = config.get("volume_indicator", {})
        volume_source = volume_config.get("source", "yahoo")  # Default to Yahoo Finance
        use_nearest_expiry = volume_config.get("use_nearest_expiry", True)
        fallback_to_proxy = volume_config.get("fallback_to_proxy", True)
        
        volume_fetched = False
        
        # Check if volume is missing or all zeros
        if 'volume' not in df.columns or df['volume'].isna().all() or (df['volume'] == 0).all():
            print("⚠️  WARNING: Volume data not available from index data")
            print("   Indices don't have volume data in Kite Connect")
            
            # Try to fetch volume from configured source
            if volume_source == "yahoo":
                print(f"   Attempting to fetch volume from Yahoo Finance...")
                yahoo_volume = fetch_volume_from_yahoo(
                    SEGMENT, from_date, to_date, TIME_INTERVAL
                )
                
                if yahoo_volume is not None and not yahoo_volume.empty:
                    # Align Yahoo volume with index data by timestamp
                    try:
                        # Convert Yahoo volume Series to DataFrame with date column
                        df_volume_temp = pd.DataFrame({
                            'date': yahoo_volume.index,
                            'volume': yahoo_volume.values
                        })
                        
                        # Convert main df to have date column
                        df_temp = df.reset_index()
                        if 'date' not in df_temp.columns:
                            # If index name is different, rename it
                            df_temp = df_temp.rename(columns={df.index.name or 'index': 'date'})
                        
                        # Use merge_asof for time-based nearest neighbor matching
                        df_merged = pd.merge_asof(
                            df_temp.sort_values('date'),
                            df_volume_temp.sort_values('date'),
                            on='date',
                            direction='nearest',
                            tolerance=pd.Timedelta(minutes=5)
                        )
                        
                        # Set index back and extract volume
                        df_merged = df_merged.set_index('date')
                        df['volume'] = df_merged['volume']
                        
                    except Exception as e:
                        logger.warning(f"Error aligning volume with merge_asof: {e}, using simple reindex")
                        # Fallback: simple reindex (may have NaN values that we'll fill)
                        df['volume'] = yahoo_volume.reindex(df.index)
                    
                    # Fill any remaining NaN values
                    if df['volume'].isna().any():
                        df['volume'] = df['volume'].ffill().bfill()
                        if df['volume'].isna().any():
                            df['volume'] = df['volume'].fillna(df['volume'].median())
                    
                    # Ensure no zero values
                    df.loc[df['volume'] == 0, 'volume'] = df['volume'].replace(0, df['volume'].median() * 0.1)
                    
                    print("   ✅ Successfully fetched volume from Yahoo Finance")
                    print(f"   Volume range: {df['volume'].min():.0f} to {df['volume'].max():.0f}")
                    volume_fetched = True
                else:
                    print("   ⚠️  Could not fetch volume from Yahoo Finance")
            
            elif volume_source == "futures":
                print(f"   Attempting to fetch volume from futures contracts...")
                futures_volume = fetch_volume_from_futures(
                    kite, SEGMENT, from_date, to_date, TIME_INTERVAL
                )
                
                if futures_volume is not None and not futures_volume.empty:
                    # Align futures volume with index data by timestamp
                    # Use merge_asof for time-based alignment (works with all pandas versions)
                    try:
                        # Convert futures volume Series to DataFrame with date column
                        df_volume_temp = pd.DataFrame({
                            'date': futures_volume.index,
                            'volume': futures_volume.values
                        })
                        
                        # Convert main df to have date column
                        df_temp = df.reset_index()
                        if 'date' not in df_temp.columns:
                            # If index name is different, rename it
                            df_temp = df_temp.rename(columns={df.index.name or 'index': 'date'})
                        
                        # Use merge_asof for time-based nearest neighbor matching
                        df_merged = pd.merge_asof(
                            df_temp.sort_values('date'),
                            df_volume_temp.sort_values('date'),
                            on='date',
                            direction='nearest',
                            tolerance=pd.Timedelta(minutes=5)
                        )
                        
                        # Set index back and extract volume
                        df_merged = df_merged.set_index('date')
                        df['volume'] = df_merged['volume']
                        
                    except Exception as e:
                        logger.warning(f"Error aligning volume with merge_asof: {e}, using simple reindex")
                        # Fallback: simple reindex (may have NaN values that we'll fill)
                        df['volume'] = futures_volume.reindex(df.index)
                    
                    # Fill any remaining NaN values
                    if df['volume'].isna().any():
                        df['volume'] = df['volume'].ffill().bfill()
                        if df['volume'].isna().any():
                            df['volume'] = df['volume'].fillna(df['volume'].median())
                    
                    # Ensure no zero values
                    df.loc[df['volume'] == 0, 'volume'] = df['volume'].replace(0, df['volume'].median() * 0.1)
                    
                    print("   ✅ Successfully fetched volume from futures contracts")
                    print(f"   Volume range: {df['volume'].min():.0f} to {df['volume'].max():.0f}")
                    volume_fetched = True
                else:
                    print("   ⚠️  Could not fetch volume from futures contracts")
            
            # Fallback to futures if Yahoo failed and configured
            if not volume_fetched and volume_config.get("fallback_to_futures", True) and volume_source == "yahoo":
                print(f"   Attempting to fetch volume from futures contracts as fallback...")
                futures_volume = fetch_volume_from_futures(
                    kite, SEGMENT, from_date, to_date, TIME_INTERVAL
                )
                
                if futures_volume is not None and not futures_volume.empty:
                    # Align futures volume with index data by timestamp
                    try:
                        # Convert futures volume Series to DataFrame with date column
                        df_volume_temp = pd.DataFrame({
                            'date': futures_volume.index,
                            'volume': futures_volume.values
                        })
                        
                        # Convert main df to have date column
                        df_temp = df.reset_index()
                        if 'date' not in df_temp.columns:
                            # If index name is different, rename it
                            df_temp = df_temp.rename(columns={df.index.name or 'index': 'date'})
                        
                        # Use merge_asof for time-based nearest neighbor matching
                        df_merged = pd.merge_asof(
                            df_temp.sort_values('date'),
                            df_volume_temp.sort_values('date'),
                            on='date',
                            direction='nearest',
                            tolerance=pd.Timedelta(minutes=5)
                        )
                        
                        # Set index back and extract volume
                        df_merged = df_merged.set_index('date')
                        df['volume'] = df_merged['volume']
                        
                    except Exception as e:
                        logger.warning(f"Error aligning volume with merge_asof: {e}, using simple reindex")
                        # Fallback: simple reindex (may have NaN values that we'll fill)
                        df['volume'] = futures_volume.reindex(df.index)
                    
                    # Fill any remaining NaN values
                    if df['volume'].isna().any():
                        df['volume'] = df['volume'].ffill().bfill()
                        if df['volume'].isna().any():
                            df['volume'] = df['volume'].fillna(df['volume'].median())
                    
                    # Ensure no zero values
                    df.loc[df['volume'] == 0, 'volume'] = df['volume'].replace(0, df['volume'].median() * 0.1)
                    
                    print("   ✅ Successfully fetched volume from futures contracts (fallback)")
                    print(f"   Volume range: {df['volume'].min():.0f} to {df['volume'].max():.0f}")
                    volume_fetched = True
                else:
                    print("   ⚠️  Could not fetch volume from futures contracts (fallback)")
            
            # Fallback to proxy volume if configured or if all other sources failed
            if not volume_fetched and fallback_to_proxy:
                print("   Using price-based proxy volume as fallback...")
                
                # Calculate proxy volume based on price movement and volatility
                df['price_range'] = df['high'] - df['low']
                df['price_change'] = abs(df['close'] - df['open'])
                df['volatility'] = df['price_range'] / df['close']  # Normalized volatility
                
                # Proxy volume = (price_range * price_change * volatility) * 1000000
                df['volume'] = (df['price_range'] * df['price_change'] * df['volatility'] * 1000000).fillna(0)
                df['volume'] = df['volume'].replace(0, 1)
                
                # Normalize to reasonable range
                volume_mean = df['volume'].mean()
                if volume_mean > 0:
                    df['volume'] = (df['volume'] / volume_mean) * 1000000
                
                print("   ✅ Generated proxy volume based on price movement and volatility")
                print(f"   Volume range: {df['volume'].min():.0f} to {df['volume'].max():.0f}")
                
                # Clean up temporary columns
                df.drop(columns=['price_range', 'price_change', 'volatility'], inplace=True, errors='ignore')
            elif not volume_fetched:
                print("   ❌ ERROR: Volume data required but not available and fallback disabled")
                print("   Please enable 'fallback_to_proxy' in config.json or ensure futures data is available")
                return
        else:
            # Check for zero or very low volume values
            zero_volume_count = (df['volume'] == 0).sum()
            if zero_volume_count > 0:
                print(f"⚠️  WARNING: {zero_volume_count} candles have zero volume")
                # Replace zero volume with a small value to avoid calculation issues
                df.loc[df['volume'] == 0, 'volume'] = df['volume'].replace(0, df['volume'].median() * 0.1)
                print("   ✅ Replaced zero volume with small values based on median")
            
            # Check for NaN values
            nan_volume_count = df['volume'].isna().sum()
            if nan_volume_count > 0:
                print(f"⚠️  WARNING: {nan_volume_count} candles have NaN volume")
                # Fill NaN with forward fill, then backward fill, then median
                df['volume'] = df['volume'].ffill().bfill()
                if df['volume'].isna().any():
                    df['volume'] = df['volume'].fillna(df['volume'].median())
                print("   ✅ Filled NaN volume values")
        
        print(f"✅ Fetched {len(df)} candles from Kite Connect")
        print(f"   Date range: {df.index[0]} to {df.index[-1]}")
        print()
        
        # Check if we have data for the target date
        target_date_data = df[df.index.date == TARGET_DATE.date()]
        if target_date_data.empty:
            print(f"⚠️  WARNING: No data found for {TARGET_DATE.date()}")
            print(f"   Available dates: {df.index.date.min()} to {df.index.date.max()}")
            print()
            print("Running diagnostic on all available dates instead...")
            print()
            target_date = None
        else:
            print(f"✅ Found {len(target_date_data)} candles for {TARGET_DATE.date()}")
            print()
            target_date = TARGET_DATE
        
    except Exception as e:
        print(f"❌ ERROR: Failed to fetch data from Kite Connect: {e}")
        import traceback
        traceback.print_exc()
        print()
        print("Troubleshooting tips:")
        print("  1. Check if your access token is valid and not expired")
        print("  2. Verify the date range is within Kite's limits (60 days for intraday)")
        print("  3. Ensure the segment and interval are correct")
        print("  4. Check your internet connection and Kite API status")
        return
    
    # Check if we should use HLML.py for 5-minute timeframe
    use_hlml = (TIME_INTERVAL.lower() == "5minute")
    
    if use_hlml:
        print("📊 Using HLML.py for signal generation (5-minute timeframe)")
        print()
        
        # Compute HLML indicators
        try:
            df_hlml = compute_pvs(df, rsi_len=RSI_PERIOD, ema_len=3, wma_len=6)
            
            # Filter for target date if specified
            if target_date:
                df_hlml_filtered = df_hlml[df_hlml.index.date == target_date.date()]
            else:
                df_hlml_filtered = df_hlml
            
            if df_hlml_filtered.empty:
                print(f"⚠️  No data available for analysis")
                return
            
            # Analyze HLML signals
            print("="*80)
            print("HLML SIGNAL ANALYSIS")
            print("="*80)
            print(f"Total candles analyzed: {len(df_hlml_filtered)}")
            print()
            
            # Count signals
            buy_signals = df_hlml_filtered['buy_signal'].sum()
            sell_signals = df_hlml_filtered['sell_signal'].sum()
            
            print(f"📈 Buy Signals (PE): {buy_signals}")
            print(f"📉 Sell Signals (CE): {sell_signals}")
            print()
            
            # Filter signals by candle type (as per strategy requirements)
            # PE Buy: buy_signal + red candle
            # CE Buy: sell_signal + green candle
            pe_signals_valid = 0
            ce_signals_valid = 0
            
            buy_rows = df_hlml_filtered[df_hlml_filtered['buy_signal']]
            sell_rows = df_hlml_filtered[df_hlml_filtered['sell_signal']]
            
            # Show signal details
            if buy_signals > 0:
                print("BUY Signals (PE - Bearish setup):")
                for idx, row in buy_rows.iterrows():
                    is_red = row['close'] < row['open']
                    is_valid = is_red
                    status = "✅ VALID" if is_valid else "❌ INVALID (needs red candle)"
                    if is_valid:
                        pe_signals_valid += 1
                    print(f"  - {idx}: {status}")
                    print(f"    RSI={row['rsi']:.2f}, PS={row['price_strength']:.2f}, "
                          f"VS={row['volume_strength']:.2f}, Zone={row['zone']}, "
                          f"Close={row['close']:.2f}, Candle={'Red' if is_red else 'Green'}")
                print()
            
            if sell_signals > 0:
                print("SELL Signals (CE - Bullish setup):")
                for idx, row in sell_rows.iterrows():
                    is_green = row['close'] > row['open']
                    is_valid = is_green
                    status = "✅ VALID" if is_valid else "❌ INVALID (needs green candle)"
                    if is_valid:
                        ce_signals_valid += 1
                    print(f"  - {idx}: {status}")
                    print(f"    RSI={row['rsi']:.2f}, PS={row['price_strength']:.2f}, "
                          f"VS={row['volume_strength']:.2f}, Zone={row['zone']}, "
                          f"Close={row['close']:.2f}, Candle={'Green' if is_green else 'Red'}")
                print()
            
            # Summary of valid signals
            print("="*80)
            print("HLML SIGNAL SUMMARY")
            print("="*80)
            print(f"Total Buy signals (PE): {buy_signals}")
            print(f"  Valid (with red candle): {pe_signals_valid}")
            print(f"  Invalid (wrong candle type): {buy_signals - pe_signals_valid}")
            print()
            print(f"Total Sell signals (CE): {sell_signals}")
            print(f"  Valid (with green candle): {ce_signals_valid}")
            print(f"  Invalid (wrong candle type): {sell_signals - ce_signals_valid}")
            print()
            print(f"✅ Total Valid Trading Signals: {pe_signals_valid + ce_signals_valid}")
            print("="*80)
            print()
            
            # Show why signals weren't generated (if any)
            if buy_signals == 0 and sell_signals == 0:
                print("⚠️  No signals generated by HLML")
                print()
                print("Checking conditions:")
                
                # Check if Price Strength and Volume Strength crossed RSI
                price_cross_down = (df_hlml_filtered['price_strength'].shift(1) > df_hlml_filtered['rsi'].shift(1)) & \
                                  (df_hlml_filtered['price_strength'] <= df_hlml_filtered['rsi'])
                vol_cross_down = (df_hlml_filtered['volume_strength'].shift(1) > df_hlml_filtered['rsi'].shift(1)) & \
                                (df_hlml_filtered['volume_strength'] <= df_hlml_filtered['rsi'])
                price_cross_up = (df_hlml_filtered['price_strength'].shift(1) < df_hlml_filtered['rsi'].shift(1)) & \
                               (df_hlml_filtered['price_strength'] >= df_hlml_filtered['rsi'])
                vol_cross_up = (df_hlml_filtered['volume_strength'].shift(1) < df_hlml_filtered['rsi'].shift(1)) & \
                              (df_hlml_filtered['volume_strength'] >= df_hlml_filtered['rsi'])
                
                price_cross_down_count = price_cross_down.sum()
                price_cross_up_count = price_cross_up.sum()
                vol_cross_down_count = vol_cross_down.sum()
                vol_cross_up_count = vol_cross_up.sum()
                both_cross_down = (price_cross_down & vol_cross_down).sum()
                both_cross_up = (price_cross_up & vol_cross_up).sum()
                
                print(f"  Price Strength crossed DOWN RSI: {price_cross_down_count} times")
                print(f"  Price Strength crossed UP RSI: {price_cross_up_count} times")
                print(f"  Volume Strength crossed DOWN RSI: {vol_cross_down_count} times")
                print(f"  Volume Strength crossed UP RSI: {vol_cross_up_count} times")
                print(f"  Both crossed DOWN simultaneously (Buy signal): {both_cross_down} times")
                print(f"  Both crossed UP simultaneously (Sell signal): {both_cross_up} times")
                print()
                
                # Show sample values for debugging
                if len(df_hlml_filtered) > 0:
                    sample = df_hlml_filtered.iloc[-5:]  # Last 5 candles
                    print("Sample values (last 5 candles):")
                    for idx, row in sample.iterrows():
                        print(f"  {idx}: RSI={row['rsi']:.2f}, PS={row['price_strength']:.2f}, "
                              f"VS={row['volume_strength']:.2f}, Zone={row['zone']}")
                print()
            
            print("="*80)
            print()
            
            # Also run the original diagnostic for comparison
            print("📊 Running original strategy diagnostic for comparison...")
            print()
        
        except Exception as e:
            print(f"❌ ERROR: Failed to compute HLML signals: {e}")
            import traceback
            traceback.print_exc()
            print()
            print("Falling back to original strategy diagnostic...")
            print()
            use_hlml = False
    
    # Initialize strategy for original diagnostic
    try:
        segment_enum = Segment[SEGMENT.upper()]
        strategy = RSIStrategy(
            segment=segment_enum,
            rsi_period=RSI_PERIOD,
            timeframe=TIME_INTERVAL
        )
        if not use_hlml:
            print(f"✅ Strategy initialized: {SEGMENT} with RSI period {RSI_PERIOD}")
            print()
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize strategy: {e}")
        return
    
    # Run diagnostic (original strategy)
    if not use_hlml:
        print("🔍 Running diagnostic analysis...")
        print()
    
    try:
        results = diagnose_signals_for_date(
            df=df,
            strategy=strategy,
            target_date=target_date,
            verbose=True
        )
        
        # Additional analysis
        print("\n" + "="*80)
        print("ADDITIONAL ANALYSIS")
        print("="*80)
        
        # Check data quality for target date
        if target_date:
            target_df = df[df.index.date == target_date.date()]
            if not target_df.empty:
                print(f"\nData Quality for {target_date.date()}:")
                print(f"  Total candles: {len(target_df)}")
                print(f"  Missing volume: {target_df['volume'].isna().sum()}")
                print(f"  Zero volume: {(target_df['volume'] == 0).sum()}")
                print(f"  Bullish candles: {(target_df['close'] > target_df['open']).sum()}")
                print(f"  Bearish candles: {(target_df['close'] < target_df['open']).sum()}")
                print(f"  Neutral candles: {(target_df['close'] == target_df['open']).sum()}")
        
        # Summary
        print(f"\n📊 SUMMARY:")
        print(f"  Total signals found: {results['signals_found']}")
        print(f"  PE signals: {results['pe_signals']}")
        print(f"  CE signals: {results['ce_signals']}")
        print(f"  Crossover events: {len(results['crossover_events'])}")
        
        if results['signals_found'] == 0:
            print(f"\n⚠️  NO SIGNALS GENERATED!")
            print(f"\nPossible reasons:")
            if results['crossover_events']:
                print(f"  - {len(results['crossover_events'])} crossover(s) occurred but candle type didn't match")
            else:
                print(f"  - No crossovers occurred between Price Strength and Volume Strength")
            
            if results['data_quality_issues']:
                print(f"  - Data quality issues detected:")
                for issue in results['data_quality_issues']:
                    print(f"    * {issue}")
        
        print("="*80)
        
    except Exception as e:
        print(f"❌ ERROR: Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()
        return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Diagnostic interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

