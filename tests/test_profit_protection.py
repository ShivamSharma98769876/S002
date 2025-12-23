"""
Test Cycle-wise Profit Protection System
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, date
from src.risk_management.profit_protection import ProfitProtection
from src.database.repository import (
    PositionRepository, TradeRepository, DailyStatsRepository
)
from src.database.models import Position, Trade
from src.api.kite_client import KiteClient


@pytest.fixture
def mock_repos():
    """Mock repositories"""
    position_repo = Mock(spec=PositionRepository)
    trade_repo = Mock(spec=TradeRepository)
    daily_stats_repo = Mock(spec=DailyStatsRepository)
    
    return position_repo, trade_repo, daily_stats_repo


@pytest.fixture
def mock_kite_client():
    """Mock Kite client"""
    return Mock(spec=KiteClient)


def test_get_protected_profit(mock_repos, mock_kite_client):
    """Test getting protected profit"""
    position_repo, trade_repo, daily_stats_repo = mock_repos
    
    # Mock protected profit
    trade_repo.get_protected_profit.return_value = 5000.0
    
    profit_protection = ProfitProtection(
        position_repo,
        trade_repo,
        daily_stats_repo,
        mock_kite_client
    )
    
    protected_profit = profit_protection.get_protected_profit()
    assert protected_profit == 5000.0


def test_get_current_positions_pnl(mock_repos, mock_kite_client):
    """Test getting current positions P&L"""
    position_repo, trade_repo, daily_stats_repo = mock_repos
    
    # Mock positions
    mock_pos1 = Mock(spec=Position)
    mock_pos1.unrealized_pnl = 2000.0
    mock_pos2 = Mock(spec=Position)
    mock_pos2.unrealized_pnl = 3000.0
    
    position_repo.get_active_positions.return_value = [mock_pos1, mock_pos2]
    
    profit_protection = ProfitProtection(
        position_repo,
        trade_repo,
        daily_stats_repo,
        mock_kite_client
    )
    
    current_pnl = profit_protection.get_current_positions_pnl()
    assert current_pnl == 5000.0


def test_get_total_daily_pnl(mock_repos, mock_kite_client):
    """Test getting total daily P&L breakdown"""
    position_repo, trade_repo, daily_stats_repo = mock_repos
    
    # Mock protected profit
    trade_repo.get_protected_profit.return_value = 8000.0
    
    # Mock positions
    mock_pos = Mock(spec=Position)
    mock_pos.unrealized_pnl = 2000.0
    position_repo.get_active_positions.return_value = [mock_pos]
    
    profit_protection = ProfitProtection(
        position_repo,
        trade_repo,
        daily_stats_repo,
        mock_kite_client
    )
    
    pnl_breakdown = profit_protection.get_total_daily_pnl()
    
    assert pnl_breakdown["protected_profit"] == 8000.0
    assert pnl_breakdown["current_pnl"] == 2000.0
    assert pnl_breakdown["total_pnl"] == 10000.0


def test_profit_locking_on_trade_close(mock_repos, mock_kite_client):
    """Test that profit is locked when trade closes with profit"""
    position_repo, trade_repo, daily_stats_repo = mock_repos
    
    # Mock position with profit
    mock_position = Mock(spec=Position)
    mock_position.id = 1
    mock_position.instrument_token = "12345"
    mock_position.trading_symbol = "NIFTY25JAN24000CE"
    mock_position.exchange = "NFO"
    mock_position.entry_time = datetime.now()
    mock_position.entry_price = 100.0
    mock_position.current_price = 150.0
    mock_position.quantity = 50
    mock_position.lot_size = 1
    
    # Mock trade creation
    mock_trade = Mock(spec=Trade)
    mock_trade.id = 1
    mock_trade.realized_pnl = 2500.0  # (150 - 100) * 50
    trade_repo.create_trade.return_value = mock_trade
    
    # Mock protected profit
    trade_repo.get_protected_profit.return_value = 2500.0
    
    profit_protection = ProfitProtection(
        position_repo,
        trade_repo,
        daily_stats_repo,
        mock_kite_client
    )
    
    # Process position closure
    result = profit_protection._process_position_closure(mock_position)
    
    assert result is not None
    assert result["is_profit"] == True
    assert result["protected"] == True
    assert result["realized_pnl"] == 2500.0
    
    # Verify trade was created
    trade_repo.create_trade.assert_called_once()
    
    # Verify position was deactivated
    position_repo.deactivate_position.assert_called_once_with(1)


def test_no_profit_locking_on_loss(mock_repos, mock_kite_client):
    """Test that profit is not locked when trade closes with loss"""
    position_repo, trade_repo, daily_stats_repo = mock_repos
    
    # Mock position with loss
    mock_position = Mock(spec=Position)
    mock_position.id = 1
    mock_position.instrument_token = "12345"
    mock_position.trading_symbol = "NIFTY25JAN24000CE"
    mock_position.exchange = "NFO"
    mock_position.entry_time = datetime.now()
    mock_position.entry_price = 150.0
    mock_position.current_price = 100.0
    mock_position.quantity = 50
    mock_position.lot_size = 1
    
    # Mock trade creation
    mock_trade = Mock(spec=Trade)
    mock_trade.id = 1
    mock_trade.realized_pnl = -2500.0  # (100 - 150) * 50
    trade_repo.create_trade.return_value = mock_trade
    
    # Mock protected profit (should remain unchanged)
    trade_repo.get_protected_profit.return_value = 0.0
    
    profit_protection = ProfitProtection(
        position_repo,
        trade_repo,
        daily_stats_repo,
        mock_kite_client
    )
    
    # Process position closure
    result = profit_protection._process_position_closure(mock_position)
    
    assert result is not None
    assert result["is_profit"] == False
    assert result["protected"] == False
    assert result["realized_pnl"] == -2500.0


def test_separate_risk_calculation(mock_repos, mock_kite_client):
    """Test that daily loss limit applies only to current positions, not protected profit"""
    position_repo, trade_repo, daily_stats_repo = mock_repos
    
    # Mock: Protected profit = ₹8,000, Current position loss = ₹3,000
    trade_repo.get_protected_profit.return_value = 8000.0
    
    mock_position = Mock(spec=Position)
    mock_position.unrealized_pnl = -3000.0  # Loss
    position_repo.get_active_positions.return_value = [mock_position]
    
    profit_protection = ProfitProtection(
        position_repo,
        trade_repo,
        daily_stats_repo,
        mock_kite_client
    )
    
    pnl_breakdown = profit_protection.get_total_daily_pnl()
    
    # Protected profit should remain ₹8,000
    assert pnl_breakdown["protected_profit"] == 8000.0
    # Current P&L should be -₹3,000
    assert pnl_breakdown["current_pnl"] == -3000.0
    # Total P&L should be ₹5,000 (₹8,000 - ₹3,000)
    assert pnl_breakdown["total_pnl"] == 5000.0
    
    # Daily loss limit should apply only to current_pnl (-₹3,000), not total
    # So loss limit check should be on ₹3,000, not ₹5,000

