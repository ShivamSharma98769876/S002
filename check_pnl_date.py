#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check P&L for a specific date"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
import csv
from datetime import date

# Check CSV file
date_str = "2025-12-24"
csv_file = Path("data/live_trader") / f"live_trades_{date_str}.csv"

print(f"\n{'='*60}")
print(f"P&L CHECK FOR {date_str}")
print(f"{'='*60}")

if csv_file.exists():
    print(f"\n[OK] CSV file found: {csv_file}")
    total_pnl = 0.0
    paper_pnl = 0.0
    live_pnl = 0.0
    paper_trades = 0
    live_trades = 0
    trades = []
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)
            mode = row.get('mode', 'PAPER').upper()
            pnl_value = float(row.get('pnl_value', 0) or 0)
            total_pnl += pnl_value
            
            if mode == 'PAPER':
                paper_pnl += pnl_value
                paper_trades += 1
            elif mode == 'LIVE':
                live_pnl += pnl_value
                live_trades += 1
    
    print(f"\nP&L Summary:")
    print(f"  Total P&L: ₹{total_pnl:,.2f}")
    print(f"  Paper P&L: ₹{paper_pnl:,.2f} ({paper_trades} trades)")
    print(f"  Live P&L: ₹{live_pnl:,.2f} ({live_trades} trades)")
    print(f"  Total Trades: {len(trades)}")
    
    if trades:
        print(f"\nTrade Details:")
        for i, trade in enumerate(trades, 1):
            print(f"  {i}. {trade.get('option_symbol', 'N/A')} ({trade.get('mode', 'N/A')})")
            print(f"     Entry: ₹{float(trade.get('entry_price', 0)):.2f} | Exit: ₹{float(trade.get('exit_price', 0)):.2f}")
            print(f"     P&L: ₹{float(trade.get('pnl_value', 0)):.2f} ({trade.get('pnl_points', 0)} pts)")
else:
    print(f"\n[!] CSV file not found: {csv_file}")
    print("   This means no trades were closed on this date, or the file hasn't been created yet.")

# Check database
try:
    from src.database.models import DatabaseManager
    from src.database.repository import TradeRepository, PositionRepository, DailyStatsRepository
    from datetime import datetime
    
    db = DatabaseManager()
    trade_repo = TradeRepository(db)
    pos_repo = PositionRepository(db)
    stats_repo = DailyStatsRepository(db)
    
    target_date = datetime(2025, 12, 24).date()
    
    # Check DailyStats
    session = db.get_session()
    from src.database.models import DailyStats
    from sqlalchemy import func
    
    stats = session.query(DailyStats).filter(
        func.date(DailyStats.date) == target_date
    ).first()
    
    if stats:
        print(f"\nDatabase DailyStats for {date_str}:")
        print(f"  Protected Profit: ₹{stats.protected_profit:,.2f}")
        print(f"  Unrealized P&L: ₹{stats.total_unrealized_pnl:,.2f}")
        print(f"  Total P&L: ₹{stats.protected_profit + stats.total_unrealized_pnl:,.2f}")
    
    # Check trades in database
    trades_db = trade_repo.get_trades_by_date(target_date)
    if trades_db:
        print(f"\nDatabase Trades for {date_str}: {len(trades_db)} trades")
        total_realized = sum(t.realized_pnl for t in trades_db)
        print(f"  Total Realized P&L: ₹{total_realized:,.2f}")
    
    session.close()
except Exception as e:
    print(f"\n[!] Could not check database: {e}")

print(f"\n{'='*60}\n")

