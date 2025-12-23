"""
Migration script to add transaction_type column to trades table
Run this once to update existing database schema
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import DatabaseManager
from sqlalchemy import text

def migrate():
    """Add transaction_type column to trades table"""
    db_manager = DatabaseManager()
    session = db_manager.get_session()
    
    try:
        # Check if column already exists
        result = session.execute(text("""
            SELECT COUNT(*) as count 
            FROM pragma_table_info('trades') 
            WHERE name='transaction_type'
        """))
        
        column_exists = result.fetchone()[0] > 0
        
        if not column_exists:
            print("Adding transaction_type column to trades table...")
            # Add transaction_type column
            session.execute(text("""
                ALTER TABLE trades 
                ADD COLUMN transaction_type VARCHAR(10) DEFAULT 'BUY'
            """))
            
            # Update existing records based on quantity sign
            session.execute(text("""
                UPDATE trades 
                SET transaction_type = CASE 
                    WHEN quantity > 0 THEN 'BUY' 
                    ELSE 'SELL' 
                END
            """))
            
            session.commit()
            print("✅ Migration successful: Added transaction_type column to trades table")
        else:
            print("ℹ️  Column transaction_type already exists, skipping migration")
            
    except Exception as e:
        session.rollback()
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    migrate()

