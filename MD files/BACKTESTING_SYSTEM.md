# RSI Strategy Backtesting System

## Overview
A comprehensive backtesting system for the RSI Divergence + Trend Reversal strategy on intraday options trading. The system allows you to test your strategy on historical data and analyze performance metrics.

## Features

### 1. RSI Trading Agent (`src/trading/rsi_agent.py`)
- **RSI Strategy Implementation**: Implements the RSI Divergence + Trend Reversal strategy with Price Strength vs Volume Strength
- **Entry Conditions**:
  - **PE Buy (Bearish setup)**:
    * Price must be in a Bearish/Red candle (current timeframe must be red)
    * Price Strength (blue line) crosses downwards to Volume Strength (red line) from above
    * RSI blue line crosses downwards red line from above (downward crossover)
    * If SL hits → re-enter on every new red candle until trend confirms
  - **CE Buy (Bullish setup)**:
    * Price must be in a Bullish/Green candle (current timeframe must be green)
    * Price Strength (blue line) crosses upward to Volume Strength (red line) from below
    * RSI blue line crosses upward red line from below (upward crossover)
    * If SL hits → re-enter on every new green candle until trend confirms
- **Exit Conditions**: Stop Loss, Trailing Stop Loss, Target
- **Re-entry Logic**: After Stop Loss hit, system automatically re-enters on matching candle type (red for PE, green for CE) until trend confirms
- **Scaling Rules**: Adds lots at profit milestones (segment-specific)

### 2. Backtesting Engine (`src/backtesting/backtest_engine.py`)
- Runs backtests on historical data
- Tracks all trades with entry/exit details
- Calculates comprehensive performance metrics:
  - Total trades, Win rate, Profit factor
  - Net P&L, Max drawdown, Return percentage
  - Winning vs losing trades

### 3. Historical Data Fetcher (`src/backtesting/data_fetcher.py`)
- Fetches historical OHLCV data from Zerodha Kite API
- Supports multiple segments (NIFTY, SENSEX, BANKNIFTY)
- Handles instrument token resolution
- Supports 15-minute timeframe (as per strategy)

### 4. Backtesting UI (`src/ui/templates/backtest.html`)
- Beautiful, modern interface matching dashboard design
- Parameter configuration panel
- Real-time backtest execution
- Comprehensive results display
- Export to Excel/CSV functionality

## Usage

### Accessing the Backtesting System
1. Start the application: `python main.py`
2. Navigate to: `http://127.0.0.1:5000/backtest/`
3. Or click "Backtesting" link from the dashboard

### Running a Backtest

1. **Configure Parameters**:
   - **Segment**: Choose NIFTY, SENSEX, or BANKNIFTY
   - **From Date**: Start date for backtest
   - **To Date**: End date for backtest
   - **RSI Period**: RSI calculation period (default: 14)
   - **Initial Capital**: Starting capital in ₹ (default: ₹100,000)
   - **Expiry**: Optional option expiry date

2. **Run Backtest**: Click "Run Backtest" button

3. **View Results**:
   - Summary metrics (Net P&L, Win Rate, etc.)
   - Detailed trade history with:
     - Entry/Exit time and price
     - Spot price
     - P&L and Return %
     - Exit reason (Stop Loss, Trailing SL, Target)

4. **Export Results**: Click "Export to Excel" to download CSV file

## Strategy Details

### Segment-Specific Parameters

#### NIFTY
- Initial Lot: 1
- Stop Loss: ₹20
- Trailing Stop: ₹20
- Lot 2: Add 5 lots at ₹750 profit
- Lot 3: Add 5 lots at ₹3,750 profit
- Lot 4: Add 5 lots at ₹5,000 profit

#### SENSEX / BANKNIFTY
- Initial Lot: 1
- Stop Loss: ₹50
- Trailing Stop: ₹50
- Lot 2: Add 10 lots at ₹400 profit
- Lot 3: Add 10 lots at ₹4,000 profit
- Lot 4: Add 10 lots at ₹10,000 profit

### Entry Rules
- **Timeframe**: Configurable (default: 5-minute candles, supports 3m, 5m, 15m, 30m, 1h)
- **RSI Period**: Default 9 (configurable)
- **Price Strength**: 3 EMA (Exponential Moving Average) of price (blue line)
- **Volume Strength**: 6 WMA (Weighted Moving Average) of volume (red line)
- **PE Entry (Bearish)**:
  * Current candle must be red/bearish (close < open)
  * Price Strength (blue) crosses DOWNWARDS to Volume Strength (red) from above
  * RSI blue line crosses downwards red line from above
- **CE Entry (Bullish)**:
  * Current candle must be green/bullish (close > open)
  * Price Strength (blue) crosses UPWARD to Volume Strength (red) from below
  * RSI blue line crosses upward red line from below

### Exit Rules
- **Stop Loss**: Fixed stop loss per segment (in points)
- **Trailing Stop Loss**: Trails profit by fixed amount (in points)
- **Re-entry After SL**: 
  * If SL hits on PE trade → re-enter on every new red candle until trend confirms
  * If SL hits on CE trade → re-enter on every new green candle until trend confirms
  * Re-entry continues until a successful trade confirms the trend

## API Endpoints

### `GET /backtest/`
Backtesting page UI

### `POST /backtest/run`
Run backtest with parameters:
```json
{
  "segment": "NIFTY",
  "from_date": "2024-01-01",
  "to_date": "2024-01-31",
  "rsi_period": 14,
  "initial_capital": 100000,
  "expiry": "2024-01-25"  // Optional
}
```

### `GET /backtest/status`
Check authentication status

## Requirements

The system requires:
- Zerodha Kite API authentication
- Historical data access (via Kite API)
- pandas and numpy for data processing

## Performance Metrics

The backtesting system calculates:
- **Total Trades**: Number of completed trades
- **Win Rate**: Percentage of winning trades
- **Net P&L**: Total profit minus total loss
- **Profit Factor**: Total profit / Total loss
- **Return %**: Percentage return on initial capital
- **Max Drawdown**: Maximum peak-to-trough decline
- **Winning/Losing Trades**: Breakdown of trade outcomes

## Export Format

Exported CSV includes:
1. Summary section with all metrics
2. Trade history with:
   - Entry/Exit timestamps
   - Entry/Exit prices
   - Spot prices
   - Lots traded
   - P&L and Return %
   - Exit reasons

## Integration

The backtesting system is fully integrated with:
- Main application (`main.py`)
- Dashboard UI (with navigation link)
- Risk management system (uses same Kite client)

## Notes

- Backtests require authenticated Kite client
- Date range limited to 365 days
- Historical data depends on Zerodha API availability
- Results are calculated based on close prices (15-min candles)
- Slippage and transaction costs not included in calculations

## Future Enhancements

Potential improvements:
- Multiple strategy comparison
- Walk-forward optimization
- Monte Carlo simulation
- Performance charts and graphs
- Strategy parameter optimization
- Real-time paper trading mode

