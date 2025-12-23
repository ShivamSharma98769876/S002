"""
Backfill script for open_positions CSV:

- Uses `option_symbol`, `segment`, `option_type`, `expiry`, and timestamps
  to fetch option premiums from Kite.
- Adds two new columns:
    - `entry_premium`   : premium at `entry_time`
    - `current_premium` : premium at `update_time` (or entry_time if empty)
- Optionally can correct `strike_price` if it does not match `option_symbol`.

Usage (from project root):

    python backfill_option_premiums.py data/live_trader/open_positions_2025-12-03_UPDATED.csv

Requirements:
- `config/config.json` must contain a valid `access_token`.
- Zerodha Kite credentials must be valid; otherwise the script will log errors.
"""

import sys
import os
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
from datetime import datetime

from src.config.config_manager import ConfigManager
from src.api.kite_client import KiteClient
from src.utils.premium_fetcher import (
    get_exchange_for_segment,
    fetch_premium_by_tradingsymbol,
)


def parse_iso_timestamp(value: str) -> Optional[datetime]:
    """Parse ISO-like timestamp from CSV (e.g. 2025-12-03T09:50:00)."""
    if not value or not isinstance(value, str):
        return None
    try:
        # pandas may already have parsed, but for robustness use fromisoformat
        return datetime.fromisoformat(value)
    except Exception:
        # Last resort: try common format
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


def decode_strike_from_symbol(symbol: str) -> Optional[int]:
    """
    Best-effort extraction of strike price from option symbol.

    Examples:
      - BANKNIFTY25DEC59200PE -> 59200
      - NIFTY25D0926050PE     -> 26050
      - SENSEX25D0485000CE    -> 85000
    """
    if not symbol or not isinstance(symbol, str):
        return None

    # Strip final two letters (CE/PE)
    core = symbol[:-2]

    # Walk backwards to find where digits (strike) start
    i = len(core) - 1
    while i >= 0 and core[i].isdigit():
        i -= 1
    digits = core[i + 1 :]
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def fetch_premium_for_row(
    kite_client: KiteClient,
    option_symbol: str,
    segment: str,
    timestamp: Optional[datetime],
) -> Optional[float]:
    """Fetch option premium for a single row at a given timestamp."""
    if not timestamp:
        return None

    try:
        exchange = get_exchange_for_segment(segment)
        result = fetch_premium_by_tradingsymbol(
            kite_client=kite_client,
            tradingsymbol=option_symbol,
            timestamp=timestamp,
            exchange=exchange,
            window_minutes=10,
            interval="5minute",
        )
        if result:
            premium, _inst = result
            return float(premium)
    except Exception as e:
        print(f"[WARN] Failed to fetch premium for {option_symbol} at {timestamp}: {e}")
    return None


def backfill_csv(csv_path: Path) -> None:
    """Backfill premiums for the given CSV file."""
    if not csv_path.exists():
        print(f"[ERROR] Path not found: {csv_path}")
        return
    
    if csv_path.is_dir():
        print(f"[ERROR] Path is a directory, not a file: {csv_path}")
        print(f"[INFO] Please provide the full path to a CSV file, e.g.:")
        print(f"       python backfill_option_premiums.py data/live_trader/open_positions_2025-12-03_UPDATED.csv")
        # Try to find CSV files in the directory
        csv_files = list(csv_path.glob("*.csv"))
        if csv_files:
            print(f"[INFO] Found {len(csv_files)} CSV file(s) in directory:")
            for f in csv_files:
                print(f"       - {f}")
        return

    print(f"[INFO] Reading CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    if df.empty:
        print("[INFO] CSV is empty, nothing to backfill.")
        return

    # Ensure required columns exist
    required_cols = [
        "segment",
        "option_symbol",
        "option_type",
        "strike_price",
        "expiry",
        "entry_time",
        "update_time",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"[ERROR] CSV missing required columns: {missing}")
        return

    # Add new columns if they don't exist yet
    if "entry_premium" not in df.columns:
        df["entry_premium"] = pd.NA
    if "current_premium" not in df.columns:
        df["current_premium"] = pd.NA

    # Initialise Kite client
    config_manager = ConfigManager()
    kite_client = KiteClient(config_manager)

    # Load access_token from raw config.json (same as get_premium_by_symbol.py)
    raw_config_path = config_manager.config_dir / "config.json"
    if not raw_config_path.exists():
        print(f"[ERROR] Config file not found: {raw_config_path}")
        return

    import json

    with open(raw_config_path, "r") as f:
        config_data = json.load(f)
    access_token = config_data.get("access_token")
    if not access_token:
        print("[ERROR] access_token not found in config/config.json")
        return

    print("[INFO] Setting access token and verifying authentication...")
    kite_client.set_access_token(access_token)
    if not kite_client.is_authenticated():
        print("[ERROR] Kite authentication failed (access_token may be invalid or expired).")
        return

    print("[INFO] Kite authentication OK. Starting backfill...")

    updated_count = 0

    for idx, row in df.iterrows():
        segment = str(row["segment"]).upper()
        option_symbol = str(row["option_symbol"]).upper()

        print(f"\n[ROW {idx}] {segment} {option_symbol}")

        # Validate/fix strike_price from symbol
        decoded_strike = decode_strike_from_symbol(option_symbol)
        if decoded_strike is not None:
            if "strike_price" in row and not pd.isna(row["strike_price"]):
                existing_strike = int(float(row["strike_price"]))
                if existing_strike != decoded_strike:
                    print(
                        f"  [INFO] Correcting strike_price from {existing_strike} "
                        f"to {decoded_strike} based on option_symbol."
                    )
                    df.at[idx, "strike_price"] = decoded_strike
            else:
                df.at[idx, "strike_price"] = decoded_strike

        # Entry premium
        entry_ts = parse_iso_timestamp(str(row["entry_time"])) if row.get("entry_time") else None
        if pd.isna(row.get("entry_premium")) or row.get("entry_premium") in ("", None):
            entry_prem = fetch_premium_for_row(kite_client, option_symbol, segment, entry_ts)
            if entry_prem is not None:
                df.at[idx, "entry_premium"] = entry_prem
                print(f"  [OK] entry_premium = {entry_prem:.2f}")
            else:
                print("  [WARN] Could not fetch entry_premium.")

        # Current premium (use update_time if present, else entry_time)
        update_time_val = row.get("update_time")
        curr_ts = parse_iso_timestamp(str(update_time_val)) if update_time_val else entry_ts

        if pd.isna(row.get("current_premium")) or row.get("current_premium") in ("", None):
            curr_prem = fetch_premium_for_row(kite_client, option_symbol, segment, curr_ts)
            if curr_prem is not None:
                df.at[idx, "current_premium"] = curr_prem
                print(f"  [OK] current_premium = {curr_prem:.2f}")
            else:
                print("  [WARN] Could not fetch current_premium.")

        updated_count += 1

    # Backup original
    backup_path = csv_path.with_suffix(csv_path.suffix + ".prem_backup")
    df_original = pd.read_csv(csv_path)
    df_original.to_csv(backup_path, index=False)
    print(f"\n[INFO] Original file backed up to: {backup_path}")

    # Save updated CSV
    df.to_csv(csv_path, index=False)
    print(f"[INFO] Backfill complete. Updated {updated_count} rows in: {csv_path}")


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        print("Usage: python backfill_option_premiums.py <open_positions_csv_path>")
        return
    csv_path = Path(argv[1])
    backfill_csv(csv_path)


if __name__ == "__main__":
    main(sys.argv)


