"""
Broker Context Manager
Manages the current BrokerID (User ID) for multi-tenancy support.
All database operations will be filtered by the current BrokerID.
"""

import threading
from typing import Optional, Dict
from src.utils.logger import get_logger

logger = get_logger("broker_context")

# Thread-local storage for current broker ID
_thread_local = threading.local()

# Global cache: access_token -> broker_id (for persistence across requests)
# This allows BrokerID to persist across different Flask request threads
_broker_id_cache: Dict[str, str] = {}
# Global cache: access_token -> profile (for persistence across requests)
_profile_cache: Dict[str, Dict] = {}
_cache_lock = threading.Lock()


class BrokerContext:
    """Context manager for BrokerID (User ID from Kite API)"""
    
    @staticmethod
    def set_broker_id(broker_id: str, access_token: Optional[str] = None):
        """Set the current broker ID for this thread and optionally cache it by access_token"""
        if not broker_id:
            raise ValueError("BrokerID cannot be empty")
        broker_id_str = str(broker_id)
        _thread_local.broker_id = broker_id_str
        logger.debug(f"BrokerID set to: {broker_id_str}")
        
        # Cache by access_token for persistence across requests
        if access_token:
            with _cache_lock:
                _broker_id_cache[access_token] = broker_id_str
                logger.debug(f"BrokerID cached for access_token: {broker_id_str}")
    
    @staticmethod
    def get_broker_id(access_token: Optional[str] = None) -> Optional[str]:
        """Get the current broker ID for this thread, or from cache if access_token provided"""
        # First check thread-local storage
        broker_id = getattr(_thread_local, 'broker_id', None)
        if broker_id:
            return broker_id
        
        # If not in thread-local and access_token provided, try cache
        if access_token:
            with _cache_lock:
                broker_id = _broker_id_cache.get(access_token)
                if broker_id:
                    # Set it in thread-local for this request
                    _thread_local.broker_id = broker_id
                    logger.debug(f"BrokerID retrieved from cache: {broker_id}")
                    return broker_id
        
        return None
    
    @staticmethod
    def get_broker_id_from_cache(access_token: str) -> Optional[str]:
        """Get BrokerID from cache by access_token"""
        with _cache_lock:
            return _broker_id_cache.get(access_token)
    
    @staticmethod
    def clear_broker_id_cache(access_token: Optional[str] = None):
        """Clear BrokerID from cache"""
        if access_token:
            with _cache_lock:
                _broker_id_cache.pop(access_token, None)
                _profile_cache.pop(access_token, None)
                logger.debug(f"BrokerID and profile cleared from cache for access_token")
        else:
            with _cache_lock:
                _broker_id_cache.clear()
                _profile_cache.clear()
                logger.debug("BrokerID and profile cache cleared")
    
    @staticmethod
    def get_profile_from_cache(access_token: str) -> Optional[Dict]:
        """Get profile from cache by access_token"""
        with _cache_lock:
            return _profile_cache.get(access_token)
    
    @staticmethod
    def set_profile_cache(access_token: str, profile: Dict):
        """Cache profile by access_token"""
        with _cache_lock:
            _profile_cache[access_token] = profile
            # Also extract and cache broker_id if available
            broker_id = str(profile.get('user_id', '') or profile.get('userid', ''))
            if broker_id:
                _broker_id_cache[access_token] = broker_id
            logger.debug(f"Profile cached for access_token")
    
    @staticmethod
    def clear_broker_id():
        """Clear the current broker ID"""
        if hasattr(_thread_local, 'broker_id'):
            delattr(_thread_local, 'broker_id')
        logger.debug("BrokerID cleared")
    
    @staticmethod
    def require_broker_id() -> str:
        """Get broker ID or raise error if not set"""
        broker_id = BrokerContext.get_broker_id()
        if not broker_id:
            raise ValueError("BrokerID not set. Please authenticate first.")
        return broker_id
    
    def __init__(self, broker_id: str):
        """Context manager entry"""
        self.broker_id = broker_id
        self.previous_broker_id = None
    
    def __enter__(self):
        """Enter context - save previous and set new"""
        self.previous_broker_id = BrokerContext.get_broker_id()
        BrokerContext.set_broker_id(self.broker_id)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context - restore previous or clear"""
        if self.previous_broker_id:
            BrokerContext.set_broker_id(self.previous_broker_id)
        else:
            BrokerContext.clear_broker_id()
        return False

