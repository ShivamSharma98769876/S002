# How to Clear Protected Profit

Protected Profit is calculated from all completed trades (profit + loss) for a specific date. To clear it, you need to delete the trade records for that date.

## ⚠️ WARNING

**This is a destructive operation** that permanently deletes trade records. The data cannot be recovered after deletion. Make sure you have a backup if needed.

## Methods to Clear Protected Profit

### Method 1: Using API Endpoint (Admin Only)

**Endpoint:** `POST /api/protected-profit/clear`

**Authentication:** Requires Admin token in Authorization header

**Request Body:**
```json
{
  "date": "2024-01-15"  // Optional: Date in YYYY-MM-DD format. If not provided, clears today's trades
}
```

**Example using cURL:**
```bash
curl -X POST http://localhost:5000/api/protected-profit/clear \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -d '{"date": "2024-01-15"}'
```

**Example using Python:**
```python
import requests

url = "http://localhost:5000/api/protected-profit/clear"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer YOUR_ADMIN_TOKEN"
}
data = {
    "date": "2024-01-15"  # Optional: clears today if not provided
}

response = requests.post(url, json=data, headers=headers)
print(response.json())
```

**Response:**
```json
{
  "success": true,
  "message": "Protected Profit cleared for 2024-01-15",
  "deleted_count": 5,
  "protected_profit_after": 0.0,
  "date": "2024-01-15"
}
```

### Method 2: Using Python Script

You can also use the repository directly:

```python
from datetime import date
from src.database.models import DatabaseManager
from src.database.repository import TradeRepository

# Initialize
db_manager = DatabaseManager()
trade_repo = TradeRepository(db_manager)

# Clear protected profit for a specific date
trade_date = date(2024, 1, 15)  # Change to your desired date
deleted_count = trade_repo.delete_trades_by_date(trade_date)

print(f"Deleted {deleted_count} trades. Protected Profit cleared for {trade_date}")

# Verify
protected_profit = trade_repo.get_protected_profit(trade_date)
print(f"Protected Profit after clearing: ₹{protected_profit:.2f}")
```

### Method 3: Direct Database Query (Advanced)

If you need to clear trades directly from the database:

```sql
-- WARNING: This permanently deletes data!
-- Replace '2024-01-15' with your desired date

DELETE FROM trades 
WHERE DATE(exit_time) = '2024-01-15';
```

## What Happens When You Clear Protected Profit?

1. **All trade records for the specified date are deleted** from the database
2. **Protected Profit for that date becomes ₹0.00**
3. **Trade history for that date is removed** (cannot be recovered)
4. **Daily loss limit continues to work** (it only applies to live positions anyway)
5. **Other dates are not affected** (only the specified date is cleared)

## Important Notes

1. **Protected Profit is date-specific**: Clearing trades for one date does not affect other dates
2. **Daily loss limit is unaffected**: It only applies to live positions, not protected profit
3. **Automatic reset**: Protected Profit automatically resets to 0 for a new trading day (since it's calculated from trades for that day)
4. **Backup recommended**: Consider backing up your database before clearing trades

## When to Clear Protected Profit?

- **Start of new trading session**: If you want to reset for a fresh start
- **Testing/Development**: When testing the system with clean data
- **Data correction**: If trades were incorrectly recorded and need to be removed
- **Manual reset**: When you want to manually reset the day's P&L

## Getting Admin Token

To get an admin token, you need to:

1. Login to the admin panel: `POST /admin/login`
2. Use the returned token in subsequent requests

Example:
```python
import requests

# Login
login_response = requests.post(
    "http://localhost:5000/admin/login",
    json={"password": "YOUR_ADMIN_PASSWORD"}
)
token = login_response.json()["token"]

# Use token for protected profit clear
clear_response = requests.post(
    "http://localhost:5000/api/protected-profit/clear",
    headers={"Authorization": f"Bearer {token}"},
    json={"date": "2024-01-15"}
)
```

## Alternative: View Protected Profit Without Clearing

If you just want to see the current Protected Profit without clearing it:

**Endpoint:** `GET /api/status`

This returns the current Protected Profit value along with other system status.

