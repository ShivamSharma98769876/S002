# Testing Guide: Candle Fallback Mechanism

## What Changed
The system now uses the **most recent completed candle** when the exact expected candle isn't available from the API, instead of skipping the signal entirely.

## How to Test

### 1. **Monitor Live Trading Logs**

Watch the log files for your segments:
- `logs/LIVE_NIFTY_YYYY-MM-DD.log`
- `logs/LIVE_BANKNIFTY_YYYY-MM-DD.log`
- `logs/LIVE_SENSEX_YYYY-MM-DD.log`

Or use the Live Trader dashboard at: `http://127.0.0.1:5000/live`

### 2. **What to Look For**

#### ✅ **Success Case - Exact Candle Found:**
```
✅ Found candle from API (exact): 2025-12-12 10:05:00 [Window 10:00–10:05] ...
```
This means the exact candle was found - **no change in behavior**.

#### ⚠️ **New Behavior - Using Closest Candle:**
```
⚠️ Exact candle 2025-12-12 10:05:00 not found, using closest available: 2025-12-12 10:04:00 [Window 09:59–10:04] (diff: 1.0 min)
```
This is the **new fallback behavior** - the system found a nearby candle and is using it.

#### ⛔ **Still Skipping - Candle Too Far:**
```
⛔ Skipping signal: Exact candle 2025-12-12 10:05:00 not available, and closest candle 2025-12-12 09:55:00 is too far (10.0 min away)
```
This means the closest candle is more than 5 minutes away - signal is still skipped (safety measure).

### 3. **Expected Improvements**

**Before the change:**
- You would see: `⛔ Skipping signal: Exact candle ... not available from API`
- Signals were completely missed

**After the change:**
- You should see: `⚠️ Exact candle ... not found, using closest available: ...`
- Signals are generated using the closest available candle (if within 5 minutes)

### 4. **Verification Checklist**

- [ ] System is running in LIVE or PAPER mode
- [ ] Check logs during active trading hours (9:15 AM - 3:30 PM IST)
- [ ] Look for the new warning message: `⚠️ Exact candle ... not found, using closest available`
- [ ] Verify signals are being generated when they previously would have been skipped
- [ ] Confirm trades are being taken correctly with the fallback candle

### 5. **When This Happens Most**

The fallback is most likely to trigger:
- **Right after a candle completes** (e.g., at 10:06:00, looking for 10:05:00 candle)
- **During high volatility periods** when API might be slightly delayed
- **During market open** (9:15-9:30 AM) when data is still stabilizing

### 6. **Monitoring Commands**

**Windows PowerShell:**
```powershell
# Watch NIFTY logs in real-time
Get-Content logs\LIVE_NIFTY_2025-12-12.log -Wait -Tail 50

# Search for fallback messages
Select-String -Path logs\LIVE_*.log -Pattern "Exact candle.*not found, using closest"
```

**Linux/Mac:**
```bash
# Watch logs in real-time
tail -f logs/LIVE_NIFTY_2025-12-12.log

# Search for fallback messages
grep "Exact candle.*not found, using closest" logs/LIVE_*.log
```

### 7. **What Success Looks Like**

✅ **Good signs:**
- Fewer "Skipping signal" messages
- More signals being generated
- Trades being taken that previously would have been missed
- Warning messages show small time differences (< 2 minutes)

⚠️ **Watch out for:**
- Frequent fallback messages with large time differences (> 3 minutes) - might indicate API issues
- Trades being taken on stale data - should not happen as we check candle age

### 8. **If Issues Occur**

If you see problems:
1. Check the time difference in the warning message
2. Verify the candle data looks correct (OHLC values)
3. Monitor if signals are being generated correctly
4. Check if trades are being taken appropriately

---

**Note:** This change prioritizes **not missing signals** while maintaining data quality by only using candles within 5 minutes of the expected time.

