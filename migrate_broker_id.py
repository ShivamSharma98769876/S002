"""
Script to migrate existing data from 'DEFAULT' broker_id to actual user BrokerID
Run this after authenticating to update existing records with your BrokerID
"""

import sys
from src.database.models import DatabaseManager
from src.utils.broker_context import BrokerContext
from sqlalchemy import text
from src.utils.logger import get_logger

logger = get_logger("migration")

def migrate_broker_id(old_broker_id: str, new_broker_id: str):
    """Migrate all records from old_broker_id to new_broker_id"""
    db = DatabaseManager()
    session = db.get_session()
    
    try:
        # Set BrokerID in context for this operation
        BrokerContext.set_broker_id(new_broker_id)
        
        tables_to_migrate = [
            ('trades', 'broker_id'),
            ('positions', 'broker_id'),
            ('daily_stats', 'broker_id'),
            ('daily_purge_flags', 'broker_id')
        ]
        
        total_updated = 0
        
        for table_name, column_name in tables_to_migrate:
            # Count records to update
            count_result = session.execute(text(f"""
                SELECT COUNT(*) FROM {table_name} 
                WHERE {column_name} = :old_id
            """), {"old_id": old_broker_id})
            count = count_result.scalar()
            
            if count > 0:
                # Update records
                update_result = session.execute(text(f"""
                    UPDATE {table_name} 
                    SET {column_name} = :new_id 
                    WHERE {column_name} = :old_id
                """), {"old_id": old_broker_id, "new_id": new_broker_id})
                
                session.commit()
                updated = update_result.rowcount
                total_updated += updated
                logger.info(f"Updated {updated} records in {table_name} from '{old_broker_id}' to '{new_broker_id}'")
            else:
                logger.info(f"No records to update in {table_name}")
        
        logger.info(f"Migration complete! Total records updated: {total_updated}")
        return total_updated
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error during migration: {e}", exc_info=True)
        raise
    finally:
        session.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python migrate_broker_id.py <new_broker_id> [old_broker_id]")
        print("Example: python migrate_broker_id.py UK9394 DEFAULT")
        sys.exit(1)
    
    new_broker_id = sys.argv[1]
    old_broker_id = sys.argv[2] if len(sys.argv) > 2 else 'DEFAULT'
    
    print(f"Migrating data from '{old_broker_id}' to '{new_broker_id}'...")
    migrate_broker_id(old_broker_id, new_broker_id)
    print("Migration completed!")

