# How to Run the Updated Trading System

This guide explains how to run the updated program with the corrected Price Strength and Volume Strength calculations.

## Prerequisites

1. **Python 3.8+** installed
2. **Dependencies** installed:
   ```bash
   pip install -r requirements.txt
   ```
3. **Configuration** set up in `config/config.json`:
   - `api_key`: Your Zerodha API key
   - `access_token`: Your Zerodha access token
   - `volume_indicator`: Configured for Yahoo Finance

## Quick Start Options

### Option 1: Test with Diagnostic Script (Recommended First)

Test the updated calculations on a specific date:

```bash
# Test for November 27th, 2024 (default)
python diagnose_nov27.py

# Test for a specific date
python diagnose_nov27.py --date 2024-12-01

# Test with different segment
python diagnose_nov27.py --date 2024-12-01 --segment BANKNIFTY

# Test with different interval
python diagnose_nov27.py --date 2024-12-01 --segment NIFTY --interval 5minute

# Full custom example
python diagnose_nov27.py --date 2024-12-01 --segment BANKNIFTY --interval 15minute --rsi-period 9
```

**What it does:**
- Fetches data from Kite Connect
- Calculates RSI(9), Price Strength (EMA(3) of RSI), and Volume Strength (WMA(6) of RSI)
- Shows signal generation analysis
- Displays crossover events and why signals were/weren't generated

**Expected Output:**
```
✅ Fetched 500 candles from Kite Connect
✅ Strategy initialized: NIFTY with RSI period 9
📊 Running diagnostic analysis...

Price Strength: EMA(3) of RSI(9)
Volume Strength: WMA(6) of RSI(9)
...
```

### Option 2: Run Full Dashboard (Backtesting + Live Trading)

Start the main application with web dashboard:

```bash
python main.py
```

**What it does:**
- Starts the risk management system
- Launches web dashboard at `http://127.0.0.1:5000`
- Provides access to:
  - **Backtesting**: Test strategy on historical data
  - **Live Trader**: Run live trading (if authenticated)
  - **Dashboard**: Monitor positions and P&L

**Access the Dashboard:**
1. Open browser: `http://127.0.0.1:5000`
2. Navigate to **Backtesting** tab
3. Configure parameters and run backtest

### Option 3: Run Backtesting via Web UI

1. Start the main application:
   ```bash
   python main.py
   ```

2. Open browser: `http://127.0.0.1:5000/backtest/`

3. Configure backtest parameters:
   - **Segment**: NIFTY, BANKNIFTY, or SENSEX
   - **From Date**: Start date (e.g., 2024-11-01)
   - **To Date**: End date (e.g., 2024-11-30)
   - **Time Interval**: 5minute, 15minute, 30minute, 1hour
   - **RSI Period**: 9 (default, matches TradingView)
   - **Initial Capital**: Starting capital in ₹

4. Click **"Run Backtest"**

5. View results:
   - Summary metrics (Net P&L, Win Rate, etc.)
   - Detailed trade history
   - Export to Excel/CSV

### Option 4: Run Live Trader (Paper or Live Mode)

1. Start the main application:
   ```bash
   python main.py
   ```

2. Open browser: `http://127.0.0.1:5000/live-trader/`

3. Configure live trader:
   - **Segment**: NIFTY, BANKNIFTY, or SENSEX
   - **Mode**: PAPER (simulation) or LIVE (real trades)
   - **Timeframe**: 5minute, 15minute, etc.
   - **RSI Period**: 9

4. Click **"Start Live Trader"**

⚠️ **Warning**: LIVE mode places real orders. Use PAPER mode for testing.

## Understanding the Updated Calculations

The system now calculates:

1. **RSI(9)**: Relative Strength Index with period 9, calculated from close prices
2. **Price Strength**: EMA(3) applied on RSI(9) - Blue line
3. **Volume Strength**: WMA(6) applied on RSI(9) - Red line

**Signal Generation:**
- **PE Buy (Bearish)**: Price Strength crosses DOWN to Volume Strength + Red candle
- **CE Buy (Bullish)**: Price Strength crosses UP to Volume Strength + Green candle

## Command Line Arguments

### Diagnostic Script (`diagnose_nov27.py`)

| Argument | Options | Default | Description |
|----------|---------|---------|-------------|
| `--date` | YYYY-MM-DD | 2024-11-27 | Target date to diagnose |
| `--segment` | NIFTY, BANKNIFTY, SENSEX | NIFTY | Trading segment |
| `--interval` | 3minute, 5minute, 15minute, 30minute, 1hour | 5minute | Time interval |
| `--rsi-period` | Integer | 9 | RSI period |

## Troubleshooting

### Issue: "Access token not found"
**Solution**: Add `access_token` to `config/config.json`:
```json
{
  "access_token": "your-access-token-here"
}
```

### Issue: "Volume data not available"
**Solution**: The system will automatically:
1. Try Yahoo Finance (if configured)
2. Fall back to futures contracts
3. Fall back to proxy volume

Check `config/config.json`:
```json
{
  "volume_indicator": {
    "source": "yahoo",
    "fallback_to_futures": true,
    "fallback_to_proxy": true
  }
}
```

### Issue: "Insufficient data for RSI calculation"
**Solution**: Ensure you have at least 13 candles of historical data. The system needs:
- 9 candles for RSI(9)
- 3 more for EMA(3) of RSI
- 6 more for WMA(6) of RSI
- Total: 13+ candles minimum

### Issue: "No signals generated"
**Check:**
1. Verify crossover occurred (Price Strength vs Volume Strength)
2. Check candle type matches signal (Red for PE, Green for CE)
3. Run diagnostic script to see detailed analysis

## Example Workflow

### Step 1: Test Calculations
```bash
python diagnose_nov27.py --date 2024-12-01 --segment NIFTY --interval 5minute
```

### Step 2: Run Backtest
1. Start main app: `python main.py`
2. Open: `http://127.0.0.1:5000/backtest/`
3. Configure and run backtest

### Step 3: Analyze Results
- Review trade history
- Check win rate and P&L
- Export results for further analysis

### Step 4: Live Trading (Optional)
1. Test in PAPER mode first
2. Verify signals are correct
3. Switch to LIVE mode when ready

## Key Files

- `diagnose_nov27.py`: Diagnostic script for testing calculations
- `main.py`: Main application entry point
- `src/trading/rsi_agent.py`: Strategy implementation (updated calculations)
- `src/backtesting/backtest_engine.py`: Backtesting engine
- `src/HLML.py`: PVS calculation logic (reference implementation)

## Logs

Check logs for detailed information:
- `logs/app.log`: Application logs
- `logs/api.log`: API interaction logs
- `logs/risk.log`: Risk management logs

## Next Steps

1. ✅ Test with diagnostic script
2. ✅ Run backtest on historical data
3. ✅ Verify signal generation matches expectations
4. ✅ Test in PAPER mode before going LIVE

## Support

For issues or questions:
1. Check logs in `logs/` directory
2. Run diagnostic script for detailed analysis
3. Review `DIAGNOSTIC_USAGE.md` for diagnostic details
4. Review `BACKTESTING_SYSTEM.md` for backtesting details

