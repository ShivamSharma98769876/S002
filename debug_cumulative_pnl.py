"""Debug cumulative P&L calculation"""
from src.database.models import DatabaseManager
from src.database.repository import TradeRepository
from src.utils.broker_context import BrokerContext
from sqlalchemy import func, and_
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
all_trades = session.query(Trade).filter(Trade.broker_id == 'UK9394').all()

print(f"Total trades: {len(all_trades)}")
print(f"Today: {today}")
print(f"Week start: {week_start}")
print(f"\nAll Time P&L: {sum(t.realized_pnl for t in all_trades):.2f}")

# Check week trades
week_trades = [t for t in all_trades if t.exit_time >= week_start_datetime and t.exit_time <= today_end]
print(f"Week trades count: {len(week_trades)}")
print(f"Week P&L: {sum(t.realized_pnl for t in week_trades):.2f}")

# Show sample trade dates
print(f"\nSample trade exit times (first 5):")
for t in all_trades[:5]:
    print(f"  Trade ID {t.id}: exit_time={t.exit_time}, realized_pnl={t.realized_pnl:.2f}, in_week={t.exit_time >= week_start_datetime and t.exit_time <= today_end}")

# Check for trades with future dates or unusual dates
print(f"\nChecking for date issues:")
future_trades = [t for t in all_trades if t.exit_time > today_end]
print(f"Trades with exit_time > today_end: {len(future_trades)}")
if future_trades:
    for t in future_trades[:3]:
        print(f"  Trade ID {t.id}: exit_time={t.exit_time}, realized_pnl={t.realized_pnl:.2f}")

session.close()

