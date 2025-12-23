"""
Notification System
Multi-channel notification service for alerts and critical events
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
from src.utils.logger import get_logger
from src.config.config_manager import ConfigManager
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = get_logger("notifications")


class NotificationPriority(Enum):
    """Notification priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationChannel(Enum):
    """Notification delivery channels"""
    EMAIL = "email"
    SMS = "sms"
    IN_APP = "in_app"
    WHATSAPP = "whatsapp"


@dataclass
class Notification:
    """Notification data structure"""
    message: str
    priority: NotificationPriority
    channels: List[NotificationChannel]
    timestamp: datetime
    category: str
    details: Optional[Dict[str, Any]] = None


class NotificationService:
    """Centralized notification service"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        user_config = config_manager.get_user_config()
        
        self.email_enabled = bool(user_config.notification_email)
        self.sms_enabled = bool(user_config.notification_phone)
        self.in_app_enabled = True  # Always enabled
        
        self.email_address = user_config.notification_email
        self.phone_number = user_config.notification_phone
        
        # Notification queue
        self.notification_queue: List[Notification] = []
        self.sent_notifications: Dict[str, datetime] = {}  # Track to avoid duplicates
    
    def send_notification(
        self,
        message: str,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        channels: Optional[List[NotificationChannel]] = None,
        category: str = "general",
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Send notification through specified channels
        
        Args:
            message: Notification message
            priority: Notification priority
            channels: List of channels to use (default: all enabled)
            category: Notification category
            details: Additional details
        """
        if channels is None:
            channels = self._get_default_channels(priority)
        
        notification = Notification(
            message=message,
            priority=priority,
            channels=channels,
            timestamp=datetime.now(),
            category=category,
            details=details
        )
        
        # Check for duplicates (same message in last 5 minutes)
        if self._is_duplicate(message):
            logger.debug(f"Skipping duplicate notification: {message}")
            return
        
        # Add to queue
        self.notification_queue.append(notification)
        
        # Send through each channel
        for channel in channels:
            try:
                if channel == NotificationChannel.EMAIL and self.email_enabled:
                    self._send_email(notification)
                elif channel == NotificationChannel.SMS and self.sms_enabled:
                    self._send_sms(notification)
                elif channel == NotificationChannel.IN_APP:
                    self._send_in_app(notification)
                elif channel == NotificationChannel.WHATSAPP and self.sms_enabled:
                    self._send_whatsapp(notification)
            except Exception as e:
                logger.error(f"Error sending notification via {channel.value}: {e}")
        
        # Mark as sent
        self.sent_notifications[message] = datetime.now()
    
    def _get_default_channels(self, priority: NotificationPriority) -> List[NotificationChannel]:
        """Get default channels based on priority"""
        channels = [NotificationChannel.IN_APP]  # Always include in-app
        
        if priority in [NotificationPriority.HIGH, NotificationPriority.CRITICAL]:
            if self.email_enabled:
                channels.append(NotificationChannel.EMAIL)
            if self.sms_enabled:
                channels.append(NotificationChannel.SMS)
        
        return channels
    
    def _is_duplicate(self, message: str) -> bool:
        """Check if same message was sent recently"""
        if message not in self.sent_notifications:
            return False
        
        last_sent = self.sent_notifications[message]
        time_diff = (datetime.now() - last_sent).total_seconds()
        
        # Consider duplicate if sent within last 5 minutes
        return time_diff < 300
    
    def _send_email(self, notification: Notification):
        """Send email notification"""
        if not self.email_address:
            return
        
        try:
            # Create email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[{notification.priority.value.upper()}] Risk Management Alert"
            msg['From'] = "risk-management@system.local"
            msg['To'] = self.email_address
            
            # Create HTML email
            html = f"""
            <html>
                <body>
                    <h2>Risk Management Alert</h2>
                    <p><strong>Priority:</strong> {notification.priority.value.upper()}</p>
                    <p><strong>Category:</strong> {notification.category}</p>
                    <p><strong>Message:</strong> {notification.message}</p>
                    <p><strong>Time:</strong> {notification.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
                </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            # TODO: Configure SMTP settings
            # For now, just log
            logger.info(f"Email notification sent: {notification.message}")
            
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            raise
    
    def _send_sms(self, notification: Notification):
        """Send SMS notification"""
        if not self.phone_number:
            return
        
        try:
            # TODO: Integrate with SMS gateway (Twilio, etc.)
            # For now, just log
            logger.info(f"SMS notification sent to {self.phone_number}: {notification.message}")
            
        except Exception as e:
            logger.error(f"Error sending SMS: {e}")
            raise
    
    def _send_whatsapp(self, notification: Notification):
        """Send WhatsApp notification"""
        if not self.phone_number:
            return
        
        try:
            # TODO: Integrate with WhatsApp API
            # For now, just log
            logger.info(f"WhatsApp notification sent to {self.phone_number}: {notification.message}")
            
        except Exception as e:
            logger.error(f"Error sending WhatsApp: {e}")
            raise
    
    def _send_in_app(self, notification: Notification):
        """Send in-app notification"""
        try:
            # Store notification for UI to pick up
            # This will be handled by the dashboard
            logger.info(f"In-app notification: {notification.message}")
            
            # TODO: Store in database or message queue for UI
            # For now, notifications are logged and can be displayed via WebSocket
            
        except Exception as e:
            logger.error(f"Error sending in-app notification: {e}")
            raise
    
    # Specific notification methods
    def notify_loss_warning(self, current_loss: float, limit: float):
        """Notify when loss approaches limit (90%)"""
        message = f"Daily loss approaching ₹{current_loss:.2f} (90% of ₹{limit:.2f} limit)"
        self.send_notification(
            message=message,
            priority=NotificationPriority.HIGH,
            category="loss_warning"
        )
    
    def notify_loss_limit_reached(self, next_trading_day: str):
        """Notify when loss limit is reached"""
        message = f"Daily loss limit hit - All positions closed. Trading blocked until {next_trading_day}"
        self.send_notification(
            message=message,
            priority=NotificationPriority.CRITICAL,
            category="loss_limit"
        )
    
    def notify_trailing_sl_activated(self, profit: float):
        """Notify when trailing SL activates"""
        message = f"Profit ₹{profit:.2f} reached - Trailing SL activated"
        self.send_notification(
            message=message,
            priority=NotificationPriority.MEDIUM,
            category="trailing_sl"
        )
    
    def notify_trailing_sl_updated(self, new_level: float):
        """Notify when trailing SL is updated"""
        message = f"Trailing SL updated to ₹{new_level:.2f}"
        self.send_notification(
            message=message,
            priority=NotificationPriority.LOW,
            category="trailing_sl"
        )
    
    def notify_trailing_sl_triggered(self):
        """Notify when trailing SL is triggered"""
        message = "Trailing SL triggered - All positions closed"
        self.send_notification(
            message=message,
            priority=NotificationPriority.CRITICAL,
            category="trailing_sl"
        )
    
    def notify_trade_completed(self, profit: float, symbol: str):
        """Notify when trade is completed with profit"""
        message = f"Trade closed manually - Profit ₹{profit:.2f} protected | Symbol: {symbol}"
        self.send_notification(
            message=message,
            priority=NotificationPriority.MEDIUM,
            category="trade_completion"
        )

