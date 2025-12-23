"""
Comprehensive Logging System
Supports structured logging with different log levels, file rotation, and audit logging
"""

import logging
import logging.handlers
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
import colorlog


class Logger:
    """Centralized logging system"""
    
    def __init__(self, log_dir: Optional[Path] = None, log_level: str = "INFO"):
        if log_dir is None:
            log_dir = Path(__file__).parent.parent.parent / "logs"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self._setup_loggers()
    
    def _setup_loggers(self):
        """Setup all loggers"""
        # Main application logger
        self.app_logger = self._create_logger(
            name="app",
            log_file=self.log_dir / "app.log",
            max_bytes=10 * 1024 * 1024,  # 10MB
            backup_count=10
        )
        
        # API logger
        self.api_logger = self._create_logger(
            name="api",
            log_file=self.log_dir / "api.log",
            max_bytes=10 * 1024 * 1024,
            backup_count=10
        )
        
        # Risk management logger
        self.risk_logger = self._create_logger(
            name="risk",
            log_file=self.log_dir / "risk.log",
            max_bytes=10 * 1024 * 1024,
            backup_count=10
        )
        
        # Audit logger (for critical operations)
        self.audit_logger = self._create_logger(
            name="audit",
            log_file=self.log_dir / "audit.log",
            max_bytes=50 * 1024 * 1024,  # 50MB for audit
            backup_count=20,
            use_color=False  # Audit logs should be plain
        )
        
        # Error logger
        self.error_logger = self._create_logger(
            name="error",
            log_file=self.log_dir / "error.log",
            max_bytes=10 * 1024 * 1024,
            backup_count=10
        )
    
    def _create_logger(
        self,
        name: str,
        log_file: Path,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 10,
        use_color: bool = True
    ) -> logging.Logger:
        """Create a logger with file rotation and console output"""
        logger = logging.getLogger(name)
        logger.setLevel(self.log_level)
        
        # Avoid duplicate handlers
        if logger.handlers:
            return logger
        
        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(self.log_level)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # Console handler with colors
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.log_level)
        
        if use_color:
            console_formatter = colorlog.ColoredFormatter(
                '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S',
                log_colors={
                    'DEBUG': 'cyan',
                    'INFO': 'green',
                    'WARNING': 'yellow',
                    'ERROR': 'red',
                    'CRITICAL': 'red,bg_white',
                }
            )
        else:
            console_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    def log_audit(self, action: str, details: dict, user: Optional[str] = None):
        """Log audit trail for critical operations"""
        timestamp = datetime.now().isoformat()
        audit_entry = {
            "timestamp": timestamp,
            "action": action,
            "user": user or "system",
            "details": details
        }
        self.audit_logger.info(f"AUDIT: {action} | User: {user or 'system'} | Details: {details}")
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get a specific logger by name"""
        loggers = {
            "app": self.app_logger,
            "api": self.api_logger,
            "risk": self.risk_logger,
            "audit": self.audit_logger,
            "error": self.error_logger
        }
        return loggers.get(name, self.app_logger)


# Global logger instance
_logger_instance: Optional[Logger] = None


def get_logger(name: str = "app") -> logging.Logger:
    """Get logger instance"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger()
    return _logger_instance.get_logger(name)


def initialize_logger(log_dir: Optional[Path] = None, log_level: str = "INFO"):
    """Initialize the global logger"""
    global _logger_instance
    _logger_instance = Logger(log_dir, log_level)


def get_segment_logger(segment: str, mode: str, log_dir: Optional[Path] = None) -> logging.Logger:
    """
    Get a segment-specific logger for Paper/Live trading.
    
    Args:
        segment: Segment name (NIFTY, BANKNIFTY, SENSEX)
        mode: Trading mode (PAPER or LIVE)
        log_dir: Optional log directory, defaults to logs/
    
    Returns:
        Logger instance configured for the segment and mode
    """
    if log_dir is None:
        log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Format: Paper_Sensex_2025-11-28.log or Live_Banknifty_2025-11-28.log
    today = datetime.now().strftime("%Y-%m-%d")
    segment_normalized = segment.upper()
    mode_normalized = mode.upper()
    log_file_name = f"{mode_normalized}_{segment_normalized}_{today}.log"
    log_file = log_dir / log_file_name
    
    # Create unique logger name
    logger_name = f"{mode_normalized.lower()}_{segment_normalized.lower()}"
    logger = logging.getLogger(logger_name)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.INFO)
    
    # File handler with rotation (daily rotation)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=50 * 1024 * 1024,  # 50MB per file
        backupCount=30,  # Keep 30 days of backups
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Console handler (optional - can be disabled if too verbose)
    # Only add console handler if not already present
    has_console = any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    if not has_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = colorlog.ColoredFormatter(
            '%(log_color)s[%(asctime)s] %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    return logger
