"""
Custom Exception Classes for the Risk Management System
"""


class RiskManagementError(Exception):
    """Base exception for risk management system"""
    pass


class ConfigurationError(RiskManagementError):
    """Configuration-related errors"""
    pass


class APIError(RiskManagementError):
    """Zerodha API related errors"""
    pass


class AuthenticationError(APIError):
    """Authentication failures"""
    pass


class OrderExecutionError(APIError):
    """Order execution failures"""
    pass


class PositionError(RiskManagementError):
    """Position-related errors"""
    pass


class LossLimitExceededError(RiskManagementError):
    """Daily loss limit exceeded"""
    pass


class TradingBlockedError(RiskManagementError):
    """Trading is currently blocked"""
    pass


class DatabaseError(RiskManagementError):
    """Database operation errors"""
    pass


class ValidationError(RiskManagementError):
    """Data validation errors"""
    pass


class NotificationError(RiskManagementError):
    """Notification delivery errors"""
    pass


class TrailingSLTriggeredError(RiskManagementError):
    """Trailing stop loss triggered"""
    pass

