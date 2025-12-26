"""
Zerodha Kite Connect API Client
Handles authentication, position monitoring, order execution, and account information
"""

from kiteconnect import KiteConnect
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime
import time
import functools
from src.utils.logger import get_logger
from src.utils.exceptions import (
    APIError, AuthenticationError, OrderExecutionError
)
from src.config.config_manager import ConfigManager

logger = get_logger("api")


def retry_api_call(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 10.0):
    """
    Decorator to retry API calls with exponential backoff.
    Handles transient network errors, timeouts, and rate limits.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    last_exception = e
                    
                    # Check if error is retryable
                    is_retryable = any(keyword in error_str for keyword in [
                        'timeout', 'connection', 'network', 'temporarily unavailable',
                        'too many requests', 'rate limit', 'service unavailable',
                        'bad gateway', 'gateway timeout', 'internal server error',
                        'connection reset', 'connection aborted', 'broken pipe'
                    ])
                    
                    # Don't retry authentication errors or permanent failures
                    if not is_retryable or attempt == max_retries - 1:
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(
                        f"API call failed (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay:.1f} seconds..."
                    )
                    time.sleep(delay)
            
            # If all retries failed, raise the last exception
            raise last_exception
        return wrapper
    return decorator


class KiteClient:
    """Zerodha Kite Connect API client wrapper"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        user_config = config_manager.get_user_config()
        self.api_key = user_config.api_key
        self.api_secret = user_config.api_secret
        self.kite: Optional[KiteConnect] = None
        self.access_token: Optional[str] = None
        self._authenticated = False
    
    def authenticate(self, request_token: str) -> bool:
        """Authenticate with Zerodha using request token"""
        try:
            if not self.kite:
                self.kite = KiteConnect(api_key=self.api_key)
            
            data = self.kite.generate_session(request_token, api_secret=self.api_secret)
            self.access_token = data['access_token']
            self.kite.set_access_token(self.access_token)
            self._authenticated = True
            
            logger.info("Successfully authenticated with Zerodha Kite Connect")
            return True
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise AuthenticationError(f"Failed to authenticate: {str(e)}")
    
    def set_access_token(self, access_token: str):
        """Set access token directly (for persistent sessions)"""
        try:
            if not self.kite:
                self.kite = KiteConnect(api_key=self.api_key)
            self.kite.set_access_token(access_token)
            self.access_token = access_token
            self._authenticated = True
            logger.info("Access token set successfully")
        except Exception as e:
            logger.error(f"Failed to set access token: {e}")
            raise AuthenticationError(f"Failed to set access token: {str(e)}")
    
    def is_authenticated(self) -> bool:
        """Check if client is authenticated and token is valid (with caching to avoid rate limits)"""
        if not self._authenticated or self.kite is None:
            return False
        
        # Cache validation result to avoid too many API calls
        if not hasattr(self, '_last_auth_check'):
            self._last_auth_check = 0
            self._cached_auth_result = False
        
        # Only validate token every 60 seconds to avoid rate limits
        current_time = time.time()
        if current_time - self._last_auth_check < 60:
            return self._cached_auth_result
        
        # Verify token is valid by making a lightweight API call with retry
        try:
            # Try to get user profile (lightweight call) with retry
            self._call_with_retry(lambda: self.kite.profile())
            self._cached_auth_result = True
            self._last_auth_check = current_time
            return True
        except Exception as e:
            error_str = str(e).lower()
            # Don't mark as disconnected for transient network errors
            is_transient = any(keyword in error_str for keyword in [
                'timeout', 'connection', 'network', 'temporarily unavailable',
                'service unavailable', 'bad gateway', 'gateway timeout'
            ])
            
            if is_transient:
                # Keep cached result for transient errors, but log warning
                logger.warning(f"Token validation failed due to transient error: {e}. Keeping cached auth status.")
                return self._cached_auth_result
            
            # Only log warning if it's not a rate limit error
            if "too many requests" not in error_str and "rate limit" not in error_str:
                logger.warning(f"Token validation failed: {e}")
            # Token might be expired or invalid
            self._authenticated = False
            self._cached_auth_result = False
            self._last_auth_check = current_time
            return False
    
    def _call_with_retry(self, func: Callable, max_retries: int = 3, base_delay: float = 1.0):
        """Helper method to retry API calls with exponential backoff"""
        last_exception = None
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                error_str = str(e).lower()
                last_exception = e
                
                # Check if error is retryable
                is_retryable = any(keyword in error_str for keyword in [
                    'timeout', 'connection', 'network', 'temporarily unavailable',
                    'too many requests', 'rate limit', 'service unavailable',
                    'bad gateway', 'gateway timeout', 'internal server error',
                    'connection reset', 'connection aborted', 'broken pipe'
                ])
                
                # Don't retry on last attempt or non-retryable errors
                if not is_retryable or attempt == max_retries - 1:
                    raise
                
                # Calculate delay with exponential backoff
                delay = min(base_delay * (2 ** attempt), 10.0)
                logger.debug(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
        
        raise last_exception
    
    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch current positions from Zerodha"""
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            positions = self.kite.positions()
            # Filter non-equity positions (exclude NSE, BSE equity)
            non_equity_positions = []
            all_net_positions = positions.get('net', [])
            
            logger.debug(f"Total net positions from API: {len(all_net_positions)}")
            
            for pos in all_net_positions:
                exchange = pos.get('exchange', '').upper()
                tradingsymbol = pos.get('tradingsymbol', '').upper()
                instrument_type = pos.get('instrument_type', '').upper()
                raw_quantity = pos.get('quantity', 0)
                quantity = int(raw_quantity)  # Preserve sign: positive = BUY, negative = SELL
                
                # Log all positions for debugging
                logger.debug(
                    f"Position: {exchange}:{tradingsymbol} | "
                    f"Type: {instrument_type} | Qty: {quantity} ({'BUY' if quantity > 0 else 'SELL' if quantity < 0 else 'ZERO'}) | "
                    f"Product: {pos.get('product', 'N/A')}"
                )
                
                # Exclude equity positions (NSE, BSE) if configured
                if self._should_exclude_equity(exchange):
                    logger.debug(f"Skipping equity position: {exchange}:{tradingsymbol}")
                    continue
                
                # Include positions with non-zero quantity (can be negative for SELL)
                if quantity != 0:
                    non_equity_positions.append(pos)
                    logger.info(f"Found non-equity position: {exchange}:{tradingsymbol} | Qty: {quantity} ({'BUY' if quantity > 0 else 'SELL'})")
            
            logger.info(f"Fetched {len(non_equity_positions)} non-equity positions from {len(all_net_positions)} total positions")
            return non_equity_positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            raise APIError(f"Failed to fetch positions: {str(e)}")
    
    def _should_exclude_equity(self, exchange: str) -> bool:
        """
        Check if equity positions should be excluded based on config
        
        Args:
            exchange: Exchange code
            
        Returns:
            True if equity and filtering is enabled, False otherwise
        """
        # Check if equity filtering is enabled
        try:
            admin_config = self.config_manager.get_admin_config()
            if not admin_config.exclude_equity_trades:
                return False  # Don't filter if disabled
        except Exception:
            # If config can't be loaded, default to filtering (safe default)
            pass
        
        if not exchange:
            return False
        
        exchange_upper = exchange.upper()
        return exchange_upper in ['NSE', 'BSE']
    
    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def get_all_positions(self) -> Dict[str, Any]:
        """Fetch all positions (including non-options) for debugging"""
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            positions = self.kite.positions()
            logger.debug(f"All positions structure: {list(positions.keys())}")
            return positions
        except Exception as e:
            logger.error(f"Error fetching all positions: {e}")
            raise APIError(f"Failed to fetch all positions: {str(e)}")
    
    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def get_orders(self) -> List[Dict[str, Any]]:
        """Fetch order book from Zerodha"""
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            orders = self.kite.orders()
            logger.debug(f"Fetched {len(orders)} orders")
            return orders
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            raise APIError(f"Failed to fetch orders: {str(e)}")
    
    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def place_market_order(
        self,
        tradingsymbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        product: str = "MIS",
        tag: Optional[str] = None
    ) -> str:
        """
        Place a market order
        
        Args:
            tradingsymbol: Trading symbol (e.g., 'NIFTY25JAN24000CE')
            exchange: Exchange (e.g., 'NFO')
            transaction_type: 'BUY' or 'SELL'
            quantity: Quantity in lots
            product: Product type ('MIS', 'NRML', etc.)
        
        Returns:
            Order ID
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            order_params = dict(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=product,
                order_type=self.kite.ORDER_TYPE_MARKET,
                validity=self.kite.VALIDITY_DAY,
            )
            if tag:
                order_params["tag"] = tag
            order_id = self.kite.place_order(**order_params)
            
            logger.info(
                f"Market order placed: {transaction_type} {quantity} {tradingsymbol} "
                f"on {exchange} | Order ID: {order_id}"
            )
            return str(order_id)
        except Exception as e:
            logger.error(f"Error placing market order: {e}")
            raise OrderExecutionError(f"Failed to place order: {str(e)}")
    
    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def place_stop_loss_order(
        self,
        tradingsymbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        trigger_price: float,
        price: Optional[float] = None,
        product: str = "MIS",
        tag: Optional[str] = None
    ) -> str:
        """
        Place a stop loss order
        
        Args:
            tradingsymbol: Trading symbol (e.g., 'NIFTY25JAN24000CE')
            exchange: Exchange (e.g., 'NFO')
            transaction_type: 'BUY' or 'SELL' (opposite of entry for SL)
            quantity: Quantity in lots
            trigger_price: Trigger price for SL order
            price: Limit price (if None, uses trigger_price + 1 for BUY, trigger_price - 1 for SELL)
            product: Product type ('MIS', 'NRML', etc.)
        
        Returns:
            Order ID
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            # Get tick size from instrument (default 0.05 for NFO options)
            tick_size = 0.05  # Default for NFO options
            try:
                instruments = self.kite.instruments(exchange)
                for inst in instruments:
                    if inst.get('tradingsymbol') == tradingsymbol:
                        tick_size = inst.get('tick_size', 0.05)
                        break
            except Exception as e:
                logger.debug(f"Could not fetch tick size for {tradingsymbol}, using default 0.05: {e}")
            
            # Round trigger price to nearest multiple of tick size, then to whole number
            trigger_price_rounded_to_tick = round(trigger_price / tick_size) * tick_size
            # Then round to nearest whole number (no decimals)
            trigger_price_rounded = round(trigger_price_rounded_to_tick)
            
            # If price not specified, set difference to exactly 1
            if price is None:
                # For BUY SL: limit = trigger + 1
                # For SELL SL: limit = trigger - 1
                if transaction_type == "BUY":
                    price = trigger_price_rounded + 1
                else:  # SELL
                    price = trigger_price_rounded - 1
            else:
                # Round price to nearest whole number
                price = round(price)
            
            # Ensure both prices are whole numbers (no decimals)
            trigger_price_final = int(trigger_price_rounded)
            price_final = int(price)
            
            # Verify difference is exactly 1
            if transaction_type == "BUY":
                if price_final != trigger_price_final + 1:
                    logger.warning(
                        f"Adjusting limit price to maintain difference of 1: "
                        f"trigger={trigger_price_final}, setting limit={trigger_price_final + 1}"
                    )
                    price_final = trigger_price_final + 1
            else:  # SELL
                if price_final != trigger_price_final - 1:
                    logger.warning(
                        f"Adjusting limit price to maintain difference of 1: "
                        f"trigger={trigger_price_final}, setting limit={trigger_price_final - 1}"
                    )
                    price_final = trigger_price_final - 1
            
            order_params = dict(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=product,
                order_type=self.kite.ORDER_TYPE_SL,
                price=price_final,
                trigger_price=trigger_price_final,
                validity=self.kite.VALIDITY_DAY,
            )
            if tag:
                order_params["tag"] = tag
            order_id = self.kite.place_order(**order_params)
            
            logger.info(
                f"Stop Loss order placed: {transaction_type} {quantity} {tradingsymbol} "
                f"on {exchange} | Trigger: ₹{trigger_price_final} (rounded from ₹{trigger_price:.2f}), "
                f"Limit: ₹{price_final} (diff: {abs(price_final - trigger_price_final)}) | Order ID: {order_id}"
            )
            return str(order_id)
        except Exception as e:
            logger.error(f"Error placing stop loss order: {e}")
            raise OrderExecutionError(f"Failed to place stop loss order: {str(e)}")
    
    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def modify_order(
        self,
        order_id: str,
        trigger_price: Optional[float] = None,
        price: Optional[float] = None,
        quantity: Optional[int] = None
    ) -> str:
        """
        Modify an existing order (typically SL order for trailing stop)
        
        Args:
            order_id: Order ID to modify
            trigger_price: New trigger price (for SL orders)
            price: New limit price
            quantity: New quantity (optional)
        
        Returns:
            Modified order ID (may be same or new order ID)
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            # Build modification parameters
            modify_params = {}
            if trigger_price is not None:
                modify_params['trigger_price'] = trigger_price
            if price is not None:
                modify_params['price'] = price
            if quantity is not None:
                modify_params['quantity'] = quantity
            
            if not modify_params:
                raise ValueError("At least one parameter (trigger_price, price, or quantity) must be provided")
            
            modified_order_id = self.kite.modify_order(
                variety=self.kite.VARIETY_REGULAR,
                order_id=order_id,
                **modify_params
            )
            
            logger.info(
                f"Order modified: Order ID {order_id} → {modified_order_id} | "
                f"Trigger: ₹{trigger_price:.2f if trigger_price else 'N/A'}, "
                f"Price: ₹{price:.2f if price else 'N/A'}"
            )
            return str(modified_order_id)
        except Exception as e:
            error_msg = str(e)
            if "does not exist" in error_msg.lower() or "not found" in error_msg.lower():
                logger.warning(f"Order {order_id} no longer exists (may be executed/cancelled)")
                raise OrderExecutionError(f"Order {order_id} does not exist: {error_msg}")
            else:
                logger.error(f"Error modifying order {order_id}: {e}")
                raise OrderExecutionError(f"Failed to modify order: {str(e)}")
    
    def square_off_position(
        self,
        tradingsymbol: str,
        exchange: str,
        quantity: int,
        product: str = "MIS"
    ) -> str:
        """Square off a position (opposite transaction)"""
        # Determine transaction type based on position
        # For now, we'll use SELL to close long positions
        # In production, you'd check the position type first
        return self.place_market_order(
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            transaction_type="SELL",  # This should be determined from position
            quantity=quantity,
            product=product
        )
    
    def square_off_all_positions(self) -> List[str]:
        """Square off all open positions"""
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            positions = self.get_positions()
            order_ids = []
            
            for pos in positions:
                if pos.get('quantity', 0) != 0:  # Only positions with quantity
                    try:
                        # Determine transaction type
                        quantity = abs(pos.get('quantity', 0))
                        tradingsymbol = pos.get('tradingsymbol')
                        exchange = pos.get('exchange')
                        product = pos.get('product', 'MIS')
                        
                        # If quantity is positive, it's a long position, so SELL to close
                        # If quantity is negative, it's a short position, so BUY to close
                        transaction_type = "SELL" if pos.get('quantity', 0) > 0 else "BUY"
                        
                        order_id = self.place_market_order(
                            tradingsymbol=tradingsymbol,
                            exchange=exchange,
                            transaction_type=transaction_type,
                            quantity=quantity,
                            product=product
                        )
                        order_ids.append(order_id)
                        time.sleep(0.1)  # Small delay between orders
                    except Exception as e:
                        logger.error(f"Error squaring off position {pos.get('tradingsymbol')}: {e}")
                        continue
            
            logger.info(f"Squared off {len(order_ids)} positions")
            return order_ids
        except Exception as e:
            logger.error(f"Error squaring off all positions: {e}")
            raise OrderExecutionError(f"Failed to square off positions: {str(e)}")
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get status of an order"""
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            orders = self.get_orders()
            order = next((o for o in orders if str(o.get('order_id')) == order_id), None)
            
            if not order:
                return {"error": "Order not found"}
            
            return {
                "order_id": order.get('order_id'),
                "status": order.get('status'),
                "filled_quantity": order.get('filled_quantity', 0),
                "pending_quantity": order.get('pending_quantity', 0),
                "rejected_reason": order.get('rejected_reason'),
                "exchange_order_id": order.get('exchange_order_id')
            }
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return {"error": str(e)}
    
    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def get_margins(self) -> Dict[str, Any]:
        """Get account margins"""
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            margins = self.kite.margins()
            return margins
        except Exception as e:
            logger.error(f"Error fetching margins: {e}")
            raise APIError(f"Failed to fetch margins: {str(e)}")
    
    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def get_profile(self) -> Dict[str, Any]:
        """Get user profile"""
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            profile = self.kite.profile()
            return profile
        except Exception as e:
            logger.error(f"Error fetching profile: {e}")
            raise APIError(f"Failed to fetch profile: {str(e)}")
    
    # === Live index data helpers for Live Trader ===

    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def get_index_ltp(self, index_symbol: str) -> float:
        """
        Get the latest traded price (LTP) for a given index (e.g. NIFTY 50).
        
        Args:
            index_symbol: Logical index name: 'NIFTY', 'BANKNIFTY', 'SENSEX'
        
        Returns:
            Latest traded price as float
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        # Map logical names to Kite index symbols
        symbol_map = {
            "NIFTY": "NSE:NIFTY 50",
            "BANKNIFTY": "NSE:NIFTY BANK",
            "SENSEX": "BSE:SENSEX"
        }
        key = index_symbol.upper()
        if key not in symbol_map:
            raise APIError(f"Unsupported index_symbol: {index_symbol}")
        
        kite_symbol = symbol_map[key]
        
        try:
            logger.debug(f"Fetching LTP from Kite API for {index_symbol} ({kite_symbol})")
            quotes = self.kite.quote([kite_symbol])
            data = quotes.get(kite_symbol, {})
            ltp = data.get("last_price")
            if ltp is None:
                raise APIError(f"No LTP in quote for {kite_symbol}")
            logger.debug(f"Successfully fetched LTP for {index_symbol}: ₹{float(ltp):.2f}")
            return float(ltp)
        except Exception as e:
            logger.error(f"Error fetching LTP for {index_symbol}: {e}")
            raise APIError(f"Failed to fetch LTP for {index_symbol}: {str(e)}")

    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def get_index_ohlc(self, index_symbol: str) -> Dict[str, float]:
        """
        Get the current day's OHLC for a given index.
        
        Args:
            index_symbol: Logical index name: 'NIFTY', 'BANKNIFTY', 'SENSEX'
        
        Returns:
            Dict with keys: open, high, low, close (if available from Kite)
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        symbol_map = {
            "NIFTY": "NSE:NIFTY 50",
            "BANKNIFTY": "NSE:NIFTY BANK",
            "SENSEX": "BSE:SENSEX"
        }
        key = index_symbol.upper()
        if key not in symbol_map:
            raise APIError(f"Unsupported index_symbol: {index_symbol}")
        
        kite_symbol = symbol_map[key]
        
        try:
            quotes = self.kite.quote([kite_symbol])
            data = quotes.get(kite_symbol, {})
            ohlc = data.get("ohlc", {})
            return {
                "open": float(ohlc.get("open")) if ohlc.get("open") is not None else None,
                "high": float(ohlc.get("high")) if ohlc.get("high") is not None else None,
                "low": float(ohlc.get("low")) if ohlc.get("low") is not None else None,
                "close": float(ohlc.get("close")) if ohlc.get("close") is not None else None,
                "ltp": float(data.get("last_price")) if data.get("last_price") is not None else None,
            }
        except Exception as e:
            logger.error(f"Error fetching OHLC for {index_symbol}: {e}")
            raise APIError(f"Failed to fetch OHLC for {index_symbol}: {str(e)}")
    
    @retry_api_call(max_retries=3, base_delay=1.0, max_delay=10.0)
    def get_option_chain_with_delta(
        self,
        segment: str,
        option_type: str,
        expiry: str,
        exchange: str = "NFO"
    ) -> List[Dict[str, Any]]:
        """
        Get option chain with Delta values for a given segment, option type, and expiry.
        
        Args:
            segment: Trading segment (NIFTY, BANKNIFTY, SENSEX)
            option_type: CE or PE
            expiry: Expiry date in YYYY-MM-DD format
            exchange: Exchange name (default: NFO)
        
        Returns:
            List of dicts with keys: strike, tradingsymbol, delta, premium, instrument_token, etc.
            Sorted by strike price.
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Please authenticate first.")
        
        try:
            # Get all instruments for the exchange
            instruments = self.kite.instruments(exchange)
            
            # Filter instruments for the segment, option type, and expiry
            # Expiry format in Kite: YYMMDD (e.g., 251230 for 2025-12-30)
            expiry_parts = expiry.split('-')
            if len(expiry_parts) != 3:
                raise ValueError(f"Invalid expiry format: {expiry}. Expected YYYY-MM-DD")
            
            year_short = expiry_parts[0][-2:]  # Last 2 digits of year
            month = expiry_parts[1]
            day = expiry_parts[2]
            expiry_kite = f"{year_short}{month}{day}"  # YYMMDD
            
            segment_upper = segment.upper()
            option_type_upper = option_type.upper()
            
            # Filter instruments
            matching_instruments = []
            for inst in instruments:
                name = inst.get('name', '')
                instrument_type = inst.get('instrument_type', '')
                exp = inst.get('expiry', '')
                
                # Check if it matches segment, option type, and expiry
                if (segment_upper in name and 
                    instrument_type == option_type_upper and 
                    exp == expiry_kite):
                    matching_instruments.append(inst)
            
            if not matching_instruments:
                logger.warning(
                    f"No instruments found for {segment} {option_type} expiry {expiry} "
                    f"(Kite format: {expiry_kite})"
                )
                return []
            
            # Build list of tradingsymbols for quote request
            tradingsymbols = []
            for inst in matching_instruments:
                tradingsymbol = inst.get('tradingsymbol')
                if tradingsymbol:
                    kite_symbol = f"{exchange}:{tradingsymbol}"
                    tradingsymbols.append((kite_symbol, inst))
            
            if not tradingsymbols:
                return []
            
            # Fetch quotes for all instruments (Kite allows batch quotes)
            # Split into batches of 50 (Kite API limit)
            all_quotes = {}
            batch_size = 50
            for i in range(0, len(tradingsymbols), batch_size):
                batch = tradingsymbols[i:i + batch_size]
                batch_symbols = [sym for sym, _ in batch]
                
                try:
                    quotes = self.kite.quote(batch_symbols)
                    all_quotes.update(quotes)
                except Exception as e:
                    logger.warning(f"Error fetching quotes for batch {i//batch_size + 1}: {e}")
                    continue
            
            # Build result list with Delta values
            result = []
            for kite_symbol, inst in tradingsymbols:
                quote_data = all_quotes.get(kite_symbol, {})
                if not quote_data:
                    continue
                
                # Extract Delta from Greeks
                greeks = quote_data.get('greeks', {})
                delta = greeks.get('delta')
                
                # Skip if Delta is not available
                if delta is None:
                    continue
                
                # Get premium (LTP or last traded price)
                premium = quote_data.get('last_price') or quote_data.get('ohlc', {}).get('close')
                if premium is None:
                    continue
                
                strike = inst.get('strike', 0)
                tradingsymbol = inst.get('tradingsymbol', '')
                instrument_token = inst.get('instrument_token', 0)
                
                result.append({
                    'strike': int(strike),
                    'tradingsymbol': tradingsymbol,
                    'delta': float(delta),
                    'premium': float(premium),
                    'instrument_token': instrument_token,
                    'exchange': exchange,
                    'instrument_type': option_type_upper,
                    'expiry': expiry,
                    'volume': quote_data.get('volume', 0),
                    'oi': quote_data.get('oi', 0),
                    'greeks': greeks  # Include all Greeks for reference
                })
            
            # Sort by strike price
            result.sort(key=lambda x: x['strike'])
            
            logger.debug(
                f"Fetched {len(result)} options with Delta for {segment} {option_type} "
                f"expiry {expiry} (Delta range: {min(r['delta'] for r in result):.3f} to "
                f"{max(r['delta'] for r in result):.3f})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching option chain with Delta: {e}", exc_info=True)
            raise APIError(f"Failed to fetch option chain with Delta: {str(e)}")
    
