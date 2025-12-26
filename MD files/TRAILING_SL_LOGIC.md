# Trailing Stop Loss Logic by Trade Regime

## Overview

Trailing Stop Loss (TSL) automatically adjusts the stop loss level as the position moves favorably, locking in profits while allowing for continued gains. The logic differs between **Buy** and **Sell** regimes.

---

## Buy Regime (Buying Options)

### Concept
- **Profit when:** Premium increases (option gains value)
- **SL Direction:** Moves UP as premium increases
- **SL Type:** Absolute points (fixed distance)

### Initial SL Calculation
```
Entry Premium: ₹100
Stop Loss: 50 points
Initial SL = ₹100 - 50 = ₹50
```

### Trailing SL Logic
```
Trailing SL = highest_premium_reached - stop_loss_points
```

**Key Points:**
- Tracks **highest premium** reached since entry
- SL moves UP when premium increases
- SL **never moves DOWN** (one-way movement)
- Minimum SL = Initial SL (can't go below entry - stop_loss)

### Example Scenario (Buy Regime)

```
Time    Premium   Highest   Trailing SL   Action
10:00   ₹100      ₹100      ₹50           Entry (Initial SL)
10:05   ₹120      ₹120      ₹70           ✅ SL moves UP (120 - 50)
10:10   ₹150      ₹150      ₹100          ✅ SL moves UP (150 - 50)
10:15   ₹140      ₹150      ₹100          ❌ SL stays (can't move down)
10:20   ₹130      ₹150      ₹100          ❌ SL stays
10:25   ₹95       ₹150      ₹100          Monitoring
10:30   ₹99       ₹150      ₹100          EXIT! (premium ≤ SL)
```

**Logic:**
- Premium rises to ₹150 → SL moves to ₹100
- Premium drops to ₹140 → SL stays at ₹100 (locked profit)
- Premium hits ₹99 → Exit triggered (below SL)

---

## Sell Regime (Selling Options)

### Concept
- **Profit when:** Premium decreases (option loses value)
- **SL Direction:** Moves DOWN as premium decreases
- **SL Type:** Percentage-based (% of premium)

### Initial SL Calculation
```
Entry Premium: ₹50
Stop Loss: 30% (for NIFTY)
SL Amount = 30% of ₹50 = ₹15
Initial SL = ₹50 + ₹15 = ₹65
```

### Trailing SL Logic
```
Trailing SL = lowest_premium_reached + (stop_loss% / 100 × lowest_premium)
```

**Key Points:**
- Tracks **lowest premium** reached since entry
- SL moves DOWN when premium decreases (favorable movement)
- SL **never moves UP** (one-way movement)
- Maximum SL = Initial SL (can't go above entry + stop_loss%)
- Uses **percentage** of premium (not absolute points)

### Example Scenario (Sell Regime - NIFTY 30%)

```
Time    Premium   Lowest    SL Amount   Trailing SL   Action
10:00   ₹50       ₹50       ₹15          ₹65           Entry (Initial SL)
10:05   ₹45       ₹45       ₹13.50       ₹58.50       ✅ SL moves DOWN (45 + 13.50)
10:10   ₹40       ₹40       ₹12          ₹52          ✅ SL moves DOWN (40 + 12)
10:15   ₹35       ₹35       ₹10.50       ₹45.50       ✅ SL moves DOWN (35 + 10.50)
10:20   ₹38       ₹35       ₹10.50       ₹45.50       ❌ SL stays (can't move up)
10:25   ₹42       ₹35       ₹10.50       ₹45.50       ❌ SL stays
10:30   ₹48       ₹35       ₹10.50       ₹45.50       Monitoring
10:35   ₹46       ₹35       ₹10.50       ₹45.50       EXIT! (premium ≥ SL)
```

**Logic:**
- Premium drops to ₹35 → SL moves to ₹45.50 (35 + 30% of 35)
- Premium rises to ₹38 → SL stays at ₹45.50 (locked profit)
- Premium hits ₹46 → Exit triggered (above SL)

### Detailed Calculation Example (Sell Regime)

**NIFTY Example (30%):**
```
Entry Premium: ₹50
Initial SL = ₹50 + (30% of ₹50) = ₹50 + ₹15 = ₹65

If premium drops to ₹40:
  Lowest Premium = ₹40
  SL Amount = 30% of ₹40 = ₹12
  Trailing SL = ₹40 + ₹12 = ₹52 ✅

If premium drops further to ₹30:
  Lowest Premium = ₹30
  SL Amount = 30% of ₹30 = ₹9
  Trailing SL = ₹30 + ₹9 = ₹39 ✅

If premium rises to ₹35:
  Lowest Premium = ₹30 (stays)
  Trailing SL = ₹39 (stays) ❌ Can't move up
```

**BANKNIFTY Example (40%):**
```
Entry Premium: ₹80
Initial SL = ₹80 + (40% of ₹80) = ₹80 + ₹32 = ₹112

If premium drops to ₹60:
  SL Amount = 40% of ₹60 = ₹24
  Trailing SL = ₹60 + ₹24 = ₹84 ✅
```

**SENSEX Example (50%):**
```
Entry Premium: ₹100
Initial SL = ₹100 + (50% of ₹100) = ₹100 + ₹50 = ₹150

If premium drops to ₹70:
  SL Amount = 50% of ₹70 = ₹35
  Trailing SL = ₹70 + ₹35 = ₹105 ✅
```

---

## Comparison Table

| Feature | Buy Regime | Sell Regime |
|---------|-----------|-------------|
| **Profit Direction** | Premium increases | Premium decreases |
| **SL Type** | Absolute points | Percentage (%) |
| **Tracks** | Highest premium | Lowest premium |
| **SL Movement** | Moves UP | Moves DOWN |
| **One-Way** | Never moves DOWN | Never moves UP |
| **Calculation** | `highest - points` | `lowest + (lowest × %)` |
| **Example** | ₹150 - 50 = ₹100 | ₹35 + (35 × 30%) = ₹45.50 |

---

## Key Rules

### 1. **One-Way Movement**
- **Buy:** SL only moves UP, never DOWN
- **Sell:** SL only moves DOWN, never UP

### 2. **Boundary Protection**
- **Buy:** Trailing SL can never go below Initial SL
- **Sell:** Trailing SL can never go above Initial SL

### 3. **Update Frequency**
- SL is recalculated on every position update (every monitoring interval)
- SL order in Kite is modified when change ≥ 0.5 points

### 4. **Exit Trigger**
- **Buy:** Exit when `current_premium ≤ trailing_sl`
- **Sell:** Exit when `current_premium ≥ trailing_sl`

---

## Visual Example

### Buy Regime:
```
Premium:    100 → 120 → 150 → 140 → 130 → 95 → EXIT
Trailing:   50 →  70 → 100 → 100 → 100 → 100 → TRIGGERED
            ↑     ↑     ↑     ↑     ↑     ↑
          Entry Moves Moves Stays Stays Exit
                 UP    UP   Same  Same
```

### Sell Regime (30%):
```
Premium:    50 → 45 → 40 → 35 → 38 → 42 → 48 → EXIT
Trailing:   65 → 58.5 → 52 → 45.5 → 45.5 → 45.5 → 45.5 → TRIGGERED
            ↑     ↑      ↑     ↑      ↑      ↑      ↑
          Entry Moves  Moves Moves  Stays  Stays  Exit
                DOWN   DOWN  DOWN   Same  Same
```

---

## Summary

1. **Buy Regime:** Tracks highest premium, SL moves up with fixed points distance
2. **Sell Regime:** Tracks lowest premium, SL moves down with percentage-based distance
3. **Both:** One-way movement only, protects profits as position moves favorably
4. **Both:** SL order automatically modified in Kite when significant change occurs

