"""Debug which trades are being counted in the week"""
from src.database.models import DatabaseManager
from src.utils.broker_context import BrokerContext
from datetime import datetime, timedelta
from src.utils.date_utils import get_current_ist_time
from src.database.models import Trade

db = DatabaseManager()
BrokerContext.set_broker_id('UK9394')
session = db.get_session()

now = get_current_ist_time()
today = now.date()
today_start = datetime.combine(today, datetime.min.time())
today_end = datetime.combine(today, datetime.max.time())

week_start = today - timedelta(days=6)
week_start_datetime = datetime.combine(week_start, datetime.min.time())

# Get all trades
all_trades = session.query(Trade).filter(Trade.broker_id == 'UK9394').order_by(Trade.exit_time).all()

print(f"Today: {today}")
print(f"Week start: {week_start} ({week_start_datetime})")
print(f"Today end: {today_end}")
print(f"\nAll trades (32 total):")
print(f"  Total P&L: {sum(t.realized_pnl for t in all_trades):.2f}")

# Check week trades with detailed info
week_trades = []
for t in all_trades:
    if t.exit_time >= week_start_datetime and t.exit_time <= today_end:
        week_trades.append(t)

print(f"\nWeek trades ({len(week_trades)} total):")
print(f"  Total P&L: {sum(t.realized_pnl for t in week_trades):.2f}")
print(f"\nWeek trade details:")
for t in week_trades:
    print(f"  ID {t.id}: exit_time={t.exit_time}, pnl={t.realized_pnl:.2f}, date={t.exit_time.date()}")

# Check if there are duplicate trades or if exit_time has timezone issues
print(f"\nChecking for duplicates or timezone issues...")
print(f"Unique trade IDs in week: {len(set(t.id for t in week_trades))}")
print(f"Total trade IDs: {len(set(t.id for t in all_trades))}")

session.close()

