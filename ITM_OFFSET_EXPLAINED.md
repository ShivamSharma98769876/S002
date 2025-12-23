# ITM Offset (Points) - Complete Explanation

## What is ITM Offset?

**ITM Offset** is the distance (in points) from the **ATM (At The Money)** strike to select the trading strike for options.

## How It Works

The formula in the code (`select_itm_strike` function):

```python
# For CE (Call Options):
strike = ATM - itm_offset

# For PE (Put Options):
strike = ATM + itm_offset
```

## Understanding Different Values

### Positive ITM Offset (e.g., +100)

**Meaning**: Selects **ITM (In The Money)** strikes

**Example with NIFTY spot = 24,000:**
- ATM Strike = 24,000 (rounded to nearest 50)
- ITM Offset = +100

**For CE (Call Option)**:
- Strike = 24,000 - 100 = **23,900** ✅ (ITM - below spot)
- This is ITM because spot (24,000) > strike (23,900)
- Premium: Higher (ITM options cost more)
- Delta: Higher (~0.6-0.8)
- Probability: Higher chance of profit

**For PE (Put Option)**:
- Strike = 24,000 + 100 = **24,100** ✅ (ITM - above spot)
- This is ITM because spot (24,000) < strike (24,100)
- Premium: Higher (ITM options cost more)
- Delta: Higher (~0.6-0.8)
- Probability: Higher chance of profit

---

### Negative ITM Offset (e.g., -100)

**Meaning**: Selects **OTM (Out of The Money)** strikes

**Example with NIFTY spot = 24,000:**
- ATM Strike = 24,000
- ITM Offset = -100

**For CE (Call Option)**:
- Strike = 24,000 - (-100) = 24,000 + 100 = **24,100** ❌ (OTM - above spot)
- This is OTM because spot (24,000) < strike (24,100)
- Premium: Lower (OTM options cost less)
- Delta: Lower (~0.2-0.4)
- Probability: Lower chance of profit, but higher reward if it moves

**For PE (Put Option)**:
- Strike = 24,000 + (-100) = 24,000 - 100 = **23,900** ❌ (OTM - below spot)
- This is OTM because spot (24,000) > strike (23,900)
- Premium: Lower (OTM options cost less)
- Delta: Lower (~0.2-0.4)
- Probability: Lower chance of profit, but higher reward if it moves

---

### Zero ITM Offset (0)

**Meaning**: Selects **ATM (At The Money)** strikes

**Example with NIFTY spot = 24,000:**
- ATM Strike = 24,000
- ITM Offset = 0

**For CE (Call Option)**:
- Strike = 24,000 - 0 = **24,000** (ATM)
- Premium: Moderate
- Delta: ~0.5
- Probability: Moderate

**For PE (Put Option)**:
- Strike = 24,000 + 0 = **24,000** (ATM)
- Premium: Moderate
- Delta: ~0.5
- Probability: Moderate

---

## Visual Examples

### Example 1: NIFTY Spot = 24,000, ITM Offset = +100

```
Spot Price: 24,000
ATM Strike: 24,000

CE Strike: 24,000 - 100 = 23,900 (ITM) ✅
  └─ Spot (24,000) > Strike (23,900) → ITM Call

PE Strike: 24,000 + 100 = 24,100 (ITM) ✅
  └─ Spot (24,000) < Strike (24,100) → ITM Put
```

### Example 2: NIFTY Spot = 24,000, ITM Offset = -100

```
Spot Price: 24,000
ATM Strike: 24,000

CE Strike: 24,000 - (-100) = 24,100 (OTM) ❌
  └─ Spot (24,000) < Strike (24,100) → OTM Call

PE Strike: 24,000 + (-100) = 23,900 (OTM) ❌
  └─ Spot (24,000) > Strike (23,900) → OTM Put
```

### Example 3: NIFTY Spot = 24,000, ITM Offset = -200

