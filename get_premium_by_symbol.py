#!/usr/bin/env python3
"""
Get Premium by Trading Symbol and Timestamp

This script fetches the option premium for a given trading symbol at a specific date and time
using the Kite Connect API.

Usage:
    python get_premium_by_symbol.py <tradingsymbol> <date> <time>
    
Example:
    python get_premium_by_symbol.py BANKNIFTY30DEC2559900PE 2025-11-28 11:30:00
"""

import sys
import os
import re
from datetime import datetime, timedelta
import pandas as pd

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

try:
    from src.api.kite_client import KiteClient
    from src.config.config_manager import ConfigManager
except ImportError as e:
    print(f"Error: Could not import required modules. Make sure you're running from the project root.")
    print(f"Import error: {e}")
    sys.exit(1)


def get_premium_by_symbol(tradingsymbol: str, date: str, time: str, exchange: str = "NFO"):
    """
    Get premium for a trading symbol at a specific date and time.
    
    Args:
        tradingsymbol: Trading symbol (e.g., BANKNIFTY30DEC2559900PE)
        date: Date in YYYY-MM-DD format (e.g., 2025-11-28)
        time: Time in HH:MM:SS format (e.g., 11:30:00)
        exchange: Exchange name (default: NFO)
    
    Returns:
        dict with premium information or None if not found
    """
    try:
        # Initialize Config Manager
        config_manager = ConfigManager()
        
        # Initialize Kite Client
        kite_client = KiteClient(config_manager)
        
        # Load access token from config file
        import json
        config_path = config_manager.config_dir / "config.json"
        
        if not config_path.exists():
            print(f"Error: Config file not found at {config_path}")
            print("Please ensure config/config.json exists with your access_token.")
            return None
        
        try:
            with open(config_path, 'r') as f:
                config_data = json.load(f)
            
            access_token = config_data.get("access_token")
            if not access_token:
                print("Error: access_token not found in config/config.json")
                print("Please add your access_token to the config file.")
                return None
            
            # Set access token
            print("Setting access token from config file...")
            kite_client.set_access_token(access_token)
            
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in config file: {e}")
            return None
        except Exception as e:
            print(f"Error loading config file: {e}")
            return None
        
        # Check authentication
        print("Verifying authentication...")
        if not kite_client.is_authenticated():
            print("Error: Kite API authentication failed.")
            print("The access_token in config/config.json may be expired or invalid.")
            print("Please authenticate via the main application or update the access_token.")
            return None
        
        print("✓ Successfully authenticated with Kite API")
        
        # Parse date and time
        try:
            datetime_str = f"{date} {time}"
            target_timestamp = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
            # Make timezone-aware (IST - Indian Standard Time, UTC+5:30)
            # Kite API returns timezone-aware datetimes, so we need to match that
            try:
                from pytz import timezone
                ist = timezone('Asia/Kolkata')
                target_timestamp = ist.localize(target_timestamp)
            except ImportError:
                # Fallback if pytz is not available - use UTC offset manually
                from datetime import timezone as dt_timezone
                ist_offset = dt_timezone(timedelta(hours=5, minutes=30))
                target_timestamp = target_timestamp.replace(tzinfo=ist_offset)
        except ValueError as e:
            print(f"Error: Invalid date/time format. Use YYYY-MM-DD for date and HH:MM:SS for time. Error: {e}")
            return None
        
        print(f"Looking for premium for {tradingsymbol} at {target_timestamp}")
        
        # Auto-detect exchange from tradingsymbol if not explicitly provided
        # Try to extract segment from tradingsymbol
        segment_match = None
        for seg in ['BANKNIFTY', 'NIFTY', 'SENSEX']:
            if tradingsymbol.startswith(seg):
                segment_match = seg
                break
        
        # Use correct exchange based on segment
        if segment_match:
            from src.utils.premium_fetcher import get_exchange_for_segment
            detected_exchange = get_exchange_for_segment(segment_match)
            if exchange == "NFO":  # Only override if default was used
                exchange = detected_exchange
                print(f"Auto-detected exchange: {exchange} for segment: {segment_match}")
        
        # Get instruments from the correct exchange
        print(f"Fetching instruments list from {exchange} exchange...")
        instruments = kite_client.kite.instruments(exchange)
        
        # Find the instrument by tradingsymbol
        instrument = None
        for inst in instruments:
            if inst.get('tradingsymbol') == tradingsymbol:
                instrument = inst
                break
        
        if not instrument:
            print(f"Error: Trading symbol '{tradingsymbol}' not found in {exchange} exchange.")
            print(f"Available instruments count: {len(instruments)}")
            
            # Try to extract segment, strike, and option type from tradingsymbol
            # Format: SEGMENTDDMMMYYSTRIKEOPTIONTYPE (e.g., BANKNIFTY30DEC2559900PE)
            segment_match = None
            strike_match = None
            option_type_match = None
            
            # Try to match segment (BANKNIFTY, NIFTY, SENSEX)
            for seg in ['BANKNIFTY', 'NIFTY', 'SENSEX']:
                if tradingsymbol.startswith(seg):
                    segment_match = seg
                    break
            
            # Try to extract strike (look for numbers before PE/CE)
            import re
            strike_pattern = r'(\d+)(PE|CE)$'
            match = re.search(strike_pattern, tradingsymbol)
            if match:
                strike_match = int(match.group(1))
                option_type_match = match.group(2)
            
            # Show matching instruments
            print("\n" + "="*80)
            print("SEARCHING FOR MATCHING INSTRUMENTS...")
            print("="*80)
            
            matching_instruments = []
            
            # Filter by segment if found
            if segment_match:
                print(f"\nFiltering by segment: {segment_match}")
                # segment_filtered = [inst for inst in instruments 
                #                   if inst.get('name') == segment_match and 
                #                   inst.get('segment') == 'NFO-OPT']
                
                
                segment_filtered = [  inst for inst in instruments
                                    if segment_match in str(inst.get('tradingsymbol', '')).upper() and 
                                    inst.get('segment', '').endswith('-OPT')
                                    ]

                
                
                print(f"Found {len(segment_filtered)} {segment_match} options")
                
                # Filter by option type if found
                if option_type_match:
                    print(f"Filtering by option type: {option_type_match}")
                    type_filtered = [inst for inst in segment_filtered 
                                   if inst.get('instrument_type') == option_type_match]
                    print(f"Found {len(type_filtered)} {segment_match} {option_type_match} options")
                    
                    # Filter by strike if found (show strikes within ±500 range)
                    if strike_match:
                        print(f"Filtering by strike: {strike_match} (±500 range)")
                        strike_filtered = [inst for inst in type_filtered 
                                         if abs(float(inst.get('strike', 0)) - strike_match) <= 500]
                        print(f"Found {len(strike_filtered)} {segment_match} {option_type_match} options near strike {strike_match}")
                        
                        # Show top 20 matching instruments
                        if strike_filtered:
                            print(f"\nShowing top 20 matching instruments (sorted by strike):")
                            strike_filtered.sort(key=lambda x: abs(float(x.get('strike', 0)) - strike_match))
                            for i, inst in enumerate(strike_filtered[:20], 1):
                                expiry = inst.get('expiry')
                                expiry_str = str(expiry.date()) if hasattr(expiry, 'date') else str(expiry)
                                print(f"  {i:2d}. {inst.get('tradingsymbol'):25s} | "
                                      f"Strike: {inst.get('strike'):8.0f} | "
                                      f"Expiry: {expiry_str} | "
                                      f"Token: {inst.get('instrument_token')}")
                            matching_instruments = strike_filtered[:20]
                        else:
                            # Show all type_filtered if no strike match
                            print(f"\nShowing all {segment_match} {option_type_match} options (sorted by strike):")
                            type_filtered.sort(key=lambda x: float(x.get('strike', 0)))
                            for i, inst in enumerate(type_filtered[:30], 1):
                                expiry = inst.get('expiry')
                                expiry_str = str(expiry.date()) if hasattr(expiry, 'date') else str(expiry)
                                print(f"  {i:2d}. {inst.get('tradingsymbol'):25s} | "
                                      f"Strike: {inst.get('strike'):8.0f} | "
                                      f"Expiry: {expiry_str} | "
                                      f"Token: {inst.get('instrument_token')}")
                            matching_instruments = type_filtered[:30]
                    else:
                        # Show all type_filtered if no strike match
                        print(f"\nShowing all {segment_match} {option_type_match} options (sorted by strike):")
                        type_filtered.sort(key=lambda x: float(x.get('strike', 0)))
                        for i, inst in enumerate(type_filtered[:30], 1):
                            expiry = inst.get('expiry')
                            expiry_str = str(expiry.date()) if hasattr(expiry, 'date') else str(expiry)
                            print(f"  {i:2d}. {inst.get('tradingsymbol'):25s} | "
                                  f"Strike: {inst.get('strike'):8.0f} | "
                                  f"Expiry: {expiry_str} | "
                                  f"Token: {inst.get('instrument_token')}")
                        matching_instruments = type_filtered[:30]
                else:
                    # Show all segment_filtered if no option type match
                    print(f"\nShowing all {segment_match} options (sorted by strike):")
                    segment_filtered.sort(key=lambda x: float(x.get('strike', 0)))
                    for i, inst in enumerate(segment_filtered[:30], 1):
                        expiry = inst.get('expiry')
                        expiry_str = str(expiry.date()) if hasattr(expiry, 'date') else str(expiry)
                        print(f"  {i:2d}. {inst.get('tradingsymbol'):25s} | "
                              f"Type: {inst.get('instrument_type'):3s} | "
                              f"Strike: {inst.get('strike'):8.0f} | "
                              f"Expiry: {expiry_str}")
                    matching_instruments = segment_filtered[:30]
            else:
                # Show similar symbols if segment not found
                print(f"\nCould not identify segment from '{tradingsymbol}'")
                print("Showing similar symbols (first 20):")
                similar = [inst.get('tradingsymbol') for inst in instruments 
                          if tradingsymbol[:10].upper() in inst.get('tradingsymbol', '').upper()][:20]
                if similar:
                    for i, sym in enumerate(similar, 1):
                        print(f"  {i:2d}. {sym}")
                else:
                    print("  No similar symbols found.")
            
            # For SENSEX, show format examples
            if segment_match == 'SENSEX':
                print("\n" + "="*80)
                print("SENSEX TRADINGSYMBOL FORMAT GUIDE")
                print("="*80)
                print("Monthly format: SENSEX + YY + MMM + STRIKE + OPTIONTYPE")
                print("  Example: SENSEX25DEC85700PE (for Dec 2025, strike 85700, PE)")
                print("  Used when expiry is the LAST THURSDAY of the month")
                print("\nWeekly format: SENSEX + YY + M + DD + STRIKE + OPTIONTYPE")
                print("  Example: SENSEX25D0485700PE (for Dec 4, 2025, strike 85700, PE)")
                print("  Where M = first letter of month (D for Dec, J for Jan, F for Feb, etc.)")
                print("  Used when expiry is a Thursday but NOT the last Thursday of the month")
                print("\nNote: SENSEX weekly expiry is on Thursday, monthly is last Thursday of month")
                print("\nTo build the correct symbol automatically, use:")
                print("  python get_premium_by_symbol.py SENSEX <strike> <CE|PE> <expiry_date> <date> <time>")
                print("  Example: python get_premium_by_symbol.py SENSEX 85700 PE 2025-12-26 2025-11-28 11:30:00")
                print("="*80)
            
            print("="*80)
            print(f"\nTip: Use one of the tradingsymbols listed above for the correct format.")
            if segment_match == 'SENSEX':
                print("For SENSEX, you can also use the parameter method to auto-build the symbol.")
            
            # Show available instruments summary
            print("\n" + "="*80)
            print("AVAILABLE INSTRUMENTS SUMMARY")
            print("="*80)
            if segment_match:
                segment_instruments = [inst for inst in instruments 
                                      if inst.get('name') == segment_match and 
                                      inst.get('segment') == 'NFO-OPT']
                print(f"Total {segment_match} instruments available: {len(segment_instruments)}")
                
                # If no instruments found, show all available segments to help debug
                if len(segment_instruments) == 0:
                    print(f"\n⚠️  No {segment_match} instruments found. Showing all available segments:")
                    from collections import defaultdict
                    by_segment = defaultdict(int)
                    for inst in instruments:
                        if inst.get('segment') == 'NFO-OPT':
                            name = inst.get('name', 'UNKNOWN')
                            by_segment[name] += 1
                    
                    print("\nAvailable option segments in NFO:")
                    for seg, count in sorted(by_segment.items()):
                        print(f"  {seg}: {count} instruments")
                    
                    # Also check if there are any instruments with similar names
                    print(f"\nSearching for instruments with '{segment_match}' in tradingsymbol...")
                    similar_symbols = [inst for inst in instruments 
                                       if segment_match.upper() in inst.get('tradingsymbol', '').upper() and
                                       inst.get('segment') == 'NFO-OPT']
                    if similar_symbols:
                        print(f"Found {len(similar_symbols)} instruments with '{segment_match}' in tradingsymbol:")
                        # Group by name
                        by_name = defaultdict(list)
                        for inst in similar_symbols:
                            by_name[inst.get('name')].append(inst)
                        
                        for name, insts in sorted(by_name.items()):
                            print(f"  {name}: {len(insts)} instruments")
                            # Show a few examples
                            for inst in insts[:5]:
                                expiry = inst.get('expiry')
                                expiry_str = str(expiry.date()) if hasattr(expiry, 'date') else str(expiry)
                                print(f"    - {inst.get('tradingsymbol')} (Strike: {inst.get('strike')}, Expiry: {expiry_str})")
                            if len(insts) > 5:
                                print(f"    ... and {len(insts) - 5} more")
                    else:
                        print(f"  No instruments found with '{segment_match}' in tradingsymbol")
                else:
                    # Show unique expiries
                    from collections import defaultdict
                    by_expiry = defaultdict(int)
                    for inst in segment_instruments:
                        expiry = inst.get('expiry')
                        expiry_str = str(expiry.date()) if hasattr(expiry, 'date') else str(expiry)
                        by_expiry[expiry_str] += 1
                    
                    print(f"\nAvailable expiries ({len(by_expiry)}):")
                    for expiry_str in sorted(by_expiry.keys())[:10]:  # Show first 10 expiries
                        print(f"  {expiry_str}: {by_expiry[expiry_str]} instruments")
                    if len(by_expiry) > 10:
                        print(f"  ... and {len(by_expiry) - 10} more expiries")
            else:
                print(f"Total instruments in {exchange}: {len(instruments)}")
                # Show segments breakdown
                from collections import defaultdict
                by_segment = defaultdict(int)
                for inst in instruments:
                    if inst.get('segment') == 'NFO-OPT':
                        name = inst.get('name', 'UNKNOWN')
                        by_segment[name] += 1
                
                if by_segment:
                    print("\nOptions by segment:")
                    for seg, count in sorted(by_segment.items()):
                        print(f"  {seg}: {count} instruments")
            print("="*80)
            
            return None
        
        print(f"Found instrument: {instrument.get('tradingsymbol')}")
        print(f"  Instrument Token: {instrument.get('instrument_token')}")
        print(f"  Name: {instrument.get('name')}")
        print(f"  Strike: {instrument.get('strike')}")
        print(f"  Instrument Type: {instrument.get('instrument_type')}")
        print(f"  Expiry: {instrument.get('expiry')}")
        
        # Get instrument token
        instrument_token = instrument['instrument_token']
        
        # Fetch historical data around the target timestamp
        # Get data for a window around the timestamp (10 minutes before and after)
        # Ensure from_date and to_date are timezone-aware
        from_date = target_timestamp - timedelta(minutes=10)
        to_date = target_timestamp + timedelta(minutes=10)
        
        # Kite API expects timezone-naive datetimes, so convert to naive
        # But keep target_timestamp timezone-aware for comparison
        from_date_naive = from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
        to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date
        
        # Use 5-minute interval for better accuracy
        interval = "5minute"
        
        print(f"Fetching historical data from {from_date_naive} to {to_date_naive} (interval: {interval})...")
        
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
                print(f"Error: No historical data found for {tradingsymbol} around {target_timestamp}")
                print(f"\nInstrument details:")
                print(f"  Tradingsymbol: {instrument.get('tradingsymbol')}")
                print(f"  Instrument Token: {instrument_token}")
                print(f"  Expiry: {instrument.get('expiry')}")
                print(f"  Strike: {instrument.get('strike')}")
                print(f"  Type: {instrument.get('instrument_type')}")
                print(f"\nNote: Historical data may not be available for this date/time.")
                print(f"Try a different date/time or check if the instrument was active at that time.")
                
                # Show available instruments for this segment
                print("\n" + "="*80)
                print("AVAILABLE INSTRUMENTS FOR THIS SEGMENT")
                print("="*80)
                try:
                    segment_name = instrument.get('name')
                    if segment_name:
                        segment_instruments = [inst for inst in instruments 
                                              if inst.get('name') == segment_name and 
                                              inst.get('segment') == 'NFO-OPT']
                        print(f"Total {segment_name} instruments: {len(segment_instruments)}")
                        
                        if segment_instruments:
                            # Show by expiry
                            from collections import defaultdict
                            by_expiry = defaultdict(list)
                            for inst in segment_instruments:
                                expiry = inst.get('expiry')
                                expiry_str = str(expiry.date()) if hasattr(expiry, 'date') else str(expiry)
                                by_expiry[expiry_str].append(inst)
                            
                            print(f"\nAvailable expiries ({len(by_expiry)}):")
                            for expiry_str in sorted(by_expiry.keys())[:15]:
                                insts = by_expiry[expiry_str]
                                print(f"  {expiry_str}: {len(insts)} instruments")
                                # Show a few examples for this expiry
                                if len(insts) <= 5:
                                    for inst in insts[:5]:
                                        print(f"      - {inst.get('tradingsymbol')} (Strike: {inst.get('strike')}, Type: {inst.get('instrument_type')})")
                                else:
                                    # Show strikes near the requested one
                                    requested_strike = instrument.get('strike')
                                    if requested_strike:
                                        nearby = sorted(insts, key=lambda x: abs(float(x.get('strike', 0)) - float(requested_strike)))[:5]
                                        print(f"      Examples (near strike {requested_strike}):")
                                        for inst in nearby:
                                            print(f"      - {inst.get('tradingsymbol')} (Strike: {inst.get('strike')}, Type: {inst.get('instrument_type')})")
                            
                            if len(by_expiry) > 15:
                                print(f"  ... and {len(by_expiry) - 15} more expiries")
                except Exception as e:
                    print(f"Could not show available instruments: {e}")
                print("="*80)
                
                return None
            
            # Convert to DataFrame for easier processing
            df = pd.DataFrame(candles)
            df['date'] = pd.to_datetime(df['date'])
            
            # Ensure both are timezone-aware (Kite returns IST timezone)
            # If df['date'] is timezone-naive, localize it to IST
            if df['date'].dt.tz is None:
                try:
                    from pytz import timezone
                    ist = timezone('Asia/Kolkata')
                    df['date'] = df['date'].dt.tz_localize(ist)
                except ImportError:
                    # Fallback: assume IST (UTC+5:30)
                    from datetime import timezone as dt_timezone
                    ist_offset = dt_timezone(timedelta(hours=5, minutes=30))
                    df['date'] = df['date'].dt.tz_localize(ist_offset)
            
            # Ensure target_timestamp is also timezone-aware
            if target_timestamp.tzinfo is None:
                try:
                    from pytz import timezone
                    ist = timezone('Asia/Kolkata')
                    target_timestamp = ist.localize(target_timestamp)
                except ImportError:
                    from datetime import timezone as dt_timezone
                    ist_offset = dt_timezone(timedelta(hours=5, minutes=30))
                    target_timestamp = target_timestamp.replace(tzinfo=ist_offset)
            
            # Find the candle closest to the target timestamp
            df['time_diff'] = abs(df['date'] - target_timestamp)
            closest_candle = df.loc[df['time_diff'].idxmin()]
            
            # Get premium (close price)
            premium = float(closest_candle['close'])
            candle_time = closest_candle['date']
            time_diff_seconds = abs((candle_time - target_timestamp).total_seconds())
            
            result = {
                'tradingsymbol': tradingsymbol,
                'target_timestamp': target_timestamp.isoformat(),
                'candle_timestamp': candle_time.isoformat(),
                'time_difference_seconds': time_diff_seconds,
                'premium': premium,
                'open': float(closest_candle['open']),
                'high': float(closest_candle['high']),
                'low': float(closest_candle['low']),
                'close': float(closest_candle['close']),
                'volume': int(closest_candle.get('volume', 0)),
                'instrument_token': instrument_token,
                'instrument_details': {
                    'name': instrument.get('name'),
                    'strike': instrument.get('strike'),
                    'instrument_type': instrument.get('instrument_type'),
                    'expiry': str(instrument.get('expiry'))
                }
            }
            
            return result
            
        except Exception as e:
            print(f"Error fetching historical data: {e}")
            import traceback
            traceback.print_exc()
            
            # Show available instruments
            print("\n" + "="*80)
            print("AVAILABLE INSTRUMENTS (Error occurred)")
            print("="*80)
            try:
                if 'instrument' in locals() and instrument:
                    segment_name = instrument.get('name')
                    if segment_name:
                        segment_instruments = [inst for inst in instruments 
                                              if inst.get('name') == segment_name and 
                                              inst.get('segment') == 'NFO-OPT']
                        print(f"Total {segment_name} instruments: {len(segment_instruments)}")
                        
                        # Show similar tradingsymbols
                        if 'tradingsymbol' in locals() and tradingsymbol:
                            print(f"\nSearching for instruments similar to '{tradingsymbol}'...")
                            similar = [inst for inst in segment_instruments 
                                      if tradingsymbol[:10].upper() in inst.get('tradingsymbol', '').upper()]
                            if similar:
                                print(f"Found {len(similar)} similar tradingsymbols:")
                                for i, inst in enumerate(similar[:20], 1):
                                    expiry = inst.get('expiry')
                                    expiry_str = str(expiry.date()) if hasattr(expiry, 'date') else str(expiry)
                                    print(f"  {i:2d}. {inst.get('tradingsymbol'):25s} | "
                                          f"Strike: {inst.get('strike'):8.0f} | "
                                          f"Type: {inst.get('instrument_type'):3s} | "
                                          f"Expiry: {expiry_str}")
            except Exception as inner_e:
                print(f"Could not show available instruments: {inner_e}")
            print("="*80)
            
            return None
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Try to show available instruments if we have access to kite_client and instruments
        try:
            if 'kite_client' in locals() and kite_client and kite_client.is_authenticated():
                print("\n" + "="*80)
                print("AVAILABLE INSTRUMENTS (for reference)")
                print("="*80)
                try:
                    if 'instruments' not in locals():
                        instruments = kite_client.kite.instruments(exchange)
                    
                    print(f"Total instruments in {exchange}: {len(instruments)}")
                    
                    # Show segments breakdown
                    from collections import defaultdict
                    by_segment = defaultdict(int)
                    for inst in instruments:
                        if inst.get('segment') == 'NFO-OPT':
                            name = inst.get('name', 'UNKNOWN')
                            by_segment[name] += 1
                    
                    if by_segment:
                        print("\nOptions by segment:")
                        for seg, count in sorted(by_segment.items()):
                            print(f"  {seg}: {count} instruments")
                    
                    # If we have a tradingsymbol, try to show similar ones
                    if 'tradingsymbol' in locals() and tradingsymbol:
                        print(f"\nSearching for instruments similar to '{tradingsymbol}'...")
                        similar = [inst.get('tradingsymbol') for inst in instruments 
                                  if tradingsymbol[:10].upper() in inst.get('tradingsymbol', '').upper()][:20]
                        if similar:
                            print(f"Found {len(similar)} similar tradingsymbols:")
                            for i, sym in enumerate(similar[:10], 1):
                                print(f"  {i:2d}. {sym}")
                            if len(similar) > 10:
                                print(f"  ... and {len(similar) - 10} more")
                except Exception as inner_e:
                    print(f"Could not fetch instruments: {inner_e}")
                print("="*80)
        except:
            pass  # Don't fail if we can't show instruments
        
        return None


