"""
Tests for Market Hours Handling
"""

import unittest
from unittest.mock import Mock, patch
from datetime import datetime, time as dt_time
from src.utils.date_utils import is_market_open, get_current_ist_time, get_next_trading_day
from src.risk_management.trading_block_manager import TradingBlockManager
from src.database.repository import DailyStatsRepository


class TestMarketHours(unittest.TestCase):
    """Test cases for market hours handling"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_daily_stats_repo = Mock(spec=DailyStatsRepository)
        self.trading_block_manager = TradingBlockManager(self.mock_daily_stats_repo)
    
    @patch('src.utils.date_utils.get_current_ist_time')
    def test_is_market_open_during_hours(self, mock_time):
        """Test market open check during trading hours"""
        # Mock time to 10:00 AM (within market hours)
        mock_ist = Mock()
        mock_ist.time.return_value = dt_time(10, 0)
        mock_ist.weekday.return_value = 0  # Monday
        mock_time.return_value = mock_ist
        
        self.assertTrue(is_market_open())
    
    @patch('src.utils.date_utils.get_current_ist_time')
    def test_is_market_open_before_hours(self, mock_time):
        """Test market open check before trading hours"""
        # Mock time to 8:00 AM (before market opens)
        mock_ist = Mock()
        mock_ist.time.return_value = dt_time(8, 0)
        mock_ist.weekday.return_value = 0  # Monday
        mock_time.return_value = mock_ist
        
        self.assertFalse(is_market_open())
    
    @patch('src.utils.date_utils.get_current_ist_time')
    def test_is_market_open_after_hours(self, mock_time):
        """Test market open check after trading hours"""
        # Mock time to 4:00 PM (after market closes)
        mock_ist = Mock()
        mock_ist.time.return_value = dt_time(16, 0)
        mock_ist.weekday.return_value = 0  # Monday
        mock_time.return_value = mock_ist
        
        self.assertFalse(is_market_open())
    
    @patch('src.utils.date_utils.get_current_ist_time')
    def test_is_market_open_weekend(self, mock_time):
        """Test market open check on weekend"""
        # Mock time to Saturday
        mock_ist = Mock()
        mock_ist.time.return_value = dt_time(10, 0)
        mock_ist.weekday.return_value = 5  # Saturday
        mock_time.return_value = mock_ist
        
        self.assertFalse(is_market_open())
    
    @patch('src.utils.date_utils.get_current_ist_time')
    def test_trading_block_reset_at_market_open(self, mock_time):
        """Test trading block reset at market open (9:15 AM)"""
        # Mock time to 9:15 AM
        mock_ist = Mock()
        mock_ist.time.return_value = dt_time(9, 15)
        mock_ist.weekday.return_value = 0  # Monday
        
        with patch('src.risk_management.trading_block_manager.get_current_ist_time', return_value=mock_ist):
            with patch('src.risk_management.trading_block_manager.is_market_open', return_value=True):
                self.trading_block_manager.trading_blocked = True
                self.trading_block_manager.check_and_reset_block()
                
                # Block should be reset
                self.assertFalse(self.trading_block_manager.trading_blocked)


if __name__ == '__main__':
    unittest.main()

