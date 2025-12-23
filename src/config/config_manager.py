"""
Configuration Management System
Handles loading and validation of configuration files
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field, validator


class UserConfig(BaseModel):
    """User-configurable parameters"""
    api_key: str = Field(..., description="Zerodha API Key")
    api_secret: str = Field(..., description="Zerodha API Secret")
    environment: str = Field(default="dev", description="Environment: dev or prod")
    log_level: str = Field(default="INFO", description="Logging level")
    notification_email: Optional[str] = Field(None, description="Email for notifications")
    notification_phone: Optional[str] = Field(None, description="Phone for SMS notifications")
    
    @validator('environment')
    def validate_environment(cls, v):
        if v not in ['dev', 'prod']:
            raise ValueError('Environment must be "dev" or "prod"')
        return v
    
    @validator('log_level')
    def validate_log_level(cls, v):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f'Log level must be one of {valid_levels}')
        return v.upper()


class AdminConfig(BaseModel):
    """Admin-only locked parameters"""
    daily_loss_limit: float = Field(default=5000.0, description="Daily loss limit in ₹")
    trailing_sl_activation: float = Field(default=5000.0, description="Trailing SL activation threshold in ₹")
    trailing_sl_increment: float = Field(default=10000.0, description="Trailing SL increment in ₹")
    loss_warning_threshold: float = Field(default=0.9, description="Warning threshold (90% of loss limit)")
    trading_block_enabled: bool = Field(default=True, description="Enable trading block on loss limit")
    exclude_equity_trades: bool = Field(default=True, description="Exclude equity trades (NSE, BSE) from positions and trade history")
    
    @validator('daily_loss_limit', 'trailing_sl_activation', 'trailing_sl_increment')
    def validate_positive_amounts(cls, v):
        if v <= 0:
            raise ValueError('Amount must be positive')
        return v
    
    @validator('loss_warning_threshold')
    def validate_warning_threshold(cls, v):
        if not 0 < v < 1:
            raise ValueError('Warning threshold must be between 0 and 1')
        return v


class ConfigManager:
    """Manages application configuration"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent / "config"
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
        
        self.user_config_path = self.config_dir / "config.json"
        self.admin_config_path = self.config_dir / "admin_config.json"
        
        self.user_config: Optional[UserConfig] = None
        self.admin_config: Optional[AdminConfig] = None
        
    def load_configs(self) -> Tuple[UserConfig, AdminConfig]:
        """Load and validate both configuration files"""
        # Load user config
        if not self.user_config_path.exists():
            raise FileNotFoundError(
                f"User config file not found: {self.user_config_path}\n"
                "Please create config.json from config.example.json"
            )
        
        with open(self.user_config_path, 'r') as f:
            user_data = json.load(f)
        self.user_config = UserConfig(**user_data)
        
        # Load admin config
        if not self.admin_config_path.exists():
            raise FileNotFoundError(
                f"Admin config file not found: {self.admin_config_path}\n"
                "Please create admin_config.json from admin_config.example.json"
            )
        
        with open(self.admin_config_path, 'r') as f:
            admin_data = json.load(f)
        self.admin_config = AdminConfig(**admin_data)
        
        return self.user_config, self.admin_config
    
    def get_user_config(self) -> UserConfig:
        """Get user configuration"""
        if self.user_config is None:
            self.load_configs()
        return self.user_config
    
    def get_admin_config(self) -> AdminConfig:
        """Get admin configuration"""
        if self.admin_config is None:
            self.load_configs()
        return self.admin_config
    
    def update_admin_config(self, updates: Dict[str, Any], admin_password: str = "") -> bool:
        """Update admin config (requires admin password)"""
        # Note: Password verification is handled by AccessControl
        try:
            if not self.admin_config:
                self.load_configs()
            
            # Create updated config
            current_data = self.admin_config.dict()
            current_data.update(updates)
            
            # Validate
            updated_config = AdminConfig(**current_data)
            
            # Save
            with open(self.admin_config_path, 'w') as f:
                json.dump(updated_config.dict(), f, indent=2)
            
            # Reload config to reflect changes
            self.admin_config = updated_config
            
            return True
        except Exception as e:
            import traceback
            from src.utils.logger import get_logger
            logger = get_logger("config")
            logger.error(f"Error updating admin config: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def create_example_configs(self):
        """Create example configuration files"""
        # User config example
        user_example = {
            "api_key": "your_api_key_here",
            "api_secret": "your_api_secret_here",
            "environment": "dev",
            "log_level": "INFO",
            "notification_email": "your_email@example.com",
            "notification_phone": "+91XXXXXXXXXX"
        }
        
        example_path = self.config_dir / "config.example.json"
        with open(example_path, 'w') as f:
            json.dump(user_example, f, indent=2)
        
        # Admin config example
        admin_example = {
            "daily_loss_limit": 5000.0,
            "trailing_sl_activation": 5000.0,
            "trailing_sl_increment": 10000.0,
            "loss_warning_threshold": 0.9,
            "trading_block_enabled": True,
            "exclude_equity_trades": True
        }
        
        admin_example_path = self.config_dir / "admin_config.example.json"
        with open(admin_example_path, 'w') as f:
            json.dump(admin_example, f, indent=2)
        
        print(f"Example config files created in {self.config_dir}")
        print("Please copy config.example.json to config.json and update with your values")
        print("Please copy admin_config.example.json to admin_config.json")

