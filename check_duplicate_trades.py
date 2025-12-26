"""Check for duplicate trades"""
from src.database.models import DatabaseManager
from src.utils.broker_context import BrokerContext
from src.database.models import Trade
from collections import defaultdict

db = DatabaseManager()
BrokerContext.set_broker_id('UK9394')
session = db.get_session()

all_trades = session.query(Trade).filter(Trade.broker_id == 'UK9394').order_by(Trade.exit_time).all()

# Group by exit_time and realized_pnl to find duplicates
trade_groups = defaultdict(list)
for t in all_trades:
    key = (t.exit_time, t.realized_pnl, t.trading_symbol)
    trade_groups[key].append(t)

print(f"Total trades: {len(all_trades)}")
print(f"Unique trade combinations: {len(trade_groups)}")
print(f"Duplicates found: {len(all_trades) - len(trade_groups)}")

print(f"\nDuplicate trades:")
for key, trades in trade_groups.items():
    if len(trades) > 1:
        exit_time, pnl, symbol = key
        print(f"  {symbol}: exit_time={exit_time}, pnl={pnl:.2f}, count={len(trades)}, IDs={[t.id for t in trades]}")

# Calculate correct P&L (using unique trades only)
unique_trades = []
seen = set()
for t in all_trades:
    key = (t.exit_time, t.realized_pnl, t.trading_symbol)
    if key not in seen:
        unique_trades.append(t)
        seen.add(key)

print(f"\nCorrected calculations:")
print(f"  All trades (with duplicates): {len(all_trades)}, P&L: {sum(t.realized_pnl for t in all_trades):.2f}")
print(f"  Unique trades only: {len(unique_trades)}, P&L: {sum(t.realized_pnl for t in unique_trades):.2f}")

session.close()

