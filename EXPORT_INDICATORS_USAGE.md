# Export Indicators for TradingView Comparison

## Overview

This tool exports calculated RSI, PS (Price Strength), and VS (Volume Strength) values to CSV for easy comparison with TradingView's "Hilega Milega" indicator.

## Quick Start

### Export indicators for a specific date:

```bash
# Export SENSEX indicators for December 5, 2025
python export_indicators.py --segment SENSEX --date 2025-12-05

# Export NIFTY indicators for today
python export_indicators.py --segment NIFTY

# Export BANKNIFTY with custom interval
python export_indicators.py --segment BANKNIFTY --date 2025-12-05 --interval 5minute
```

## Command Line Arguments

| Argument | Options | Default | Description |
|----------|---------|---------|-------------|
| `--segment` | NIFTY, BANKNIFTY, SENSEX | SENSEX | Trading segment |
| `--date` | YYYY-MM-DD | Today | Target date |
| `--interval` | 1minute, 3minute, 5minute, 15minute, 30minute, 1hour | 5minute | Candle interval |
| `--rsi-period` | Integer | 9 | RSI period |
| `--ps-ema` | Integer | 3 | Price Strength EMA period |
| `--vs-wma` | Integer | 21 | Volume Strength WMA period |
| `--output` | File path | `indicators_<segment>_<date>.csv` | Output CSV file path |

## Output Format

The exported CSV contains the following columns:

- **Timestamp**: Candle timestamp
- **Open, High, Low, Close**: OHLC prices
- **Volume**: Trading volume
- **RSI**: RSI(9) value
- **PS**: Price Strength (EMA(3) of RSI)
- **VS**: Volume Strength (WMA(21) of RSI)
- **PS_VS_Diff**: PS - VS difference
- **Candle_Type**: Bullish, Bearish, or Neutral
- **Crossover_Type**: PE (PS↓VS), CE (PS↑VS), or None

## Example Output

```
Timestamp,Open,High,Low,Close,Volume,RSI,PS,VS,PS_VS_Diff,Candle_Type,Crossover_Type
2025-12-05 09:20:00,85700.0,85750.0,85680.0,85730.0,1000000,65.23,64.12,63.45,0.67,Bullish,None
2025-12-05 09:25:00,85730.0,85780.0,85720.0,85760.0,1200000,66.45,64.58,63.67,0.91,Bullish,None
2025-12-05 09:30:00,85760.0,85800.0,85750.0,85790.0,1500000,67.12,64.98,63.89,1.09,Bullish,CE (PS↑VS)
```

## Comparison with TradingView

1. **Export your data:**
   ```bash
   python export_indicators.py --segment SENSEX --date 2025-12-05
   ```

2. **Open TradingView:**
   - Load SENSEX chart with "Hilega Milega" indicator
   - Set indicator parameters: RSI(9), EMA(3), WMA(21)
   - Match the same date and timeframe

3. **Compare values:**
   - Open the exported CSV in Excel/Google Sheets
   - Compare RSI, PS, VS values with TradingView
   - Verify crossover events match

4. **Check for discrepancies:**
   - If values differ, check:
     - Data source (BSE vs NSE)
     - Candle boundaries (5-minute alignment)
     - RSI calculation method
     - EMA/WMA smoothing formulas

## Programmatic Usage

You can also use the export function programmatically:

```python
from src.trading.rsi_agent import RSIStrategy, Segment
import pandas as pd

# Initialize strategy
strategy = RSIStrategy(
    segment=Segment.SENSEX,
    rsi_period=9,
    price_strength_ema=3,
    volume_strength_wma=21
)

# Load your DataFrame (must have datetime index)
df = pd.DataFrame(...)  # Your OHLCV data
df.index = pd.to_datetime(df.index)

# Export to CSV
export_df = strategy.export_indicators_for_comparison(
    df,
    output_path="indicators.csv"
)

# Or get DataFrame without saving
export_df = strategy.export_indicators_for_comparison(df)
print(export_df[['Timestamp', 'RSI', 'PS', 'VS']].tail())
```

## Troubleshooting

### No data exported
- Ensure you have enough historical data (at least 21 candles for WMA)
- Check if Kite API is authenticated
- Verify the date has trading data

### Values don't match TradingView
- Check data source alignment (BSE vs NSE)
- Verify candle boundaries match exactly
- Compare RSI calculation method (Wilder's smoothing)
- Check EMA/WMA formulas match TradingView

### Authentication errors
- Run the main application first to authenticate Kite API
- Check `config/config.json` has valid credentials

## Notes

- The export function automatically skips candles with invalid indicators
- Minimum 21 candles required for Volume Strength WMA calculation
- Timestamps are preserved from the original DataFrame index
- Crossover detection compares current vs previous candle

