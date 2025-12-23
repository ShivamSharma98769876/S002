"""
Pytest Configuration and Fixtures
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

@pytest.fixture
def mock_db_manager():
    """Mock database manager"""
    from unittest.mock import Mock
    from src.database.models import DatabaseManager
    return Mock(spec=DatabaseManager)

@pytest.fixture
def mock_config_manager():
    """Mock configuration manager"""
    from unittest.mock import Mock
    from src.config.config_manager import ConfigManager
    
    config = Mock(spec=ConfigManager)
    user_config = Mock()
    user_config.api_key = "test_key"
    user_config.api_secret = "test_secret"
    user_config.environment = "dev"
    user_config.log_level = "INFO"
    
    admin_config = Mock()
    admin_config.daily_loss_limit = 5000.0
    admin_config.trailing_sl_activation = 5000.0
    admin_config.trailing_sl_increment = 10000.0
    admin_config.loss_warning_threshold = 0.8
    admin_config.admin_password = "admin123"
    
    config.get_user_config.return_value = user_config
    config.get_admin_config.return_value = admin_config
    
    return config

@pytest.fixture
def mock_kite_client():
    """Mock Kite client"""
    from unittest.mock import Mock
    from src.api.kite_client import KiteClient
    
    client = Mock(spec=KiteClient)
    client.access_token = "test_token"
    client.is_authenticated.return_value = True
    return client

@pytest.fixture
def mock_repositories(mock_db_manager):
    """Mock repositories"""
    from unittest.mock import Mock
    from src.database.repository import (
        PositionRepository,
        TradeRepository,
        DailyStatsRepository
    )
    
    position_repo = Mock(spec=PositionRepository)
    trade_repo = Mock(spec=TradeRepository)
    daily_stats_repo = Mock(spec=DailyStatsRepository)
    
    return position_repo, trade_repo, daily_stats_repo

