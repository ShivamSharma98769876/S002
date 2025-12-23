"""
Flask-based Dashboard UI
Beautiful and modern web interface for real-time monitoring
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from datetime import datetime
from typing import Optional
from pathlib import Path
import threading
from src.utils.logger import get_logger
from src.risk_management.risk_monitor import RiskMonitor
from src.database.repository import PositionRepository, TradeRepository
from src.security.access_control import AccessControl
from src.security.parameter_locker import ParameterLocker
from src.security.version_control import VersionControl
from src.config.config_manager import ConfigManager
from src.database.models import DatabaseManager

logger = get_logger("ui")


class Dashboard:
    """Dashboard web application"""
    
    def __init__(
        self,
        risk_monitor: RiskMonitor,
        position_repo: PositionRepository,
        trade_repo: TradeRepository,
        access_control: AccessControl,
        parameter_locker: ParameterLocker,
        version_control: VersionControl,
        kite_client=None,
        host: str = "0.0.0.0",
        port: int = 5000,
        debug: bool = False
    ):
        self.risk_monitor = risk_monitor
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.access_control = access_control
        self.parameter_locker = parameter_locker
        self.version_control = version_control
        self.kite_client = kite_client
        self.host = host
        self.port = port
        self.debug = debug
        
        # Get absolute paths for templates and static files
        ui_dir = Path(__file__).parent
        template_dir = ui_dir / 'templates'
        static_dir = ui_dir / 'static'
        
        self.app = Flask(__name__, 
                        template_folder=str(template_dir),
                        static_folder=str(static_dir))
        CORS(self.app)
        self._setup_routes()
        
        # Log registered routes for debugging (before panel initialization)
        logger = get_logger("ui")
        logger.info("Initial registered routes (before panels):")
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint != 'static':
                logger.info(f"  {rule.rule} [{', '.join(rule.methods - {'HEAD', 'OPTIONS'})}]")

        # Initialize admin panel
        from src.ui.admin_panel import init_admin_panel
        init_admin_panel(
            self.app,
            access_control,
            parameter_locker,
            version_control,
            kite_client=self.kite_client
        )
        
        # Initialize backtesting panel
        from src.ui.backtest_panel import init_backtest_panel
        init_backtest_panel(
            self.app,
            kite_client=self.kite_client
        )

        # Initialize live trader panel
        try:
            from src.ui.live_trader_panel import init_live_trader_panel
            init_live_trader_panel(
                self.app,
                kite_client=self.kite_client,
                dashboard_instance=self,  # Pass dashboard instance for fallback access
            )
            # Log successful registration
            logger.info("✅ Live Trader panel initialized successfully")
            # Log all registered routes after initialization
            logger.info("All registered routes after Live Trader initialization:")
            live_routes_logged = False
            for rule in self.app.url_map.iter_rules():
                if rule.endpoint != 'static' and '/live' in str(rule):
                    live_routes_logged = True
                    logger.info(f"  {rule.rule} [{', '.join(rule.methods - {'HEAD', 'OPTIONS'})}]")
            
            if not live_routes_logged:
                logger.warning("⚠️ WARNING: No /live routes found after initialization!")
                logger.warning("This might indicate the blueprint registration failed.")
                # Add a fallback direct route
                @self.app.route('/live/', methods=['GET'])
                @self.app.route('/live', methods=['GET'])
                def live_trader_fallback():
                    """Fallback route if blueprint registration failed"""
                    try:
                        from flask import render_template
                        return render_template('live_trader.html')
                    except Exception as e:
                        logger.error(f"Fallback route error: {e}")
                        return f"Live Trader page (fallback route). Error: {str(e)}", 500
                logger.info("Added fallback /live route")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Live Trader panel: {e}", exc_info=True)
            logger.error("Live Trader routes will not be available")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
    
    def _is_equity_trade(self, exchange: str) -> bool:
        """
        Check if a trade/position is equity (NSE or BSE equity segment).
        Excludes NFO, BFO, MCX, CDS and other derivative/commodity exchanges.
        Returns False if equity filtering is disabled in config.
        
        Args:
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS')
            
        Returns:
            True if equity trade and filtering is enabled, False otherwise
        """
        # Check if equity filtering is enabled
        try:
            admin_config = self.parameter_locker.config_manager.get_admin_config()
            if not admin_config.exclude_equity_trades:
                return False  # Don't filter if disabled
        except Exception:
            # If config can't be loaded, default to filtering (safe default)
            pass
        
        if not exchange:
            return False
        
        exchange_upper = exchange.upper()
        # Equity exchanges: NSE and BSE (for equity stocks)
        # Non-equity exchanges: NFO, BFO, MCX, CDS, etc.
        equity_exchanges = ['NSE', 'BSE']
        return exchange_upper in equity_exchanges
    
    def _setup_routes(self):
        """Setup Flask routes"""
        
        # Test endpoint to verify routes are working
        @self.app.route('/api/test', methods=['GET'])
        def test_endpoint():
            """Test endpoint to verify API is working"""
            return jsonify({"status": "ok", "message": "API is working"})
        
        # Route listing endpoint for debugging
        @self.app.route('/api/routes', methods=['GET'])
        def list_routes():
            """List all registered routes (for debugging)"""
            routes = []
            for rule in self.app.url_map.iter_rules():
                routes.append({
                    "endpoint": rule.endpoint,
                    "methods": list(rule.methods),
                    "path": str(rule)
                })
            return jsonify({"routes": routes})
        
        @self.app.route('/')
        def index():
            """Main dashboard page"""
            # Get API key for authentication link
            api_key = ""
            if self.kite_client:
                api_key = self.kite_client.api_key
            return render_template('dashboard.html', api_key=api_key)
        
        @self.app.route('/api/status')
        def get_status():
            """Get current system status"""
            try:
                status = self.risk_monitor.get_current_status()
                
                # Add quantity manager metrics
                quantity_manager = self.risk_monitor.quantity_manager
                status["net_position_pnl"] = quantity_manager.get_net_position_pnl()
                status["booked_profit"] = quantity_manager.get_booked_profit()
                
                # Add connectivity status
                connectivity_status = {
                    "connected": True,
                    "api_connected": False,
                    "websocket_connected": False,
                    "last_update": datetime.now().isoformat()
                }
                
                # Check API connectivity
                if self.kite_client:
                    connectivity_status["api_connected"] = self.kite_client.is_authenticated()
                
                # Check WebSocket connectivity
                if self.risk_monitor.websocket_client:
                    connectivity_status["websocket_connected"] = self.risk_monitor.websocket_client.is_connected()
                
                connectivity_status["connected"] = connectivity_status["api_connected"]
                status["connectivity"] = connectivity_status
                
                return jsonify(status)
            except Exception as e:
                logger.error(f"Error getting status: {e}")
                return jsonify({
                    "error": str(e),
                    "connectivity": {
                        "connected": False,
                        "api_connected": False,
                        "websocket_connected": False,
                        "error": str(e)
                    }
                }), 500
        
        @self.app.route('/api/connectivity', methods=['GET'])
        def check_connectivity():
            """Check system connectivity status"""
            try:
                connectivity = {
                    "connected": False,
                    "api_connected": False,
                    "websocket_connected": False,
                    "api_authenticated": False,
                    "last_check": datetime.now().isoformat(),
                    "status_message": ""
                }
                
                # Check API connectivity
                if self.kite_client:
                    connectivity["api_authenticated"] = self.kite_client.is_authenticated()
                    connectivity["api_connected"] = connectivity["api_authenticated"]
                    
                    # Try a simple API call to verify connectivity
                    if connectivity["api_authenticated"]:
                        try:
                            # Quick connectivity test - get profile (lightweight call)
                            profile = self.kite_client.kite.profile()
                            connectivity["api_connected"] = True
                            connectivity["status_message"] = "API Connected"
                        except Exception as api_error:
                            connectivity["api_connected"] = False
                            connectivity["status_message"] = f"API Error: {str(api_error)[:50]}"
                    else:
                        connectivity["status_message"] = "Not Authenticated"
                else:
                    connectivity["status_message"] = "Kite Client Not Initialized"
                
                # Check WebSocket connectivity
                if self.risk_monitor.websocket_client:
                    connectivity["websocket_connected"] = self.risk_monitor.websocket_client.is_connected()
                    if connectivity["websocket_connected"]:
                        connectivity["status_message"] += " | WebSocket Connected"
                    else:
                        connectivity["status_message"] += " | WebSocket Disconnected"
                
                connectivity["connected"] = connectivity["api_connected"]
                
                return jsonify(connectivity)
            except Exception as e:
                logger.error(f"Error checking connectivity: {e}")
                return jsonify({
                    "connected": False,
                    "api_connected": False,
                    "websocket_connected": False,
                    "error": str(e),
                    "status_message": f"Error: {str(e)}"
                }), 500
        
        @self.app.route('/api/quantity-changes')
        def get_quantity_changes():
            """Get quantity change history"""
            try:
                quantity_manager = self.risk_monitor.quantity_manager
                position_id = request.args.get('position_id', type=int)
                
                if position_id:
                    history = quantity_manager.get_quantity_history(position_id)
                    return jsonify({"history": history})
                else:
                    # Get all positions with quantity changes
                    changes = quantity_manager.detect_quantity_changes()
                    return jsonify({"changes": changes})
            except Exception as e:
                logger.error(f"Error getting quantity changes: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/positions/clear-cache', methods=['POST'])
        def clear_positions_cache():
            """Clear all positions from cache and fetch fresh from Zerodha"""
            try:
                logger.info("Cache clear request received")
                
                # Clear all active positions
                cleared_count = self.position_repo.clear_all_positions()
                logger.info(f"Cleared {cleared_count} positions from cache")
                
                # Force fresh sync from Zerodha API
                if self.risk_monitor.position_sync:
                    kite_client = self.risk_monitor.position_sync.kite_client
                    if kite_client and kite_client.is_authenticated():
                        try:
                            # Sync fresh positions from API
                            synced_positions = self.risk_monitor.position_sync.sync_positions_from_api()
                            logger.info(f"Cache cleared: {cleared_count} positions. Fresh sync: {len(synced_positions)} positions")
                            return jsonify({
                                "success": True,
                                "message": f"Cache cleared. Fetched {len(synced_positions)} fresh positions from Zerodha",
                                "cleared_count": cleared_count,
                                "synced_count": len(synced_positions)
                            })
                        except Exception as sync_error:
                            logger.error(f"Error syncing positions after cache clear: {sync_error}", exc_info=True)
                            return jsonify({
                                "success": False,
                                "error": f"Cache cleared but sync failed: {str(sync_error)}",
                                "cleared_count": cleared_count
                            }), 500
                    else:
                        logger.warning("Cache clear requested but not authenticated with Zerodha")
                        return jsonify({
                            "success": False,
                            "error": "Not authenticated with Zerodha",
                            "cleared_count": cleared_count
                        }), 401
                else:
                    logger.warning("Cache clear requested but position_sync not available")
                    return jsonify({
                        "success": True,
                        "message": f"Cache cleared: {cleared_count} positions (Position sync not available)",
                        "cleared_count": cleared_count,
                        "synced_count": 0
                    })
            except Exception as e:
                logger.error(f"Error clearing positions cache: {e}", exc_info=True)
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/protected-profit/clear', methods=['POST'])
        def clear_protected_profit():
            """Clear protected profit by deleting trades for a specific date (Admin only)"""
            try:
                # Check admin authentication
                token = request.headers.get('Authorization', '').replace('Bearer ', '')
                if not self.access_control.is_admin(token):
                    return jsonify({"success": False, "error": "Admin access required"}), 403
                
                data = request.get_json() or {}
                trade_date_str = data.get('date', None)
                
                # Default to today's date if not specified
                if trade_date_str:
                    try:
                        trade_date = datetime.fromisoformat(trade_date_str).date()
                    except ValueError:
                        return jsonify({"success": False, "error": f"Invalid date format: {trade_date_str}. Use YYYY-MM-DD"}), 400
                else:
                    from src.utils.date_utils import get_current_ist_time
                    trade_date = get_current_ist_time().date()
                
                # Get count before deletion for confirmation
                trades_before = self.trade_repo.get_trades_by_date(trade_date)
                count_before = len(trades_before)
                
                if count_before == 0:
                    return jsonify({
                        "success": True,
                        "message": f"No trades found for {trade_date}. Protected Profit already cleared.",
                        "deleted_count": 0
                    })
                
                # Delete trades for the date
                deleted_count = self.trade_repo.delete_trades_by_date(trade_date)
                
                # Recalculate protected profit (should be 0 now)
                protected_profit = self.trade_repo.get_protected_profit(trade_date)
                
                logger.warning(
                    f"Admin cleared protected profit for {trade_date}: "
                    f"Deleted {deleted_count} trades. New protected profit: ₹{protected_profit:.2f}"
                )
                
                return jsonify({
                    "success": True,
                    "message": f"Protected Profit cleared for {trade_date}",
                    "deleted_count": deleted_count,
                    "protected_profit_after": protected_profit,
                    "date": trade_date.isoformat()
                })
            except Exception as e:
                logger.error(f"Error clearing protected profit: {e}", exc_info=True)
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/positions')
        def get_positions():
            """Get active positions with latest prices and P&L"""
            try:
                # Trigger position sync to get latest prices from API
                if self.risk_monitor.position_sync:
                    kite_client = self.risk_monitor.position_sync.kite_client
                    if kite_client and kite_client.is_authenticated():
                        try:
                            # Sync positions to update current prices and P&L
                            self.risk_monitor.position_sync.sync_positions_from_api()
                        except Exception as sync_error:
                            logger.debug(f"Position sync error (non-critical): {sync_error}")
                
                # Get positions from database (now with updated prices)
                positions = self.position_repo.get_active_positions()
                positions_data = []
                for pos in positions:
                    # Filter out equity trades (NSE, BSE)
                    if self._is_equity_trade(pos.exchange):
                        continue
                    
                    # Ensure P&L is calculated with latest price
                    if pos.current_price and pos.entry_price:
                        # Recalculate P&L to ensure it's up to date
                        from src.utils.position_utils import calculate_position_pnl
                        calculated_pnl = calculate_position_pnl(
                            pos.entry_price,
                            pos.current_price,
                            pos.quantity,
                            pos.lot_size
                        )
                        # Use calculated P&L if different (more accurate)
                        unrealized_pnl = calculated_pnl if abs(calculated_pnl - pos.unrealized_pnl) > 0.01 else pos.unrealized_pnl
                    else:
                        unrealized_pnl = pos.unrealized_pnl
                    
                    positions_data.append({
                        "id": pos.id,
                        "trading_symbol": pos.trading_symbol,
                        "exchange": pos.exchange,
                        "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                        "entry_price": pos.entry_price,
                        "current_price": pos.current_price,
                        "quantity": pos.quantity,
                        "lot_size": pos.lot_size,
                        "unrealized_pnl": unrealized_pnl
                    })
                return jsonify(positions_data)
            except Exception as e:
                logger.error(f"Error getting positions: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/trades')
        def get_trades():
            """Get trade history - fetch directly from Zerodha orderbook"""
            try:
                # Get date range from query params
                date_str = request.args.get('date', None)
                all_trades_param = request.args.get('all', 'false').lower() == 'true'
                use_orderbook = request.args.get('orderbook', 'true').lower() == 'true'
                
                # Default to today's date if no date specified and not showing all trades
                if not all_trades_param and not date_str:
                    from src.utils.date_utils import get_current_ist_time
                    today_ist = get_current_ist_time().date()
                    date_str = today_ist.isoformat()
                
                # If authenticated, fetch orders directly from Zerodha
                if use_orderbook and self.kite_client and self.kite_client.is_authenticated():
                    try:
                        # Get all orders from Zerodha
                        all_orders = self.kite_client.get_orders()
                        logger.info(f"Fetched {len(all_orders)} orders from Zerodha orderbook")
                        
                        # Filter for non-equity orders that are COMPLETE (exclude NSE, BSE equity)
                        non_equity_orders = []
                        for order in all_orders:
                            # Check if it's an equity trade (NSE, BSE)
                            exchange = order.get('exchange', '').upper()
                            
                            # Exclude equity trades (NSE, BSE)
                            if self._is_equity_trade(exchange):
                                continue
                            
                            # Only include COMPLETE orders
                            status = order.get('status', '').upper()
                            if status != 'COMPLETE':
                                continue
                            
                            # Check if order has filled quantity
                            filled_qty = order.get('filled_quantity', 0)
                            if filled_qty == 0:
                                continue
                            
                            non_equity_orders.append(order)
                        
                        # Sort by timestamp (most recent first)
                        non_equity_orders.sort(
                            key=lambda x: x.get('order_timestamp', ''),
                            reverse=True
                        )
                        
                        # Convert orders to trade format
                        from src.utils.date_utils import IST
                        from pytz import UTC
                        
                        # Consolidate orders into trades (match BUY and SELL)
                        # Group by trading symbol and match orders chronologically
                        orders_by_symbol = {}
                        for order in non_equity_orders:
                            symbol = order.get('tradingsymbol', '')
                            if symbol not in orders_by_symbol:
                                orders_by_symbol[symbol] = []
                            orders_by_symbol[symbol].append(order)
                        
                        # Process each symbol to create consolidated trades
                        trades_data = []
                        for symbol, symbol_orders in orders_by_symbol.items():
                            # Filter by date if specified
                            if date_str and not all_trades_param:
                                try:
                                    trade_date = datetime.fromisoformat(date_str).date()
                                    symbol_orders = [
                                        o for o in symbol_orders
                                        if self._parse_order_timestamp(o.get('order_timestamp', '')).date() == trade_date
                                    ]
                                except:
                                    pass
                            
                            # Sort by timestamp
                            symbol_orders.sort(key=lambda x: self._parse_order_timestamp(x.get('order_timestamp', '')))
                            
                            # Use FIFO to match BUY and SELL orders
                            pending_buys = []  # List of (order, remaining_qty)
                            pending_sells = []  # List of (order, remaining_qty)
                            
                            for order in symbol_orders:
                                try:
                                    # Parse order timestamp
                                    raw_timestamp = order.get('order_timestamp', '')
                                    order_time = self._parse_order_timestamp(raw_timestamp)
                                    
                                    # Log for debugging (first few orders only) - show both UTC and IST interpretations
                                    if len(trades_data) < 3:
                                        from pytz import UTC
                                        if raw_timestamp:
                                            try:
                                                if isinstance(raw_timestamp, datetime):
                                                    test_dt = raw_timestamp
                                                else:
                                                    test_dt = datetime.strptime(str(raw_timestamp), '%Y-%m-%d %H:%M:%S')
                                                
                                                # Test both interpretations
                                                as_utc = test_dt.replace(tzinfo=UTC).astimezone(IST)
                                                as_ist = IST.localize(test_dt)
                                                
                                                logger.info(
                                                    f"Order {order.get('order_id', '')} timestamp debug: "
                                                    f"raw={raw_timestamp}, "
                                                    f"if_UTC_then_IST={as_utc.strftime('%Y-%m-%d %H:%M:%S')}, "
                                                    f"if_IST_then_IST={as_ist.strftime('%Y-%m-%d %H:%M:%S')}, "
                                                    f"using={order_time.strftime('%Y-%m-%d %H:%M:%S')}"
                                                )
                                            except:
                                                pass
                                    
                                    transaction_type = order.get('transaction_type', '').upper()
                                    filled_qty = order.get('filled_quantity', 0)
                                    avg_price = float(order.get('average_price', 0))
                                    
                                    if transaction_type == 'BUY':
                                        remaining_qty = filled_qty
                                        # Match with pending SELL orders (short covering)
                                        while remaining_qty > 0 and pending_sells:
                                            sell_order, sell_remaining = pending_sells[0]
                                            sell_price = float(sell_order.get('average_price', 0))
                                            sell_time = self._parse_order_timestamp(sell_order.get('order_timestamp', ''))
                                            
                                            match_qty = min(remaining_qty, sell_remaining)
                                            
                                            # Calculate P&L for this match
                                            # For SELL first then BUY: P&L = (sell_price - buy_price) * qty
                                            pnl = (sell_price - avg_price) * match_qty
                                            
                                            trades_data.append({
                                                "id": f"trade_{sell_order.get('order_id', '')}_{order.get('order_id', '')}",
                                                "trading_symbol": symbol,
                                                "exchange": order.get('exchange', ''),
                                                "entry_time": sell_time.isoformat() if sell_time else None,
                                                "exit_time": order_time.isoformat() if order_time else None,
                                                "entry_price": sell_price,
                                                "exit_price": avg_price,
                                                "quantity": -abs(match_qty),  # Negative for SELL
                                                "transaction_type": "SELL",
                                                "realized_pnl": pnl,
                                                "is_profit": pnl > 0,
                                                "exit_type": "orderbook",
                                                "source": "orderbook"
                                            })
                                            
                                            remaining_qty -= match_qty
                                            sell_remaining -= match_qty
                                            
                                            if sell_remaining == 0:
                                                pending_sells.pop(0)
                                            else:
                                                pending_sells[0] = (sell_order, sell_remaining)
                                        
                                        if remaining_qty > 0:
                                            pending_buys.append((order, remaining_qty))
                                    
                                    elif transaction_type == 'SELL':
                                        remaining_qty = filled_qty
                                        # Match with pending BUY orders (long exit)
                                        while remaining_qty > 0 and pending_buys:
                                            buy_order, buy_remaining = pending_buys[0]
                                            buy_price = float(buy_order.get('average_price', 0))
                                            buy_time = self._parse_order_timestamp(buy_order.get('order_timestamp', ''))
                                            
                                            match_qty = min(remaining_qty, buy_remaining)
                                            
                                            # Calculate P&L for this match
                                            # For BUY first then SELL: P&L = (sell_price - buy_price) * qty
                                            pnl = (avg_price - buy_price) * match_qty
                                            
                                            trades_data.append({
                                                "id": f"trade_{buy_order.get('order_id', '')}_{order.get('order_id', '')}",
                                                "trading_symbol": symbol,
                                                "exchange": order.get('exchange', ''),
                                                "entry_time": buy_time.isoformat() if buy_time else None,
                                                "exit_time": order_time.isoformat() if order_time else None,
                                                "entry_price": buy_price,
                                                "exit_price": avg_price,
                                                "quantity": abs(match_qty),  # Positive for BUY
                                                "transaction_type": "BUY",
                                                "realized_pnl": pnl,
                                                "is_profit": pnl > 0,
                                                "exit_type": "orderbook",
                                                "source": "orderbook"
                                            })
                                            
                                            remaining_qty -= match_qty
                                            buy_remaining -= match_qty
                                            
                                            if buy_remaining == 0:
                                                pending_buys.pop(0)
                                            else:
                                                pending_buys[0] = (buy_order, buy_remaining)
                                        
                                        if remaining_qty > 0:
                                            pending_sells.append((order, remaining_qty))
                                
                                except Exception as e:
                                    logger.error(f"Error processing order {order.get('order_id', 'unknown')}: {e}", exc_info=True)
                                    continue
                        
                        # Calculate summary from consolidated trades
                        total_profit = sum(t.get('realized_pnl', 0) for t in trades_data if t.get('realized_pnl', 0) > 0)
                        total_loss = sum(t.get('realized_pnl', 0) for t in trades_data if t.get('realized_pnl', 0) < 0)
                        total_pnl = sum(t.get('realized_pnl', 0) for t in trades_data)
                        profitable_trades = sum(1 for t in trades_data if t.get('realized_pnl', 0) > 0)
                        loss_trades = sum(1 for t in trades_data if t.get('realized_pnl', 0) < 0)
                        
                        summary = {
                            "total_profit": total_profit,
                            "total_loss": total_loss,
                            "total_pnl": total_pnl,
                            "total_trades": len(trades_data),
                            "profitable_trades": profitable_trades,
                            "loss_trades": loss_trades
                        }
                        
                        return jsonify({
                            "trades": trades_data,
                            "summary": summary
                        })
                    except Exception as e:
                        logger.error(f"Error fetching orders from Zerodha: {e}", exc_info=True)
                        # Fall back to database trades
                        pass
                
                # Fallback to database trades if orderbook fetch fails or not authenticated
                if not use_orderbook or not self.kite_client or not self.kite_client.is_authenticated():
                    if all_trades_param or not date_str:
                        # Get all trades (all inactive/completed trades)
                        trades = self.trade_repo.get_all_trades()
                    else:
                        # Get trades for specific date
                        try:
                            trade_date = datetime.fromisoformat(date_str).date()
                            trades = self.trade_repo.get_trades_by_date(trade_date)
                        except ValueError as ve:
                            logger.error(f"Invalid date format: {date_str} - {ve}")
                            return jsonify({"error": f"Invalid date format: {date_str}"}), 400
                
                # Get inactive positions (quantity=0) - filter by date if not showing all trades
                try:
                    inactive_positions = self.position_repo.get_all_inactive_positions()
                    # Filter inactive positions by date if date is specified
                    if date_str and not all_trades_param:
                        try:
                            from src.utils.date_utils import IST
                            from pytz import UTC
                            trade_date = datetime.fromisoformat(date_str).date()
                            filtered_inactive = []
                            for position in inactive_positions:
                                # Check if position was closed on the specified date
                                if position.updated_at:
                                    updated_at_ist = position.updated_at
                                    if updated_at_ist.tzinfo is None:
                                        updated_at_ist = updated_at_ist.replace(tzinfo=UTC).astimezone(IST)
                                    else:
                                        updated_at_ist = updated_at_ist.astimezone(IST)
                                    if updated_at_ist.date() == trade_date:
                                        filtered_inactive.append(position)
                            inactive_positions = filtered_inactive
                        except Exception as filter_error:
                            logger.warning(f"Error filtering inactive positions by date: {filter_error}")
                except Exception as pos_error:
                    logger.error(f"Error getting inactive positions: {pos_error}")
                    inactive_positions = []
                
                # Get summary statistics (includes both trades and inactive positions)
                try:
                    summary = self._calculate_trades_summary(trades, inactive_positions)
                except Exception as summary_error:
                    logger.error(f"Error calculating trades summary: {summary_error}")
                    summary = {
                        "total_profit": 0,
                        "total_loss": 0,
                        "total_pnl": 0,
                        "total_trades": 0,
                        "profitable_trades": 0,
                        "loss_trades": 0
                    }
                
                from src.utils.date_utils import IST
                from pytz import UTC
                
                trades_data = []
                
                # Add completed trades
                for trade in trades:
                    try:
                        # Filter out equity trades (NSE, BSE)
                        if self._is_equity_trade(trade.exchange):
                            continue
                        
                        # Convert times to IST for display
                        entry_time_ist = trade.entry_time
                        exit_time_ist = trade.exit_time
                        
                        # Convert to IST if timezone aware, otherwise assume UTC
                        if entry_time_ist:
                            if entry_time_ist.tzinfo is None:
                                entry_time_ist = entry_time_ist.replace(tzinfo=UTC).astimezone(IST)
                            else:
                                entry_time_ist = entry_time_ist.astimezone(IST)
                            entry_time_str = entry_time_ist.isoformat()
                        else:
                            entry_time_str = None
                        
                        if exit_time_ist:
                            if exit_time_ist.tzinfo is None:
                                exit_time_ist = exit_time_ist.replace(tzinfo=UTC).astimezone(IST)
                            else:
                                exit_time_ist = exit_time_ist.astimezone(IST)
                            exit_time_str = exit_time_ist.isoformat()
                        else:
                            exit_time_str = None
                        
                        # Get transaction type (default to BUY if not set for old records)
                        transaction_type = getattr(trade, 'transaction_type', None)
                        if not transaction_type:
                            transaction_type = 'BUY' if (trade.quantity and trade.quantity > 0) else 'SELL'
                        
                        trades_data.append({
                            "id": trade.id,
                            "trading_symbol": trade.trading_symbol or "",
                            "exchange": trade.exchange or "",
                            "entry_time": entry_time_str,
                            "exit_time": exit_time_str,
                            "entry_price": trade.entry_price or 0.0,
                            "exit_price": trade.exit_price or 0.0,
                            "quantity": trade.quantity or 0,  # Can be negative for SELL
                            "transaction_type": transaction_type,
                            "realized_pnl": trade.realized_pnl or 0.0,
                            "is_profit": (trade.realized_pnl or 0.0) > 0,
                            "exit_type": trade.exit_type or "unknown",
                            "source": "trade"  # Mark as completed trade
                        })
                    except Exception as trade_error:
                        logger.error(f"Error processing trade {getattr(trade, 'id', 'unknown')}: {trade_error}", exc_info=True)
                        continue  # Skip this trade and continue with others
                
                # Add inactive positions (quantity=0) as trades
                logger.info(f"Found {len(inactive_positions)} inactive positions to add to trade history")
                for position in inactive_positions:
                    try:
                        # Filter out equity trades (NSE, BSE)
                        if self._is_equity_trade(position.exchange):
                            continue
                        
                        # Convert position to trade-like format
                        exit_time_ist = position.updated_at
                        entry_time_ist = position.entry_time
                        
                        # Convert to IST if timezone aware, otherwise assume UTC
                        if entry_time_ist:
                            if entry_time_ist.tzinfo is None:
                                entry_time_ist = entry_time_ist.replace(tzinfo=UTC).astimezone(IST)
                            else:
                                entry_time_ist = entry_time_ist.astimezone(IST)
                            entry_time_str = entry_time_ist.isoformat()
                        else:
                            entry_time_str = None
                        
                        if exit_time_ist:
                            if exit_time_ist.tzinfo is None:
                                exit_time_ist = exit_time_ist.replace(tzinfo=UTC).astimezone(IST)
                            else:
                                exit_time_ist = exit_time_ist.astimezone(IST)
                            exit_time_str = exit_time_ist.isoformat()
                        else:
                            exit_time_str = None
                        
                        # Determine transaction type - try to infer from unrealized_pnl or entry/exit prices
                        # For SELL positions that closed: if entry > exit, it was profitable (SELL)
                        # For BUY positions that closed: if exit > entry, it was profitable (BUY)
                        transaction_type = 'BUY'  # Default
                        if position.entry_price and position.current_price:
                            # If entry > current and P&L is positive, likely SELL
                            # If current > entry and P&L is positive, likely BUY
                            if position.unrealized_pnl:
                                # For SELL: profit when entry > exit
                                # For BUY: profit when exit > entry
                                if position.entry_price > position.current_price and position.unrealized_pnl > 0:
                                    transaction_type = 'SELL'
                                elif position.current_price > position.entry_price and position.unrealized_pnl > 0:
                                    transaction_type = 'BUY'
                                # If P&L is negative, reverse the logic
                                elif position.entry_price > position.current_price and position.unrealized_pnl < 0:
                                    transaction_type = 'BUY'
                                elif position.current_price > position.entry_price and position.unrealized_pnl < 0:
                                    transaction_type = 'SELL'
                        
                        # Get original quantity from position
                        # For positions with quantity=0, try to get from trade records or infer from P&L
                        original_quantity = position.quantity  # Will be 0 for inactive positions
                        try:
                            # Check if there's a trade record for this position
                            position_trades = self.trade_repo.get_trades_by_position_id(position.id)
                            if position_trades:
                                # Use the quantity from the most recent trade (preserves sign: negative for SELL)
                                original_quantity = position_trades[0].quantity
                                logger.debug(f"Found original quantity {original_quantity} from trade record for position {position.id}")
                            else:
                                # If no trade record, try to infer from P&L and prices
                                # For SELL: if entry > exit and P&L positive, quantity was negative
                                # For BUY: if exit > entry and P&L positive, quantity was positive
                                if position.entry_price and position.current_price and position.unrealized_pnl:
                                    # This is a heuristic - not perfect but better than 0
                                    if transaction_type == 'SELL':
                                        # Estimate quantity based on P&L
                                        # For SELL: P&L = (entry - exit) * abs(qty)
                                        price_diff = position.entry_price - position.current_price
                                        if abs(price_diff) > 0.01:  # Avoid division by zero
                                            estimated_qty = abs(int(position.unrealized_pnl / price_diff))
                                            original_quantity = -estimated_qty  # Negative for SELL
                                    else:
                                        # For BUY: P&L = (exit - entry) * qty
                                        price_diff = position.current_price - position.entry_price
                                        if abs(price_diff) > 0.01:  # Avoid division by zero
                                            original_quantity = int(position.unrealized_pnl / price_diff)
                                logger.debug(f"Inferred original quantity {original_quantity} for position {position.id}")
                        except Exception as qty_error:
                            logger.warning(f"Could not determine original quantity for position {position.id}: {qty_error}")
                            original_quantity = 0
                        
                        # Calculate realized P&L from unrealized P&L (final P&L when position closed)
                        realized_pnl = position.unrealized_pnl if position.unrealized_pnl else 0.0
                        is_profit = realized_pnl > 0
                        
                        trades_data.append({
                            "id": f"pos_{position.id}",  # Prefix to avoid conflicts
                            "trading_symbol": position.trading_symbol or "",
                            "exchange": position.exchange or "",
                            "entry_time": entry_time_str,
                            "exit_time": exit_time_str,
                            "entry_price": position.entry_price or 0.0,
                            "exit_price": position.current_price or position.entry_price or 0.0,
                            "quantity": original_quantity,  # Use original quantity if available, otherwise 0
                            "transaction_type": transaction_type,
                            "realized_pnl": realized_pnl,
                            "is_profit": is_profit,
                            "exit_type": "quantity_zero",  # Mark as closed due to quantity=0
                            "source": "position"  # Mark as inactive position
                        })
                        logger.debug(f"Added inactive position {position.id} ({position.trading_symbol}) to trade history")
                    except Exception as pos_error:
                        logger.error(f"Error processing inactive position {getattr(position, 'id', 'unknown')}: {pos_error}", exc_info=True)
                        continue  # Skip this position and continue with others
                
                # Sort by exit time (most recent first)
                try:
                    trades_data.sort(key=lambda x: x.get("exit_time", "") or "", reverse=True)
                except Exception as sort_error:
                    logger.warning(f"Error sorting trades: {sort_error}")
                    # Continue without sorting
                
                return jsonify({
                    "trades": trades_data,
                    "summary": summary
                })
            except Exception as e:
                logger.error(f"Error getting trades: {e}", exc_info=True)
                import traceback
                error_details = traceback.format_exc()
                logger.error(f"Full traceback: {error_details}")
                return jsonify({
                    "error": str(e),
                    "details": error_details if self.debug else None
                }), 500
        
        @self.app.route('/api/positions/<int:position_id>/exit', methods=['POST'])
        def exit_position(position_id: int):
            """Manually exit a position"""
            try:
                # Get position
                positions = self.position_repo.get_active_positions()
                position = next((p for p in positions if p.id == position_id), None)
                
                if not position:
                    return jsonify({"error": "Position not found"}), 404
                
                # Get quantity from request (optional, defaults to full quantity)
                data = request.get_json() or {}
                quantity = data.get('quantity', position.quantity)
                
                # Place market order to exit
                from src.api.kite_client import KiteClient
                from src.config.config_manager import ConfigManager
                config_manager = ConfigManager()
                kite_client = KiteClient(config_manager)
                
                transaction_type = "SELL" if position.quantity > 0 else "BUY"
                order_id = kite_client.place_market_order(
                    tradingsymbol=position.trading_symbol,
                    exchange=position.exchange,
                    transaction_type=transaction_type,
                    quantity=abs(quantity),
                    product="MIS"
                )
                
                logger.info(f"Manual exit order placed: {order_id} for position {position_id}")
                return jsonify({"success": True, "order_id": order_id})
                
            except Exception as e:
                logger.error(f"Error exiting position: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/daily-stats')
        def get_daily_stats():
            """Get daily statistics"""
            try:
                from src.database.repository import DailyStatsRepository
                from src.database.models import DatabaseManager
                
                db_manager = DatabaseManager()
                daily_stats_repo = DailyStatsRepository(db_manager)
                stats = daily_stats_repo.get_or_create_today_stats()
                
                stats_data = {
                    "date": stats.date.isoformat() if stats.date else None,
                    "total_realized_pnl": stats.total_realized_pnl,
                    "total_unrealized_pnl": stats.total_unrealized_pnl,
                    "protected_profit": stats.protected_profit,
                    "number_of_trades": stats.number_of_trades,
                    "daily_loss_used": stats.daily_loss_used,
                    "daily_loss_limit": stats.daily_loss_limit,
                    "loss_limit_hit": stats.loss_limit_hit,
                    "trading_blocked": stats.trading_blocked,
                    "trailing_sl_active": stats.trailing_sl_active,
                    "trailing_sl_level": stats.trailing_sl_level
                }
                return jsonify(stats_data)
            except Exception as e:
                logger.error(f"Error getting daily stats: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/auth/status', methods=['GET'])
        def auth_status():
            """Check authentication status"""
            try:
                if not self.kite_client:
                    return jsonify({
                        "authenticated": False,
                        "error": "Kite client not initialized"
                    })
                
                is_auth = self.kite_client.is_authenticated()
                return jsonify({
                    "authenticated": is_auth,
                    "has_access_token": self.kite_client.access_token is not None
                })
            except Exception as e:
                logger.error(f"Error checking auth status: {e}")
                return jsonify({"error": str(e), "authenticated": False}), 500
        
        @self.app.route('/api/auth/authenticate', methods=['POST'])
        def authenticate():
            """Authenticate with Zerodha using request token"""
            try:
                if not self.kite_client:
                    return jsonify({
                        "success": False,
                        "error": "Kite client not initialized"
                    }), 500
                
                data = request.get_json()
                request_token = data.get('request_token', '').strip()
                
                if not request_token:
                    return jsonify({
                        "success": False,
                        "error": "Request token is required"
                    }), 400
                
                # Authenticate with Zerodha
                success = self.kite_client.authenticate(request_token)
                
                if success:
                    logger.info("User authenticated successfully via dashboard (request token)")
                    # Update Live Trader panel's kite client
                    try:
                        from src.ui.live_trader_panel import set_kite_client
                        set_kite_client(self.kite_client)
                        logger.info("Updated Live Trader panel with authenticated Kite client")
                    except Exception as e:
                        logger.warning(f"Could not update Live Trader panel Kite client: {e}")
                    
                    return jsonify({
                        "success": True,
                        "message": "Authentication successful",
                        "access_token": self.kite_client.access_token
                    })
                else:
                    return jsonify({
                        "success": False,
                        "error": "Authentication failed"
                    }), 401
                    
            except Exception as e:
                logger.error(f"Authentication error: {e}")
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
        
        @self.app.route('/api/auth/set-access-token', methods=['POST'])
        def set_access_token():
            """Set access token directly (if user already has one)"""
            try:
                if not self.kite_client:
                    return jsonify({
                        "success": False,
                        "error": "Kite client not initialized"
                    }), 500
                
                data = request.get_json()
                access_token = data.get('access_token', '').strip()
                
                if not access_token:
                    return jsonify({
                        "success": False,
                        "error": "Access token is required"
                    }), 400
                
                # Set access token directly
                try:
                    self.kite_client.set_access_token(access_token)
                except Exception as auth_error:
                    logger.error(f"Failed to set access token: {auth_error}")
                    return jsonify({
                        "success": False,
                        "error": f"Failed to set access token: {str(auth_error)}"
                    }), 400
                
                # Verify the token works by checking authentication status
                # is_authenticated() now validates the token with an API call
                if self.kite_client.is_authenticated():
                    logger.info("User connected successfully via access token")
                    # Update Live Trader panel's kite client
                    try:
                        from src.ui.live_trader_panel import set_kite_client
                        set_kite_client(self.kite_client)
                        logger.info("Updated Live Trader panel with authenticated Kite client")
                    except Exception as e:
                        logger.warning(f"Could not update Live Trader panel Kite client: {e}")
                    
                    return jsonify({
                        "success": True,
                        "message": "Connected successfully",
                        "authenticated": True
                    })
                else:
                    return jsonify({
                        "success": False,
                        "error": "Invalid or expired access token. Please generate a new token."
                    }), 401
                    
            except Exception as e:
                logger.error(f"Set access token error: {e}")
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
        
        @self.app.route('/api/debug/positions', methods=['GET'])
        def debug_positions():
            """Debug endpoint to see all positions from API"""
            try:
                if not self.kite_client:
                    return jsonify({
                        "error": "Kite client not initialized",
                        "authenticated": False
                    }), 500
                
                # Check authentication
                if not self.kite_client.is_authenticated():
                    return jsonify({
                        "error": "Not authenticated",
                        "authenticated": False
                    }), 401
                
                # Get all positions (unfiltered)
                all_positions = self.kite_client.get_all_positions()
                
                # Get filtered options positions
                options_positions = self.kite_client.get_positions()
                
                # Get database positions
                db_positions = self.position_repo.get_active_positions()
                
                return jsonify({
                    "authenticated": True,
                    "all_positions_count": len(all_positions.get('net', [])),
                    "all_positions": all_positions.get('net', []),
                    "options_positions_count": len(options_positions),
                    "options_positions": options_positions,
                    "database_positions_count": len(db_positions),
                    "database_positions": [
                        {
                            "id": p.id,
                            "trading_symbol": p.trading_symbol,
                            "exchange": p.exchange,
                            "quantity": p.quantity,
                            "entry_price": p.entry_price,
                            "current_price": p.current_price,
                            "unrealized_pnl": p.unrealized_pnl
                        }
                        for p in db_positions
                    ]
                })
            except Exception as e:
                logger.error(f"Error in debug positions: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/orders/sync', methods=['POST'])
        def sync_orders():
            """Sync orders from Zerodha and create trade records"""
            try:
                if not self.kite_client:
                    return jsonify({
                        "success": False,
                        "error": "Kite client not initialized"
                    }), 500
                
                if not self.kite_client.is_authenticated():
                    return jsonify({
                        "success": False,
                        "error": "Not authenticated"
                    }), 401
                
                # Get optional date parameter
                data = request.get_json() or {}
                date_str = data.get('date', None)
                target_date = None
                
                if date_str:
                    try:
                        target_date = datetime.fromisoformat(date_str).date()
                    except:
                        pass
                
                # Import OrderSync
                from src.api.order_sync import OrderSync
                order_sync = OrderSync(self.kite_client, self.trade_repo, self.position_repo)
                
                # Sync orders to trades
                created_trades = order_sync.sync_orders_to_trades(target_date)
                
                logger.info(f"Order sync completed: {len(created_trades)} trades created")
                
                return jsonify({
                    "success": True,
                    "message": f"Synced orders and created {len(created_trades)} trade records",
                    "trades_created": len(created_trades),
                    "trades": created_trades
                })
                
            except Exception as e:
                logger.error(f"Error syncing orders: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
        
        @self.app.route('/api/orders', methods=['GET'])
        def get_orders():
            """Get order history from Zerodha"""
            try:
                if not self.kite_client:
                    return jsonify({
                        "error": "Kite client not initialized",
                        "authenticated": False
                    }), 500
                
                if not self.kite_client.is_authenticated():
                    return jsonify({
                        "error": "Not authenticated",
                        "authenticated": False
                    }), 401
                
                # Get orders from Zerodha
                all_orders = self.kite_client.get_orders()
                
                # Filter for options orders
                options_orders = []
                for order in all_orders:
                    exchange = order.get('exchange', '').upper()
                    tradingsymbol = order.get('tradingsymbol', '').upper()
                    
                    if exchange in ['NFO', 'BFO']:
                        if 'CE' in tradingsymbol or 'PE' in tradingsymbol:
                            options_orders.append(order)
                
                # Sort by timestamp (most recent first)
                options_orders.sort(
                    key=lambda x: x.get('order_timestamp', ''),
                    reverse=True
                )
                
                return jsonify({
                    "authenticated": True,
                    "total_orders": len(all_orders),
                    "options_orders_count": len(options_orders),
                    "orders": options_orders
                })
                
            except Exception as e:
                logger.error(f"Error getting orders: {e}")
                return jsonify({"error": str(e)}), 500
    
    def _parse_order_timestamp(self, timestamp_value):
        """Parse order timestamp - handles both string and datetime objects
        
        Note: Zerodha order timestamps are already in IST (Indian Standard Time).
        The API returns timestamps that are timezone-naive but represent IST time.
        We should localize them directly to IST, NOT convert from UTC.
        """
        from src.utils.date_utils import IST
        from pytz import UTC
        
        if not timestamp_value:
            return datetime.now(IST)
        
        # If it's already a datetime object, just convert timezone
        if isinstance(timestamp_value, datetime):
            if timestamp_value.tzinfo is None:
                # Zerodha timestamps are timezone-naive but already in IST
                # Localize directly to IST (don't convert from UTC)
                return IST.localize(timestamp_value)
            else:
                # Already timezone-aware, convert to IST
                return timestamp_value.astimezone(IST)
        
        # If it's a string, parse it
        if isinstance(timestamp_value, str):
            try:
                # Try multiple formats
                order_time = None
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%d-%m-%Y %H:%M:%S']:
                    try:
                        order_time = datetime.strptime(timestamp_value, fmt)
                        break
                    except ValueError:
                        continue
                
                if order_time:
                    if order_time.tzinfo is None:
                        # Zerodha timestamps are timezone-naive but already in IST
                        # Localize directly to IST (don't convert from UTC)
                        return IST.localize(order_time)
                    else:
                        # Already timezone-aware, convert to IST
                        return order_time.astimezone(IST)
                else:
                    logger.warning(f"Could not parse timestamp: {timestamp_value}")
                    return datetime.now(IST)
            except Exception as e:
                logger.warning(f"Error parsing timestamp {timestamp_value}: {e}")
                return datetime.now(IST)
        
        # Fallback
        return datetime.now(IST)
    
    def _calculate_trades_summary(self, trades, inactive_positions):
        """Calculate summary statistics from trades and inactive positions"""
        all_pnl = []
        
        # Add P&L from completed trades
        for trade in trades:
            all_pnl.append(trade.realized_pnl)
        
        # Add P&L from inactive positions
        for position in inactive_positions:
            pnl = position.unrealized_pnl if position.unrealized_pnl else 0.0
            all_pnl.append(pnl)
        
        total_profit = sum(p for p in all_pnl if p > 0)
        total_loss = sum(p for p in all_pnl if p < 0)
        total_pnl = sum(all_pnl)
        total_trades = len(trades) + len(inactive_positions)
        profitable_trades = sum(1 for p in all_pnl if p > 0)
        loss_trades = sum(1 for p in all_pnl if p < 0)
        
        return {
            "total_profit": total_profit,
            "total_loss": total_loss,
            "total_pnl": total_pnl,
            "total_trades": total_trades,
            "profitable_trades": profitable_trades,
            "loss_trades": loss_trades
        }
    
    def run(self):
        """Run the Flask application"""
        logger.info(f"Starting dashboard server on http://{self.host}:{self.port}")
        # Disable reloader when running in thread (Windows compatibility)
        use_reloader = self.debug and threading.current_thread() is threading.main_thread()
        self.app.run(host=self.host, port=self.port, debug=self.debug, threaded=True, use_reloader=use_reloader)

