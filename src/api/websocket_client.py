"""
Kite Connect WebSocket Client
Real-time price updates via WebSocket connection
"""

import threading
import time
import json
from typing import Dict, List, Optional, Callable, Any
from kiteconnect import KiteTicker
from src.utils.logger import get_logger
from src.utils.exceptions import APIError
from src.api.kite_client import KiteClient

logger = get_logger("api")


class WebSocketClient:
    """WebSocket client for real-time price updates"""
    
    def __init__(self, kite_client: KiteClient):
        self.kite_client = kite_client
        self.kite_ticker: Optional[KiteTicker] = None
        self.subscribed_instruments: List[int] = []
        self._is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 20  # Increased from 10 to 20 for Azure
        self.reconnect_delay = 1  # Start with 1 second
        self.max_reconnect_delay = 120  # Increased from 60 to 120 seconds for Azure
        self._last_tick_time = 0  # Track last tick received for health monitoring
        self._reconnecting = False  # Flag to prevent multiple simultaneous reconnection attempts
        
        # Callbacks
        self.on_ticks: Optional[Callable] = None
        self.on_connect: Optional[Callable] = None
        self.on_close: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        
        # Position tracking for price updates
        self.instrument_tokens: Dict[str, int] = {}  # symbol -> token mapping
    
    def set_callbacks(
        self,
        on_ticks: Optional[Callable] = None,
        on_connect: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        on_error: Optional[Callable] = None
    ):
        """Set callback functions"""
        self.on_ticks = on_ticks
        self.on_connect = on_connect
        self.on_close = on_close
        self.on_error = on_error
    
    def connect(self) -> bool:
        """Connect to Kite WebSocket"""
        try:
            if not self.kite_client.is_authenticated():
                logger.error("Kite client not authenticated. Cannot connect WebSocket.")
                return False
            
            if not self.kite_client.access_token:
                logger.error("Access token not available for WebSocket connection.")
                return False
            
            # Initialize KiteTicker
            self.kite_ticker = KiteTicker(
                self.kite_client.api_key,
                self.kite_client.access_token
            )
            
            # Set callbacks
            self.kite_ticker.on_ticks = self._on_ticks
            self.kite_ticker.on_connect = self._on_connect
            self.kite_ticker.on_close = self._on_close
            self.kite_ticker.on_error = self._on_error
            
            # Connect
            self.kite_ticker.connect(threaded=True)
            self._is_connected = True
            logger.info("WebSocket connection initiated")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting WebSocket: {e}")
            return False
    
    def disconnect(self):
        """Disconnect WebSocket"""
        try:
            if self.kite_ticker:
                self.kite_ticker.close()
                self._is_connected = False
                logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting WebSocket: {e}")
    
    def subscribe(self, instrument_tokens: List[int]):
        """Subscribe to instrument tokens for price updates"""
        if not self.kite_ticker or not self._is_connected:
            logger.warning("WebSocket not connected. Cannot subscribe.")
            return
        
        try:
            self.kite_ticker.subscribe(instrument_tokens)
            self.subscribed_instruments.extend(instrument_tokens)
            self.subscribed_instruments = list(set(self.subscribed_instruments))  # Remove duplicates
            logger.info(f"Subscribed to {len(instrument_tokens)} instruments")
        except Exception as e:
            logger.error(f"Error subscribing to instruments: {e}")
    
    def unsubscribe(self, instrument_tokens: List[int]):
        """Unsubscribe from instrument tokens"""
        if not self.kite_ticker or not self._is_connected:
            return
        
        try:
            self.kite_ticker.unsubscribe(instrument_tokens)
            self.subscribed_instruments = [
                token for token in self.subscribed_instruments
                if token not in instrument_tokens
            ]
            logger.info(f"Unsubscribed from {len(instrument_tokens)} instruments")
        except Exception as e:
            logger.error(f"Error unsubscribing from instruments: {e}")
    
    def subscribe_to_positions(self):
        """Subscribe to all active positions"""
        try:
            positions = self.kite_client.get_positions()
            instrument_tokens = []
            
            for pos in positions:
                if pos.get('quantity', 0) != 0:
                    instrument_token = pos.get('instrument_token')
                    if instrument_token:
                        instrument_tokens.append(instrument_token)
                        # Store mapping
                        symbol = pos.get('tradingsymbol', '')
                        self.instrument_tokens[symbol] = instrument_token
            
            if instrument_tokens:
                self.subscribe(instrument_tokens)
                logger.info(f"Subscribed to {len(instrument_tokens)} active positions")
            else:
                logger.info("No active positions to subscribe to")
                
        except Exception as e:
            logger.error(f"Error subscribing to positions: {e}")
    
    def _on_ticks(self, ws, ticks):
        """Handle incoming price ticks"""
        try:
            # Update last tick time for health monitoring
            self._last_tick_time = time.time()
            
            # Reset reconnect attempts on successful tick
            if self.reconnect_attempts > 0:
                self.reconnect_attempts = 0
                logger.debug("WebSocket health restored - resetting reconnect counter")
            
            if self.on_ticks:
                self.on_ticks(ticks)
        except Exception as e:
            logger.error(f"Error in on_ticks callback: {e}")
    
    def _on_connect(self, ws, response):
        """Handle WebSocket connection"""
        try:
            self._is_connected = True
            self.reconnect_attempts = 0
            self.reconnect_delay = 1
            logger.info("WebSocket connected successfully")
            
            # Resubscribe to instruments
            if self.subscribed_instruments:
                self.subscribe(self.subscribed_instruments)
            
            if self.on_connect:
                self.on_connect()
                
        except Exception as e:
            logger.error(f"Error in on_connect: {e}")
    
    def _on_close(self, ws, code, reason):
        """Handle WebSocket disconnection"""
        try:
            self._is_connected = False
            logger.warning(f"WebSocket closed: code={code}, reason={reason}")
            
            if self.on_close:
                self.on_close(code, reason)
            
            # Attempt reconnection
            self._attempt_reconnect()
            
        except Exception as e:
            logger.error(f"Error in on_close: {e}")
    
    def _on_error(self, ws, code, reason):
        """Handle WebSocket errors"""
        try:
            logger.error(f"WebSocket error: code={code}, reason={reason}")
            
            if self.on_error:
                self.on_error(code, reason)
            
            # Attempt reconnection on error
            self._attempt_reconnect()
            
        except Exception as e:
            logger.error(f"Error in on_error handler: {e}")
    
    def _attempt_reconnect(self):
        """Attempt to reconnect with exponential backoff"""
        # Prevent multiple simultaneous reconnection attempts
        if self._reconnecting:
            logger.debug("Reconnection already in progress, skipping duplicate attempt")
            return
        
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(
                f"Max reconnection attempts ({self.max_reconnect_attempts}) reached. "
                f"WebSocket will continue attempting to reconnect periodically."
            )
            # Reset counter after a longer delay to allow periodic retries
            time.sleep(300)  # Wait 5 minutes before allowing more attempts
            self.reconnect_attempts = 0
            return
        
        self._reconnecting = True
        try:
            self.reconnect_attempts += 1
            delay = min(self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)), self.max_reconnect_delay)
            
            logger.info(
                f"Attempting WebSocket reconnection {self.reconnect_attempts}/{self.max_reconnect_attempts} "
                f"in {delay:.1f} seconds..."
            )
            
            time.sleep(delay)
            
            # Verify authentication before reconnecting
            if not self.kite_client.is_authenticated():
                logger.error("Kite client not authenticated. Cannot reconnect WebSocket.")
                self._reconnecting = False
                return
            
            # Attempt reconnection
            if self.connect():
                logger.info("WebSocket reconnection successful")
                self._reconnecting = False
            else:
                logger.warning("WebSocket reconnection attempt failed, will retry")
                # Schedule another reconnection attempt
                threading.Timer(5.0, self._attempt_reconnect).start()
        except Exception as e:
            logger.error(f"Reconnection attempt failed: {e}")
            # Schedule another reconnection attempt after delay
            threading.Timer(10.0, self._attempt_reconnect).start()
        finally:
            self._reconnecting = False
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        if not self._is_connected:
            return False
        
        # Health check: if no ticks received in last 5 minutes, consider disconnected
        if self._last_tick_time > 0:
            time_since_last_tick = time.time() - self._last_tick_time
            if time_since_last_tick > 300:  # 5 minutes
                logger.warning(
                    f"No WebSocket ticks received in {time_since_last_tick:.0f} seconds. "
                    f"Connection may be stale."
                )
                # Don't mark as disconnected, but log warning
                # The on_close/on_error handlers will handle actual disconnection
        
        return self._is_connected
    
    def check_connection_health(self) -> bool:
        """
        Check WebSocket connection health and attempt recovery if needed.
        Returns True if connection is healthy, False otherwise.
        """
        if not self._is_connected:
            return False
        
        # Check if we have subscribed instruments but haven't received ticks recently
        if self.subscribed_instruments and self._last_tick_time > 0:
            time_since_last_tick = time.time() - self._last_tick_time
            if time_since_last_tick > 180:  # 3 minutes without ticks
                logger.warning(
                    f"WebSocket health check: No ticks for {time_since_last_tick:.0f} seconds. "
                    f"Attempting to resubscribe..."
                )
                # Try to resubscribe to refresh connection
                try:
                    if self.subscribed_instruments:
                        self.subscribe(self.subscribed_instruments)
                except Exception as e:
                    logger.error(f"Failed to resubscribe during health check: {e}")
                    return False
        
        return True

