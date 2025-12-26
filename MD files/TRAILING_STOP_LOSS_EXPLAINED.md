# Trailing Stop Loss Logic Explained

This document explains the two types of trailing stop loss systems in the trading application.

## 1. Per-Trade Trailing Stop Loss (Price-Based)

This trailing stop loss is applied to **each individual trade** and follows the price movement.

### How It Works

#### For CE (Call Options) - Profit when price goes UP:
```
Entry Price: ₹24,000
Trailing Stop: 50 points

Price Movement:
₹24,000 → Trailing SL = ₹23,950 (24,000 - 50)
₹24,100 → Trailing SL = ₹24,050 (24,100 - 50) ✅ Moves UP
₹24,200 → Trailing SL = ₹24,150 (24,200 - 50) ✅ Moves UP
₹24,050 → Trailing SL = ₹24,150 (stays at highest) ❌ Can't move DOWN
₹24,000 → Exit triggered! (price ≤ trailing SL)
```

**Logic:**
- Trailing SL = `current_price - trailing_stop_points`
- Only moves UP when price rises (never moves down)
- Exits when `current_price ≤ trailing_stop_price`

#### For PE (Put Options) - Profit when price goes DOWN:
```
Entry Price: ₹85,953.83
Trailing Stop: 50 points

Price Movement:
₹85,953.83 → Trailing SL = ₹86,003.83 (85,953.83 + 50)
₹85,900 → Trailing SL = ₹85,950 (85,900 + 50) ✅ Moves DOWN
₹85,800 → Trailing SL = ₹85,850 (85,800 + 50) ✅ Moves DOWN
₹85,900 → Trailing SL = ₹85,850 (stays at lowest) ❌ Can't move UP
₹85,900 → Exit triggered! (price ≥ trailing SL)
```

**Logic:**
- Trailing SL = `current_price + trailing_stop_points`
- Only moves DOWN when price falls (never moves up)
- Exits when `current_price ≥ trailing_stop_price`

### Key Features:
- ✅ **Always Active**: Starts from entry, no activation threshold
- ✅ **Price-Based**: Follows price movement in real-time
- ✅ **One-Way Movement**: Only moves in favorable direction
- ✅ **Locks Profit**: Protects profit as price moves favorably

### Example Scenario (CE):
```
Entry: ₹24,000 at 10:00 AM
Trailing Stop: 50 points

10:05 AM - Price: ₹24,050 → Trailing SL: ₹24,000
10:10 AM - Price: ₹24,100 → Trailing SL: ₹24,050 ✅
10:15 AM - Price: ₹24,150 → Trailing SL: ₹24,100 ✅
10:20 AM - Price: ₹24,080 → Trailing SL: ₹24,100 (stays) ❌
10:25 AM - Price: ₹24,090 → Exit! (24,090 ≤ 24,100)
```

## 2. Daily Profit-Based Trailing Stop Loss (System-Wide)

This trailing stop loss is applied to **total daily profit** across all trades and positions.

### How It Works

```
Activation Threshold: ₹5,000
Increment Amount: ₹10,000

Profit Movement:
₹0 → No trailing SL (inactive)
₹5,000 → Trailing SL activated at ₹5,000 ✅
₹10,000 → Trailing SL = ₹10,000 ✅
₹15,000 → Trailing SL = ₹10,000 (stays)
₹20,000 → Trailing SL = ₹20,000 ✅
₹25,000 → Trailing SL = ₹20,000 (stays)
₹30,000 → Trailing SL = ₹30,000 ✅
₹18,000 → Exit triggered! (profit ≤ trailing SL)
```

**Logic:**
- Activates when total daily profit ≥ ₹5,000
- Initial trailing SL = ₹5,000
- Updates every ₹10,000 increment:
  - Profit ₹5k-₹9k → SL = ₹5k
  - Profit ₹10k-₹19k → SL = ₹10k
  - Profit ₹20k-₹29k → SL = ₹20k
  - Profit ₹30k-₹39k → SL = ₹30k
  - And so on...
- Only moves UP (never down)
- Exits ALL positions when profit drops to trailing SL level

### Key Features:
- ✅ **Activation Threshold**: Only activates after ₹5,000 profit
- ✅ **Profit-Based**: Based on total daily profit, not individual prices
- ✅ **System-Wide**: Applies to all positions combined
- ✅ **Incremental Updates**: Moves in ₹10,000 increments
- ✅ **One-Way Movement**: Only moves up, never down

### Example Scenario:
```
9:30 AM - Start trading
10:00 AM - Profit: ₹3,000 → No trailing SL (below threshold)
10:30 AM - Profit: ₹5,500 → Trailing SL activated at ₹5,000 ✅
11:00 AM - Profit: ₹12,000 → Trailing SL = ₹10,000 ✅
11:30 AM - Profit: ₹22,000 → Trailing SL = ₹20,000 ✅
12:00 PM - Profit: ₹18,000 → Exit ALL positions! (profit ≤ ₹20,000 SL)
```

## Comparison

| Feature | Per-Trade Trailing SL | Daily Profit Trailing SL |
|---------|----------------------|-------------------------|
| **Scope** | Individual trade | All trades combined |
| **Activation** | Immediately on entry | After ₹5,000 profit |
| **Based On** | Price movement | Total daily profit |
| **Update Frequency** | Every candle/price update | Every ₹10,000 profit increment |
| **Movement** | Follows price (one-way) | Follows profit (one-way) |
| **Exit Trigger** | Price hits trailing SL | Profit drops to trailing SL |
| **Configuration** | Per-segment (20-50 points) | System-wide (₹5k activation, ₹10k increment) |

## Configuration

### Per-Trade Trailing Stop Loss
Set in segment parameters:
- **NIFTY**: 20 points
- **BANKNIFTY**: 50 points
- **SENSEX**: 50 points

### Daily Profit Trailing Stop Loss
Set in `config/admin_config.json`:
```json
{
  "trailing_sl_activation": 5000.0,  // Activate at ₹5,000
  "trailing_sl_increment": 10000.0   // Update every ₹10,000
}
```

## Visual Example

### Per-Trade Trailing SL (CE):
```
Price:    24,000 → 24,100 → 24,200 → 24,150 → 24,100 → EXIT
Trailing: 23,950 → 24,050 → 24,150 → 24,150 → 24,150 → TRIGGERED
          ↑       ↑       ↑       ↑       ↑
        Entry   Moves   Moves   Stays   Exit
                 UP      UP     Same
```

### Daily Profit Trailing SL:
```
Profit:   ₹0 → ₹5k → ₹12k → ₹22k → ₹18k → EXIT ALL
Trailing: -  → ₹5k → ₹10k → ₹20k → ₹20k → TRIGGERED
          ↑    ↑     ↑      ↑      ↑
        Inactive Active Moves Moves Exit
                         UP    UP
```

## Summary

1. **Per-Trade Trailing SL**: Protects individual trades by following price movement
   - CE: Moves up as price rises
   - PE: Moves down as price falls
   - Always active from entry

2. **Daily Profit Trailing SL**: Protects total daily profit
   - Activates at ₹5,000 profit
   - Updates every ₹10,000 increment
   - Exits all positions when profit drops

Both systems work together to protect your capital and lock in profits!

