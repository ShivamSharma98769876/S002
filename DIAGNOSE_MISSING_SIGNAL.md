# Diagnosing Missing Sell CE Signal

## When PS crosses DOWN to VS (Bearish Crossover)

The system should generate a **Sell CE** signal in Sell regime when:
1. ✅ PE crossover detected (PS crosses DOWN to VS)
2. ✅ Bearish candle on crossover candle (close < open)
3. ✅ PS/VS difference within range (if enabled)
4. ✅ Entry on next candle after crossover completes

## How to Check Your Logs

Look for these log messages around the crossover time:

### 1. Check if Crossover was Detected:
```
[CROSSOVER DETECTION] Crossover on idx X, Entry on idx Y | PE_cross=True (PS crosses DOWN)
```

### 2. Check Crossover Candle Details:
```
Crossover Candle Details (idx X): Time=..., Type=bearish, O=..., H=..., L=..., C=...
```

**Important:** The `Type` must be `bearish` (not `bullish` or `neutral`)

### 3. Check Entry Criteria:
```
PE: Crossover detected on previous candle: PASS/FAIL
PE: Bearish candle on crossover candle (where crossover happened): PASS/FAIL
PE: PS/VS difference threshold: PASS/FAIL
PE: All entry criteria: PASS/FAIL
```

### 4. Check if Signal was Generated:
```
✅ SIGNAL GENERATED: SELL_CE (CE) [Trade Regime: Sell] - [SELL] PS crosses DOWN to VS: Sell CE...
```

## Common Issues

### Issue 1: Crossover Detected but Candle Not Bearish
**Symptom:**
```
PE: Crossover detected on previous candle: PASS
PE: Bearish candle on crossover candle: FAIL
PE Crossover detected but crossover candle is not bearish: ...
```

**Solution:** The crossover candle must be red/bearish. If it's green or neutral, the signal won't generate.

### Issue 2: PS/VS Difference Outside Range
**Symptom:**
```
PE: PS/VS difference threshold: FAIL
PE entry blocked by PS/VS difference: X% < 2.0% (below minimum)
or
PE entry blocked by PS/VS difference: X% > 5.0% (above maximum)
```

**Solution:** Check your `config.json` for `strength_diff_conditions` settings. Default range is 2-5%.

### Issue 3: Exact Candle Not Available
**Symptom:**
```
⛔ Skipping signal: Exact candle ... not available from API
```

**Solution:** This should be fixed with the recent fallback mechanism, but check if the closest candle is within 5 minutes.

### Issue 4: Position Already Open
**Symptom:**
```
⚠️ CE position already open in LIVE mode (strike=...). Skipping new CE entry signal.
```

**Solution:** Close existing CE position first, or the system will allow strangle (CE + PE together).

## Quick Diagnostic Commands

**Windows PowerShell:**
```powershell
# Search for crossover detection around specific time
Select-String -Path logs\LIVE_*.log -Pattern "CROSSOVER DETECTION|PE: All entry criteria" | Select-Object -Last 20

# Check for bearish candle requirement
Select-String -Path logs\LIVE_*.log -Pattern "Bearish candle|Candle type=bearish" | Select-Object -Last 10

# Check for PS/VS difference issues
Select-String -Path logs\LIVE_*.log -Pattern "PS/VS difference|strength_diff" | Select-Object -Last 10
```

**Linux/Mac:**
```bash
# Search for crossover detection
grep -E "CROSSOVER DETECTION|PE: All entry criteria" logs/LIVE_*.log | tail -20

# Check for bearish candle requirement
grep -E "Bearish candle|Candle type=bearish" logs/LIVE_*.log | tail -10

# Check for PS/VS difference issues
grep -E "PS/VS difference|strength_diff" logs/LIVE_*.log | tail -10
```

## What to Share for Further Diagnosis

If you still can't find the issue, share:
1. The exact timestamp of the crossover in TradingView
2. Log entries from 1-2 minutes before to 1-2 minutes after that timestamp
3. The "Checks:" section from the logs showing which conditions passed/failed
4. Whether the crossover candle was red/bearish in TradingView

