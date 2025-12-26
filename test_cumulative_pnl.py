#!/usr/bin/env python3
"""
Test script to check cumulative P&L calculation
"""

import sys
from datetime import datetime
from src.database.models import DatabaseManager
from src.database.repository import DailyStatsRepository, TradeRepository

def test_cumulative_pnl():
    print("=" * 80)
    print("Testing Cumulative P&L Calculation")
    print("=" * 80)
    
    db_manager = DatabaseManager()
    daily_stats_repo = DailyStatsRepository(db_manager)
    trade_repo = TradeRepository(db_manager)
    
    # Check trades table
    session = db_manager.get_session()
    try:
        from sqlalchemy import func
        from src.database.models import Trade
        
        total_trades = session.query(func.count(Trade.id)).scalar()
        total_realized_pnl = session.query(func.sum(Trade.realized_pnl)).scalar() or 0.0
        
        print(f"\n[Trades Table]")
        print(f"  Total Trades: {total_trades}")
        print(f"  Total Realized P&L: Rs.{total_realized_pnl:,.2f}")
        
        # Check recent trades
        recent_trades = session.query(Trade).order_by(Trade.exit_time.desc()).limit(5).all()
        if recent_trades:
            print(f"\n  Recent 5 Trades:")
            for trade in recent_trades:
                print(f"    {trade.exit_time.strftime('%Y-%m-%d %H:%M')} | "
                      f"{trade.trading_symbol} | P&L: Rs.{trade.realized_pnl:,.2f}")
        else:
            print(f"\n  [WARNING] No trades found in database")
        
    finally:
        session.close()
    
    # Check daily_stats table
    session = db_manager.get_session()
    try:
        from src.database.models import DailyStats
        from sqlalchemy import func
        
        total_days = session.query(func.count(DailyStats.id)).scalar()
        print(f"\n[Daily Stats Table]")
        print(f"  Total Days: {total_days}")
        
        # Check today's stats
        today = datetime.now().date()
        today_stats = session.query(DailyStats).filter(
            func.date(DailyStats.date) == today
        ).first()
        
        if today_stats:
            print(f"\n  Today's Stats ({today}):")
            print(f"    Protected Profit: Rs.{today_stats.protected_profit or 0.0:,.2f}")
            print(f"    Unrealized P&L: Rs.{today_stats.total_unrealized_pnl or 0.0:,.2f}")
            print(f"    Total: Rs.{(today_stats.protected_profit or 0.0) + (today_stats.total_unrealized_pnl or 0.0):,.2f}")
        else:
            print(f"\n  [WARNING] No stats found for today ({today})")
        
        # Check last 5 days
        from datetime import timedelta
        week_start = today - timedelta(days=6)
        recent_stats = session.query(DailyStats).filter(
            func.date(DailyStats.date) >= week_start
        ).order_by(DailyStats.date.desc()).limit(5).all()
        
        if recent_stats:
            print(f"\n  Last 5 Days Stats:")
            for stat in recent_stats:
                date_str = stat.date.strftime('%Y-%m-%d') if stat.date else 'N/A'
                total = (stat.protected_profit or 0.0) + (stat.total_unrealized_pnl or 0.0)
                print(f"    {date_str}: Rs.{total:,.2f} "
                      f"(Protected: Rs.{stat.protected_profit or 0.0:,.2f}, "
                      f"Unrealized: Rs.{stat.total_unrealized_pnl or 0.0:,.2f})")
        
    finally:
        session.close()
    
    # Test cumulative P&L calculation
    print(f"\n[Cumulative P&L Metrics]")
    try:
        metrics = daily_stats_repo.get_cumulative_pnl_metrics()
        print(f"  All Time: Rs.{metrics['all_time']:,.2f}")
        print(f"  Year: Rs.{metrics['year']:,.2f}")
        print(f"  Month: Rs.{metrics['month']:,.2f}")
        print(f"  Week: Rs.{metrics['week']:,.2f}")
        print(f"  Day: Rs.{metrics['day']:,.2f}")
        
        if all(v == 0.0 for v in metrics.values()):
            print(f"\n  [WARNING] All metrics are zero!")
            print(f"     This could mean:")
            print(f"     1. No trades have been executed yet")
            print(f"     2. Daily stats are not being updated")
            print(f"     3. Trades table is empty")
    except Exception as e:
        print(f"\n  [ERROR] Error calculating metrics: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_cumulative_pnl()

