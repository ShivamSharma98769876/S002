"""
Unit Tests for Security Components
"""

import unittest
from unittest.mock import Mock, patch
from src.security.access_control import AccessControl
from src.security.parameter_locker import ParameterLocker
from src.security.version_control import VersionControl
from src.config.config_manager import ConfigManager
from src.database.models import DatabaseManager


class TestAccessControl(unittest.TestCase):
    """Test cases for Access Control"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_db_manager = Mock(spec=DatabaseManager)
        self.mock_config = Mock(spec=ConfigManager)
        self.mock_config.get_admin_config.return_value = Mock(
            admin_password="admin123"
        )
        
        self.access_control = AccessControl(self.mock_db_manager)
        self.access_control.config_manager = self.mock_config
        self.access_control.admin_password_hash = self.access_control._get_admin_password_hash()
    
    def test_authenticate_admin_success(self):
        """Test successful admin authentication"""
        token = self.access_control.authenticate_admin("admin123")
        
        self.assertIsNotNone(token)
        self.assertTrue(self.access_control.is_admin(token))
    
    def test_authenticate_admin_failure(self):
        """Test failed admin authentication"""
        token = self.access_control.authenticate_admin("wrong_password")
        
        self.assertIsNone(token)
    
    def test_is_admin(self):
        """Test admin role check"""
        token = self.access_control.authenticate_admin("admin123")
        
        self.assertTrue(self.access_control.is_admin(token))
        self.assertTrue(self.access_control.is_user(token))
    
    def test_session_expiry(self):
        """Test session expiry"""
        token = self.access_control.create_session("admin", "admin")
        
        # Manually expire session
        self.access_control.sessions[token]["expiry"] = self.access_control.sessions[token]["expiry"].replace(year=2020)
        
        self.assertFalse(self.access_control.is_valid_session(token))


class TestParameterLocker(unittest.TestCase):
    """Test cases for Parameter Locker"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_config = Mock(spec=ConfigManager)
        self.mock_access_control = Mock(spec=AccessControl)
        
        self.parameter_locker = ParameterLocker(self.mock_config, self.mock_access_control)
    
    def test_is_locked(self):
        """Test parameter lock status check"""
        self.assertTrue(self.parameter_locker.is_locked("daily_loss_limit"))
        self.assertTrue(self.parameter_locker.is_locked("trailing_sl_activation"))
        self.assertFalse(self.parameter_locker.is_locked("notification_channels"))
    
    def test_can_modify_parameter_unlocked(self):
        """Test modification permission for unlocked parameter"""
        self.mock_access_control.is_user.return_value = True
        
        can_modify = self.parameter_locker.can_modify_parameter("notification_channels", "token")
        
        self.assertTrue(can_modify)
    
    def test_can_modify_parameter_locked_admin(self):
        """Test modification permission for locked parameter (admin)"""
        self.mock_access_control.is_admin.return_value = True
        
        can_modify = self.parameter_locker.can_modify_parameter("daily_loss_limit", "token")
        
        self.assertTrue(can_modify)
    
    def test_can_modify_parameter_locked_user(self):
        """Test modification permission for locked parameter (user)"""
        self.mock_access_control.is_admin.return_value = False
        self.mock_access_control.is_user.return_value = True
        
        can_modify = self.parameter_locker.can_modify_parameter("daily_loss_limit", "token")
        
        self.assertFalse(can_modify)


class TestVersionControl(unittest.TestCase):
    """Test cases for Version Control"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_db_manager = Mock(spec=DatabaseManager)
        
        self.version_control = VersionControl(self.mock_db_manager)
    
    def test_log_rule_change(self):
        """Test logging rule changes"""
        session = Mock()
        self.mock_db_manager.get_session.return_value = session
        
        self.version_control.log_rule_change(
            rule_name="daily_loss_limit",
            old_value=5000.0,
            new_value=6000.0,
            changed_by="admin"
        )
        
        session.add.assert_called_once()
        session.commit.assert_called_once()


if __name__ == '__main__':
    unittest.main()

