# Trading Signal Diagnostic Tool

## Overview
The `diagnose_nov27.py` script helps you diagnose why trades were not identified for a specific date. It analyzes the Price Strength vs Volume Strength crossover conditions and identifies why signals were or weren't generated.

## Prerequisites
1. Kite API authentication must be set up (login through the web interface first)
2. Python environment with all dependencies installed
3. Historical data access via Kite API

## Usage

### Basic Usage (November 27th, 2024)
```bash
python diagnose_nov27.py
```

### Custom Date
```bash
python diagnose_nov27.py --date 2024-11-27
```

### Custom Segment
```bash
python diagnose_nov27.py --date 2024-11-27 --segment BANKNIFTY
```

### Custom Time Interval
```bash
python diagnose_nov27.py --date 2024-11-27 --segment NIFTY --interval 5minute
```

### Full Custom Example
```bash
python diagnose_nov27.py --date 2024-11-27 --segment BANKNIFTY --interval 15minute --rsi-period 9
```

## Command Line Arguments

| Argument | Options | Default | Description |
|----------|---------|---------|-------------|
| `--date` | YYYY-MM-DD | 2024-11-27 | Target date to diagnose |
| `--segment` | NIFTY, BANKNIFTY, SENSEX | NIFTY | Trading segment |
| `--interval` | 3minute, 5minute, 15minute, 30minute, 1hour | 5minute | Time interval for candles |
| `--rsi-period` | Integer | 9 | RSI period |

## Output

The script provides:

1. **Signal Summary**
   - Total signals found
   - PE signals count
   - CE signals count

2. **Crossover Events**
   - List of all crossovers that occurred
   - Whether each crossover generated a signal
   - Price Strength and Volume Strength values

3. **Candle Type Distribution**
   - Bullish, bearish, and neutral candles

4. **Data Quality Issues**
   - Missing volume data
   - Zero volume candles
   - NaN values in indicators

5. **Reasons for No Signals**
   - Crossover occurred but wrong candle type
   - No crossovers occurred
   - Data quality issues

## Understanding the Results

### If No Signals Were Generated:

1. **Check Crossover Events**
   - If crossovers occurred but no signals: The candle type didn't match
   - PE needs: Red candle + Price Strength crossing down to Volume Strength
   - CE needs: Green candle + Price Strength crossing up to Volume Strength

2. **Check Data Quality**
   - Missing or zero volume will prevent Volume Strength calculation
   - Ensure OHLC data is complete

3. **Check Indicator Values**
   - Price Strength (3 EMA) should be calculated
   - Volume Strength (6 WMA) needs at least 6 candles

## Example Output

```
================================================================================
SIGNAL DIAGNOSTIC REPORT
================================================================================
Total Candles Analyzed: 75
Starting Index: 9

Signals Found: 2
  - PE Signals: 1
  - CE Signals: 1

Candle Type Distribution:
  - Bullish: 35
  - Bearish: 38
  - Neutral: 2

Crossover Events: 5
  - 2024-11-27 09:30:00: PE crossover, PS: 24500.5→24498.2, VS: 24502.1→24500.8, Candle: bearish, Signal: YES
  - 2024-11-27 10:15:00: CE crossover, PS: 24510.2→24512.5, VS: 24508.5→24511.2, Candle: bullish, Signal: YES
  ...

Reasons No Signals Generated:
  - Crossover occurred but candle is bullish (need bearish): 2 times
  - Crossover occurred but candle is bearish (need bullish): 1 times
================================================================================
```

## Troubleshooting

### "Kite client is not authenticated"
- Login through the web interface first
- Ensure `config.json` has valid credentials

### "No data fetched"
- Check if the date is a trading day (not weekend/holiday)
- Verify the segment name is correct
- Ensure historical data is available for that period

### "No data found for target date"
- The date might be a holiday or weekend
- Check available date range in the output

## Notes

- The script fetches data from 2 days before to 1 day after the target date to ensure indicator calculations have enough historical data
- Volume Strength (6 WMA) requires at least 6 candles
- Price Strength (3 EMA) requires at least 1 candle
- The script analyzes all candles but focuses on the target date

