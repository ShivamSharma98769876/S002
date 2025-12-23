## Live Trader System Specification

### 1. Overview

The **Live Trader** system is an intraday options trading engine that uses the **same RSI Divergence + Trend Reversal strategy** as the backtesting module, but operates on **live market data**.

Initial goal:
- Run the full strategy **in real time** in **Paper / Simulation mode**, without placing actual broker orders.
- Log all trades, stop-losses, and key events to **CSV/Excel** so performance can be evaluated before enabling live execution.

Future goal:
- Switch the same logic to **Live Trading mode** (with broker execution) once the paper results are satisfactory.

Supported segments (each traded independently):
- `NIFTY`
- `BANKNIFTY`
- `SENSEX`


### 2. System Architecture

#### 2.1 High-level components

- **Segment Agents**
  - `NiftyAgent`
  - `BankNiftyAgent`
  - `SensexAgent`
  - Each agent:
    - Runs **asynchronously / in parallel**, independent of the others.
    - Subscribes to **live candles** for its index (NIFTY 50, BANKNIFTY, SENSEX) at the chosen timeframe (e.g. 5m). use the kte API for the Live
	data, don't use Yahoo Api for "Live Trader".The Access details of KIte API will be used from "Risk Management Dashboard"
    - Maintains its own state: open position, lots, SL, trailing SL, P&L, etc.
    - Uses the same `RSIStrategy` and `RSITradingAgent` logic as the backtester.

- **Signal Engine**
  - Re-uses the backtest strategy logic:
    - Input: OHLCV candles for the index using kte API for the Live data, don't use Yahoo Api for "Live Trader", The Access details of KIte API will be used from "Risk Management Dashboard".
    - Output: `BUY_CE`, `BUY_PE`, or `HOLD` signals.
  - Timeframe and RSI period are configurable (default: **5m**, **RSI 9**).

- **Instrument Selector**
  - Converts index spot price to the specific **options contract** to trade.
  - For each signal:
    - **Buy (CE)** signal → select **ITM Call option**.
    - **Sell (PE)** signal → select **ITM Put option**.
  - The distance from ATM to ITM (e.g. 100 points) is configurable.

- **Risk & Position Manager**
  - Enforces **one active position per segment** (or configurable max).
  - Applies **stop loss**, **trailing stop**, and **time-based exit** (e.g. 15:15 square-off).
  - (Future) Integrates with global **daily risk controls** (max daily loss, max trades, etc.).

- **Execution Adapter**
  - **Paper mode** (initial implementation):
    - Simulates entries and exits.
    - Writes all trade details and P&L into CSV/Excel files.
  - **Live mode** (future):
    - Sends orders via broker API (e.g. Zerodha), using the same interface.
    - Still logs trades to CSV for audit.

- **Live Trader UI**
  - New page: `Live Trader`.
  - Lets the user:
    - Select segments and parameters.
    - Start/stop the live engine.
    - Monitor current positions and P&L.
    - Download daily CSV logs.


### 3. Strategy Logic (Same as Backtest)

The Live Trader uses the **same core RSI strategy** that was validated in backtesting.

#### 3.1 Entry rules (Revised)

- **RSI Period**: Default **9** (configurable).
- **Timeframe**: Default **5-minute candles** (configurable: 3m, 5m, 15m, 30m, 1h).
- **Price Strength**: 3 EMA (Exponential Moving Average) of price (blue line)
- **Volume Strength**: 6 WMA (Weighted Moving Average) of volume (red line)

- **PE Buy (Bearish setup)**:
  - Price must be in a **Bearish/Red candle** (current timeframe must be red)
  - **Price Strength (blue line) crosses downwards to Volume Strength (red line)** from above
  - RSI blue line crosses downwards red line from above (downward crossover)
  - If SL hits → re-enter on every new red candle until trend confirms

- **CE Buy (Bullish setup)**:
  - Price must be in a **Bullish/Green candle** (current timeframe must be green)
  - **Price Strength (blue line) crosses upward to Volume Strength (red line)** from below
  - RSI blue line crosses upward red line from below (upward crossover)
  - If SL hits → re-enter on every new green candle until trend confirms

The Live Trader evaluates these conditions on each new completed candle from the live feed.

#### 3.2 Exit rules

Exit logic mirrors the backtest engine:

- **Stop Loss (SL)**
  - Defined in **points**, not percentage.
  - Default: **50 points** (configurable per segment).
  - For CE (long): exit if price drops `SL_points` below entry.
  - For PE (short): exit if price rises `SL_points` above entry.

- **Trailing Stop Loss (TSL)**
  - Trailing stop moves in the direction of profit:
    - For CE: trailing SL = current price − trailing_stop_points.
    - For PE: trailing SL = current price + trailing_stop_points.
  - TSL level is only adjusted in a favorable direction (never relaxed).
  - Exit if price hits the trailing SL level.

