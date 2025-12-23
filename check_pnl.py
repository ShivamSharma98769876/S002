#!/usr/bin/env python3
"""Check current P&L values"""
from src.database.models import DatabaseManager
from src.database.repository import TradeRepository, PositionRepository
from datetime import date

db = DatabaseManager()
trade_repo = TradeRepository(db)
pos_repo = PositionRepository(db)

today = date.today()

# Get protected profit (sum of all closed trades today)
protected_profit = trade_repo.get_protected_profit(today)
print(f"\n{'='*60}")
print(f"PROTECTED PROFIT (Closed Trades Today)")
print(f"{'='*60}")
print(f"Protected Profit: ₹{protected_profit:,.2f}")

# Get all closed trades for today
from src.database.models import Trade
from sqlalchemy import func
session = db.get_session()
trades = session.query(Trade).filter(func.date(Trade.exit_time) == today).all()
print(f"\nTotal closed trades today: {len(trades)}")
if trades:
    print("\nClosed Trades Breakdown:")
    for i, t in enumerate(trades, 1):
        print(f"  {i}. {t.trading_symbol} ({t.exchange})")
        print(f"     Entry: ₹{t.entry_price:.2f} | Exit: ₹{t.exit_price:.2f} | Qty: {t.quantity}")
        print(f"     Realized P&L: ₹{t.realized_pnl:,.2f}")
        print()
else:
    print("  No closed trades found for today")
session.close()

# Get current positions P&L
positions = pos_repo.get_active_positions()
current_pnl = sum(pos.unrealized_pnl for pos in positions)
print(f"\n{'='*60}")
print(f"CURRENT POSITIONS P&L (Open Positions)")
print(f"{'='*60}")
print(f"Active positions: {len(positions)}")
if positions:
    print("\nActive Positions Breakdown:")
    for i, p in enumerate(positions, 1):
        print(f"  {i}. {p.trading_symbol} ({p.exchange})")
        print(f"     Entry: ₹{p.entry_price:.2f} | Current: ₹{p.current_price:.2f} | Qty: {p.quantity}")
        print(f"     Unrealized P&L: ₹{p.unrealized_pnl:,.2f}")
        print()
else:
    print("  No active positions")
print(f"Total Current Positions P&L: ₹{current_pnl:,.2f}")

# Calculate Total Day P&L
total_daily_pnl = protected_profit + current_pnl
print(f"\n{'='*60}")
print(f"TOTAL DAY P&L CALCULATION")
print(f"{'='*60}")
print(f"Protected Profit (Closed Trades):  ₹{protected_profit:>15,.2f}")
print(f"Current Positions P&L (Open):       ₹{current_pnl:>15,.2f}")
print(f"{'─'*60}")
print(f"TOTAL DAY P&L:                      ₹{total_daily_pnl:>15,.2f}")
print(f"{'='*60}\n")

