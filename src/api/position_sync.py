"""
Position Synchronization
Syncs positions from Zerodha API to local database
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from pytz import UTC
from src.utils.logger import get_logger
from src.api.kite_client import KiteClient
from src.database.repository import PositionRepository
from src.database.models import Position
from src.utils.date_utils import IST

logger = get_logger("api")


class PositionSync:
    """Synchronizes positions between Zerodha and local database"""
    
    def __init__(self, kite_client: KiteClient, position_repo: PositionRepository):
        self.kite_client = kite_client
        self.position_repo = position_repo
    
    def _parse_order_timestamp(self, timestamp_str: str) -> datetime:
        """
        Parse order timestamp from Kite API.
        Kite returns timestamps in IST format: 'YYYY-MM-DD HH:MM:SS'
        """
        if not timestamp_str:
            return datetime.utcnow()
        
        try:
            if isinstance(timestamp_str, datetime):
                dt = timestamp_str
            else:
                # Parse as IST (Kite returns IST timestamps)
                dt = datetime.strptime(str(timestamp_str), '%Y-%m-%d %H:%M:%S')
            
            # If no timezone info, assume IST
            if dt.tzinfo is None:
                dt = IST.localize(dt)
            
            # Convert to UTC for storage
            return dt.astimezone(UTC).replace(tzinfo=None)
        except Exception as e:
            logger.debug(f"Error parsing timestamp '{timestamp_str}': {e}")
            return datetime.utcnow()
    
    def sync_positions_from_api(self) -> List[Position]:
        """
        Fetch positions from Zerodha API and sync to database
        
        Returns:
            List of synced positions
        """
        try:
            # Get positions from Zerodha
            api_positions = self.kite_client.get_positions()
            
            # Get all active positions from database BEFORE processing API positions
            # This helps us detect positions that disappeared from API (closed manually)
            db_active_positions = {}
            try:
                active_positions = self.position_repo.get_active_positions()
                for pos in active_positions:
                    db_active_positions[str(pos.instrument_token)] = pos
            except Exception as e:
                logger.debug(f"Error getting active positions for sync: {e}")
            
            # Track which positions are still in API
            api_instrument_tokens = set()
            
            synced_positions = []
            
            for api_pos in api_positions:
                # Extract position data first (needed for all checks)
                trading_symbol = api_pos.get('tradingsymbol', '')
                exchange = api_pos.get('exchange', '')
                instrument_token = str(api_pos.get('instrument_token', ''))
                
                # Track this instrument as present in API
                api_instrument_tokens.add(instrument_token)
                
                # Exclude equity positions (NSE, BSE) if configured
                if self._should_exclude_equity(exchange):
                    logger.debug(f"Skipping equity position: {exchange}:{trading_symbol}")
                    continue
                
                # Get quantity with sign (preserve negative for SELL positions)
                # Zerodha API returns quantity with sign: positive for BUY, negative for SELL
                raw_quantity = api_pos.get('quantity', 0)
                quantity = int(raw_quantity)  # Can be negative for SELL
                
                # Check if position became inactive (quantity=0)
                # We still process it to mark it as inactive
                if quantity == 0:
                    # Check if we have an active position for this instrument
                    existing_position = None
                    try:
                        active_positions = self.position_repo.get_active_positions()
                        existing_position = next(
                            (p for p in active_positions if p.instrument_token == instrument_token),
                            None
                        )
                    except Exception:
                        pass
                    
                    # If we have an active position that became 0, mark it as inactive
                    # BUT preserve the original quantity for display purposes
                    if existing_position:
                        # Store original quantity before setting to 0 (for trade history display)
                        original_quantity = existing_position.quantity
                        
                        # Try to get exit price and time from orderbook
                        exit_price = api_pos.get('last_price', existing_position.current_price)
                        exit_time = datetime.utcnow()
                        
                        # Try to find the exit order from orderbook to get actual exit price and time
                        try:
                            if self.kite_client and self.kite_client.is_authenticated():
                                orders = self.kite_client.get_orders()
                                # Find the most recent COMPLETE order for this symbol that would close the position
                                # For SELL positions (negative qty), look for BUY orders
                                # For BUY positions (positive qty), look for SELL orders
                                exit_transaction_type = "BUY" if original_quantity < 0 else "SELL"
                                
                                matching_orders = [
                                    o for o in orders
                                    if (o.get('tradingsymbol', '').upper() == trading_symbol.upper() and
                                        o.get('exchange', '').upper() == exchange.upper() and
                                        o.get('transaction_type', '').upper() == exit_transaction_type and
                                        o.get('status', '').upper() == 'COMPLETE' and
                                        o.get('filled_quantity', 0) > 0)
                                ]
                                
                                if matching_orders:
                                    # Sort by timestamp (most recent first)
                                    matching_orders.sort(
                                        key=lambda x: self._parse_order_timestamp(x.get('order_timestamp', '')),
                                        reverse=True
                                    )
                                    # Get the most recent exit order
                                    exit_order = matching_orders[0]
                                    exit_price = float(exit_order.get('average_price', exit_price))
                                    exit_time_str = exit_order.get('order_timestamp', '')
                                    if exit_time_str:
                                        try:
                                            exit_time = self._parse_order_timestamp(exit_time_str)
                                            # Convert to UTC if needed
                                            if exit_time.tzinfo:
                                                exit_time = exit_time.astimezone(UTC).replace(tzinfo=None)
                                        except:
                                            pass
                                    
                                    logger.info(
                                        f"Found exit order for {trading_symbol}: "
                                        f"Exit price=₹{exit_price:.2f}, Exit time={exit_time}"
                                    )
                        except Exception as e:
                            logger.debug(f"Could not fetch exit order from orderbook: {e}")
                        
                        # IMPORTANT: Get a fresh session and merge the object to ensure changes are persisted
                        session = self.position_repo.db_manager.get_session()
                        try:
                            # Merge the position object into this session
                            position_to_update = session.merge(existing_position)
                            
                            # Update all fields
                            position_to_update.quantity = 0
                            position_to_update.is_active = False
                            position_to_update.current_price = exit_price  # Use exit price as current price
                            position_to_update.updated_at = exit_time
                            
                            # Store exit price and time if Position model supports it
                            if hasattr(position_to_update, 'exit_price'):
                                position_to_update.exit_price = exit_price
                            if hasattr(position_to_update, 'exit_time'):
                                position_to_update.exit_time = exit_time
                            
                            # Update P&L to final value using original quantity
                            if position_to_update.current_price:
                                from src.utils.position_utils import calculate_position_pnl
                                # Calculate P&L using original quantity (not 0)
                                position_to_update.unrealized_pnl = calculate_position_pnl(
                                    position_to_update.entry_price,
                                    position_to_update.current_price,
                                    original_quantity,  # Use original quantity for P&L calculation
                                    position_to_update.lot_size
                                )
                            
                            # Commit the changes
                            session.commit()
                            logger.debug(f"Successfully committed position {trading_symbol} as inactive (quantity=0)")
                        except Exception as commit_error:
                            session.rollback()
                            logger.error(f"Error committing position update: {commit_error}", exc_info=True)
                            raise
                        finally:
                            session.close()
                        logger.info(
                            f"Position {trading_symbol} marked as inactive (quantity=0, original qty was {original_quantity}, "
                            f"exit price=₹{exit_price:.2f})"
                        )
                    continue
                
                # Get prices
                entry_price = api_pos.get('average_price', 0.0)
                current_price = api_pos.get('last_price', entry_price)
                
                # Calculate P&L
                pnl = api_pos.get('pnl', 0.0)
                
                # Get lot size (default 1 for options)
                lot_size = api_pos.get('lot_size', 1)
                
                # Get existing position to detect quantity changes
                existing_position = None
                try:
                    active_positions = self.position_repo.get_active_positions()
                    existing_position = next(
                        (p for p in active_positions if p.instrument_token == instrument_token),
                        None
                    )
                except Exception:
                    pass
                
                old_quantity = existing_position.quantity if existing_position else 0
                
                # Create or update position in database (quantity can be negative for SELL)
                position = self.position_repo.create_or_update_position(
                    instrument_token=instrument_token,
                    trading_symbol=trading_symbol,
                    exchange=exchange,
                    entry_price=entry_price,
                    quantity=quantity,  # Can be negative for SELL positions
                    lot_size=lot_size,
                    current_price=current_price
                )
                
                # Update P&L
                if position:
                    self.position_repo.update_position_pnl(position.id, current_price)
                    synced_positions.append(position)
                    
                    # Log quantity change if detected
                    if existing_position and old_quantity != quantity:
                        logger.info(
                            f"Quantity change detected for {trading_symbol}: "
                            f"{old_quantity} -> {quantity} (change: {quantity - old_quantity})"
                        )
            
            # After processing all API positions, check for positions that disappeared from API
            # These are positions that were in database but not in API response (manually closed)
            logger.info(
                f"Position sync: Found {len(db_active_positions)} active positions in DB, "
                f"{len(api_instrument_tokens)} positions in API response"
            )
            
            disappeared_count = 0
            for instrument_token, db_position in db_active_positions.items():
                if instrument_token not in api_instrument_tokens:
                    disappeared_count += 1
                    # Position exists in database but not in API - it was closed
                    logger.info(
                        f"Detected closed position (not in API): {db_position.trading_symbol} "
                        f"(Token: {instrument_token})"
                    )
                    
                    # Mark as inactive and try to get exit details from orderbook
                    original_quantity = db_position.quantity
                    exit_price = db_position.current_price or db_position.entry_price
                    exit_time = datetime.utcnow()
                    
                    # Try to find exit order from orderbook
                    try:
                        if self.kite_client and self.kite_client.is_authenticated():
                            orders = self.kite_client.get_orders()
                            exit_transaction_type = "BUY" if original_quantity < 0 else "SELL"
                            
                            matching_orders = [
                                o for o in orders
                                if (o.get('tradingsymbol', '').upper() == db_position.trading_symbol.upper() and
                                    o.get('exchange', '').upper() == db_position.exchange.upper() and
                                    o.get('transaction_type', '').upper() == exit_transaction_type and
                                    o.get('status', '').upper() == 'COMPLETE' and
                                    o.get('filled_quantity', 0) > 0)
                            ]
                            
                            if matching_orders:
                                matching_orders.sort(
                                    key=lambda x: self._parse_order_timestamp(x.get('order_timestamp', '')),
                                    reverse=True
                                )
                                exit_order = matching_orders[0]
                                exit_price = float(exit_order.get('average_price', exit_price))
                                exit_time_str = exit_order.get('order_timestamp', '')
                                if exit_time_str:
                                    try:
                                        exit_time = self._parse_order_timestamp(exit_time_str)
                                        if exit_time.tzinfo:
                                            exit_time = exit_time.astimezone(UTC).replace(tzinfo=None)
                                    except:
                                        pass
                                
                                logger.info(
                                    f"Found exit order for {db_position.trading_symbol}: "
                                    f"Exit price=₹{exit_price:.2f}, Exit time={exit_time}"
                                )
                    except Exception as e:
                        logger.debug(f"Could not fetch exit order from orderbook: {e}")
                    
                    # Update position to inactive
                    # IMPORTANT: Get a fresh session and merge the object to ensure changes are persisted
                    session = self.position_repo.db_manager.get_session()
                    try:
                        # Merge the position object into this session
                        position_to_update = session.merge(db_position)
                        
                        # Update all fields
                        position_to_update.quantity = 0
                        position_to_update.is_active = False
                        position_to_update.current_price = exit_price
                        position_to_update.updated_at = exit_time
                        
                        if hasattr(position_to_update, 'exit_price'):
                            position_to_update.exit_price = exit_price
                        if hasattr(position_to_update, 'exit_time'):
                            position_to_update.exit_time = exit_time
                        
                        # Update P&L
                        if position_to_update.current_price:
                            from src.utils.position_utils import calculate_position_pnl
                            position_to_update.unrealized_pnl = calculate_position_pnl(
                                position_to_update.entry_price,
                                position_to_update.current_price,
                                original_quantity,
                                position_to_update.lot_size
                            )
                        
                        # Commit the changes
                        session.commit()
                        logger.debug(f"Successfully committed position {db_position.trading_symbol} as inactive")
                    except Exception as commit_error:
                        session.rollback()
                        logger.error(f"Error committing position update: {commit_error}", exc_info=True)
                        raise
                    finally:
                        session.close()
                    
                    logger.info(
                        f"Position {db_position.trading_symbol} marked as inactive "
                        f"(disappeared from API, exit price=₹{exit_price:.2f})"
                    )
            
            if disappeared_count > 0:
                logger.info(
                    f"Position sync: Detected {disappeared_count} closed positions "
                    f"(not in API response, marked as inactive)"
                )
            
            logger.debug(f"Synced {len(synced_positions)} positions from API")
            return synced_positions
            
        except Exception as e:
            logger.error(f"Error syncing positions from API: {e}")
            return []
    
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
            config_manager = self.kite_client.config_manager
            admin_config = config_manager.get_admin_config()
            if not admin_config.exclude_equity_trades:
                return False  # Don't filter if disabled
        except Exception:
            # If config can't be loaded, default to filtering (safe default)
            pass
        
        if not exchange:
            return False
        
        exchange_upper = exchange.upper()
        return exchange_upper in ['NSE', 'BSE']
    
    def update_position_prices(self, price_updates: Dict[int, float]):
        """
        Update position prices from WebSocket ticks
        
        Args:
            price_updates: Dict mapping instrument_token to current_price
        """
        try:
            active_positions = self.position_repo.get_active_positions()
            
            for position in active_positions:
                try:
                    instrument_token = int(position.instrument_token)
                    if instrument_token in price_updates:
                        current_price = price_updates[instrument_token]
                        self.position_repo.update_position_pnl(position.id, current_price)
                except (ValueError, KeyError):
                    continue
            
        except Exception as e:
            logger.error(f"Error updating position prices: {e}")