- **Time-based exit**
  - All open positions are force-closed near market close (e.g. **15:15**).
  - Reason logged as: `EOD square-off`.


### 4. Instrument Selection (Options)

Each agent converts an index signal into a specific options trade.

#### 4.1 ATM and ITM calculation

- **ATM strike** rules (same as backtest engine, configurable if needed):
  - NIFTY: nearest multiple of **50**.
  - BANKNIFTY: nearest multiple of **100**.
  - SENSEX: nearest multiple of **100**.

- **ITM offset (points)**:
  - Configurable parameter, default **100 points**.
  - For **Buy CE** signals:
    - ITM strike = ATM strike **− ITM_offset_points**.
  - For **Buy PE** (short direction) signals:
    - ITM strike = ATM strike **+ ITM_offset_points**.

- **Expiry selection**:
  - Default: **nearest available expiry** for the chosen index options.
  - In future, can be overridden via UI (e.g. choose weekly or monthly expiry explicitly).
  
- **Lot selection**:
  - Default: System will identify the Lot size based on the Index and start the trade with the 1 Lot for the chosen index options. keep the Lot size in Config file and reference from there 

#### 4.2 Pyramid on Lots
- **Pyramid concept**:

  - Default: System will add the lots after certin points achived. so add the field next to Segment like Pyramid and keep the default like for Nifty 10, BAnknifty 20 and sensex 20. add "Lot Addition" field also and defalt to 5 for Nifty, for BankNifty and Sensex default to 10 
  once Total Profit is equal to or greater than the (Number of Quantity traded * Pyramid) than add additional lots defined in "Lot Addition" corrosponding to Segment, this has to be repeated only whne again same condition apears like in Nifty Profit for individual trade > Quantity * Pyramid
  Example for Nifty 
  Initaly Quantity Traded 	75 (Lot Size)
  Pyramid 					5
  "Lot Addition"			5
  Limit on the Maximim	Qty 1500
	Profit in the current trade 250, nothing to be done 
	Profit reached to 		75*5=375 or more, the system will add lots defined in  "Lot Addition" field. in this case total lots will be 6 and quantity will be 75*6=450
	now next Pyramiding will happen only when profit is greater than 450*5 =2250
	The pyramiding will keep happening until max quantiy reached to 1500
	System will keep the lot size in config file for dynamic calculation.
	
 Example for BankNifty 
  Initaly Quantity Traded 	35 (Lot Size)
  Pyramid 					20
  "Lot Addition"			10
  Limit on the Maximim	Qty 1000
	Profit in the current trade 250, nothing to be done 
	Profit reached to 		35*20=750 or more, the system will add lots defined in  "Lot Addition" field. in this case total lots will be 11 and quantity will be 35*11=385
	now next Pyramiding will happen only when profit is greater than 385*20 =7700
	The pyramiding will keep happening until max quantiy reached to 1000
	System will keep the lot size in config file for dynamic calculation.
	
Example for Sansex  
  Initaly Quantity Traded 	20 (Lot Size)
  Pyramid 					20
  "Lot Addition"			10
  Limit on the Maximim	Qty 1000
	Profit in the current trade 250, nothing to be done 
	Profit reached to 		20*20=400 or more, the system will add lots defined in  "Lot Addition" field. in this case total lots will be 11 and quantity will be 20*11=220
	now next Pyramiding will happen only when profit is greater than 220*20 =4400
	The pyramiding will keep happening until max quantiy reached to 1000
	System will keep the lot size in config file for dynamic calculation.
	
- **SL update on Pyramiding **:
	
	Quantity of the Stoploss order will always in sysnc with the Quantity are being traded or Pyramiding, meand SL quantity also be updated on sucessful Pyramiding. 
  


### 5. Modes of Operation

#### 5.1 Paper Trading Mode (Monitoring Mode)

This is the **only mode implemented initially** to safely evaluate the strategy in live conditions.

- No real broker orders are placed.
- Every entry, SL, TSL update, and exit is:
  - Simulated in memory.
  - Recorded to CSV/Excel with timestamps and prices.
- The system behaves **as if** it is trading live:
  - Uses real-time candles.
  - Computes RSI and signals.
  - Selects instruments.
  - Applies SL and TSL.
  - Produces full trade statistics.

This mode allows detailed analysis and comparison with backtest results before going live.

#### 5.2 Live Trading Mode (Future)

When enabled later:

- The **same logic** will run, but:
  - Orders are sent to the broker (e.g. Zerodha Kite) using a pluggable execution client.
  - SL and TSL will be managed via live orders or bracket/OCO structures where supported.
- All trades are still logged to CSV for transparency and performance review.


### 6. Live Trader UI – Parameters and Controls

The `Live Trader` page mirrors the **Backtest Parameters** but is focused on **real-time control**.

