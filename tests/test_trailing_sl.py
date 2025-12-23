"""
Test Trailing Stop Loss System
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, date
from src.risk_management.trailing_stop_loss import TrailingStopLoss
from src.config.config_manager import ConfigManager
from src.api.kite_client import KiteClient
from src.database.repository import (
    PositionRepository, DailyStatsRepository, TradeRepository
)
from src.database.models import DatabaseManager, Position


@pytest.fixture
def mock_config_manager():
    """Mock configuration manager"""
    config = Mock(spec=ConfigManager)
    admin_config = Mock()
    admin_config.trailing_sl_activation = 5000.0
    admin_config.trailing_sl_increment = 10000.0
    config.get_admin_config.return_value = admin_config
    return config


@pytest.fixture
def mock_repos():
    """Mock repositories"""
    position_repo = Mock(spec=PositionRepository)
    daily_stats_repo = Mock(spec=DailyStatsRepository)
    trade_repo = Mock(spec=TradeRepository)
    
    # Mock get_protected_profit to return 0
    trade_repo.get_protected_profit.return_value = 0.0
    
    return position_repo, daily_stats_repo, trade_repo


def test_trailing_sl_activation(mock_config_manager, mock_repos):
    """Test trailing SL activation at ₹5,000 profit"""
    position_repo, daily_stats_repo, trade_repo = mock_repos
    
    # Mock position with profit
    mock_position = Mock(spec=Position)
    mock_position.unrealized_pnl = 5000.0
    position_repo.get_active_positions.return_value = [mock_position]
    
    kite_client = Mock(spec=KiteClient)
    trailing_sl = TrailingStopLoss(
        mock_config_manager,
        kite_client,
        position_repo,
        daily_stats_repo,
        trade_repo
    )
    
    # Check trailing SL
    status = trailing_sl.check_and_update_trailing_sl()
    
    assert status["trailing_sl_active"] == True
    assert status["trailing_sl_level"] == 5000.0
    assert status["total_profit"] == 5000.0


def test_trailing_sl_increment(mock_config_manager, mock_repos):
    """Test trailing SL increment logic"""
    position_repo, daily_stats_repo, trade_repo = mock_repos
    
    kite_client = Mock(spec=KiteClient)
    trailing_sl = TrailingStopLoss(
        mock_config_manager,
        kite_client,
        position_repo,
        daily_stats_repo,
        trade_repo
    )
    
    # Activate at ₹5,000
    mock_position = Mock(spec=Position)
    mock_position.unrealized_pnl = 5000.0
    position_repo.get_active_positions.return_value = [mock_position]
    trailing_sl.check_and_update_trailing_sl()
    
    # Profit grows to ₹15,000 - SL should move to ₹10,000
    mock_position.unrealized_pnl = 15000.0
    status = trailing_sl.check_and_update_trailing_sl()
    
    assert status["trailing_sl_level"] == 10000.0
    
    # Profit grows to ₹28,000 - SL should move to ₹20,000
    mock_position.unrealized_pnl = 28000.0
    status = trailing_sl.check_and_update_trailing_sl()
    
    assert status["trailing_sl_level"] == 20000.0


def test_trailing_sl_trigger(mock_config_manager, mock_repos):
    """Test trailing SL trigger when profit drops"""
    position_repo, daily_stats_repo, trade_repo = mock_repos
    
    kite_client = Mock(spec=KiteClient)
    kite_client.square_off_all_positions.return_value = ["order1", "order2"]
    
    trailing_sl = TrailingStopLoss(
        mock_config_manager,
        kite_client,
        position_repo,
        daily_stats_repo,
        trade_repo
    )
    
    # Activate and set SL at ₹10,000
    mock_position = Mock(spec=Position)
    mock_position.unrealized_pnl = 15000.0
    position_repo.get_active_positions.return_value = [mock_position]
    trailing_sl.check_and_update_trailing_sl()
    
    # Profit drops to ₹10,000 - should trigger
    mock_position.unrealized_pnl = 10000.0
    status = trailing_sl.check_and_update_trailing_sl()
    
    assert status["triggered"] == True
    kite_client.square_off_all_positions.assert_called_once()


def test_trailing_sl_only_moves_up(mock_config_manager, mock_repos):
    """Test that trailing SL only moves up, never down"""
    position_repo, daily_stats_repo, trade_repo = mock_repos
    
    kite_client = Mock(spec=KiteClient)
    trailing_sl = TrailingStopLoss(
        mock_config_manager,
        kite_client,
        position_repo,
        daily_stats_repo,
        trade_repo
    )
    
    # Activate and grow to ₹15,000 (SL at ₹10,000)
    mock_position = Mock(spec=Position)
    mock_position.unrealized_pnl = 15000.0
    position_repo.get_active_positions.return_value = [mock_position]
    trailing_sl.check_and_update_trailing_sl()
    
    initial_sl = trailing_sl.trailing_sl_level
    
    # Profit drops to ₹12,000 - SL should stay at ₹10,000
    mock_position.unrealized_pnl = 12000.0
    trailing_sl.check_and_update_trailing_sl()
    
    assert trailing_sl.trailing_sl_level == initial_sl  # Should not decrease

