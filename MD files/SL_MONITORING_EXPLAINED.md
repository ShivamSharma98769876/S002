# Stop Loss (SL) Monitoring and Update Flow - Hybrid Approach

## Overview

With the **hybrid approach** (1-minute monitoring, 5-minute signal generation), the SL monitoring and updating system works as follows:

- **Signal Generation**: Uses 5-minute candles for PS/VS calculation (maintains signal quality)
- **Monitoring Frequency**: Checks every 1 minute for entry/exit/SL status (faster reaction)
- **SL Order Updates**: Updates trailing SL in Kite when premium moves favorably

---

## Complete SL Lifecycle Flow

### 1. **Initial SL Order Placement** (At Entry)

**When**: Immediately after entry order is placed

**Location**: `_handle_entry()` method

**Process**:
```
Entry Order Placed (e.g., BUY PE @ ₹340)
    ↓
Calculate Initial SL Price:
  - Buy Regime: SL = entry_premium - stop_loss (e.g., ₹340 - 50 = ₹290)
  - Sell Regime: SL = entry_premium + stop_loss (e.g., ₹340 + 50 = ₹390)
    ↓
Place SL Order in Kite:
  - Order Type: STOP LOSS (ORDER_TYPE_SL)
  - Trigger Price: Initial SL price
  - Transaction Type: Opposite of entry (BUY entry → SELL SL, SELL entry → BUY SL)
    ↓
Store SL Order Info:
  - sl_order_id: Order ID from Kite
  - sl_trigger_price: Initial SL price
  - sl_status: 'TRIGGER PENDING'
```

**Example**:
- Entry: BUY PE @ ₹340 (Buy regime)
- Initial SL: ₹290 (₹340 - 50)
- SL Order: SELL @ Trigger ₹290, Status: TRIGGER PENDING

---

### 2. **SL Status Monitoring** (Every 1 Minute)

**When**: Every monitoring interval (1 minute) - NEW with hybrid approach!

**Location**: `_handle_exit()` method (called from `_tick()`)

**Process**:
```
Every 1 Minute Tick:
    ↓
For each open position:
    ↓
Check SL Order Status in Kite:
  - Call: execution.get_sl_order_status(position_key)
  - Returns: 'TRIGGER PENDING', 'COMPLETE', 'CANCELLED', 'REJECTED'
    ↓
Based on Status:
  - COMPLETE → Exit position (SL hit)
  - CANCELLED → Allow new trades
  - TRIGGER PENDING → Continue monitoring
  - REJECTED → Exit position (error)
```

**Timeline Example**:
```
10:00 AM - Entry @ ₹340, SL @ ₹290 (TRIGGER PENDING)
10:01 AM - Check SL status → TRIGGER PENDING ✅ (continue)
10:02 AM - Check SL status → TRIGGER PENDING ✅ (continue)
10:03 AM - Check SL status → TRIGGER PENDING ✅ (continue)
10:04 AM - Check SL status → COMPLETE ❌ → Exit position
```

**Benefits of 1-Minute Monitoring**:
- ✅ Faster detection of SL execution (within 1 minute vs 5 minutes)
- ✅ Quicker reaction to SL hits
- ✅ Better risk management

---

### 3. **Trailing SL Calculation** (Every 5 Minutes or on Pyramiding)

**When**: 
- Every 5 minutes (position update interval)
- Immediately on pyramiding events

**Location**: `_update_open_position_in_csv()` method

**Process**:
```
Check if Update Needed:
  - Is pyramiding event? → Update immediately
  - 5 minutes passed since last update? → Update
  - First update? → Update
    ↓
Fetch Current Option Premium:
  - Get current premium from Kite API
  - Compare with entry premium
    ↓
Track Highest/Lowest Premium:
  - Buy Regime: Track highest_premium (premium increase = profit)
  - Sell Regime: Track lowest_premium (premium decrease = profit)
    ↓
Calculate Trailing SL:
  - Buy: trailing_sl = highest_premium - stop_loss
  - Sell: trailing_sl = lowest_premium + stop_loss
    ↓
Ensure One-Way Movement:
  - Buy: SL can only move UP (never below initial SL)
  - Sell: SL can only move DOWN (never above initial SL)
```

