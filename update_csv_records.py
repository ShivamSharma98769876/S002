"""
Script to update existing CSV records with latest code logic:
- Add expiry dates
- Fix stop loss calculations (based on premium, not spot)
- Fix option symbols
"""

import pandas as pd
from datetime import datetime
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.utils.premium_fetcher import get_expiry_date, build_tradingsymbol
from src.config.config_manager import ConfigManager
import json


def load_expiry_config():
    """Load expiry config from config.json"""
    try:
        config_manager = ConfigManager()
        config_path = config_manager.config_dir / "config.json"
        if config_path.exists():
            with open(config_path, 'r') as f:
                config_data = json.load(f)
                return config_data.get("expiry_config", {})
    except Exception as e:
        print(f"Error loading config: {e}")
    return {
        "BANKNIFTY": {"duration": "Monthly", "day_of_week": "Thursday"},
        "NIFTY": {"duration": "Weekly", "day_of_week": "Tuesday"},
        "SENSEX": {"duration": "Weekly", "day_of_week": "Thursday"}
    }


def is_premium_price(price: float, segment: str) -> bool:
    """Check if price looks like premium (small) vs spot (large)"""
    # Premium prices are typically < 1000, spot prices are much larger
    if segment == "BANKNIFTY":
        return price < 1000  # BANKNIFTY spot is ~59000-60000
    elif segment == "SENSEX":
        return price < 1000  # SENSEX spot is ~85000
    elif segment == "NIFTY":
        return price < 1000  # NIFTY spot is ~26000
    return price < 1000


def update_csv_record(row, expiry_config):
    """Update a single CSV record with latest logic"""
    segment = row['segment']
    entry_time_str = row['entry_time']
    entry_price = float(row['entry_price'])
    current_price = float(row['current_price'])
    stop_loss_points = float(row['stop_loss_points'])
    option_type = row['option_type']
    strike_price = float(row['strike_price'])
    
    # Parse entry time
    try:
        entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
        if entry_time.tzinfo is None:
            # Assume IST if no timezone
            from datetime import timezone, timedelta
            ist = timezone(timedelta(hours=5, minutes=30))
            entry_time = entry_time.replace(tzinfo=ist)
    except:
        entry_time = datetime.now()
    
    # Get segment config
    seg_config = expiry_config.get(segment.upper(), {})
    duration = seg_config.get("duration", "Weekly")
    day_of_week = seg_config.get("day_of_week", "Thursday")
    
    # Calculate expiry date
    expiry_date_obj = get_expiry_date(entry_time, duration, day_of_week)
    if expiry_date_obj:
        expiry_str = expiry_date_obj.strftime("%Y-%m-%d")
    else:
        expiry_str = ""
    
    # Check if prices are premium or spot
    entry_is_premium = is_premium_price(entry_price, segment)
    current_is_premium = is_premium_price(current_price, segment)
    
    # Fix initial_sl_price: For all long buys, SL = entry_premium - stop_loss_points
    if entry_is_premium:
        initial_sl_price = entry_price - stop_loss_points
    else:
        # If entry is spot price, we can't fix it properly, but apply same logic
        # (This shouldn't happen with latest code, but for old records)
        initial_sl_price = entry_price - stop_loss_points
    
    # Fix current_sl_price: Trailing stop based on highest premium reached
    if entry_is_premium and current_is_premium:
        # Both are premiums - calculate trailing stop
        highest_premium = max(entry_price, current_price)
        current_sl_price = highest_premium - stop_loss_points
        # Ensure it doesn't go below initial SL
        if current_sl_price < initial_sl_price:
            current_sl_price = initial_sl_price
    elif entry_is_premium:
        # Entry is premium but current is spot - use entry for SL calculation
        current_sl_price = initial_sl_price
    else:
        # Both are spot prices - can't fix properly, but apply same logic
        highest_price = max(entry_price, current_price)
        current_sl_price = highest_price - stop_loss_points
        if current_sl_price < initial_sl_price:
            current_sl_price = initial_sl_price
    
    # Rebuild option symbol if expiry is available
    option_symbol = row.get('option_symbol', '')
    if expiry_str and strike_price > 0:
        try:
            new_symbol = build_tradingsymbol(
                segment,
                int(strike_price),
                option_type,
                expiry_str,
                expiry_config
            )
            if new_symbol:
                option_symbol = new_symbol
        except Exception as e:
            print(f"Warning: Could not rebuild symbol for {segment} {strike_price} {option_type}: {e}")
    
    # Update row
    row['expiry'] = expiry_str
    row['initial_sl_price'] = initial_sl_price
    row['current_sl_price'] = current_sl_price
    row['option_symbol'] = option_symbol
    
    return row


def update_csv_file(file_path: str):
    """Update all records in a CSV file"""
    print(f"Reading CSV file: {file_path}")
    df = pd.read_csv(file_path)
    
    expiry_config = load_expiry_config()
    
    print(f"Found {len(df)} records to update")
    
    # Update each row
    updated_rows = []
    for idx, row in df.iterrows():
        try:
            updated_row = update_csv_record(row, expiry_config)
            updated_rows.append(updated_row)
            print(f"  Updated record {idx + 1}: {row['segment']} {row['option_type']} strike={row['strike_price']}")
        except Exception as e:
            print(f"  Error updating record {idx + 1}: {e}")
            updated_rows.append(row)  # Keep original if update fails
    
    # Create updated DataFrame
    updated_df = pd.DataFrame(updated_rows)
    
    # Backup original file
    backup_path = file_path.replace('.csv', '_backup.csv')
    df.to_csv(backup_path, index=False)
    print(f"Backup saved to: {backup_path}")
    
    # Write updated file
    updated_df.to_csv(file_path, index=False)
    print(f"Updated CSV saved to: {file_path}")
    
    return updated_df


if __name__ == "__main__":
    csv_file = "data/live_trader/open_positions_2025-12-03.csv"
    
    if not os.path.exists(csv_file):
        print(f"Error: File not found: {csv_file}")
        sys.exit(1)
    
    print("=" * 60)
    print("Updating CSV records with latest code logic")
    print("=" * 60)
    
    updated_df = update_csv_file(csv_file)
    
    print("\n" + "=" * 60)
    print("Update complete!")
    print("=" * 60)
    print("\nSummary of changes:")
    print("- Expiry dates added/updated")
    print("- Initial SL: entry_premium - stop_loss_points (for all long buys)")
    print("- Current SL: max(entry, current) - stop_loss_points (trailing stop)")
    print("- Option symbols rebuilt with expiry dates")
    print(f"\nBackup saved. Review the updated file: {csv_file}")

