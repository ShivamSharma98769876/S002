#!/usr/bin/env python3
"""
Simple script to view risk_management.db contents
Usage: python view_db.py
"""

import sqlite3
from pathlib import Path
from datetime import datetime
import sys

DB_PATH = Path("data/risk_management.db")

def print_table_info(conn, table_name):
    """Print table structure and sample data"""
    cursor = conn.cursor()
    
    # Get table structure
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    
    print(f"\n{'='*80}")
    print(f"Table: {table_name}")
    print(f"{'='*80}")
    print("\nColumns:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
    
    # Get row count
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"\nTotal Rows: {count}")
    
    if count > 0:
        # Get sample data (first 5 rows)
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
        rows = cursor.fetchall()
        
        # Get column names
        cursor.execute(f"PRAGMA table_info({table_name})")
        col_names = [col[1] for col in cursor.fetchall()]
        
        print("\nSample Data (first 5 rows):")
        print("-" * 80)
        print(" | ".join(col_names))
        print("-" * 80)
        for row in rows:
            print(" | ".join(str(val) if val is not None else "NULL" for val in row))
        
        if count > 5:
            print(f"\n... and {count - 5} more rows")

def view_daily_stats(conn):
    """View daily stats with formatted output"""
    cursor = conn.cursor()
    
    print(f"\n{'='*80}")
    print("DAILY STATS (Cumulative P&L)")
    print(f"{'='*80}")
    
    cursor.execute("""
        SELECT 
            date,
            total_realized_pnl,
            total_unrealized_pnl,
            protected_profit,
            number_of_trades,
            daily_loss_used,
            daily_loss_limit,
            loss_limit_hit,
            trading_blocked
        FROM daily_stats
        ORDER BY date DESC
        LIMIT 10
    """)
    
    rows = cursor.fetchall()
    
    if rows:
        print(f"\n{'Date':<12} {'Realized P&L':>15} {'Unrealized P&L':>15} {'Protected':>15} {'Trades':>8} {'Loss Used':>12}")
        print("-" * 80)
        for row in rows:
            date_str = row[0][:10] if row[0] else "N/A"
            print(f"{date_str:<12} {row[1]:>15,.2f} {row[2]:>15,.2f} {row[3]:>15,.2f} {row[4]:>8} {row[5]:>12,.2f}")
    else:
        print("\nNo daily stats found.")

def view_recent_trades(conn):
    """View recent trades"""
    cursor = conn.cursor()
    
    print(f"\n{'='*80}")
    print("RECENT TRADES (Last 10)")
    print(f"{'='*80}")
    
    cursor.execute("""
        SELECT 
            exit_time,
            trading_symbol,
            entry_price,
            exit_price,
            quantity,
            realized_pnl,
            is_profit,
            exit_type
        FROM trades
        ORDER BY exit_time DESC
        LIMIT 10
    """)
    
    rows = cursor.fetchall()
    
    if rows:
        print(f"\n{'Exit Time':<20} {'Symbol':<25} {'Entry':>10} {'Exit':>10} {'Qty':>6} {'P&L':>12} {'Profit':>8} {'Type':<15}")
        print("-" * 120)
        for row in rows:
            exit_time = row[0][:19] if row[0] else "N/A"
            symbol = row[1][:23] if row[1] else "N/A"
            print(f"{exit_time:<20} {symbol:<25} {row[2]:>10.2f} {row[3]:>10.2f} {row[4]:>6} {row[5]:>12,.2f} {'Yes' if row[6] else 'No':>8} {row[7]:<15}")
    else:
        print("\nNo trades found.")

def view_open_positions(conn):
    """View open positions"""
    cursor = conn.cursor()
    
    print(f"\n{'='*80}")
    print("OPEN POSITIONS")
    print(f"{'='*80}")
    
    cursor.execute("""
        SELECT 
            trading_symbol,
            entry_time,
            entry_price,
            current_price,
            quantity,
            unrealized_pnl
        FROM positions
        WHERE is_active = 1
        ORDER BY entry_time DESC
    """)
    
    rows = cursor.fetchall()
    
    if rows:
        print(f"\n{'Symbol':<25} {'Entry Time':<20} {'Entry Price':>12} {'Current':>12} {'Qty':>6} {'Unrealized P&L':>15}")
        print("-" * 100)
        for row in rows:
            entry_time = row[1][:19] if row[1] else "N/A"
            symbol = row[0][:23] if row[0] else "N/A"
            current = row[3] if row[3] is not None else "N/A"
            print(f"{symbol:<25} {entry_time:<20} {row[2]:>12.2f} {str(current):>12} {row[4]:>6} {row[5]:>15,.2f}")
    else:
        print("\nNo open positions.")

def main():
    if not DB_PATH.exists():
        print(f"Error: Database file not found at {DB_PATH}")
        print(f"Current directory: {Path.cwd()}")
        sys.exit(1)
    
    print(f"Opening database: {DB_PATH.absolute()}")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # List all tables
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"\n{'='*80}")
        print("DATABASE OVERVIEW")
        print(f"{'='*80}")
        print(f"\nTables found: {', '.join(tables)}")
        
        # Show key information
        view_daily_stats(conn)
        view_recent_trades(conn)
        view_open_positions(conn)
        
        # Show table structures
        print(f"\n{'='*80}")
        print("TABLE STRUCTURES")
        print(f"{'='*80}")
        for table in tables:
            print_table_info(conn, table)
        
        conn.close()
        print(f"\n{'='*80}")
        print("Database view complete!")
        print(f"{'='*80}")
        
    except Exception as e:
        print(f"Error opening database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