**Example (Buy Regime)**:
```
Entry: ₹340, Initial SL: ₹290

10:00 AM - Premium: ₹340, Highest: ₹340, Trailing SL: ₹290
10:05 AM - Premium: ₹360, Highest: ₹360, Trailing SL: ₹310 ✅ (moved up)
10:10 AM - Premium: ₹380, Highest: ₹380, Trailing SL: ₹330 ✅ (moved up)
10:15 AM - Premium: ₹350, Highest: ₹380, Trailing SL: ₹330 ✅ (stays, can't go down)
10:20 AM - Premium: ₹400, Highest: ₹400, Trailing SL: ₹350 ✅ (moved up)
```

**Example (Sell Regime)**:
```
Entry: ₹340, Initial SL: ₹390

10:00 AM - Premium: ₹340, Lowest: ₹340, Trailing SL: ₹390
10:05 AM - Premium: ₹320, Lowest: ₹320, Trailing SL: ₹370 ✅ (moved down)
10:10 AM - Premium: ₹300, Lowest: ₹300, Trailing SL: ₹350 ✅ (moved down)
10:15 AM - Premium: ₹330, Lowest: ₹300, Trailing SL: ₹350 ✅ (stays, can't go up)
10:20 AM - Premium: ₹280, Lowest: ₹280, Trailing SL: ₹330 ✅ (moved down)
```

---

### 4. **SL Order Modification in Kite** (When Trailing SL Changes)

**When**: 
- Every 5 minutes (when position update runs)
- Only if trailing SL changed by ≥ 0.5 points
- Only if SL order is still TRIGGER PENDING

**Location**: `_update_open_position_in_csv()` method (lines 1903-1935)

**Process**:
```
Calculate New Trailing SL (from step 3)
    ↓
Check if Modification Needed:
  - Previous SL trigger price exists?
  - Change ≥ 0.5 points? (minimum threshold)
  - SL order status = TRIGGER PENDING?
    ↓
If All Conditions Met:
  - Call: execution.modify_sl_order()
  - Pass: new_trigger_price, trade_regime
    ↓
Modify SL Order in Kite:
  - Update trigger_price in existing SL order
  - Update limit_price (trigger ± 0.5)
  - Get modified order ID
    ↓
Update Position Metadata:
  - sl_order_id: Updated (may be same or new)
  - sl_trigger_price: New trailing SL price
  - sl_status: Reset to 'TRIGGER PENDING'
```

**Example Timeline**:
```
10:00 AM - Entry @ ₹340, SL @ ₹290 (placed)
10:01 AM - Check SL status → TRIGGER PENDING (no update needed)
10:02 AM - Check SL status → TRIGGER PENDING (no update needed)
10:03 AM - Check SL status → TRIGGER PENDING (no update needed)
10:04 AM - Check SL status → TRIGGER PENDING (no update needed)
10:05 AM - Position update:
           - Premium: ₹360, Highest: ₹360
           - New Trailing SL: ₹310 (changed by 20 points)
           - Modify SL order: ₹290 → ₹310 ✅
10:06 AM - Check SL status → TRIGGER PENDING @ ₹310
10:07 AM - Check SL status → TRIGGER PENDING @ ₹310
...
10:10 AM - Position update:
           - Premium: ₹380, Highest: ₹380
           - New Trailing SL: ₹330 (changed by 20 points)
           - Modify SL order: ₹310 → ₹330 ✅
```

