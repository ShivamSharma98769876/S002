"""
Test Configuration Management
"""

import pytest
from pathlib import Path
from src.config.config_manager import ConfigManager, UserConfig, AdminConfig


def test_config_manager_initialization():
    """Test ConfigManager initialization"""
    config_manager = ConfigManager()
    assert config_manager.config_dir.exists() or config_manager.config_dir.parent.exists()


def test_example_config_creation(tmp_path):
    """Test creation of example config files"""
    config_manager = ConfigManager(config_dir=tmp_path)
    config_manager.create_example_configs()
    
    assert (tmp_path / "config.example.json").exists()
    assert (tmp_path / "admin_config.example.json").exists()


def test_user_config_validation():
    """Test UserConfig validation"""
    # Valid config
    valid_config = UserConfig(
        api_key="test_key",
        api_secret="test_secret",
        environment="dev",
        log_level="INFO"
    )
    assert valid_config.environment == "dev"
    assert valid_config.log_level == "INFO"
    
    # Invalid environment
    with pytest.raises(ValueError):
        UserConfig(
            api_key="test_key",
            api_secret="test_secret",
            environment="invalid"
        )
    
    # Invalid log level
    with pytest.raises(ValueError):
        UserConfig(
            api_key="test_key",
            api_secret="test_secret",
            log_level="INVALID"
        )


def test_admin_config_validation():
    """Test AdminConfig validation"""
    # Valid config
    valid_config = AdminConfig(
        daily_loss_limit=5000.0,
        trailing_sl_activation=5000.0,
        trailing_sl_increment=10000.0
    )
    assert valid_config.daily_loss_limit == 5000.0
    
    # Invalid negative amount
    with pytest.raises(ValueError):
        AdminConfig(daily_loss_limit=-1000.0)
    
    # Invalid warning threshold
    with pytest.raises(ValueError):
        AdminConfig(loss_warning_threshold=1.5)