def main():
    """Main function to handle command line arguments."""
    if len(sys.argv) < 4:
        print("Usage:")
        print("  Method 1: python get_premium_by_symbol.py <tradingsymbol> <date> <time>")
        print("  Method 2: python get_premium_by_symbol.py <segment> <strike> <option_type> <expiry> <date> <time>")
        print("\nExamples:")
        print("  python get_premium_by_symbol.py BANKNIFTY25DEC59800PE 2025-11-28 11:30:00")
        print("  python get_premium_by_symbol.py SENSEX 85700 PE 2025-12-26 2025-11-28 11:30:00")
        print("  python get_premium_by_symbol.py NIFTY 26200 CE 2025-12-05 2025-11-28 11:30:00")
        print("\nArguments:")
        print("  Method 1:")
        print("    tradingsymbol: Trading symbol (e.g., BANKNIFTY25DEC59800PE)")
        print("    date: Date in YYYY-MM-DD format (e.g., 2025-11-28)")
        print("    time: Time in HH:MM:SS format (e.g., 11:30:00)")
        print("  Method 2:")
        print("    segment: Trading segment (NIFTY, BANKNIFTY, SENSEX)")
        print("    strike: Strike price (e.g., 85700)")
        print("    option_type: Option type (CE or PE)")
        print("    expiry: Expiry date in YYYY-MM-DD format (e.g., 2025-12-26)")
        print("    date: Date to fetch premium for (YYYY-MM-DD)")
        print("    time: Time to fetch premium for (HH:MM:SS)")
        sys.exit(1)
    
    # Check if using method 2 (6 arguments: segment, strike, option_type, expiry, date, time)
    if len(sys.argv) == 7:
        segment = sys.argv[1]
        strike = int(sys.argv[2])
        option_type = sys.argv[3]
        expiry = sys.argv[4]
        date = sys.argv[5]
        time = sys.argv[6]
        
        # Build tradingsymbol using the same logic as premium_fetcher
        try:
            from src.utils.premium_fetcher import build_tradingsymbol
            import json
            from pathlib import Path
            
            # Load expiry config
            config_path = Path(__file__).parent / "config" / "config.json"
            expiry_config = None
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config_data = json.load(f)
                    expiry_config = config_data.get("expiry_config", {})
            
            tradingsymbol = build_tradingsymbol(segment, strike, option_type, expiry, expiry_config)
            
            if not tradingsymbol:
                print(f"Error: Could not build tradingsymbol for {segment} {strike} {option_type} {expiry}")
                print("Please check the parameters and try again.")
                sys.exit(1)
            
            print(f"Built tradingsymbol: {tradingsymbol}")
            print(f"Using expiry config: {expiry_config.get(segment.upper(), {})}")
            
        except Exception as e:
            print(f"Error building tradingsymbol: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        # Method 1: tradingsymbol provided directly
        tradingsymbol = sys.argv[1]
        date = sys.argv[2]
        time = sys.argv[3]
    
    # Get premium
    result = get_premium_by_symbol(tradingsymbol, date, time)
    
    if result:
        print("\n" + "="*60)
        print("PREMIUM INFORMATION")
        print("="*60)
        print(f"Trading Symbol: {result['tradingsymbol']}")
        print(f"Target Timestamp: {result['target_timestamp']}")
        print(f"Candle Timestamp: {result['candle_timestamp']}")
        print(f"Time Difference: {result['time_difference_seconds']:.0f} seconds")
        print(f"\nPremium (Close): ₹{result['premium']:.2f}")
        print(f"Open: ₹{result['open']:.2f}")
        print(f"High: ₹{result['high']:.2f}")
        print(f"Low: ₹{result['low']:.2f}")
        print(f"Volume: {result['volume']}")
        print(f"\nInstrument Details:")
        print(f"  Name: {result['instrument_details']['name']}")
        print(f"  Strike: {result['instrument_details']['strike']}")
        print(f"  Type: {result['instrument_details']['instrument_type']}")
        print(f"  Expiry: {result['instrument_details']['expiry']}")
        print("="*60)
    else:
        print("\nFailed to fetch premium.")
        sys.exit(1)


if __name__ == "__main__":
    main()

