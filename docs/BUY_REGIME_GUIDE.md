# Buy Trade Regime - Complete Functionality Guide

## Overview

The **Buy Trade Regime** is designed for **buying options** (CE or PE) when specific technical conditions are met. This regime focuses on capturing directional moves in the underlying asset by purchasing options at optimal entry points.

---

## Core Concept

In Buy Regime:
- **CE (Call Option)**: Bought when expecting **bullish price movement** (price going up)
- **PE (Put Option)**: Bought when expecting **bearish price movement** (price going down)

The system uses **Price Strength (PS)** and **Volume Strength (VS)** indicators to identify optimal entry points.

---

## 1. Entry Conditions

### 1.1 Primary Signal: PS/VS Crossover

The system enters a trade when **Price Strength (PS)** crosses **Volume Strength (VS)**:

#### **CE Entry (Buy Call Option)**
- **Condition**: PS crosses **UP** to VS (Bullish Crossover)
- **Logic**: 
  - Before crossover: PS < VS
  - At crossover: PS ≥ VS
  - **Meaning**: Price momentum is strengthening relative to volume momentum → Bullish signal
- **Signal Generated**: `BUY_CE`

#### **PE Entry (Buy Put Option)**
- **Condition**: PS crosses **DOWN** to VS (Bearish Crossover)
- **Logic**:
  - Before crossover: PS > VS
  - At crossover: PS ≤ VS
  - **Meaning**: Price momentum is weakening relative to volume momentum → Bearish signal
- **Signal Generated**: `BUY_PE`

### 1.2 Crossover Detection Logic

- **Crossover Detection**: Happens on the **previous candle** (candle at `current_idx - 1`)
- **Entry Execution**: Happens on the **current candle** (candle at `current_idx`)
- **Why**: This ensures the crossover candle completes before entry, confirming the signal

**Example Timeline**:
```
Candle 1 (current_idx - 2): PS=50, VS=55  (Before crossover)
Candle 2 (current_idx - 1): PS=56, VS=54  (Crossover detected: PS crossed UP to VS)
Candle 3 (current_idx):     PS=58, VS=53  (Entry executed: BUY_CE)
```

---

## 2. Entry Filters

Before entering a trade, the system applies **three filters** to ensure optimal entry conditions:

### 2.1 Time Session Filter

**Purpose**: Avoid low-liquidity periods and reduce false signals.

**Buy Regime Settings**:
- **Avoid First 15 Minutes**: 09:30 - 09:45 (high volatility, false breakouts)
- **Avoid Last 15 Minutes**: 15:15 - 15:30 (low liquidity, erratic moves)
- **Optimal Trading Window**: **10:00 - 14:30**

**Configuration** (`config.json`):
```json
"time_session_filter": {
  "enabled": true,
  "avoid_first_minutes": 15,
  "avoid_last_minutes": 15,
  "buy_regime": {
    "start_hour": 10,
    "start_minute": 0,
    "end_hour": 14,
    "end_minute": 30
  }
}
```

**Behavior**:
- ✅ **PASS**: Current time is between 10:00 - 14:30
- ❌ **FAIL**: Current time is before 10:00 or after 14:30

---

### 2.2 ATR Volatility Filter

**Purpose**: Ensure sufficient volatility for option price movement.

**Buy Regime Settings**:
- **Minimum ATR Multiplier**: 1.0x (ATR must be ≥ average ATR)
- **Maximum ATR Multiplier**: None (no upper limit)
- **Logic**: Need volatility for options to move → Higher ATR = Better for Buy regime

**Configuration** (`config.json`):
```json
"atr_volatility_filter": {
  "enabled": true,
  "atr_period": 14,
  "buy_regime": {
    "min_atr_multiplier": 1.0,
    "max_atr_multiplier": null
  }
}
```

**Calculation**:
```
ATR Ratio = Current ATR / Average ATR (last 20 periods)
```

