# Cumulative P&L Queries

This document shows the exact SQL queries executed to fetch Cumulative Profit metrics.

## Method: `get_cumulative_pnl_metrics()` in `DailyStatsRepository`

The method executes the following queries:

---

## 1. Day P&L Query

**Realized P&L for Today:**
```sql
SELECT SUM(realized_pnl) 
FROM trades 
WHERE exit_time >= '2025-12-25 00:00:00' 
  AND exit_time <= '2025-12-25 23:59:59';
```

**Unrealized P&L for Today (from daily_stats):**
```sql
SELECT total_unrealized_pnl 
FROM daily_stats 
WHERE DATE(date) = '2025-12-25' 
LIMIT 1;
```

**Day P&L = Day Realized + Day Unrealized**

---

## 2. Week P&L Query (Last 7 Days)

**Realized P&L for Last 7 Days:**
```sql
SELECT SUM(realized_pnl) 
FROM trades 
WHERE exit_time >= '2025-12-19 00:00:00'  -- 7 days ago
  AND exit_time <= '2025-12-25 23:59:59';  -- today
```

**Week P&L = Week Realized + Today's Unrealized**

---

## 3. Month P&L Query (Current Month)

**Realized P&L for Current Month:**
```sql
SELECT SUM(realized_pnl) 
FROM trades 
WHERE exit_time >= '2025-12-01 00:00:00'  -- First day of current month
  AND exit_time <= '2025-12-25 23:59:59';  -- today
```

**Month P&L = Month Realized + Today's Unrealized**

---

## 4. Year P&L Query (Current Year)

**Realized P&L for Current Year:**
```sql
SELECT SUM(realized_pnl) 
FROM trades 
WHERE exit_time >= '2025-01-01 00:00:00'  -- First day of current year
  AND exit_time <= '2025-12-25 23:59:59';  -- today
```

**Year P&L = Year Realized + Today's Unrealized**

---

## 5. All Time P&L Query (Cumulative Profit)

**All Realized P&L (All Time):**
```sql
SELECT SUM(realized_pnl) 
FROM trades;
```

**All Time P&L = All Time Realized + Today's Unrealized**

---

## Summary

The **Cumulative Profit** (All Time) is calculated as:

```sql
-- Step 1: Get all realized P&L from trades table
SELECT SUM(realized_pnl) AS all_time_realized FROM trades;

-- Step 2: Get today's unrealized P&L from daily_stats
SELECT total_unrealized_pnl AS day_unrealized 
FROM daily_stats 
WHERE DATE(date) = CURRENT_DATE 
LIMIT 1;

-- Step 3: Calculate
-- Cumulative Profit = all_time_realized + day_unrealized
```

## Notes

1. **Realized P&L** comes from the `trades` table (`realized_pnl` column)
2. **Unrealized P&L** comes from the `daily_stats` table (`total_unrealized_pnl` column) for today only
3. All metrics include today's unrealized P&L to show the complete current position
4. Historical unrealized P&L is not stored (positions are closed and moved to trades table)
5. The queries use SQLAlchemy ORM, which translates to the SQL shown above

## Example Output

Based on your database:
- **All Time Realized**: Rs. -3,232.75 (from 22 trades)
- **Today's Unrealized**: Rs. 0.00 (no open positions)
- **Cumulative Profit**: Rs. -3,232.75

