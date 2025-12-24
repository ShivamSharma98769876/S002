"""
Execution adapters for Live Trader.

- PaperExecutionClient: Simulates orders and logs trades/events to CSV files.
- LiveExecutionClient: Places real orders via Kite API and logs to CSV.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
import csv
import os

from src.api.kite_client import KiteClient
from src.utils.logger import get_logger
from src.utils.exceptions import OrderExecutionError

logger = get_logger("live_trader")


LOG_DIR = Path("data") / "live_trader"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


@dataclass
class PaperTradeRecord:
    segment: str
    mode: str  # PAPER / LIVE
    signal_type: str  # BUY_CE / BUY_PE
    option_symbol: str
    option_type: str  # CE / PE
    strike_price: float
    expiry: str
    lots: int
    quantity: int
    entry_time: datetime
    entry_price: float
    stop_loss_points: float
    initial_sl_price: float
    trailing_stop_points: float
    exit_time: datetime
    exit_price: float
    exit_reason: str
    pnl_points: float
    pnl_value: float
    return_pct: float


@dataclass
class OpenPositionRecord:
    """Record for tracking open positions with periodic updates"""
    segment: str
    mode: str  # PAPER / LIVE
    status: str  # OPEN / CLOSED
    signal_type: str  # BUY_CE / BUY_PE
    option_symbol: str
    option_type: str  # CE / PE
    strike_price: float
    expiry: str
    entry_time: datetime
    entry_price: float
    current_price: float
    current_lots: int
    current_quantity: int
    stop_loss_points: float
    initial_sl_price: float
    current_sl_price: float  # Trailing stop price
    trailing_stop_points: float
    current_pnl_points: float
    current_pnl_value: float
    current_return_pct: float
    pyramiding_count: int  # Number of times pyramiding occurred
    last_pyramiding_time: Optional[datetime] = None
    update_time: Optional[datetime] = None  # Last update timestamp
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    final_pnl_points: Optional[float] = None
    final_pnl_value: Optional[float] = None


class PaperExecutionClient:
    """
    Simulated execution client for Live Trader (Paper mode).

    Responsibilities:
      - Accept "orders" from agents.
      - Compute P&L on close.
      - Append trades to CSV files per day.
    """

    def __init__(self, mode: str = "PAPER"):
        self.mode = mode
        logger.info(f"PaperExecutionClient initialized in mode={mode}")

    def log_trade(self, record: PaperTradeRecord) -> None:
        """Append a completed trade to today's CSV file."""
        file_path = LOG_DIR / f"live_trades_{_today_str()}.csv"
        
        # Try to restore from Azure Blob Storage if file doesn't exist
        if not file_path.exists():
            try:
                from src.utils.csv_backup import restore_csv_file
                restore_csv_file(file_path)
            except Exception as e:
                logger.debug(f"Could not restore CSV from backup: {e}")
        
        is_new = not file_path.exists()

        fieldnames = list(asdict(record).keys())

        with file_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if is_new:
                writer.writeheader()
            row: Dict[str, Any] = {}
            for k, v in asdict(record).items():
                if isinstance(v, datetime):
                    row[k] = v.isoformat()
                else:
                    row[k] = v
            writer.writerow(row)

        # Backup to Azure Blob Storage after writing
        try:
            from src.utils.csv_backup import backup_csv_file
            backup_csv_file(file_path)
        except Exception as e:
            logger.debug(f"Could not backup CSV to Azure: {e}")

        logger.info(
            f"Logged paper trade: segment={record.segment}, symbol={record.option_symbol}, "
            f"pnl={record.pnl_value:.2f} ({record.pnl_points:.2f} pts)"
        )
    
    def log_open_position(self, record: OpenPositionRecord) -> None:
        """Log or update an open position in CSV file."""
        file_path = LOG_DIR / f"open_positions_{_today_str()}.csv"
        is_new = not file_path.exists()
        
        # Create record dict with all fields
        record_dict = asdict(record)
        # Ensure update_time is set
        if record_dict.get('update_time') is None:
            record_dict['update_time'] = datetime.now()
        
        # Convert datetime fields to ISO format
        for k, v in record_dict.items():
            if isinstance(v, datetime):
                record_dict[k] = v.isoformat() if v else ""
            elif v is None:
                record_dict[k] = ""
        
        fieldnames = list(record_dict.keys())
        
        # If file exists, try to update existing row or append new one
        position_key = f"{record.segment}_{record.strike_price}_{record.option_type}"
        
        if is_new:
            # Create new file with header
            with file_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(record_dict)
        else:
            # Read existing file, update matching row, or append new row
            rows = []
            updated = False
            
            if file_path.exists():
                with file_path.open("r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames or fieldnames
                    for row in reader:
                        # Check if this row matches our position
                        row_key = f"{row.get('segment', '')}_{row.get('strike_price', '')}_{row.get('option_type', '')}"
                        if row_key == position_key and row.get('status', '') == 'OPEN':
                            # Update existing open position
                            rows.append(record_dict)
                            updated = True
                        else:
                            rows.append(row)
            
            # If not updated, append as new row
            if not updated:
                rows.append(record_dict)
            
            # Write all rows back
            with file_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            # Backup to Azure Blob Storage after writing
            try:
                from src.utils.csv_backup import backup_csv_file
                backup_csv_file(file_path)
            except Exception as e:
                logger.debug(f"Could not backup CSV to Azure: {e}")
        
        logger.debug(
            f"Updated open position: segment={record.segment}, symbol={record.option_symbol}, "
            f"status={record.status}, P&L=₹{record.current_pnl_value:.2f} ({record.current_pnl_points:.2f} pts), "
            f"lots={record.current_lots}, update_time={record_dict.get('update_time', '')}"
        )


class LiveExecutionClient:
    """
    Real execution client for Live Trader (Live mode).
    
    Places actual orders via Kite API and logs trades to CSV.
    """

    def __init__(self, kite_client: KiteClient, mode: str = "LIVE"):
        if not kite_client or not kite_client.is_authenticated():
            raise RuntimeError("Kite client must be authenticated for Live trading")
        self.kite_client = kite_client
        self.mode = mode
        self._open_positions: Dict[str, Dict[str, Any]] = {}  # Track open positions
        logger.warning(f"LiveExecutionClient initialized in LIVE mode - REAL ORDERS WILL BE PLACED!")

    def _find_option_instrument(
        self,
        segment: str,
        strike: int,
        option_type: str,
        expiry: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find option instrument from Kite API.
        Uses tradingsymbol format (BANKNIFTY25DEC59900PE) first, then falls back to filtering.
        
        Args:
            segment: NIFTY, BANKNIFTY, or SENSEX
            strike: Strike price
            option_type: CE or PE
            expiry: Expiry date (YYYY-MM-DD), defaults to nearest weekly expiry
            
        Returns:
            Instrument dict with 'tradingsymbol', 'instrument_token', 'exchange', etc.
        """
        try:
            # Get correct exchange for segment
            from src.utils.premium_fetcher import get_exchange_for_segment
            exchange = get_exchange_for_segment(segment)
            
            # Get instruments list from the correct exchange
            instruments = self.kite_client.kite.instruments(exchange)
            
            # Map segment to base name
            segment_map = {
                "NIFTY": "NIFTY",
                "BANKNIFTY": "BANKNIFTY",
                "SENSEX": "SENSEX"
            }
            base_name = segment_map.get(segment.upper())
            if not base_name:
                logger.error(f"Unknown segment: {segment}")
                return None
            
            # Determine segment code based on exchange
            segment_code = 'BFO-OPT' if exchange == 'BFO' else 'NFO-OPT'
            
            # First, try to find by tradingsymbol if expiry is provided (same format as get_premium_by_symbol.py)
            if expiry:
                from src.utils.premium_fetcher import build_tradingsymbol, find_instrument_by_tradingsymbol
                import json
                from pathlib import Path
                
                # Load expiry config
                try:
                    config_path = Path(__file__).parent.parent.parent / "config" / "config.json"
                    expiry_config = None
                    if config_path.exists():
                        with open(config_path, 'r') as f:
                            config_data = json.load(f)
                            expiry_config = config_data.get("expiry_config", {})
                except Exception as e:
                    logger.debug(f"Could not load expiry config: {e}, using defaults")
                    expiry_config = None
                
                tradingsymbol = build_tradingsymbol(segment, strike, option_type, expiry, expiry_config)
                if tradingsymbol:
                    instrument = find_instrument_by_tradingsymbol(tradingsymbol, instruments, exchange)
                    if instrument:
                        logger.debug(f"Found instrument by tradingsymbol: {tradingsymbol}")
                        return instrument
            
            # Fallback: Filter by base name and option type
            filtered = [
                inst for inst in instruments
                if inst.get('segment') == segment_code and
                inst['name'] == base_name and
                inst['instrument_type'] == option_type.upper() and
                inst['strike'] == float(strike)
            ]
            
            if not filtered:
                logger.error(f"No instruments found for {base_name} {strike} {option_type}")
                return None
            
            # If expiry specified, filter by expiry
            if expiry:
                from datetime import datetime
                expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
                
                # Helper to get date from expiry
                def get_expiry_date(expiry_obj):
                    if expiry_obj is None:
                        return None
                    if isinstance(expiry_obj, datetime):
                        return expiry_obj.date()
                    elif hasattr(expiry_obj, 'date'):
                        try:
                            return expiry_obj.date()
                        except:
                            return None
                    elif hasattr(expiry_obj, 'year'):
                        return expiry_obj
                    return None
                
                filtered = [
                    inst for inst in filtered
                    if get_expiry_date(inst.get('expiry')) == expiry_date
                ]
            
            # If no expiry specified or no match, use nearest expiry (weekly)
            if not filtered:
                # Get all expiries and find nearest
                expiries = sorted(set(
                    inst['expiry'].date() if hasattr(inst['expiry'], 'date') else inst['expiry']
                    for inst in instruments 
                    if inst.get('name') == base_name and inst.get('expiry')
                ))
                if expiries:
                    from datetime import date
                    today = date.today()
                    nearest_expiry = min(expiries, key=lambda x: abs((x - today).days))
                    
                    def get_expiry_date(expiry_obj):
                        if expiry_obj is None:
                            return None
                        if isinstance(expiry_obj, datetime):
                            return expiry_obj.date()
                        elif hasattr(expiry_obj, 'date'):
                            try:
                                return expiry_obj.date()
                            except:
                                return None
                        elif hasattr(expiry_obj, 'year'):
                            return expiry_obj
                        return None
                    
                    filtered = [
                        inst for inst in instruments
                        if inst.get('segment') == 'NFO-OPT' and
                        inst['name'] == base_name and
                        inst['instrument_type'] == option_type.upper() and
                        inst['strike'] == float(strike) and
                        get_expiry_date(inst.get('expiry')) == nearest_expiry
                    ]
            
            if not filtered:
                logger.error(f"No instruments found for {base_name} {strike} {option_type}")
                return None
            
            # Return the first match (most liquid)
            return filtered[0]
            
        except Exception as e:
            logger.error(f"Error finding option instrument: {e}", exc_info=True)
            return None

    def place_entry_order(
        self,
        segment: str,
        strike: int,
        option_type: str,
        quantity: int,
        expiry: Optional[str] = None,
        trade_regime: str = "Buy",  # "Buy" or "Sell"
        time_interval: str = "5minute"
    ) -> Dict[str, Any]:
        """
        Place entry order for an option based on trade regime.
        
        Args:
            trade_regime: "Buy" places BUY order, "Sell" places SELL order
        
        Returns:
            Dict with 'order_id', 'tradingsymbol', 'entry_price', etc.
        """
        try:
            instrument = self._find_option_instrument(segment, strike, option_type, expiry)
            if not instrument:
                raise OrderExecutionError(f"Could not find instrument for {segment} {strike} {option_type}")

            # Determine transaction type based on trade regime
            transaction_type = "BUY" if trade_regime == "Buy" else "SELL"
            
            # Place market order
            order_id = self.kite_client.place_market_order(
                tradingsymbol=instrument['tradingsymbol'],
                exchange=instrument['exchange'],
                transaction_type=transaction_type,
                quantity=quantity,
                product="MIS",  # Intraday
                tag="S0002"
            )
            
            # Get order details to get execution price
            orders = self.kite_client.get_orders()
            order = next((o for o in orders if str(o.get('order_id')) == str(order_id)), None)
            
            entry_price = 0.0
            if order:
                entry_price = float(order.get('average_price', 0) or order.get('price', 0))
            
            result = {
                "order_id": order_id,
                "tradingsymbol": instrument['tradingsymbol'],
                "instrument_token": instrument['instrument_token'],
                "exchange": instrument['exchange'],
                "entry_price": entry_price,
                "quantity": quantity,
                "status": "PLACED"
            }
            
            # Store position info
            position_key = f"{segment}_{strike}_{option_type}"
            self._open_positions[position_key] = result
            
            logger.warning(
                f"LIVE ORDER PLACED: {transaction_type} {quantity} {instrument['tradingsymbol']} "
                f"@ {entry_price} | Order ID: {order_id} | Trade Regime: {trade_regime}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error placing entry order: {e}", exc_info=True)
            raise OrderExecutionError(f"Failed to place entry order: {str(e)}")

    def place_stop_loss_order(
        self,
        position_key: str,
        stop_loss_price: float,
        trade_regime: str = "Buy"
    ) -> Optional[str]:
        """
        Place stop loss order immediately after entry.
        
        For Buy regime: Entry is BUY, SL is SELL (to exit)
        For Sell regime: Entry is SELL, SL is BUY (to exit)
        
        Args:
            position_key: Position key (e.g., "NIFTY_24000_CE")
            stop_loss_price: Stop loss trigger price
            trade_regime: "Buy" or "Sell" - determines SL order transaction type
        
        Returns:
            SL order ID or None if failed
        """
        if position_key not in self._open_positions:
            logger.warning(f"Position {position_key} not found for SL order")
            return None
        
        position = self._open_positions[position_key]
        tradingsymbol = position.get('tradingsymbol')
        exchange = position.get('exchange', 'NFO')
        quantity = position.get('quantity', 0)
        
        if not tradingsymbol or quantity == 0:
            logger.error(f"Cannot place SL order: missing tradingsymbol or quantity")
            return None
        
        try:
            # Determine SL transaction type (opposite of entry)
            # Buy regime: Entry BUY → SL SELL
            # Sell regime: Entry SELL → SL BUY
            sl_transaction_type = "SELL" if trade_regime == "Buy" else "BUY"
            
            # Place SL order
            sl_order_id = self.kite_client.place_stop_loss_order(
                tradingsymbol=tradingsymbol,
                exchange=exchange,
                transaction_type=sl_transaction_type,
                quantity=abs(quantity),  # Use absolute quantity
                trigger_price=stop_loss_price,
                product="MIS",
                tag="S0002"
            )
            
            # Store SL order info in position
            position['sl_order_id'] = sl_order_id
            position['sl_trigger_price'] = stop_loss_price
            position['sl_status'] = 'TRIGGER PENDING'  # Initial status
            
            logger.warning(
                f"🛡️ STOP LOSS ORDER PLACED: {sl_transaction_type} {abs(quantity)} {tradingsymbol} "
                f"@ Trigger: ₹{stop_loss_price:.2f} | Order ID: {sl_order_id} | Trade Regime: {trade_regime}"
            )
            
            return sl_order_id
            
        except Exception as e:
            logger.error(f"Failed to place stop loss order: {e}", exc_info=True)
            return None
    
    def get_sl_order_status(self, position_key: str) -> Optional[str]:
        """
        Get current status of SL order for a position.
        
        Returns:
            Order status: 'TRIGGER PENDING', 'COMPLETE', 'CANCELLED', 'REJECTED', or None
        """
        if position_key not in self._open_positions:
            return None
        
        position = self._open_positions[position_key]
        sl_order_id = position.get('sl_order_id')
        
        if not sl_order_id:
            return None
        
        try:
            order_status = self.kite_client.get_order_status(str(sl_order_id))
            status = order_status.get('status', '').upper()
            
            # Update position with latest status
            position['sl_status'] = status
            
            return status
        except Exception as e:
            logger.error(f"Error checking SL order status: {e}")
            return None
    
    def modify_sl_order(
        self,
        position_key: str,
        new_trigger_price: float,
        trade_regime: str = "Buy"
    ) -> Optional[str]:
        """
        Modify existing SL order with new trigger price (for trailing stop).
        
        Args:
            position_key: Position key (e.g., "NIFTY_24000_CE")
            new_trigger_price: New SL trigger price
            trade_regime: "Buy" or "Sell" - determines price calculation
        
        Returns:
            Modified order ID or None if failed
        """
        if position_key not in self._open_positions:
            logger.warning(f"Position {position_key} not found for SL order modification")
            return None
        
        position = self._open_positions[position_key]
        sl_order_id = position.get('sl_order_id')
        current_sl_trigger = position.get('sl_trigger_price')
        
        if not sl_order_id:
            logger.warning(f"No SL order ID found for position {position_key}")
            return None
        
        # Check if SL order is still pending (can't modify if already executed/cancelled)
        sl_status = position.get('sl_status', '')
        if sl_status in ['COMPLETE', 'CANCELLED', 'REJECTED']:
            logger.warning(
                f"Cannot modify SL order {sl_order_id}: status is {sl_status}"
            )
            return None
        
        # Only modify if trigger price has actually changed
        if current_sl_trigger is not None and abs(new_trigger_price - current_sl_trigger) < 0.01:
            logger.debug(f"SL trigger price unchanged: ₹{new_trigger_price:.2f}, skipping modification")
            return sl_order_id
        
        try:
            # Round trigger price to nearest whole number (no decimals)
            new_trigger_price_rounded = round(new_trigger_price)
            
            # Calculate new limit price with difference of exactly 1
            # For Buy regime: SL is SELL order, so price = trigger - 1
            # For Sell regime: SL is BUY order, so price = trigger + 1
            if trade_regime == "Buy":
                new_limit_price = new_trigger_price_rounded - 1  # SELL order
            else:  # Sell
                new_limit_price = new_trigger_price_rounded + 1  # BUY order
            
            # Ensure both are whole numbers
            new_trigger_price_final = int(new_trigger_price_rounded)
            new_limit_price_final = int(new_limit_price)
            
            # Modify the SL order
            modified_order_id = self.kite_client.modify_order(
                order_id=str(sl_order_id),
                trigger_price=new_trigger_price_final,
                price=new_limit_price_final
            )
            
            # Update position with new SL info
            position['sl_order_id'] = modified_order_id  # May be same or new order ID
            position['sl_trigger_price'] = new_trigger_price
            position['sl_status'] = 'TRIGGER PENDING'  # Reset status after modification
            
            logger.warning(
                f"🛡️ STOP LOSS ORDER MODIFIED: Order ID {sl_order_id} → {modified_order_id} | "
                f"Old Trigger: ₹{current_sl_trigger:.2f} → New Trigger: ₹{new_trigger_price_final} "
                f"(rounded from ₹{new_trigger_price:.2f}), Limit: ₹{new_limit_price_final} (diff: {abs(new_limit_price_final - new_trigger_price_final)}) | "
                f"Trade Regime: {trade_regime}"
            )
            
            return modified_order_id
            
        except Exception as e:
            logger.error(f"Failed to modify stop loss order {sl_order_id}: {e}", exc_info=True)
            return None

    def _check_position_exists_in_kite(self, tradingsymbol: str, exchange: str) -> bool:
        """
        Check if a position actually exists in Kite by checking API.
        
        Args:
            tradingsymbol: Trading symbol to check
            exchange: Exchange (e.g., 'NFO')
            
        Returns:
            True if position exists in Kite, False otherwise
        """
        try:
            kite_positions = self.kite_client.get_positions()
            for kite_pos in kite_positions:
                if (kite_pos.get('tradingsymbol', '').upper() == tradingsymbol.upper() and
                    kite_pos.get('exchange', '').upper() == exchange.upper()):
                    quantity = int(kite_pos.get('quantity', 0))
                    if quantity != 0:  # Position exists and has non-zero quantity
                        logger.info(
                            f"✅ Position exists in Kite: {exchange}:{tradingsymbol} "
                            f"with quantity={quantity}"
                        )
                        return True
            logger.warning(
                f"⚠️ Position NOT found in Kite: {exchange}:{tradingsymbol} "
                f"(may already be closed or never opened)"
            )
            return False
        except Exception as e:
            logger.error(f"Error checking position in Kite: {e}", exc_info=True)
            # If we can't check, assume position exists to be safe (don't skip exit)
            return True
    
    def check_kite_position_by_option_type(self, segment: str, option_type: str) -> Optional[Dict[str, Any]]:
        """
        Check if a position of specific option type (CE/PE) exists in Kite for a segment.
        
        Args:
            segment: Segment name (e.g., 'NIFTY', 'BANKNIFTY', 'SENSEX')
            option_type: Option type ('CE' or 'PE')
            
        Returns:
            Position dict if found, None otherwise
        """
        try:
            kite_positions = self.kite_client.get_positions()
            segment_upper = segment.upper()
            option_type_upper = option_type.upper()
            
            for kite_pos in kite_positions:
                tradingsymbol = kite_pos.get('tradingsymbol', '').upper()
                quantity = int(kite_pos.get('quantity', 0))
                
                # Check if this is the segment and option type we're looking for
                if quantity != 0:  # Only check non-zero positions
                    # Check if symbol contains segment name and option type
                    if (segment_upper in tradingsymbol and 
                        option_type_upper in tradingsymbol):
                        logger.info(
                            f"✅ Found {option_type_upper} position in Kite for {segment}: "
                            f"{kite_pos.get('exchange')}:{tradingsymbol} with quantity={quantity}"
                        )
                        return kite_pos
            
            logger.debug(
                f"No {option_type_upper} position found in Kite for {segment}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Error checking Kite position for {segment} {option_type}: {e}",
                exc_info=True
            )
            # Return None on error - let caller decide what to do
            return None
    
    def check_open_trade_with_tag_and_product(
        self, 
        segment: str, 
        option_type: str, 
        tag: str = "S0002", 
        product: str = "MIS"
    ) -> bool:
        """
        Check if there's an open trade (order or position) with specific tag and product for the option type.
        Used in Sell Regime to prevent duplicate entries on the same side.
        
        Args:
            segment: Segment name (e.g., 'NIFTY', 'BANKNIFTY', 'SENSEX')
            option_type: Option type ('CE' or 'PE')
            tag: Order tag to filter by (default: "S0002")
            product: Product type to filter by (default: "MIS")
            
        Returns:
            True if open trade exists, False otherwise
        """
        try:
            segment_upper = segment.upper()
            option_type_upper = option_type.upper()
            
            # Check open/pending orders with tag="S0002" and product="MIS"
            orders = self.kite_client.get_orders()
            open_statuses = ['OPEN', 'TRIGGER PENDING', 'PENDING']
            
            for order in orders:
                order_tag = order.get('tag', '')
                order_product = order.get('product', '').upper()
                order_status = order.get('status', '').upper()
                tradingsymbol = order.get('tradingsymbol', '').upper()
                
                # Check if order matches criteria
                if (order_tag == tag and 
                    order_product == product.upper() and
                    order_status in open_statuses and
                    segment_upper in tradingsymbol and
                    option_type_upper in tradingsymbol):
                    quantity = int(order.get('quantity', 0))
                    if quantity != 0:
                        logger.info(
                            f"✅ Found open {option_type_upper} order with tag={tag}, product={product} "
                            f"for {segment}: {tradingsymbol} (status={order_status}, qty={quantity})"
                        )
                        return True
            
            # Also check positions (from completed orders with tag="S0002")
            kite_positions = self.kite_client.get_positions()
            for kite_pos in kite_positions:
                tradingsymbol = kite_pos.get('tradingsymbol', '').upper()
                quantity = int(kite_pos.get('quantity', 0))
                pos_product = kite_pos.get('product', '').upper()
                
                # Check if position matches criteria
                if (quantity != 0 and
                    pos_product == product.upper() and
                    segment_upper in tradingsymbol and
                    option_type_upper in tradingsymbol):
                    # Note: Positions don't store tag, but if product=MIS and it's our segment/option_type,
                    # it's likely from our strategy (especially in Sell Regime where we check before entry)
                    logger.info(
                        f"✅ Found {option_type_upper} position with product={product} "
                        f"for {segment}: {tradingsymbol} (qty={quantity})"
                    )
                    return True
            
            logger.debug(
                f"No open {option_type_upper} trade found with tag={tag}, product={product} for {segment}"
            )
            return False
        except Exception as e:
            logger.error(
                f"Error checking open trade with tag={tag}, product={product} for {segment} {option_type}: {e}",
                exc_info=True
            )
            # On error, return False to allow entry (fail open)
            return False
    
    def square_off_position(
        self,
        position_key: str,
        reason: str = "Exit",
        trade_regime: str = "Buy",  # "Buy" or "Sell" - determines exit order type
        check_kite_first: bool = True  # Check if position exists in Kite before squaring off
    ) -> Dict[str, Any]:
        """
        Square off an open position.
        
        For Buy regime: SELL to close (opposite of entry)
        For Sell regime: BUY to close (opposite of entry)
        
        Args:
            position_key: Position key
            reason: Exit reason
            trade_regime: "Buy" or "Sell"
            check_kite_first: If True, verify position exists in Kite before squaring off
        
        Returns:
            Dict with exit details including P&L
        """
        if position_key not in self._open_positions:
            raise OrderExecutionError(f"Position {position_key} not found")
        
        position = self._open_positions[position_key]
        
        # Check if position actually exists in Kite before squaring off
        if check_kite_first:
            position_exists = self._check_position_exists_in_kite(
                position['tradingsymbol'],
                position['exchange']
            )
            if not position_exists:
                logger.warning(
                    f"⚠️ Position {position_key} does not exist in Kite. "
                    f"Skipping square-off order. Reason: {reason}"
                )
                # Mark as closed internally but don't place exit order
                entry_price = position['entry_price']
                result = {
                    "order_id": None,
                    "exit_price": 0.0,
                    "entry_price": entry_price,
                    "pnl_points": 0.0,
                    "pnl_value": 0.0,
                    "reason": f"{reason} (Position not found in Kite - already closed)",
                    "skipped": True
                }
                # Remove from open positions
                del self._open_positions[position_key]
                return result
        
        try:
            # Determine exit transaction type based on trade regime
            # Buy regime: entered with BUY, exit with SELL
            # Sell regime: entered with SELL, exit with BUY
            exit_transaction_type = "SELL" if trade_regime == "Buy" else "BUY"
            
            # Place exit order to close position
            order_id = self.kite_client.place_market_order(
                tradingsymbol=position['tradingsymbol'],
                exchange=position['exchange'],
                transaction_type=exit_transaction_type,
                quantity=position['quantity'],
                product="MIS",
                tag="S0002"
            )
            
            # Get order details
            orders = self.kite_client.get_orders()
            order = next((o for o in orders if str(o.get('order_id')) == str(order_id)), None)
            
            exit_price = 0.0
            if order:
                exit_price = float(order.get('average_price', 0) or order.get('price', 0))
            
            entry_price = position['entry_price']
            # P&L calculation based on trade regime
            # Buy: (exit - entry) * quantity
            # Sell: (entry - exit) * quantity
            if trade_regime == "Buy":
                pnl_points = exit_price - entry_price
            else:  # Sell
                pnl_points = entry_price - exit_price
            pnl_value = pnl_points * position['quantity']
            
            result = {
                "order_id": order_id,
                "exit_price": exit_price,
                "entry_price": entry_price,
                "pnl_points": pnl_points,
                "pnl_value": pnl_value,
                "reason": reason
            }
            
            # Remove from open positions
            del self._open_positions[position_key]
            
            logger.warning(
                f"LIVE ORDER CLOSED: {exit_transaction_type} {position['quantity']} {position['tradingsymbol']} "
                f"@ {exit_price} | P&L: ₹{pnl_value:.2f} ({pnl_points:.2f} pts) | Order ID: {order_id} | Trade Regime: {trade_regime}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error squaring off position: {e}", exc_info=True)
            raise OrderExecutionError(f"Failed to square off position: {str(e)}")

    def log_trade(self, record: PaperTradeRecord) -> None:
        """Append a completed trade to today's CSV file (same as PaperExecutionClient)."""
        file_path = LOG_DIR / f"live_trades_{_today_str()}.csv"
        
        # Try to restore from Azure Blob Storage if file doesn't exist
        if not file_path.exists():
            try:
                from src.utils.csv_backup import restore_csv_file
                restore_csv_file(file_path)
            except Exception as e:
                logger.debug(f"Could not restore CSV from backup: {e}")
        
        is_new = not file_path.exists()

        fieldnames = list(asdict(record).keys())

        with file_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if is_new:
                writer.writeheader()
            row: Dict[str, Any] = {}
            for k, v in asdict(record).items():
                if isinstance(v, datetime):
                    row[k] = v.isoformat()
                else:
                    row[k] = v
            writer.writerow(row)

        # Backup to Azure Blob Storage after writing
        try:
            from src.utils.csv_backup import backup_csv_file
            backup_csv_file(file_path)
        except Exception as e:
            logger.debug(f"Could not backup CSV to Azure: {e}")

        logger.info(
            f"Logged LIVE trade: segment={record.segment}, symbol={record.option_symbol}, "
            f"pnl={record.pnl_value:.2f} ({record.pnl_points:.2f} pts)"
        )
    
    def log_open_position(self, record: OpenPositionRecord) -> None:
        """Log or update an open position in CSV file (same as PaperExecutionClient)."""
        # Delegate to PaperExecutionClient's implementation
        # Create a temporary instance to use the method
        temp_paper_client = PaperExecutionClient(mode="PAPER")
        temp_paper_client.log_open_position(record)


