"""
Position Synchronization
Syncs positions from Zerodha API to local database
"""

from typing import List, Dict, Any
from datetime import datetime
from src.utils.logger import get_logger
from src.api.kite_client import KiteClient
from src.database.repository import PositionRepository
from src.database.models import Position

logger = get_logger("api")


class PositionSync:
    """Synchronizes positions between Zerodha and local database"""
    
    def __init__(self, kite_client: KiteClient, position_repo: PositionRepository):
        self.kite_client = kite_client
        self.position_repo = position_repo
    
    def sync_positions_from_api(self) -> List[Position]:
        """
        Fetch positions from Zerodha API and sync to database
        
        Returns:
            List of synced positions
        """
        try:
            # Get positions from Zerodha
            api_positions = self.kite_client.get_positions()
            
            synced_positions = []
            
            for api_pos in api_positions:
                # Extract position data first (needed for all checks)
                trading_symbol = api_pos.get('tradingsymbol', '')
                exchange = api_pos.get('exchange', '')
                instrument_token = str(api_pos.get('instrument_token', ''))
                
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
                        existing_position.quantity = 0
                        existing_position.is_active = False
                        existing_position.current_price = api_pos.get('last_price', existing_position.current_price)
                        existing_position.updated_at = datetime.utcnow()
                        # Update P&L to final value using original quantity
                        if existing_position.current_price:
                            from src.utils.position_utils import calculate_position_pnl
                            # Calculate P&L using original quantity (not 0)
                            existing_position.unrealized_pnl = calculate_position_pnl(
                                existing_position.entry_price,
                                existing_position.current_price,
                                original_quantity,  # Use original quantity for P&L calculation
                                existing_position.lot_size
                            )
                        session = self.position_repo.db_manager.get_session()
                        try:
                            session.commit()
                        finally:
                            session.close()
                        logger.info(f"Position {trading_symbol} marked as inactive (quantity=0, original qty was {original_quantity})")
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

