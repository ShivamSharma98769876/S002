"""
Access Control System
Two-tier access: User level and Admin level
"""

import hashlib
import secrets
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from src.utils.logger import get_logger
from src.database.models import DatabaseManager, AuditLog
from sqlalchemy.orm import Session

logger = get_logger("security")


@dataclass
class UserSession:
    """User session data"""
    user_id: str
    role: str  # 'user' or 'admin'
    created_at: datetime
    expires_at: datetime
    token: str


class AccessControl:
    """Access control and authentication system"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.active_sessions: Dict[str, UserSession] = {}
        self.session_timeout = timedelta(hours=24)  # 24 hour session
        
        # Default admin password hash (should be changed in production)
        # Password: admin123 (change this!)
        self.admin_password_hash = self._hash_password("admin123")
    
    def _hash_password(self, password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def _generate_token(self) -> str:
        """Generate secure session token"""
        return secrets.token_urlsafe(32)
    
    def authenticate_user(self, username: str, password: str) -> Optional[str]:
        """
        Authenticate user (basic implementation)
        Returns session token if successful
        """
        # For now, we have a simple user authentication
        # In production, this should use proper user database
        if username == "user" and password:
            # User level - no password required for basic access
            token = self._generate_token()
            session = UserSession(
                user_id=username,
                role="user",
                created_at=datetime.now(),
                expires_at=datetime.now() + self.session_timeout,
                token=token
            )
            self.active_sessions[token] = session
            logger.info(f"User authenticated: {username}")
            return token
        return None
    
    def authenticate_admin(self, password: str) -> Optional[str]:
        """
        Authenticate admin with password
        Returns session token if successful
        """
        password_hash = self._hash_password(password)
        if password_hash == self.admin_password_hash:
            token = self._generate_token()
            session = UserSession(
                user_id="admin",
                role="admin",
                created_at=datetime.now(),
                expires_at=datetime.now() + self.session_timeout,
                token=token
            )
            self.active_sessions[token] = session
            logger.info("Admin authenticated")
            self._log_audit("admin_login", {"user": "admin"})
            return token
        logger.warning("Admin authentication failed")
        return None
    
    def verify_admin_password(self, password: str) -> bool:
        """
        Verify admin password without creating a session
        Returns True if password is correct
        """
        password_hash = self._hash_password(password)
        return password_hash == self.admin_password_hash
    
    def verify_session(self, token: str) -> Optional[UserSession]:
        """Verify session token and return session if valid"""
        if token not in self.active_sessions:
            return None
        
        session = self.active_sessions[token]
        
        # Check if session expired
        if datetime.now() > session.expires_at:
            del self.active_sessions[token]
            return None
        
        return session
    
    def is_admin(self, token: str) -> bool:
        """Check if session has admin privileges"""
        session = self.verify_session(token)
        return session is not None and session.role == "admin"
    
    def is_user(self, token: str) -> bool:
        """Check if session has user privileges"""
        session = self.verify_session(token)
        return session is not None
    
    def logout(self, token: str):
        """Logout and invalidate session"""
        if token in self.active_sessions:
            session = self.active_sessions[token]
            logger.info(f"User logged out: {session.user_id}")
            if session.role == "admin":
                self._log_audit("admin_logout", {"user": "admin"})
            del self.active_sessions[token]
    
    def change_admin_password(self, old_password: str, new_password: str, token: str) -> bool:
        """Change admin password (requires admin authentication)"""
        if not self.is_admin(token):
            logger.warning("Unauthorized admin password change attempt")
            return False
        
        old_hash = self._hash_password(old_password)
        if old_hash != self.admin_password_hash:
            logger.warning("Incorrect old password for admin password change")
            return False
        
        self.admin_password_hash = self._hash_password(new_password)
        logger.info("Admin password changed")
        self._log_audit("admin_password_change", {"user": "admin"}, token)
        return True
    
    def _log_audit(self, action: str, details: Dict[str, Any], token: Optional[str] = None):
        """Log audit event"""
        try:
            session = self.db_manager.get_session()
            try:
                user = "admin" if token and self.is_admin(token) else "system"
                audit_entry = AuditLog(
                    action=action,
                    user=user,
                    details=str(details),
                    timestamp=datetime.utcnow()
                )
                session.add(audit_entry)
                session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Error logging audit: {e}")
    
    def get_audit_logs(self, limit: int = 100) -> list:
        """Get audit logs (admin only)"""
        try:
            session = self.db_manager.get_session()
            try:
                logs = session.query(AuditLog).order_by(
                    AuditLog.timestamp.desc()
                ).limit(limit).all()
                return [
                    {
                        "id": log.id,
                        "timestamp": log.timestamp.isoformat(),
                        "action": log.action,
                        "user": log.user,
                        "details": log.details
                    }
                    for log in logs
                ]
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Error getting audit logs: {e}")
            return []

