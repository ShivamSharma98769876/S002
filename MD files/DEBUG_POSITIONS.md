# Debugging: Options Positions Not Showing

## Issue
Options positions from Zerodha are not appearing in the dashboard.

## Possible Causes

### 1. Authentication Not Complete
- **Check**: Is the Kite client authenticated?
- **Solution**: Complete Zerodha OAuth authentication
- **Verify**: Check logs for "Kite client not authenticated" errors

### 2. No Options Positions in Account
- **Check**: Do you have active options positions in Zerodha?
- **Solution**: Ensure you have open options positions with quantity > 0

### 3. Filtering Logic Too Strict
- **Check**: Are positions being filtered out incorrectly?
- **Solution**: The filtering now checks:
  - Exchange must be 'NFO' or 'BFO'
  - Symbol must contain 'CE' or 'PE'

### 4. Position Sync Not Running
- **Check**: Is position sync happening every 30 seconds?
- **Solution**: Check monitoring loop is active

## Debugging Steps

### Step 1: Check Authentication
```python
# In Python console or add to code
from src.api.kite_client import KiteClient
from src.config.config_manager import ConfigManager

cm = ConfigManager()
kc = KiteClient(cm)
print("Authenticated:", kc.is_authenticated())
```

### Step 2: Check Raw Positions from API
```python
# Get all positions (before filtering)
positions = kc.kite.positions()
print("All positions:", positions)
print("Net positions:", positions.get('net', []))
```

### Step 3: Check Filtered Options Positions
```python
# Get filtered options positions
options = kc.get_positions()
print("Options positions:", options)
print("Count:", len(options))
```

### Step 4: Check Database Positions
```python
# Check what's in database
from src.database.models import DatabaseManager
from src.database.repository import PositionRepository

db = DatabaseManager()
repo = PositionRepository(db)
active = repo.get_active_positions()
print("Active positions in DB:", len(active))
for pos in active:
    print(f"  {pos.trading_symbol} - Qty: {pos.quantity}")
```

### Step 5: Check Position Sync
```python
# Manually trigger sync
from src.api.position_sync import PositionSync
sync = PositionSync(kc, repo)
synced = sync.sync_positions_from_api()
print("Synced positions:", len(synced))
```

## Common Issues & Fixes

### Issue: "Not authenticated" errors
**Fix**: Complete Zerodha OAuth flow:
1. Get request token from Zerodha
2. Call `kite_client.authenticate(request_token)`
3. Or set access token directly: `kite_client.set_access_token(token)`

### Issue: Positions exist but not showing
**Fix**: Check filtering logic:
- Ensure exchange is 'NFO' or 'BFO'
- Ensure symbol contains 'CE' or 'PE'
- Check quantity > 0

### Issue: Positions in API but not in database
**Fix**: Check position sync:
- Verify sync is running (every 30 seconds)
- Check for sync errors in logs
- Manually trigger sync to test

## Enhanced Logging

Add this to see what's happening:

```python
# In kite_client.py get_positions()
logger.info(f"Total positions from API: {len(positions.get('net', []))}")
for pos in positions.get('net', []):
    logger.debug(f"Position: {pos.get('exchange')}:{pos.get('tradingsymbol')} - Qty: {pos.get('quantity')}")
logger.info(f"Filtered options positions: {len(options_positions)}")
```

## Testing

1. **Test with mock data**:
   - Create test positions in database
   - Verify they show in dashboard

2. **Test API connection**:
   - Verify authentication works
   - Verify API calls succeed
   - Check response format

3. **Test filtering**:
   - Verify options filtering logic
   - Test with different symbol formats
   - Test with different exchanges

## Next Steps

1. Check authentication status
2. Verify positions exist in Zerodha
3. Check filtering logic
4. Verify position sync is working
5. Check database for synced positions