**Behavior**:
- ✅ **PASS**: ATR Ratio ≥ 1.0x (sufficient volatility)
- ❌ **FAIL**: ATR Ratio < 1.0x (low volatility, options won't move much)

---

### 2.3 RSI Extreme Filter

**Purpose**: Avoid entries when RSI is overbought/oversold (reversal risk).

**Buy Regime Settings**:

#### **CE Entry (Buy Call)**:
- **Maximum RSI**: 75
- **Logic**: Avoid buying CE when RSI > 75 (overbought, reversal risk)
- **Preference**: RSI between 30-70 for better entries

#### **PE Entry (Buy Put)**:
- **Minimum RSI**: 25
- **Logic**: Avoid buying PE when RSI < 25 (oversold, reversal risk)
- **Preference**: RSI between 30-70 for better entries

**Configuration** (`config.json`):
```json
"rsi_extreme_filter": {
  "enabled": true,
  "buy_regime": {
    "ce_max_rsi": 75,
    "pe_min_rsi": 25
  }
}
```

**Behavior**:
- ✅ **PASS (CE)**: RSI ≤ 75
- ❌ **FAIL (CE)**: RSI > 75 (overbought)
- ✅ **PASS (PE)**: RSI ≥ 25
- ❌ **FAIL (PE)**: RSI < 25 (oversold)

---

## 3. Multi-Timeframe Confirmation

**Purpose**: Confirm 5-minute signal with 1-minute data alignment.

### 3.1 1-Minute PS/VS Alignment

- **Check**: 1-minute PS/VS should align with 5-minute signal direction
- **CE Signal**: 1-minute PS should be above VS (or moving in that direction)
- **PE Signal**: 1-minute PS should be below VS (or moving in that direction)

### 3.2 Momentum Filter

- **Check**: 1-minute PS/VS momentum should support the signal
- **Threshold**: Momentum ≥ 0.5 (configurable)

### 3.3 Divergence Detection

- **Check**: No significant divergence between 5-minute and 1-minute PS/VS
- **Threshold**: Divergence < 2.0% (configurable)

### 3.4 Volume Confirmation

- **Check**: Volume spike on 1-minute data confirms the signal
- **Threshold**: Volume ≥ 1.5x average (configurable)

**Configuration** (`config.json`):
```json
"multi_timeframe_confirmation": {
  "enabled": true,
  "require_alignment": true,
  "momentum_threshold": 0.5
},
"divergence_detection": {
  "enabled": true,
  "threshold": 2.0
},
"volume_confirmation": {
  "enabled": true,
  "spike_threshold": 1.5
}
```

---

## 4. PS/VS Difference Threshold

**Purpose**: Ensure sufficient separation between PS and VS for meaningful signals.

**Configuration** (`config.json`):
```json
"strength_diff_conditions": {
  "enabled": true,
  "min_ps_vs_diff_pct": 2.0,
  "max_ps_vs_diff_pct": 5.0
}
```

**Calculation**:
```
PS/VS Difference % = |PS - VS| / max(|PS|, |VS|) × 100
```

**Behavior**:
- ✅ **PASS**: Difference between 2.0% - 5.0%
- ❌ **FAIL**: Difference < 2.0% (too close, weak signal) or > 5.0% (too extreme)

**Dynamic Thresholds** (if enabled):
- **Tight Range**: 2.0% - 3.0% (when 5-min and 1-min align)
- **Wide Range**: 3.0% - 20.0% (when 5-min and 1-min don't align)

---

## 5. Stop Loss (SL) Calculation

### 5.1 Buy Regime SL Logic

**Type**: **Fixed Points** (absolute value)

**Calculation**:
```
SL Price = Entry Premium - Stop Loss Points
```

**Example**:
- Entry Premium: ₹100
- Stop Loss: 30 points
- **SL Price**: ₹100 - 30 = **₹70**

**Configuration** (`config.json`):
```json
"segments": {
  "NIFTY": {
    "stop_loss": 30
  }
}
```

### 5.2 SL Order Placement

- **Order Type**: Stop Loss (SL-M)
- **Trigger Price**: SL Price (₹70 in example)
- **Limit Price**: Trigger Price + 1 (₹71 in example)
- **Product**: MIS (Intraday)
- **Validity**: DAY

**Important**: 
- SL is placed **immediately after entry order**
- SL order prices are rounded to whole numbers
- Difference between trigger and limit price is exactly 1

---

## 6. Exit Conditions

### 6.1 Primary Exit: Stop Loss Trigger

- **Exit Trigger**: When current premium reaches or crosses SL price
- **Execution**: SL order is executed by exchange
- **Result**: Position is automatically squared off

### 6.2 No Automatic Profit Target

- **Buy Regime**: Exits only via Stop Loss
- **No Trailing Stop**: Not implemented for Buy regime
- **No Target Exit**: System does not exit on profit targets

### 6.3 Manual Exit

- Positions can be manually squared off via dashboard
- Manual exit calculates P&L based on exit premium

---

## 7. P&L Calculation

### 7.1 Buy Regime P&L Logic

**For CE (Buy Call)**:
```
P&L Points = Current Premium - Entry Premium
P&L Value = P&L Points × Lot Size × Number of Lots
```

**For PE (Buy Put)**:
```
P&L Points = Current Premium - Entry Premium
P&L Value = P&L Points × Lot Size × Number of Lots
```

**Example**:
- Entry Premium: ₹100
- Current Premium: ₹120
- Lot Size: 75
- Lots: 1
- **P&L Points**: ₹120 - ₹100 = ₹20
- **P&L Value**: ₹20 × 75 × 1 = **₹1,500**

---

## 8. Position Management

### 8.1 Single Position Per Option Type

- **Buy Regime**: Only **one position** per option type (CE or PE) at a time
- **No Strangle**: Unlike Sell regime, Buy regime does not allow simultaneous CE and PE positions
- **Re-entry**: Allowed after SL hit, if crossover conditions are met again

### 8.2 Position Tracking

- **Entry Details Stored**:
  - Entry Premium
  - Entry Strike
  - Entry Spot Price
  - Entry Expiry
  - Trading Symbol
  - Entry Timestamp
  - Entry Reason (crossover details)

- **Current Position Monitoring**:
  - Current Premium (from Kite API)
  - Current P&L (points and value)
  - SL Status
  - Position Update Time

---

## 9. Complete Entry Flow

### Step-by-Step Process:

1. **Crossover Detection** (Previous Candle)
   - System detects PS/VS crossover on candle at `current_idx - 1`
   - Determines if it's CE (PS↑VS) or PE (PS↓VS) crossover

2. **Filter Checks** (Current Candle)
   - ✅ Time Session Filter: Check if within 10:00-14:30
   - ✅ ATR Volatility Filter: Check if ATR ≥ 1.0x average
   - ✅ RSI Extreme Filter: Check RSI limits (CE: ≤75, PE: ≥25)

3. **Multi-Timeframe Checks** (If Enabled)
   - ✅ 1-minute PS/VS alignment
   - ✅ Momentum filter
   - ✅ Divergence check
   - ✅ Volume confirmation

4. **PS/VS Difference Check**
   - ✅ Ensure PS/VS difference is within 2.0%-5.0% (or dynamic range)

5. **Entry Order Placement**
   - Calculate strike price (ATM or ITM based on config)
   - Fetch option premium from Kite API
   - Place entry order (BUY for CE/PE)
   - Wait for order execution

6. **Stop Loss Order Placement**
   - Calculate SL price: Entry Premium - Stop Loss Points
   - Round SL prices to whole numbers
   - Place SL order (SL-M)
   - Monitor SL status

7. **Position Monitoring**
   - Continuously monitor current premium
   - Calculate and log P&L
   - Check SL order status
   - Exit when SL triggers

---

## 10. Configuration Summary

### Complete Buy Regime Configuration:

```json
{
  "time_session_filter": {
    "enabled": true,
    "avoid_first_minutes": 15,
    "avoid_last_minutes": 15,
    "buy_regime": {
      "start_hour": 10,
      "start_minute": 0,
      "end_hour": 14,
      "end_minute": 30
    }
  },
  "atr_volatility_filter": {
    "enabled": true,
    "atr_period": 14,
    "buy_regime": {
      "min_atr_multiplier": 1.0,
      "max_atr_multiplier": null
    }
  },
  "rsi_extreme_filter": {
    "enabled": true,
    "buy_regime": {
      "ce_max_rsi": 75,
      "pe_min_rsi": 25
    }
  },
  "strength_diff_conditions": {
    "enabled": true,
    "min_ps_vs_diff_pct": 2.0,
    "max_ps_vs_diff_pct": 5.0
  },
  "multi_timeframe_confirmation": {
    "enabled": true,
    "require_alignment": true,
    "momentum_threshold": 0.5
  },
  "divergence_detection": {
    "enabled": true,
    "threshold": 2.0
  },
  "volume_confirmation": {
    "enabled": true,
    "spike_threshold": 1.5
  },
  "dynamic_threshold": {
    "enabled": true,
    "tight_range": [2.0, 3.0],
    "wide_range": [3.0, 20.0]
  },
  "segments": {
    "NIFTY": {
      "stop_loss": 30
    }
  }
}
```

---

## 11. Example Scenarios

### Scenario 1: Successful CE Entry

**Timeline**:
- **09:45**: PS=45, VS=50 (PS < VS)
- **09:50**: PS=52, VS=48 (PS crosses UP to VS) ← **Crossover Detected**
- **09:55**: System checks filters:
  - ✅ Time: 09:55 (within 10:00-14:30) - **WAIT** (too early)
- **10:00**: System checks filters:
  - ✅ Time: 10:00 (within 10:00-14:30) - **PASS**
  - ✅ ATR: 1.2x average - **PASS**
  - ✅ RSI: 65 (≤75) - **PASS**
  - ✅ Multi-timeframe: Aligned - **PASS**
  - ✅ PS/VS Diff: 3.5% - **PASS**
- **10:00**: **BUY_CE order placed** @ ₹100
- **10:00**: **SL order placed** @ ₹70 (100 - 30)
- **10:30**: Premium reaches ₹120 → P&L = ₹1,500
- **11:00**: Premium drops to ₹70 → **SL triggered** → Exit @ ₹70

**Result**: Entry @ ₹100, Exit @ ₹70, **Loss: ₹2,250** (30 points × 75 lots)

---

### Scenario 2: PE Entry Blocked by RSI Filter

**Timeline**:
- **10:15**: PS=60, VS=55 (PS > VS)
- **10:20**: PS=54, VS=56 (PS crosses DOWN to VS) ← **Crossover Detected**
- **10:25**: System checks filters:
  - ✅ Time: 10:25 - **PASS**
  - ✅ ATR: 1.1x average - **PASS**
  - ❌ RSI: 20 (<25) - **FAIL** ← **Entry Blocked**
- **10:25**: **No entry** - Logged: "PE entry blocked by RSI filter: RSI oversold: 20.00 < 25"

**Result**: No trade executed (filter protection)

---

### Scenario 3: CE Entry Blocked by Time Filter

**Timeline**:
- **09:35**: PS=48, VS=52 (PS < VS)
- **09:40**: PS=54, VS=50 (PS crosses UP to VS) ← **Crossover Detected**
- **09:45**: System checks filters:
  - ❌ Time: 09:45 (before 10:00) - **FAIL** ← **Entry Blocked**
- **09:45**: **No entry** - Logged: "CE entry blocked by time filter: Too early: Within first 15 minutes after market open"

**Result**: No trade executed (filter protection)

---

## 12. Key Differences: Buy vs Sell Regime

| Aspect | Buy Regime | Sell Regime |
|--------|-----------|-------------|
| **Entry Type** | Buy Options (CE/PE) | Sell Options (CE/PE) |
| **SL Type** | Fixed Points | Percentage-based |
| **SL Calculation** | Entry - Points | Entry + (Entry × %) |
| **Position Limit** | 1 per type (CE or PE) | Can have both (Strangle) |
| **Time Window** | 10:00 - 14:30 | 10:00-11:30, 12:00-14:30 |
| **ATR Requirement** | ≥ 1.0x (high volatility) | 0.8x - 1.5x (moderate) |
| **RSI for CE** | ≤ 75 (avoid overbought) | ≥ 60 (prefer overbought) |
| **RSI for PE** | ≥ 25 (avoid oversold) | ≤ 40 (prefer oversold) |
| **Exit Method** | SL only | SL only |

---

## 13. Troubleshooting

### Common Issues:

1. **No Entries Despite Crossovers**
   - Check filter logs for which filter is blocking
   - Verify time is within 10:00-14:30
   - Check ATR is ≥ 1.0x average
   - Verify RSI is within limits (CE: ≤75, PE: ≥25)

2. **SL Not Triggering**
   - Check SL order status in Kite
   - Verify SL price calculation (Entry - Points)
   - Ensure SL order was placed successfully

3. **Multiple Positions**
   - Buy regime should only have 1 position per type
   - Check if previous position was properly closed
   - Verify position sync with Kite API

---

## 14. Best Practices

1. **Monitor Filter Status**: Check logs to understand why entries are blocked
2. **Verify SL Placement**: Always confirm SL order is placed after entry
3. **Check Market Hours**: Ensure trading within optimal window (10:00-14:30)
4. **Review ATR**: Monitor ATR levels to understand volatility conditions
5. **RSI Awareness**: Understand RSI levels to avoid extreme entries

---

## 15. Logging and Monitoring

### Key Log Messages:

- **Crossover Detection**: `✅ BULLISH CROSSOVER DETECTED: PS crossed UP to VS`
- **Filter Status**: `✅ PASS: CE: Time session filter - Optimal session: 10:00-14:30`
- **Entry Blocked**: `❌ FAIL: CE entry blocked by RSI filter: RSI overbought: 78.50 > 75`
- **Entry Executed**: `✅ LIVE ENTRY ORDER PLACED: BUY_CE @ ₹100`
- **SL Placed**: `🛡️ STOP LOSS ORDER PLACED: SL Trigger @ ₹70`
- **Position Opened**: `✅ POSITION OPENED: BUY_CE strike=26000 Premium=₹100`

---

## Conclusion

The **Buy Trade Regime** is a comprehensive system for buying options based on PS/VS crossovers, with multiple filters to ensure optimal entry conditions. The system focuses on:

- **Quality over Quantity**: Multiple filters ensure only high-probability entries
- **Risk Management**: Fixed-point SL provides clear risk control
- **Time Optimization**: Trading only during optimal hours
- **Volatility Awareness**: ATR filter ensures sufficient movement potential
- **RSI Protection**: Avoids extreme RSI levels for better entries

For questions or issues, refer to the logs and filter status messages for detailed information about why entries are allowed or blocked.