```
Spot Price: 24,000
ATM Strike: 24,000

CE Strike: 24,000 - (-200) = 24,200 (Deep OTM) ❌
  └─ Further OTM, cheaper premium, lower probability

PE Strike: 24,000 + (-200) = 23,800 (Deep OTM) ❌
  └─ Further OTM, cheaper premium, lower probability
```

---

## Comparison Table

| ITM Offset | CE Strike (Spot=24,000) | PE Strike (Spot=24,000) | Type | Premium | Delta | Risk/Reward |
|------------|------------------------|-------------------------|------|---------|-------|-------------|
| **+200** | 23,800 | 24,200 | Deep ITM | Very High | ~0.8-0.9 | Lower Risk, Lower Reward |
| **+100** | 23,900 | 24,100 | ITM | High | ~0.6-0.7 | Moderate Risk, Moderate Reward |
| **0** | 24,000 | 24,000 | ATM | Moderate | ~0.5 | Balanced |
| **-100** | 24,100 | 23,900 | OTM | Low | ~0.2-0.3 | Higher Risk, Higher Reward |
| **-200** | 24,200 | 23,800 | Deep OTM | Very Low | ~0.1-0.2 | Very High Risk, Very High Reward |

---

## When to Use Negative ITM Offset (-100)

### Advantages:
1. **Lower Premium Cost**: OTM options are cheaper
2. **Higher Leverage**: Same capital can buy more contracts
3. **Higher Potential Returns**: If move is strong, OTM can give higher % returns
4. **Lower Break-Even**: For CE, break-even is strike + premium (lower strike = lower break-even)

### Disadvantages:
1. **Lower Probability**: OTM options have lower chance of ending in profit
2. **Time Decay**: OTM options lose value faster (theta decay)
3. **Lower Delta**: Smaller price movement per point of underlying move
4. **Higher Risk**: More likely to expire worthless

---

## Real-World Example: ITM Offset = -100

**Scenario**: NIFTY spot = 24,000, Signal = BUY CE

### With ITM Offset = +100 (ITM):
- Strike Selected: 23,900 CE
- Premium: ₹150 (example)
- Investment: ₹150 × 75 lots = ₹11,250
- Break-Even: 23,900 + 150 = 24,050
- If NIFTY goes to 24,200: Profit = (24,200 - 24,050) × 75 = ₹11,250 (100% return)
- Probability: Higher (ITM has intrinsic value)

### With ITM Offset = -100 (OTM):
- Strike Selected: 24,100 CE
- Premium: ₹50 (example - cheaper!)
- Investment: ₹50 × 75 lots = ₹3,750
- Break-Even: 24,100 + 50 = 24,150
- If NIFTY goes to 24,200: Profit = (24,200 - 24,150) × 75 = ₹3,750 (100% return)
- Probability: Lower (OTM has no intrinsic value)

**Key Difference**: 
- OTM requires **stronger move** to be profitable (needs to cross 24,150 vs 24,050)
- But costs **less** (₹3,750 vs ₹11,250)
- Same % return if move is strong enough, but lower probability

---

## Recommendation

### Use Positive ITM Offset (+50 to +150):
- ✅ Higher probability trades
- ✅ Better for consistent profits
- ✅ Lower risk
- ✅ Good for beginners

### Use Negative ITM Offset (-50 to -150):
- ⚠️ Only if you expect **strong moves**
- ⚠️ Higher risk, higher reward
- ⚠️ Requires good market timing
- ⚠️ Better for experienced traders

### Use Zero (0):
- ✅ Balanced approach
- ✅ ATM options
- ✅ Moderate risk/reward

---

## Summary

**ITM Offset = -100 means**:
- **CE**: Selects strike **100 points ABOVE** ATM (OTM Call)
- **PE**: Selects strike **100 points BELOW** ATM (OTM Put)
- **Result**: Cheaper premiums, lower probability, higher risk/reward ratio
- **Use Case**: When expecting strong directional moves

**Note**: The parameter name "ITM Offset" is a bit misleading when negative - it actually selects OTM strikes. A better name might be "Strike Offset" or "ATM Offset".

