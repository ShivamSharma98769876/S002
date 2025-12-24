# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
import csv
from datetime import datetime
from src.database.models import DatabaseManager, DailyStats
from src.database.repository import TradeRepository
from sqlalchemy import func

date_str = "2025-12-24"
target_date = datetime(2025, 12, 24).date()

print(f"\n{'='*60}")
print(f"P&L CHECK FOR {date_str}")
print(f"{'='*60}")

# Check CSV
csv_file = Path("data/live_trader") / f"live_trades_{date_str}.csv"
if csv_file.exists():
    print(f"\n[OK] CSV file found")
    total_pnl = 0.0
    paper_pnl = 0.0
    live_pnl = 0.0
    paper_trades = 0
    live_trades = 0
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            mode = row.get('mode', 'PAPER').upper()
            pnl_value = float(row.get('pnl_value', 0) or 0)
            total_pnl += pnl_value
            
            if mode == 'PAPER':
                paper_pnl += pnl_value
                paper_trades += 1
            elif mode == 'LIVE':
                live_pnl += pnl_value
                live_trades += 1
    
    print(f"  Total P&L: Rs.{total_pnl:,.2f}")
    print(f"  Paper P&L: Rs.{paper_pnl:,.2f} ({paper_trades} trades)")
    print(f"  Live P&L: Rs.{live_pnl:,.2f} ({live_trades} trades)")
else:
    print(f"\n[!] CSV file not found: {csv_file}")
    print("   No closed trades recorded in CSV for this date")

# Check Database
try:
    db = DatabaseManager()
    session = db.get_session()
    
    # Check DailyStats
    stats = session.query(DailyStats).filter(
        func.date(DailyStats.date) == target_date
    ).first()
    
    if stats:
        total_pnl = stats.protected_profit + stats.total_unrealized_pnl
        print(f"\n[OK] Database DailyStats found:")
        print(f"  Protected Profit (Closed): Rs.{stats.protected_profit:,.2f}")
        print(f"  Unrealized P&L (Open): Rs.{stats.total_unrealized_pnl:,.2f}")
        print(f"  TOTAL P&L: Rs.{total_pnl:,.2f}")
    else:
        print(f"\n[!] No DailyStats record found in database for {date_str}")
    
    # Check trades
    trade_repo = TradeRepository(db)
    try:
        trades = trade_repo.get_trades_by_date(target_date)
        if trades:
            total_realized = sum(t.realized_pnl for t in trades)
            print(f"\n[OK] Database Trades: {len(trades)} trades")
            print(f"  Total Realized P&L: Rs.{total_realized:,.2f}")
        else:
            print(f"\n[!] No trades found in database for {date_str}")
    except:
        pass
    
    session.close()
except Exception as e:
    print(f"\n[!] Database error: {e}")

print(f"\n{'='*60}\n")

