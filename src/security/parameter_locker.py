"""
Parameter Locking Mechanism
Locks critical risk parameters from user modification
"""

from typing import Dict, Any, List, Optional, TYPE_CHECKING
from src.utils.logger import get_logger
from src.config.config_manager import ConfigManager
from src.security.access_control import AccessControl
from src.database.models import DatabaseManager

if TYPE_CHECKING:
    from src.security.version_control import VersionControl

logger = get_logger("security")


class ParameterLocker:
    """Manages locking of critical risk parameters"""
    
    # Locked parameters that require admin access to modify
    LOCKED_PARAMETERS = [
        "daily_loss_limit",
        "trailing_sl_activation",
        "trailing_sl_increment",
        "loss_warning_threshold",
        "trading_block_enabled",
        "exclude_equity_trades"
    ]
    
    def __init__(self, config_manager: ConfigManager, access_control: AccessControl, version_control: Optional["VersionControl"] = None):
        self.config_manager = config_manager
        self.access_control = access_control
        self.version_control = version_control
    
    def is_locked(self, parameter_name: str) -> bool:
        """Check if a parameter is locked"""
        return parameter_name in self.LOCKED_PARAMETERS
    
    def get_locked_parameters(self) -> List[str]:
        """Get list of all locked parameters"""
        return self.LOCKED_PARAMETERS.copy()
    
    def can_modify(self, parameter_name: str, token: str) -> bool:
        """Check if user can modify a parameter"""
        if not self.is_locked(parameter_name):
            return True  # Unlocked parameters can be modified by anyone
        
        # Locked parameters require admin access
        return self.access_control.is_admin(token)
    
    def update_parameter(
        self,
        parameter_name: str,
        value: Any,
        token: str,
        admin_password: Optional[str] = None
    ) -> bool:
        """
        Update a parameter (requires admin if locked)
        
        Args:
            parameter_name: Name of parameter to update
            value: New value
            token: User session token
            admin_password: Admin password (required for locked parameters)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.is_locked(parameter_name):
            # Unlocked parameter - can be modified by any authenticated user
            if not self.access_control.is_user(token):
                logger.warning(f"Unauthorized attempt to modify {parameter_name}")
                return False
            
            # Update in user config
            # For now, we'll just log - actual implementation would update config
            logger.info(f"Parameter {parameter_name} updated to {value} by user")
            return True
        
        # Locked parameter - requires admin
        if not self.access_control.is_admin(token):
            logger.warning(f"Unauthorized attempt to modify locked parameter {parameter_name}")
            return False
        
        # Verify admin password if provided
        if admin_password:
            admin_token = self.access_control.authenticate_admin(admin_password)
            if not admin_token:
                logger.warning(f"Invalid admin password for parameter update: {parameter_name}")
                return False
        
        # Get old value for version control
        param_info = self.get_parameter_info(parameter_name)
        old_value = param_info.get('current_value')
        
        # Update admin config
        try:
            updates = {parameter_name: value}
            success = self.config_manager.update_admin_config(updates, admin_password or "")
            
            if not success:
                return False
            
            # Log audit
            session = self.access_control.verify_session(token)
            changed_by = session.user_id if session else "unknown"
            self.access_control._log_audit(
                "parameter_update",
                {"parameter": parameter_name, "old_value": old_value, "new_value": value},
                token
            )
            
            # Record version (if version_control is available)
            # Note: Version control is also handled in admin_panel.py, so this is optional
            try:
                if self.version_control:
                    self.version_control.record_change(
                        parameter_name,
                        old_value,
                        value,
                        changed_by,
                        f"Updated via admin panel"
                    )
            except Exception as version_error:
                # Version control failure shouldn't prevent parameter update
                logger.warning(f"Failed to record version for {parameter_name}: {version_error}")
            
            logger.info(f"Locked parameter {parameter_name} updated to {value} by admin")
            return True
        except Exception as e:
            logger.error(f"Error updating parameter {parameter_name}: {e}", exc_info=True)
            return False
    
    def get_parameter_info(self, parameter_name: str) -> Dict[str, Any]:
        """Get parameter information including lock status"""
        admin_config = self.config_manager.get_admin_config()
        is_locked = self.is_locked(parameter_name)
        
        info = {
            "name": parameter_name,
            "is_locked": is_locked,
            "current_value": getattr(admin_config, parameter_name, None),
            "requires_admin": is_locked
        }
        
        return info
    
    def get_all_parameters_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all parameters"""
        admin_config = self.config_manager.get_admin_config()
        all_params = {}
        
        # Get all admin config parameters
        for param in self.LOCKED_PARAMETERS:
            all_params[param] = self.get_parameter_info(param)
        
        return all_params

