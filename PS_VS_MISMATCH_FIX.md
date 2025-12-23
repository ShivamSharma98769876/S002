# PS/VS Mismatch with TradingView - Issue and Fix

## Problem Description

**Symptom**: Logs show PS > VS, but TradingView shows PS < VS at the same time.

**Example from logs**:
```
2025-12-19 10:26:48 - INFO - Indicators :: PS=57.48, VS=50.16
2025-12-19 10:26:48 - INFO - CE: Bullish crossover (PS crosses UP to VS) detected on previous candle: FAIL 
  (❌ NO BULLISH CROSSOVER: PS was already above VS | Before: PS=53.91 ≥ VS=47.89 → Current: PS=55.03 > VS=48.94)
```

But TradingView shows PS **below** VS at 10:26:00.

## Root Cause

The system was using **OLD candles from a different time window** when the exact expected candle wasn't available from the API.

### What Was Happening:

1. **At 10:26:48**, the system expects candle at **10:25:00** (window **10:20–10:25**)
2. **Kite API** hasn't published that candle yet (it's still forming or delayed)
3. **System falls back** to the "most recent usable candle" from API
4. **Finds candle at 10:21:48** (window **10:15–10:20**) - this is **OLD data**
5. **Calculates PS/VS** on this old candle → PS=57.48, VS=50.16 (PS > VS)
6. **TradingView** shows the completed **10:20–10:25** candle → PS < VS

**Result**: PS/VS values don't match because we're looking at different candles!

### Why This Happens:

- **Kite API delay**: The API may not publish the exact candle immediately when it completes
- **Window mismatch**: Using a candle from a different 5-minute window gives different PS/VS values
- **PS/VS are cumulative**: These indicators depend on historical RSI values, so using the wrong candle window causes incorrect calculations

## Solution

Modified the candle selection logic in `src/live_trader/agents.py` to:

1. **Only use candles from the SAME window** as expected
2. **Check database first** if API doesn't have the exact window
3. **Skip signal** if the correct window candle isn't available (prevents PS/VS mismatch)

### New Logic Flow:

```
1. Try to get exact candle from API
   ├─ Found? → Use it ✅
   └─ Not found? → Check for candles from SAME window
      ├─ Found same window candle? → Use it ✅
      └─ Not found? → Check database
         ├─ Database has same window? → Use it ✅
         └─ Database also different window? → Skip signal ⛔
            (Prevents PS/VS mismatch)
```

### Key Changes:

1. **Window matching**: Only accepts candles from the expected window (e.g., 10:20–10:25)
2. **Database fallback**: Checks database for the correct window candle before giving up
3. **Skip instead of mismatch**: Rather than using wrong data, skip the signal to avoid incorrect PS/VS calculations

## Verification

To verify the fix is working:

1. **Run the diagnostic script**:
   ```bash
   python diagnose_ps_vs_mismatch.py --segment NIFTY --time "2025-12-19 10:26:00"
   ```

2. **Check logs** for:
   - ✅ "Found candle from API (same window)" - Good!
   - ✅ "Using database candle (same window)" - Good!
   - ⛔ "Skipping signal: Expected candle window ... not available" - System is protecting against mismatch

3. **Compare with TradingView**:
   - PS/VS values should now match when the correct candle is used
   - If values still don't match, check:
     - Are you using the same timeframe? (5-minute)
     - Are you looking at the same candle window?
     - Are the indicator settings identical? (RSI=9, PS=EMA(3), VS=WMA(21))

## WMA Calculation Verification

The WMA calculation was verified to match TradingView:

- **TradingView WMA**: `(n*P1 + (n-1)*P2 + ... + 1*Pn) / sum`
  - Where P1 = newest, Pn = oldest
- **Our WMA**: `1*oldest + 2*... + n*newest / sum`
  - These are mathematically equivalent ✅

The issue was **NOT** the calculation, but **using the wrong candle data**.

## Impact

- **Before**: System used old candles → PS/VS mismatch → Wrong signals
- **After**: System waits for correct candle → PS/VS match → Correct signals

**Trade-off**: Some signals may be skipped if the API is delayed, but this is better than using incorrect data.

## Related Files

- `src/live_trader/agents.py` - Candle selection logic (modified)
- `src/trading/rsi_agent.py` - PS/VS calculation (verified correct)
- `diagnose_ps_vs_mismatch.py` - Diagnostic script (new)

