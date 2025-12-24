"""
Daily P&L Updater
Updates daily P&L by checking all open and closed positions from CSV and database.
Runs hourly and before market close.
"""

from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional
import csv

from src.utils.logger import get_logger
from src.utils.date_utils import get_current_ist_time
from src.database.models import DatabaseManager

# Define LOG_DIR - same as in execution.py
LOG_DIR = Path("data/live_trader")
LOG_DIR.mkdir(parents=True, exist_ok=True)
from src.database.repository import (
    TradeRepository, 
    PositionRepository, 
    DailyStatsRepository
)

logger = get_logger("pnl_updater")


class DailyPnlUpdater:
    """Updates daily P&L by aggregating data from CSV files and database"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.trade_repo = TradeRepository(self.db_manager)
        self.position_repo = PositionRepository(self.db_manager)
        self.stats_repo = DailyStatsRepository(self.db_manager)
    
    def calculate_daily_pnl_from_csv(self, target_date: date) -> Dict[str, float]:
        """
        Calculate daily P&L from CSV files (closed trades).
        
        Returns:
            Dict with paper_pnl, live_pnl, paper_trades, live_trades
        """
        date_str = target_date.strftime("%Y-%m-%d")
        csv_file = LOG_DIR / f"live_trades_{date_str}.csv"
        
        paper_pnl = 0.0
        live_pnl = 0.0
        paper_trades = 0
        live_trades = 0
        
        if csv_file.exists():
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        mode = row.get('mode', 'PAPER').upper()
                        pnl_value = float(row.get('pnl_value', 0) or 0)
                        
                        if mode == 'PAPER':
                            paper_pnl += pnl_value
                            paper_trades += 1
                        elif mode == 'LIVE':
                            live_pnl += pnl_value
                            live_trades += 1
            except Exception as e:
                logger.warning(f"Error reading CSV for {date_str}: {e}")
        
        return {
            'paper_pnl': paper_pnl,
            'live_pnl': live_pnl,
            'paper_trades': paper_trades,
            'live_trades': live_trades,
            'total_realized_pnl': paper_pnl + live_pnl
        }
    
    def calculate_unrealized_pnl_from_csv(self, target_date: date) -> Dict[str, Any]:
        """
        Calculate unrealized P&L from open positions CSV file.
        
        Returns:
            Dict with total_unrealized_pnl and position details
        """
        date_str = target_date.strftime("%Y-%m-%d")
        csv_file = LOG_DIR / f"open_positions_{date_str}.csv"
        
        total_unrealized = 0.0
        positions = []
        
        # Also check previous day's file (positions carried over)
        prev_date = target_date - timedelta(days=1)
        prev_csv = LOG_DIR / f"open_positions_{prev_date.strftime('%Y-%m-%d')}.csv"
        
        files_to_check = [csv_file, prev_csv] if prev_csv.exists() else [csv_file]
        
        for file_path in files_to_check:
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            if row.get('status', '').upper() == 'OPEN':
                                pnl_value = float(row.get('current_pnl_value', 0) or 0)
                                total_unrealized += pnl_value
                                positions.append({
                                    'symbol': row.get('option_symbol', 'N/A'),
                                    'mode': row.get('mode', 'N/A'),
                                    'pnl': pnl_value
                                })
                except Exception as e:
                    logger.warning(f"Error reading open positions CSV {file_path.name}: {e}")
        
        return {
            'total_unrealized_pnl': total_unrealized,
            'positions': positions,
            'position_count': len(positions)
        }
    
    def calculate_unrealized_pnl_from_database(self) -> float:
        """Calculate unrealized P&L from database active positions"""
        try:
            active_positions = self.position_repo.get_active_positions()
            return sum(pos.unrealized_pnl for pos in active_positions)
        except Exception as e:
            logger.error(f"Error calculating unrealized P&L from database: {e}")
            return 0.0
    
    def get_protected_profit_from_database(self, target_date: date) -> float:
        """Get protected profit (realized P&L) from database"""
        try:
            return self.trade_repo.get_protected_profit(target_date)
        except Exception as e:
            logger.error(f"Error getting protected profit from database: {e}")
            return 0.0
    
    def update_daily_pnl(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Update daily P&L by aggregating data from CSV and database.
        This is the main function to call hourly and before market close.
        
        Args:
            target_date: Date to update P&L for (default: today)
        
        Returns:
            Dict with complete P&L breakdown
        """
        if target_date is None:
            target_date = get_current_ist_time().date()
        
        logger.info(f"Updating daily P&L for {target_date}")
        
        # Get realized P&L from CSV (closed trades)
        csv_pnl = self.calculate_daily_pnl_from_csv(target_date)
        
        # Get unrealized P&L from CSV (open positions)
        csv_unrealized = self.calculate_unrealized_pnl_from_csv(target_date)
        
        # Get protected profit from database (more accurate)
        db_protected_profit = self.get_protected_profit_from_database(target_date)
        
        # Get unrealized P&L from database (more accurate)
        db_unrealized_pnl = self.calculate_unrealized_pnl_from_database()
        
        # Use database values if available, otherwise fall back to CSV
        protected_profit = db_protected_profit if db_protected_profit != 0.0 else csv_pnl['total_realized_pnl']
        unrealized_pnl = db_unrealized_pnl if db_unrealized_pnl != 0.0 else csv_unrealized['total_unrealized_pnl']
        
        total_pnl = protected_profit + unrealized_pnl
        
        # Update DailyStats in database
        try:
            self.stats_repo.update_daily_stats(
                total_unrealized_pnl=unrealized_pnl,
                protected_profit=protected_profit
            )
            logger.info(
                f"Updated DailyStats: Protected Profit=Rs.{protected_profit:,.2f}, "
                f"Unrealized P&L=Rs.{unrealized_pnl:,.2f}, "
                f"Total P&L=Rs.{total_pnl:,.2f}"
            )
        except Exception as e:
            logger.error(f"Error updating DailyStats: {e}")
        
        return {
            'date': target_date.strftime("%Y-%m-%d"),
            'protected_profit': protected_profit,
            'unrealized_pnl': unrealized_pnl,
            'total_pnl': total_pnl,
            'paper_pnl': csv_pnl['paper_pnl'],
            'live_pnl': csv_pnl['live_pnl'],
            'paper_trades': csv_pnl['paper_trades'],
            'live_trades': csv_pnl['live_trades'],
            'open_positions': csv_unrealized['position_count']
        }


def update_daily_pnl_hourly():
    """Function to be called hourly to update P&L"""
    updater = DailyPnlUpdater()
    return updater.update_daily_pnl()


def update_daily_pnl_before_market_close():
    """Function to be called before market close to ensure final P&L is recorded"""
    updater = DailyPnlUpdater()
    result = updater.update_daily_pnl()
    logger.warning(
        f"FINAL P&L UPDATE BEFORE MARKET CLOSE: "
        f"Total P&L=Rs.{result['total_pnl']:,.2f} "
        f"(Protected: Rs.{result['protected_profit']:,.2f}, "
        f"Unrealized: Rs.{result['unrealized_pnl']:,.2f})"
    )
    return result

