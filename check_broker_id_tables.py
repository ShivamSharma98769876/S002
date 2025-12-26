"""Check which tables have records with UK9394 broker_id"""
from src.database.models import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
session = db.get_session()

tables = ['trades', 'positions', 'daily_stats', 'daily_purge_flags']

print('Tables updated with UK9394:')
print('=' * 60)

for table in tables:
    result = session.execute(
        text(f'SELECT COUNT(*) FROM {table} WHERE broker_id = :broker_id'),
        {'broker_id': 'UK9394'}
    )
    count = result.scalar()
    print(f'{table:20s}: {count:4d} records')

session.close()

