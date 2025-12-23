"""Quick test for 11:20 AM values using Kite API"""
import sys
from datetime import datetime

print("Starting...")
sys.stdout.flush()

from src.backtesting.data_fetcher import HistoricalDataFetcher
from src.trading.rsi_agent import RSIStrategy, Segment
from src.api.kite_client import KiteClient
from src.config.config_manager import ConfigManager

print("Imports done")
sys.stdout.flush()

entry_time = datetime(2025, 11, 27, 11, 20, 0)
segment = "BANKNIFTY"

print(f"Target: {entry_time}")
sys.stdout.flush()

config = ConfigManager()
print("Config loaded")
sys.stdout.flush()

kite_client = KiteClient(config)
print("Kite client created")
sys.stdout.flush()

print(f"Authenticated: {kite_client.is_authenticated()}")
sys.stdout.flush()

data_fetcher = HistoricalDataFetcher(kite_client)
print("Data fetcher created")
sys.stdout.flush()

from_date = entry_time.replace(hour=9, minute=15, second=0, microsecond=0)
to_date = entry_time.replace(hour=15, minute=30, second=0, microsecond=0)

print(f"Fetching from {from_date} to {to_date}...")
sys.stdout.flush()

df = data_fetcher.fetch_segment_data_from_kite(
    segment=segment,
    from_date=from_date,
    to_date=to_date,
    interval="5minute"
)

print(f"Data fetched: {len(df)} candles")
sys.stdout.flush()

if df.empty:
    print("Kite failed, trying Yahoo...")
    sys.stdout.flush()
    df = data_fetcher.fetch_segment_data(segment, from_date, to_date, "5minute")
    print(f"Yahoo data: {len(df)} candles")
    sys.stdout.flush()

if not df.empty:
    strategy = RSIStrategy(Segment.BANKNIFTY, rsi_period=9, price_strength_ema=3, volume_strength_wma=21)
    price_strength = strategy.calculate_price_strength(df)
    volume_strength = strategy.calculate_volume_strength(df)
    
    # Find 11:20
    for idx in range(len(df)):
        if abs((df.index[idx] - entry_time).total_seconds()) <= 300:
            print(f"\n=== VALUES AT 11:20 AM ===")
            print(f"Time: {df.index[idx]}")
            print(f"OHLC: {df.iloc[idx][['open','high','low','close']].to_dict()}")
            if idx >= 2:
                print(f"\nPrevious candle ({df.index[idx-1]}):")
                print(f"  PS: {price_strength.iloc[idx-1]:.2f}, VS: {volume_strength.iloc[idx-1]:.2f}")
                print(f"  Crossover: PS < VS -> PS >= VS? {price_strength.iloc[idx-2] < volume_strength.iloc[idx-2] and price_strength.iloc[idx-1] >= volume_strength.iloc[idx-1]}")
            print(f"Current: PS: {price_strength.iloc[idx]:.2f}, VS: {volume_strength.iloc[idx]:.2f}")
            break

