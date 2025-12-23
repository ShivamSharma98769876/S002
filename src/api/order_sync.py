"""
Order History Synchronization
Syncs completed orders from Zerodha and creates trade records
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from src.utils.logger import get_logger
from src.api.kite_client import KiteClient
from src.database.repository import TradeRepository, PositionRepository
from src.utils.date_utils import IST
from pytz import UTC

logger = get_logger("api")


class OrderSync:
    """Synchronizes order history from Zerodha and creates trade records"""
    
    def __init__(self, kite_client: KiteClient, trade_repo: TradeRepository, position_repo: PositionRepository):
        self.kite_client = kite_client
        self.trade_repo = trade_repo
        self.position_repo = position_repo
    
    def sync_orders_to_trades(self, target_date: Optional[datetime.date] = None) -> List[Dict[str, Any]]:
        """
        Fetch orders from Zerodha and create trade records for completed options orders
        
        Args:
            target_date: Optional date to filter orders (default: today in IST)
        
        Returns:
            List of created trade records
        """
        if not self.kite_client.is_authenticated():
            logger.warning("Not authenticated - cannot sync orders")
            return []
        
        try:
            # Default to today's date in IST if not specified
            if target_date is None:
                from src.utils.date_utils import get_current_ist_time
                target_date = get_current_ist_time().date()
                logger.info(f"No target date specified, using today's date: {target_date}")
            
            # Get all orders from Zerodha
            all_orders = self.kite_client.get_orders()
            logger.info(f"Fetched {len(all_orders)} orders from Zerodha, filtering for date: {target_date}")
            
            # Filter for non-equity orders - include COMPLETE and REJECTED orders
            # (REJECTED might have partial fills, COMPLETE are fully filled)
            # Exclude equity orders (NSE, BSE)
            non_equity_orders = []
            skipped_count = 0
            for order in all_orders:
                # Check order status - include COMPLETE and partially filled orders
                status = order.get('status', '').upper()
                # Skip only CANCELLED and PENDING orders
                if status in ['CANCELLED', 'PENDING', 'OPEN', 'TRIGGER PENDING']:
                    skipped_count += 1
                    continue
                
                # Include COMPLETE, REJECTED (might have fills), and other statuses with fills
                filled_qty = order.get('filled_quantity', 0)
                if filled_qty == 0 and status != 'COMPLETE':
                    skipped_count += 1
                    continue
                
                # Exclude equity orders (NSE, BSE) if configured
                exchange = order.get('exchange', '').upper()
                tradingsymbol = order.get('tradingsymbol', '').upper()
                
                if self._should_exclude_equity(exchange):
                    skipped_count += 1
                    continue
                
                # Filter by date - Zerodha timestamps are in UTC
                order_time_str = order.get('order_timestamp', '')
                if order_time_str:
                    try:
                        # Parse order timestamp - Zerodha format: "YYYY-MM-DD HH:MM:SS" (IST)
                        # Try multiple formats
                        order_time = None
                        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%d-%m-%Y %H:%M:%S']:
                            try:
                                order_time = datetime.strptime(order_time_str, fmt)
                                break
                            except ValueError:
                                continue
                        
                        if order_time is None:
                            logger.warning(f"Could not parse order timestamp: {order_time_str}")
                            skipped_count += 1
                            continue
                        
                        # Zerodha timestamps are in UTC (timezone-naive)
                        # Convert to IST timezone-aware datetime
                        if order_time.tzinfo is None:
                            # Assume UTC (Zerodha API returns timestamps in UTC)
                            order_time = order_time.replace(tzinfo=UTC).astimezone(IST)
                        else:
                            order_time = order_time.astimezone(IST)
                        
                        # Compare dates in IST
                        order_date_ist = order_time.date()
                        if order_date_ist != target_date:
                            logger.debug(
                                f"Order {order.get('order_id')} date {order_date_ist} != target {target_date}, "
                                f"time: {order_time_str} -> {order_time}"
                            )
                            skipped_count += 1
                            continue
                        
                        logger.debug(
                            f"Including order {order.get('order_id')} at {order_time_str} "
                            f"(IST: {order_time}) for date {target_date}"
                        )
                    except Exception as e:
                        logger.warning(f"Error parsing order timestamp {order_time_str}: {e}")
                        skipped_count += 1
                        continue
                else:
                    # No timestamp - skip this order
                    logger.warning(f"Order {order.get('order_id')} has no timestamp, skipping")
                    skipped_count += 1
                    continue
                
                non_equity_orders.append(order)
            
            logger.info(
                f"Found {len(non_equity_orders)} completed non-equity orders for {target_date} "
                f"(skipped {skipped_count} orders)"
            )
            
            # Group orders by instrument and match BUY/SELL pairs
            # For each instrument, we need to match BUY and SELL orders
            created_trades = []
            processed_order_ids = set()
            
            # Group orders by trading symbol
            orders_by_symbol: Dict[str, List[Dict]] = {}
            for order in non_equity_orders:
                symbol = order.get('tradingsymbol', '')
                if symbol not in orders_by_symbol:
                    orders_by_symbol[symbol] = []
                orders_by_symbol[symbol].append(order)
            
            # Process each symbol's orders using FIFO matching
            for symbol, symbol_orders in orders_by_symbol.items():
                # Sort by timestamp
                symbol_orders.sort(key=lambda x: x.get('order_timestamp', ''))
                
                # Use FIFO queue approach: track pending BUY and SELL orders
                pending_buys = []  # List of (order, remaining_qty)
                pending_sells = []  # List of (order, remaining_qty)
                
                for order in symbol_orders:
                    order_id = order.get('order_id')
                    if order_id in processed_order_ids:
                        continue
                    
                    transaction_type = order.get('transaction_type', '').upper()
                    filled_qty = order.get('filled_quantity', 0)
                    
                    if transaction_type == 'BUY':
                        # Try to match with pending SELL orders (short covering)
                        remaining_qty = filled_qty
                        while remaining_qty > 0 and pending_sells:
                            sell_order, sell_remaining = pending_sells[0]
                            
                            # Match quantity
                            match_qty = min(remaining_qty, sell_remaining)
                            
                            # Create trade record
                            trade = self._create_trade_from_orders_partial(
                                sell_order, order, match_qty, is_short=True
                            )
                            if trade:
                                created_trades.append(trade)
                            
                            # Update remaining quantities
                            remaining_qty -= match_qty
                            sell_remaining -= match_qty
                            
                            if sell_remaining == 0:
                                pending_sells.pop(0)
                                processed_order_ids.add(sell_order.get('order_id'))
                            else:
                                pending_sells[0] = (sell_order, sell_remaining)
                        
                        # Add remaining to pending BUYs (only if not fully matched)
                        if remaining_qty > 0:
                            pending_buys.append((order, remaining_qty))
                        elif remaining_qty == 0 and filled_qty > 0:
                            # Fully matched, mark as processed
                            processed_order_ids.add(order_id)
                    
                    elif transaction_type == 'SELL':
                        # Try to match with pending BUY orders (long exit)
                        remaining_qty = filled_qty
                        while remaining_qty > 0 and pending_buys:
                            buy_order, buy_remaining = pending_buys[0]
                            
                            # Match quantity
                            match_qty = min(remaining_qty, buy_remaining)
                            
                            # Create trade record
                            trade = self._create_trade_from_orders_partial(
                                buy_order, order, match_qty, is_short=False
                            )
                            if trade:
                                created_trades.append(trade)
                            
                            # Update remaining quantities
                            remaining_qty -= match_qty
                            buy_remaining -= match_qty
                            
                            if buy_remaining == 0:
                                pending_buys.pop(0)
                                processed_order_ids.add(buy_order.get('order_id'))
                            else:
                                pending_buys[0] = (buy_order, buy_remaining)
                        
                        # Add remaining to pending SELLs (short positions)
                        if remaining_qty > 0:
                            pending_sells.append((order, remaining_qty))
                        elif remaining_qty == 0 and filled_qty > 0:
                            # Fully matched, mark as processed
                            processed_order_ids.add(order_id)
            
            logger.info(f"Created {len(created_trades)} trade records from orders")
            return created_trades
            
        except Exception as e:
            logger.error(f"Error syncing orders to trades: {e}", exc_info=True)
            return []
    
    def _create_trade_from_orders_partial(
        self,
        entry_order: Dict[str, Any],
        exit_order: Dict[str, Any],
        quantity: int,
        is_short: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Create a trade record from matched orders with partial quantity
        
        Args:
            entry_order: Entry order
            exit_order: Exit order
            quantity: Quantity to match
            is_short: True if this is a short position
        
        Returns:
            Created trade record or None
        """
        try:
            # Use the same prices from orders (average price)
            entry_price = float(entry_order.get('average_price', 0))
            exit_price = float(exit_order.get('average_price', 0))
            
            if entry_price == 0 or exit_price == 0:
                return None
            
            # Determine transaction type and quantity sign
            if is_short:
                transaction_type = 'SELL'
                qty = -abs(quantity)  # Negative for SELL
            else:
                transaction_type = 'BUY'
                qty = abs(quantity)  # Positive for BUY
            
            # Parse timestamps - Zerodha returns in UTC
            entry_time_str = entry_order.get('order_timestamp', '')
            exit_time_str = exit_order.get('order_timestamp', '')
            
            try:
                # Parse timestamp - Zerodha returns in UTC
                entry_time = None
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%d-%m-%Y %H:%M:%S']:
                    try:
                        entry_time = datetime.strptime(entry_time_str, fmt)
                        break
                    except ValueError:
                        continue
                
                if entry_time is None:
                    entry_time = datetime.now(IST)
                elif entry_time.tzinfo is None:
                    # Zerodha timestamps are in UTC (timezone-naive)
                    entry_time = entry_time.replace(tzinfo=UTC).astimezone(IST)
                else:
                    entry_time = entry_time.astimezone(IST)
            except Exception as e:
                logger.warning(f"Error parsing entry_time {entry_time_str}: {e}")
                entry_time = datetime.now(IST)
            
            try:
                # Parse timestamp - Zerodha returns in UTC
                exit_time = None
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%d-%m-%Y %H:%M:%S']:
                    try:
                        exit_time = datetime.strptime(exit_time_str, fmt)
                        break
                    except ValueError:
                        continue
                
                if exit_time is None:
                    exit_time = datetime.now(IST)
                elif exit_time.tzinfo is None:
                    # Zerodha timestamps are in UTC (timezone-naive)
                    exit_time = exit_time.replace(tzinfo=UTC).astimezone(IST)
                else:
                    exit_time = exit_time.astimezone(IST)
            except Exception as e:
                logger.warning(f"Error parsing exit_time {exit_time_str}: {e}")
                exit_time = datetime.now(IST)
            
            # Get instrument details
            trading_symbol = entry_order.get('tradingsymbol', '')
            exchange = entry_order.get('exchange', '')
            instrument_token = str(entry_order.get('instrument_token', ''))
            
            # Check if trade already exists (avoid duplicates)
            existing_trades = self.trade_repo.get_all_trades()
            for existing in existing_trades:
                if (existing.trading_symbol == trading_symbol and
                    abs((existing.entry_time - entry_time).total_seconds()) < 60 and
                    abs((existing.exit_time - exit_time).total_seconds()) < 60 and
                    abs(existing.entry_price - entry_price) < 0.01 and
                    abs(existing.exit_price - exit_price) < 0.01 and
                    abs(existing.quantity) == abs(qty)):
                    logger.debug(f"Trade already exists for {trading_symbol} at {entry_time}")
                    return None
            
            # Create trade record
            trade = self.trade_repo.create_trade(
                instrument_token=instrument_token,
                trading_symbol=trading_symbol,
                exchange=exchange,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=qty,
                exit_type='manual',
                transaction_type=transaction_type
            )
            
            logger.info(
                f"Created trade record: {trading_symbol} | "
                f"{transaction_type} {abs(qty)} @ {entry_price} -> {exit_price} | "
                f"P&L: {trade.realized_pnl:.2f}"
            )
            
            return {
                "id": trade.id,
                "trading_symbol": trading_symbol,
                "transaction_type": transaction_type,
                "quantity": qty,
                "realized_pnl": trade.realized_pnl
            }
            
        except Exception as e:
            logger.error(f"Error creating trade from orders: {e}", exc_info=True)
            return None
    
    def _create_trade_from_orders(
        self, 
        entry_order: Dict[str, Any], 
        exit_order: Dict[str, Any],
        is_short: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Create a trade record from matched BUY/SELL orders
        
        Args:
            entry_order: First order (BUY for long, SELL for short)
            exit_order: Second order (SELL for long, BUY for short)
            is_short: True if this is a short position (SELL first, then BUY)
        
        Returns:
            Created trade record or None
        """
        try:
            # Determine entry and exit based on order sequence
            if is_short:
                # Short position: SELL first (entry), BUY later (exit)
                entry_order_data = entry_order  # SELL
                exit_order_data = exit_order    # BUY
                transaction_type = 'SELL'
                quantity = -abs(entry_order_data.get('filled_quantity', 0))  # Negative for SELL
            else:
                # Long position: BUY first (entry), SELL later (exit)
                entry_order_data = entry_order  # BUY
                exit_order_data = exit_order    # SELL
                transaction_type = 'BUY'
                quantity = abs(entry_order_data.get('filled_quantity', 0))  # Positive for BUY
            
            # Parse timestamps - Zerodha returns in UTC
            entry_time_str = entry_order_data.get('order_timestamp', '')
            exit_time_str = exit_order_data.get('order_timestamp', '')
            
            try:
                # Parse timestamp - Zerodha returns in UTC
                entry_time = None
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%d-%m-%Y %H:%M:%S']:
                    try:
                        entry_time = datetime.strptime(entry_time_str, fmt)
                        break
                    except ValueError:
                        continue
                
                if entry_time is None:
                    entry_time = datetime.now(IST)
                elif entry_time.tzinfo is None:
                    # Zerodha timestamps are in UTC (timezone-naive)
                    entry_time = entry_time.replace(tzinfo=UTC).astimezone(IST)
                else:
                    entry_time = entry_time.astimezone(IST)
            except Exception as e:
                logger.warning(f"Error parsing entry_time {entry_time_str}: {e}")
                entry_time = datetime.now(IST)
            
            try:
                # Parse timestamp - Zerodha returns in UTC
                exit_time = None
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%d-%m-%Y %H:%M:%S']:
                    try:
                        exit_time = datetime.strptime(exit_time_str, fmt)
                        break
                    except ValueError:
                        continue
                
                if exit_time is None:
                    exit_time = datetime.now(IST)
                elif exit_time.tzinfo is None:
                    # Zerodha timestamps are in UTC (timezone-naive)
                    exit_time = exit_time.replace(tzinfo=UTC).astimezone(IST)
                else:
                    exit_time = exit_time.astimezone(IST)
            except Exception as e:
                logger.warning(f"Error parsing exit_time {exit_time_str}: {e}")
                exit_time = datetime.now(IST)
            
            # Get prices
            entry_price = float(entry_order_data.get('average_price', 0))
            exit_price = float(exit_order_data.get('average_price', 0))
            
            if entry_price == 0 or exit_price == 0:
                logger.warning(f"Invalid prices for orders: entry={entry_price}, exit={exit_price}")
                return None
            
            # Get instrument details
            trading_symbol = entry_order_data.get('tradingsymbol', '')
            exchange = entry_order_data.get('exchange', '')
            instrument_token = str(entry_order_data.get('instrument_token', ''))
            
            # Check if trade already exists (avoid duplicates)
            existing_trades = self.trade_repo.get_all_trades()
            for existing in existing_trades:
                if (existing.trading_symbol == trading_symbol and
                    abs((existing.entry_time - entry_time).total_seconds()) < 60 and
                    abs((existing.exit_time - exit_time).total_seconds()) < 60 and
                    abs(existing.entry_price - entry_price) < 0.01 and
                    abs(existing.exit_price - exit_price) < 0.01):
                    logger.debug(f"Trade already exists for {trading_symbol} at {entry_time}")
                    return None
            
            # Create trade record
            trade = self.trade_repo.create_trade(
                instrument_token=instrument_token,
                trading_symbol=trading_symbol,
                exchange=exchange,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,  # Positive for BUY, negative for SELL
                exit_type='manual',  # From order history
                transaction_type=transaction_type
            )
            
            logger.info(
                f"Created trade record: {trading_symbol} | "
                f"{transaction_type} {abs(quantity)} @ {entry_price} -> {exit_price} | "
                f"P&L: {trade.realized_pnl:.2f}"
            )
            
            return {
                "id": trade.id,
                "trading_symbol": trading_symbol,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "realized_pnl": trade.realized_pnl
            }
            
        except Exception as e:
            logger.error(f"Error creating trade from orders: {e}", exc_info=True)
            return None
    
    def _should_exclude_equity(self, exchange: str) -> bool:
        """
        Check if equity orders should be excluded based on config
        
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