#### 6.1 Controls

- **Mode**
  - `Paper` (default) / `Live` (future toggle, initially disabled).

- **Segments**
  - Checkboxes: `NIFTY`, `BANKNIFTY`, `SENSEX`.
  - Each selected segment spawns or activates its corresponding agent.

- **Strategy Parameters** (per session)
  - `Time Interval` (candle timeframe):
    - Options: 3m, **5m (default)**, 15m, 30m, 1h.
  - `RSI Period`:
    - Default: **9**.
  - `Initial Capital (₹)`:
    - Used for simulated P&L and return calculations.
  - `Stop Loss (Points)`:
    - Default: **50 points**.
  - `Trailing Stop (Points)`:
    - Default: equal to SL (e.g. 50), can be tuned.
  - `ITM Offset (Points)`:
    - Default: **100 points**.
    - Distance from ATM to ITM strike for both CE and PE trades.

- **Risk / Session Parameters** (recommended)
  - Max trades per segment per day (e.g. 5).
  - Max daily loss per segment (₹).
  - Global trading window (e.g. from 9:20 to 15:15).

- **Session control**
  - `Start Live Trader` button:
    - Validates inputs and starts agents in Paper mode.
  - `Stop Live Trader` button:
    - Stops new entries.
    - Option to immediately close all open simulated positions.

#### 6.2 Status & Monitoring

- Per-segment status cards:
  - State: `IDLE`, `WAITING FOR SIGNAL`, `IN POSITION`.
  - If in position:
    - Option symbol, strike, expiry.
    - Direction: CE/PE.
    - Entry price, SL, trailing SL.
    - Current simulated P&L.
  - Today’s stats (Paper mode):
    - Total trades.
    - Win rate.
    - Net P&L.

- Event log / recent actions:
  - Table listing recent:
    - Signals detected (even if not traded).
    - Entries taken and ignored signals (e.g. due to risk limits).
    - SL/TSL updates.
    - Exits and reasons.

- Export:
  - Button: `Download Today’s Trades (CSV)`
  - Optional: `Download Today’s Events (CSV)`.


### 7. Logging & Excel / CSV Output

Logging is critical for validating the system before real-money trading.

#### 7.1 Trade log file

- File naming:
  - `live_trades_<YYYY-MM-DD>.csv`

- One row per **completed trade** (entry + exit) in Paper mode or Live mode.

- Recommended columns:
  - `trade_id`
  - `mode` (PAPER / LIVE)
  - `segment` (NIFTY/BANKNIFTY/SENSEX)
  - `index_symbol` (e.g. NIFTY 50)
  - `index_entry_spot`
  - `time_interval`
  - `rsi_period`
  - `signal_type` (BUY_CE / BUY_PE)
  - `option_symbol`
  - `option_type` (CE/PE)
  - `strike_price`
  - `expiry`
  - `lots`
  - `entry_time`
  - `entry_price`
  - `stop_loss_points`
  - `initial_sl_price`
  - `trailing_stop_points`
  - `exit_time`
  - `exit_price`
  - `exit_reason` (SL hit / Trailing SL / EOD square-off / Manual / Risk limit)
  - `pnl_points`
  - `pnl_value`
  - `return_pct`
  - (Optional) `max_favorable_excursion`, `max_adverse_excursion`

#### 7.2 Event log file (optional)

- File naming:
  - `live_events_<YYYY-MM-DD>.csv`

- One row per **significant event**:
  - New candle processed.
  - Signal generated.
  - Entry attempted / skipped.
  - SL/TSL updated.
  - Exit executed.

- Useful for deep debugging and comparison with broker logs.


### 8. Configuration & Risk Controls

To make the system safer and more controllable, several parameters should be configurable through either JSON config or the UI.

- **Per-segment config**
  - Lot size and lot multiplier.
  - ITM offset (points).
  - Stop loss and trailing stop (points).
  - Max trades per day.
  - Allowed trading time window.

- **Global risk controls**
  - Daily net loss limit (blocks new trades when breached).
  - Daily profit target (optional, can stop trading after a strong day).
  - Ability to pause all agents from the UI.


### 9. Future Enhancements

Suggested next steps once the basic Live Trader (Paper mode) is stable:

- Add **fixed profit targets** (e.g. exit after X points profit) in addition to SL and TSL.
- Integrate with existing **risk management modules**:
  - Daily loss protection.
  - Profit protection.
  - Trailing SL at account level.
- Build **performance dashboards** that compare:
  - Backtest results vs Live-Paper results for the same period.
  - Per-segment equity curves and drawdowns.
- Implement **Live mode** with:
  - Real broker order placement and SL management.
  - Strong safety checks and dry-run modes.

This document defines the functional and architectural requirements for the **Live Trader** system so it can be implemented, tested in Paper mode, and later upgraded to full live trading with confidence.