**Modification Conditions**:
- ✅ Change ≥ 0.5 points (avoids excessive API calls)
- ✅ SL order is TRIGGER PENDING (not executed/cancelled)
- ✅ Position update interval (5 minutes) has passed

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    ENTRY (10:00 AM)                          │
│  Entry Order: BUY PE @ ₹340                                  │
│  Initial SL: ₹290 (₹340 - 50)                               │
│  SL Order Placed: SELL @ Trigger ₹290                        │
│  Status: TRIGGER PENDING                                     │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│              MONITORING (Every 1 Minute)                     │
│                                                               │
│  10:01 AM → Check SL Status → TRIGGER PENDING ✅            │
│  10:02 AM → Check SL Status → TRIGGER PENDING ✅            │
│  10:03 AM → Check SL Status → TRIGGER PENDING ✅            │
│  10:04 AM → Check SL Status → TRIGGER PENDING ✅            │
│  10:05 AM → Position Update + Trailing SL Calculation       │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│         TRAILING SL UPDATE (10:05 AM)                        │
│                                                               │
│  Current Premium: ₹360                                       │
│  Highest Premium: ₹360 (updated)                             │
│  New Trailing SL: ₹310 (₹360 - 50)                          │
│  Change: ₹290 → ₹310 (20 points) ≥ 0.5 ✅                    │
│  Status: TRIGGER PENDING ✅                                   │
│  → Modify SL Order: ₹290 → ₹310                              │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│              MONITORING (Every 1 Minute)                     │
│                                                               │
│  10:06 AM → Check SL Status → TRIGGER PENDING @ ₹310 ✅     │
│  10:07 AM → Check SL Status → TRIGGER PENDING @ ₹310 ✅     │
│  10:08 AM → Check SL Status → TRIGGER PENDING @ ₹310 ✅     │
│  10:09 AM → Check SL Status → TRIGGER PENDING @ ₹310 ✅     │
│  10:10 AM → Position Update + Trailing SL Calculation       │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│         TRAILING SL UPDATE (10:10 AM)                        │
│                                                               │
│  Current Premium: ₹380                                       │
│  Highest Premium: ₹380 (updated)                             │
│  New Trailing SL: ₹330 (₹380 - 50)                          │
│  Change: ₹310 → ₹330 (20 points) ≥ 0.5 ✅                    │
│  Status: TRIGGER PENDING ✅                                   │
│  → Modify SL Order: ₹310 → ₹330                              │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│              MONITORING (Every 1 Minute)                     │
│                                                               │
│  10:11 AM → Check SL Status → TRIGGER PENDING @ ₹330 ✅     │
│  10:12 AM → Check SL Status → TRIGGER PENDING @ ₹330 ✅     │
│  10:13 AM → Premium drops to ₹325                           │
│  10:13 AM → Check SL Status → COMPLETE ❌                    │
│  → SL Order Executed → Exit Position                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 1. **Dual Monitoring System**
- **SL Status Check**: Every 1 minute (fast reaction)
- **Trailing SL Update**: Every 5 minutes (efficient)

### 2. **Smart Update Logic**
- Only modifies if change ≥ 0.5 points (reduces API calls)
- Only modifies if SL order is TRIGGER PENDING
- One-way movement (never moves backward)

### 3. **Premium-Based Calculation**
- Uses option premium (not spot price) for SL calculation
- Tracks highest/lowest premium for trailing stop
- More accurate for options trading

### 4. **Status-Driven Exits**
- Exit based on SL order status (not spot movement)
- COMPLETE = SL hit, exit immediately
- CANCELLED = Allow new trades
- TRIGGER PENDING = Continue monitoring

---

## Benefits of Hybrid Approach

### Before (5-Minute Monitoring):
- SL status checked every 5 minutes
- Trailing SL updated every 5 minutes
- Delayed reaction to SL hits

### After (1-Minute Monitoring):
- ✅ SL status checked every 1 minute (5x faster)
- ✅ Trailing SL updated every 5 minutes (efficient)
- ✅ Faster reaction to SL hits (within 1 minute)
- ✅ Better risk management

---

## Summary

**SL Monitoring Flow**:
1. **Place SL** → Immediately after entry
2. **Monitor Status** → Every 1 minute (check if executed)
3. **Calculate Trailing** → Every 5 minutes (based on premium movement)
4. **Update SL Order** → When trailing SL changes ≥ 0.5 points
5. **Exit on SL Hit** → When SL order status = COMPLETE

**Key Points**:
- Monitoring happens every 1 minute (fast)
- Trailing SL updates every 5 minutes (efficient)
- SL order modification only when needed (≥ 0.5 points change)
- Exit based on SL order status (not spot price)

This hybrid approach provides the best of both worlds: **fast monitoring** (1 minute) with **efficient updates** (5 minutes) while maintaining **signal quality** (5-minute candles).

