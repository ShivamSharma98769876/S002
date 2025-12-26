#!/usr/bin/env python3
"""
Show the actual SQL queries for Cumulative P&L calculation
"""

from datetime import datetime, timedelta
from src.database.models import DatabaseManager, Trade, DailyStats
from sqlalchemy import func
from src.utils.date_utils import get_current_ist_time

def show_queries():
    print("=" * 80)
    print("CUMULATIVE PROFIT QUERIES")
    print("=" * 80)
    
    db_manager = DatabaseManager()
    session = db_manager.get_session()
    
    try:
        now = get_current_ist_time()
        today = now.date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        print("\n1. ALL TIME REALIZED P&L (Cumulative Profit - Main Query)")
        print("-" * 80)
        query = session.query(func.sum(Trade.realized_pnl))
        print(f"SQLAlchemy Query: session.query(func.sum(Trade.realized_pnl))")
        print(f"\nEquivalent SQL:")
        print(f"SELECT SUM(realized_pnl) FROM trades;")
        result = query.scalar() or 0.0
        print(f"\nResult: Rs.{result:,.2f}")
        
        print("\n2. TODAY'S UNREALIZED P&L")
        print("-" * 80)
        query = session.query(DailyStats).filter(func.date(DailyStats.date) == today)
        print(f"SQLAlchemy Query: session.query(DailyStats).filter(func.date(DailyStats.date) == today)")
        print(f"\nEquivalent SQL:")
        print(f"SELECT total_unrealized_pnl FROM daily_stats WHERE DATE(date) = '{today}' LIMIT 1;")
        day_stats = query.first()
        day_unrealized = (day_stats.total_unrealized_pnl or 0.0) if day_stats else 0.0
        print(f"\nResult: Rs.{day_unrealized:,.2f}")
        
        print("\n3. CUMULATIVE PROFIT CALCULATION")
        print("-" * 80)
        all_time_pnl = result + day_unrealized
        print(f"Cumulative Profit = All Time Realized + Today's Unrealized")
        print(f"                  = Rs.{result:,.2f} + Rs.{day_unrealized:,.2f}")
        print(f"                  = Rs.{all_time_pnl:,.2f}")
        
        print("\n4. OTHER METRICS QUERIES")
        print("-" * 80)
        
        # Week query
        week_start = today - timedelta(days=6)
        week_start_datetime = datetime.combine(week_start, datetime.min.time())
        print(f"\nWeek P&L Query:")
        print(f"SELECT SUM(realized_pnl) FROM trades")
        print(f"WHERE exit_time >= '{week_start_datetime}' AND exit_time <= '{today_end}';")
        
        # Month query
        month_start = today.replace(day=1)
        month_start_datetime = datetime.combine(month_start, datetime.min.time())
        print(f"\nMonth P&L Query:")
        print(f"SELECT SUM(realized_pnl) FROM trades")
        print(f"WHERE exit_time >= '{month_start_datetime}' AND exit_time <= '{today_end}';")
        
        # Year query
        year_start = today.replace(month=1, day=1)
        year_start_datetime = datetime.combine(year_start, datetime.min.time())
        print(f"\nYear P&L Query:")
        print(f"SELECT SUM(realized_pnl) FROM trades")
        print(f"WHERE exit_time >= '{year_start_datetime}' AND exit_time <= '{today_end}';")
        
        # Day query
        print(f"\nDay P&L Query:")
        print(f"SELECT SUM(realized_pnl) FROM trades")
        print(f"WHERE exit_time >= '{today_start}' AND exit_time <= '{today_end}';")
        
    finally:
        session.close()
    
    print("\n" + "=" * 80)
    print("Note: All queries use SQLAlchemy ORM which translates to the SQL shown above")
    print("=" * 80)

if __name__ == "__main__":
    show_queries()

