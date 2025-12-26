"""
Live Trader Panel Routes

Provides Flask blueprint and core routes for the Live Trader system.
Initial implementation focuses on wiring structure only (no live trading yet).
"""

from flask import Blueprint, render_template, jsonify, request, send_file
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from pathlib import Path
import csv
import re
import json

from src.api.kite_client import KiteClient
from src.live_trader.agents import LiveSegmentAgent, LiveAgentParams
from src.live_trader.execution import PaperExecutionClient, LiveExecutionClient, LOG_DIR
from src.utils.logger import get_logger
from src.config.config_manager import ConfigManager

logger = get_logger("live_trader")


# Get the template directory path
_ui_dir = Path(__file__).parent
_template_dir = _ui_dir / 'templates'

live_trader_bp = Blueprint(
    "live_trader", 
    __name__, 
    url_prefix="/live",
    template_folder=str(_template_dir)
)

_kite_client: Optional[KiteClient] = None
_dashboard_instance: Optional[Any] = None  # Reference to Dashboard instance


def get_kite_client() -> Optional[KiteClient]:
    """Get the global kite client instance used by Live Trader."""
    # First try the local client
    if _kite_client:
        return _kite_client
    # Fallback to dashboard's client if available
    if _dashboard_instance and hasattr(_dashboard_instance, 'kite_client'):
        return _dashboard_instance.kite_client
    return None


def _ensure_broker_id() -> bool:
    """Ensure BrokerID is set from authenticated user's profile or cache"""
    from src.utils.broker_context import BrokerContext
    
    # First check if already set in this thread
    if BrokerContext.get_broker_id():
        return True  # Already set
    
    # Try to get from dashboard instance's _ensure_broker_id method
    if _dashboard_instance and hasattr(_dashboard_instance, '_ensure_broker_id'):
        try:
            return _dashboard_instance._ensure_broker_id()
        except Exception as e:
            logger.debug(f"Could not ensure BrokerID via dashboard: {e}")
    
    # Fallback: try to get from kite client
    kite_client = get_kite_client()
    if kite_client and kite_client.is_authenticated():
        access_token = kite_client.access_token
        
        # Try to get from cache first (avoids API rate limits)
        if access_token:
            cached_broker_id = BrokerContext.get_broker_id_from_cache(access_token)
            if cached_broker_id:
                BrokerContext.set_broker_id(cached_broker_id)
                logger.debug(f"BrokerID retrieved from cache: {cached_broker_id}")
                return True
            
            # Try to get from profile cache
            cached_profile = BrokerContext.get_profile_from_cache(access_token)
            if cached_profile:
                broker_id = str(cached_profile.get('user_id', '') or cached_profile.get('userid', ''))
                if broker_id:
                    BrokerContext.set_broker_id(broker_id, access_token=access_token)
                    logger.debug(f"BrokerID set from cached profile: {broker_id}")
                    return True
        
        # Last resort: fetch from API (may hit rate limits)
        try:
            profile = kite_client.get_profile()
            broker_id = str(profile.get('user_id', '') or profile.get('userid', ''))
            if broker_id:
                BrokerContext.set_broker_id(broker_id, access_token=access_token)
                if access_token:
                    BrokerContext.set_profile_cache(access_token, profile)
                logger.debug(f"BrokerID set from API profile: {broker_id}")
                return True
        except Exception as e:
            logger.debug(f"Could not fetch profile to set BrokerID: {e}")
    
    return False


def set_kite_client(kite_client: Optional[KiteClient]) -> None:
    """Update the global kite client instance used by Live Trader."""
    global _kite_client
    _kite_client = kite_client
    if kite_client:
        try:
            is_auth = kite_client.is_authenticated()
            logger.info(f"✅ Kite client updated in Live Trader panel (authenticated: {is_auth})")
        except Exception as e:
            logger.warning(f"Kite client updated but error checking auth: {e}")
            logger.info(f"✅ Kite client updated in Live Trader panel (auth check failed)")
    else:
        logger.info("Kite client cleared in Live Trader panel")


class LiveAgentManager:
    """
    Manages per-segment Live Trader agents.

    This is a lightweight skeleton that we will extend in live-4/live-5/live-6.
    """

    def __init__(self):
        # In-memory status and running agents
        self._running = False
        self._segments: list[str] = []
        self._params: Dict[str, Any] = {}
        self._agents: Dict[str, LiveSegmentAgent] = {}  # Key: "{segment}_{mode}"
        self._modes: list[str] = []  # List of active modes (PAPER, LIVE, or both)

    def start(self, segments: list[str], params: Dict[str, Any]) -> None:
        """Start live trading for given segments with parameters. Supports multiple modes in parallel."""
        global _kite_client
        if not _kite_client or not _kite_client.is_authenticated():
            raise RuntimeError("Kite client not authenticated. Please authenticate first from dashboard.")

        # Stop any existing agents first
        self.stop()

        self._running = True
        self._segments = segments
        self._params = params
        self._agents = {}
        
        # Get modes to run (can be list for parallel execution)
        modes = params.get("modes", [])
        if not modes:
            # Fallback to single mode for backward compatibility
            single_mode = params.get("mode", "PAPER")
            modes = [single_mode]
        
        self._modes = modes
        
        # Validate LIVE mode requirements
        if "LIVE" in modes:
            if not _kite_client:
                raise RuntimeError("Kite client required for LIVE mode")
            logger.warning("⚠️ LIVE TRADING MODE ENABLED - REAL ORDERS WILL BE PLACED!")

        # Create agents for each segment and each mode
        for segment in segments:
            for mode in modes:
                # Create execution client for this mode
                if mode == "LIVE":
                    execution = LiveExecutionClient(_kite_client, mode="LIVE")
                else:
                    execution = PaperExecutionClient(mode="PAPER")
                
                # Create agent with same parameters for both modes
                # Both PAPER and LIVE agents use identical strategy parameters
                # Hybrid approach: time_interval for signal generation, monitoring_interval for checking frequency
                # ITM offset is now per-segment (from pyramiding_config), but keep it in params for backward compatibility
                # The actual ITM offset used will come from segment config
                agent_params = LiveAgentParams(
                    segment=segment,
                    time_interval=params.get("time_interval", "5minute"),  # Signal generation timeframe
                    rsi_period=int(params.get("rsi_period", 9)),
                    stop_loss=float(params.get("stop_loss", 50)),
                    itm_offset=float(params.get("itm_offset", 100)),  # Fallback for backward compatibility
                    initial_capital=float(params.get("initial_capital", 100000)),
                    price_strength_ema=int(params.get("price_strength_ema", 3)),
                    volume_strength_wma=int(params.get("volume_strength_wma", 21)),  # TradingView uses WMA(21)
                    trade_regime=params.get("trade_regime", "Buy"),  # Default to "Buy" for backward compatibility
                    pyramiding_config=params.get("pyramiding_config"),
                    monitoring_interval=params.get("monitoring_interval", "1minute"),  # Default to 1 minute for better entry timing
                )
                
                agent = LiveSegmentAgent(
                    kite_client=_kite_client,
                    params=agent_params,
                    execution=execution,
                    risk_limits={
                        "max_trades_per_day": params.get("max_trades_per_day", 100)
                    },
                )
                
                # Use composite key: segment_mode
                agent_key = f"{segment}_{mode}"
                self._agents[agent_key] = agent
                agent.start()
                
                logger.info(f"Started {mode} agent for {segment}")

        modes_str = " + ".join(modes)
        logger.info(f"Live Trader started in {modes_str} mode(s) for segments={segments} with params={params}")

    def stop(self) -> None:
        """Stop all live agents."""
        if self._running:
            logger.info("Stopping Live Trader agents")
        for agent in self._agents.values():
            try:
                agent.stop()
            except Exception:
                pass
        self._agents = {}
        self._running = False
        self._segments = []
        self._params = {}

    def get_status(self) -> Dict[str, Any]:
        """Return a minimal status snapshot for the UI."""
        return {
            "running": self._running,
            "segments": self._segments,
            "modes": self._modes,
            "params": self._params,
            "active_agents": len(self._agents),
        }


_agent_manager = LiveAgentManager()


@live_trader_bp.route("/", methods=["GET"], strict_slashes=False)
def live_trader_page():
    """
    Live Trader main page.
    Handles both /live and /live/
    """
    try:
        logger.info("Live Trader page requested")
        template_path = _template_dir / "live_trader.html"
        if not template_path.exists():
            logger.error(f"Template not found at: {template_path}")
            return f"Template not found at: {template_path}", 500
        return render_template("live_trader.html")
    except Exception as e:
        logger.error(f"Error rendering live_trader.html: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return f"Error loading Live Trader page: {str(e)}", 500


@live_trader_bp.route("/test", methods=["GET"])
def live_trader_test():
    """
    Simple test endpoint to verify the blueprint is registered.
    """
    return jsonify({"success": True, "message": "Live Trader blueprint is working", "route": "/live/test"})


@live_trader_bp.route("/ping", methods=["GET"])
def live_trader_ping():
    """
    Simple ping endpoint - no template needed.
    """
    return "Live Trader blueprint is working! Route: /live/ping"


@live_trader_bp.route("/status", methods=["GET"])
def live_trader_status():
    """
    Get current Live Trader status for the frontend.
    """
    try:
        status = _agent_manager.get_status()
        # Add basic API authentication info
        kite = get_kite_client()  # This now checks dashboard fallback automatically
        # Check authentication status with error handling
        kite_authenticated = False
        if kite:
            try:
                kite_authenticated = kite.is_authenticated()
                logger.info(f"✅ Kite authentication check: client exists=True, authenticated={kite_authenticated}")
            except Exception as e:
                logger.warning(f"Error checking Kite authentication: {e}")
                kite_authenticated = False
        else:
            logger.warning("⚠️ Kite client is None in Live Trader panel (checked local and dashboard fallback)")
        
        status["kite_authenticated"] = kite_authenticated
        logger.info(f"Returning Live Trader status: kite_authenticated={kite_authenticated}, running={status.get('running', False)}")
        return jsonify({"success": True, "status": status})
    except Exception as e:
        logger.error(f"Error getting Live Trader status: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/refresh-kite", methods=["POST"])
def refresh_kite_client():
    """
    Manually refresh Kite client from dashboard.
    This can be called after authentication to ensure Live Trader panel has the latest client.
    """
    try:
        # Try to get kite client from dashboard
        # We need to access it through Flask's app context or a shared registry
        # For now, return current status
        kite = get_kite_client()
        authenticated = False
        if kite:
            try:
                authenticated = kite.is_authenticated()
            except:
                pass
        
        return jsonify({
            "success": True,
            "kite_authenticated": authenticated,
            "message": f"Kite client status: {'authenticated' if authenticated else 'not authenticated'}"
        })
    except Exception as e:
        logger.error(f"Error refreshing Kite client: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/start", methods=["POST"])
def start_live_trader():
    """
    Start Live Trader in PAPER mode with given parameters.

    Expected JSON body (initial version):
    {
      "segments": ["NIFTY", "BANKNIFTY"],
      "time_interval": "5minute",
      "rsi_period": 9,
      "initial_capital": 100000,
      "stop_loss": 50,
      "itm_offset": 100
    }
    """
    try:
        data = request.get_json() or {}

        segments = data.get("segments") or []
        if isinstance(segments, str):
            segments = [segments]

        if not segments:
            return jsonify({"success": False, "error": "At least one segment must be selected"}), 400

        valid_segments = {"NIFTY", "BANKNIFTY", "SENSEX"}
        for s in segments:
            if s not in valid_segments:
                return jsonify(
                    {
                        "success": False,
                        "error": f"Invalid segment: {s}. Must be one of: {', '.join(sorted(valid_segments))}",
                    }
                ), 400

        # Load pyramiding_config from config.json if not provided in request
        pyramiding_config = data.get("pyramiding_config")
        if not pyramiding_config:
            try:
                config_manager = ConfigManager()
                config_path = config_manager.config_dir / "config.json"
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config_data = json.load(f)
                        pyramiding_config = config_data.get("pyramiding_config", {})
            except Exception as e:
                logger.warning(f"Could not load pyramiding_config from config.json: {e}, using defaults")
                pyramiding_config = {}

        params = {
            "time_interval": data.get("time_interval", "5minute"),  # Signal generation timeframe
            "monitoring_interval": data.get("monitoring_interval", "1minute"),  # Monitoring/checking interval
            "rsi_period": int(data.get("rsi_period", 9)),
            "initial_capital": float(data.get("initial_capital", 100000)),
            "stop_loss": float(data.get("stop_loss", 50)),
            "itm_offset": float(data.get("itm_offset", 100)),
            "mode": data.get("mode", "PAPER"),
            "trade_regime": data.get("trade_regime", "Buy"),  # Extract trade_regime from request
            "pyramiding_config": pyramiding_config,
        }

        _agent_manager.start(segments, params)
        return jsonify({"success": True, "status": _agent_manager.get_status()})
    except Exception as e:
        logger.error(f"Error starting Live Trader: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/config/pyramiding", methods=["GET"])
def get_pyramiding_config():
    """Get pyramiding configuration from config.json"""
    try:
        config_manager = ConfigManager()
        config_path = config_manager.config_dir / "config.json"
        if config_path.exists():
            with open(config_path, 'r') as f:
                config_data = json.load(f)
                pyramiding_config = config_data.get("pyramiding_config", {})
                return jsonify({"success": True, "pyramiding_config": pyramiding_config})
        else:
            return jsonify({"success": False, "error": "config.json not found"}), 404
    except Exception as e:
        logger.error(f"Error loading pyramiding config: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/stop", methods=["POST"])
def stop_live_trader():
    """
    Stop all Live Trader activity.
    """
    try:
        _agent_manager.stop()
        return jsonify({"success": True, "status": _agent_manager.get_status()})
    except Exception as e:
        logger.error(f"Error stopping Live Trader: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/trades", methods=["GET"])
def get_live_trades():
    """
    Get today's live trades from CSV file.
    
    Query params:
    - date: Optional date string (YYYY-MM-DD), defaults to today
    """
    try:
        date_str = request.args.get("date")
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        # Ensure LOG_DIR exists
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        file_path = LOG_DIR / f"live_trades_{date_str}.csv"
        
        # Try to restore from Azure Blob Storage if file doesn't exist
        if not file_path.exists():
            try:
                from src.utils.csv_backup import restore_csv_file
                restore_csv_file(file_path)
            except Exception as e:
                logger.debug(f"Could not restore CSV from backup: {e}")
        
        logger.debug(f"Fetching trades from: {file_path}")
        
        if not file_path.exists():
            logger.debug(f"Trade file does not exist: {file_path}")
            return jsonify({
                "success": True,
                "trades": [],
                "summary": {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "total_pnl_points": 0.0,
                    "avg_pnl": 0.0
                }
            })
        
        trades = []
        try:
            with file_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Convert numeric fields
                    for key in ["strike_price", "lots", "quantity", "entry_price", "exit_price", 
                               "stop_loss_points", "initial_sl_price", "trailing_stop_points",
                               "pnl_points", "pnl_value", "return_pct"]:
                        if key in row and row[key]:
                            try:
                                row[key] = float(row[key])
                            except (ValueError, TypeError):
                                row[key] = 0.0
                        else:
                            row[key] = 0.0
                    
                    trades.append(row)
        except Exception as csv_error:
            logger.error(f"Error reading CSV file: {csv_error}", exc_info=True)
            return jsonify({
                "success": False,
                "error": f"Error reading trade file: {str(csv_error)}"
            }), 500
        
        # Calculate summary statistics
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.get("pnl_value", 0) > 0)
        losing_trades = sum(1 for t in trades if t.get("pnl_value", 0) < 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        total_pnl = sum(t.get("pnl_value", 0) for t in trades)
        total_pnl_points = sum(t.get("pnl_points", 0) for t in trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0.0
        
        return jsonify({
            "success": True,
            "trades": trades,
            "summary": {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "win_rate": round(win_rate, 2),
                "total_pnl": round(total_pnl, 2),
                "total_pnl_points": round(total_pnl_points, 2),
                "avg_pnl": round(avg_pnl, 2)
            }
        })
    except Exception as e:
        logger.error(f"Error fetching live trades: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/trades/download", methods=["GET"])
def download_live_trades():
    """
    Download today's live trades CSV file.
    
    Query params:
    - date: Optional date string (YYYY-MM-DD), defaults to today
    """
    try:
        date_str = request.args.get("date")
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        file_path = LOG_DIR / f"live_trades_{date_str}.csv"
        
        if not file_path.exists():
            return jsonify({"success": False, "error": f"No trades found for date {date_str}"}), 404
        
        return send_file(
            str(file_path),
            as_attachment=True,
            download_name=f"live_trades_{date_str}.csv",
            mimetype="text/csv"
        )
    except Exception as e:
        logger.error(f"Error downloading live trades: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/trades/daily-pnl", methods=["GET"])
def get_daily_pnl():
    """
    Get daily P&L aggregated by date from Trades table.
    
    Query params:
    - days: Number of days to look back (default: 7)
    """
    try:
        from src.database.models import DatabaseManager, Trade
        from src.database.repository import TradeRepository
        from src.utils.broker_context import BrokerContext
        from sqlalchemy import func, and_
        from datetime import date as date_type
        
        days = int(request.args.get("days", 7))
        if days < 1 or days > 365:
            days = 7
        
        # Calculate date range - use IST timezone for accurate date calculation
        from src.utils.date_utils import get_current_ist_time
        ist_now = get_current_ist_time()
        end_date = ist_now
        start_date = end_date - timedelta(days=days - 1)  # Include today
        start_date_only = start_date.date()
        end_date_only = end_date.date()
        
        logger.debug(f"Daily P&L query: Date range {start_date_only} to {end_date_only} (IST)")
        
        # Ensure BrokerID is set before querying
        if not _ensure_broker_id():
            logger.warning("BrokerID not set for daily P&L - user may not be authenticated")
            return jsonify({
                "success": True,
                "data": [],
                "summary": {
                    "total_days": 0,
                    "total_paper_pnl": 0.0,
                    "total_live_pnl": 0.0,
                    "total_paper_trades": 0,
                    "total_live_trades": 0
                }
            })
        
        # Get broker_id from context (should be set now)
        try:
            broker_id = BrokerContext.require_broker_id()
        except ValueError as e:
            logger.warning(f"BrokerID still not set after ensure: {e}")
            return jsonify({
                "success": True,
                "data": [],
                "summary": {
                    "total_days": 0,
                    "total_paper_pnl": 0.0,
                    "total_live_pnl": 0.0,
                    "total_paper_trades": 0,
                    "total_live_trades": 0
                }
            })
        
        # Initialize database connection
        db_manager = DatabaseManager()
        session = db_manager.get_session()
        
        try:
            # Query trades grouped by date
            # Get realized P&L and trade count per day
            daily_trades = session.query(
                func.date(Trade.exit_time).label('trade_date'),
                func.sum(Trade.realized_pnl).label('total_pnl'),
                func.count(Trade.id).label('trade_count')
            ).filter(
                and_(
                    Trade.broker_id == broker_id,
                    Trade.exit_time.isnot(None),  # Only closed trades
                    func.date(Trade.exit_time) >= start_date_only,
                    func.date(Trade.exit_time) <= end_date_only
                )
            ).group_by(func.date(Trade.exit_time)).all()
            
            # Create a dictionary of date -> P&L data
            daily_data_dict = {}
            for trade_date, total_pnl, trade_count in daily_trades:
                # Handle both string (SQLite) and date object (other DBs) cases
                if isinstance(trade_date, str):
                    date_str = trade_date
                else:
                    date_str = trade_date.strftime("%Y-%m-%d")
                daily_data_dict[date_str] = {
                    "date": date_str,
                    "paper_pnl": 0.0,  # For now, we don't distinguish paper/live in trades table
                    "live_pnl": total_pnl or 0.0,  # All trades are considered "live" from DB
                    "paper_trades": 0,
                    "live_trades": int(trade_count) if trade_count else 0
                }
            
            # For today's date, also include:
            # 1. Trades from orderbook (may not be in database yet)
            # 2. Unrealized P&L from active positions
            # This ensures today's P&L includes both closed trades and open positions
            today_str = end_date_only.strftime("%Y-%m-%d")
            if today_str not in daily_data_dict:
                daily_data_dict[today_str] = {
                    "date": today_str,
                    "paper_pnl": 0.0,
                    "live_pnl": 0.0,
                    "paper_trades": 0,
                    "live_trades": 0
                }
            
            # Get today's P&L from orderbook (in case trades aren't in database yet)
            today_orderbook_pnl = 0.0
            today_orderbook_trades = 0
            try:
                # Use the global dashboard instance to access kite_client and helper methods
                if _dashboard_instance and _dashboard_instance.kite_client and _dashboard_instance.kite_client.is_authenticated():
                    # Get all orders from Zerodha
                    all_orders = _dashboard_instance.kite_client.get_orders()
                    
                    # Filter for non-equity COMPLETE orders
                    non_equity_orders = [
                        o for o in all_orders
                        if not _dashboard_instance._is_equity_trade(o.get('exchange', '').upper()) and
                           o.get('status', '').upper() == 'COMPLETE' and
                           o.get('filled_quantity', 0) > 0
                    ]
                    
                    # Group by symbol and calculate today's Net P&L from orderbook
                    orders_by_symbol = {}
                    for order in non_equity_orders:
                        symbol = order.get('tradingsymbol', '')
                        if symbol not in orders_by_symbol:
                            orders_by_symbol[symbol] = []
                        orders_by_symbol[symbol].append(order)
                    
                    # Calculate Net P&L for today using FIFO matching
                    for symbol, symbol_orders in orders_by_symbol.items():
                        # Filter by today's date
                        try:
                            symbol_orders_today = [
                                o for o in symbol_orders
                                if _dashboard_instance._parse_order_timestamp(o.get('order_timestamp', '')).date() == end_date_only
                            ]
                        except:
                            symbol_orders_today = []
                        
                        if not symbol_orders_today:
                            continue
                        
                        # Sort and match orders (FIFO)
                        symbol_orders_today.sort(key=lambda x: _dashboard_instance._parse_order_timestamp(x.get('order_timestamp', '')))
                        pending_buys = []
                        pending_sells = []
                        
                        for order in symbol_orders_today:
                            transaction_type = order.get('transaction_type', '').upper()
                            filled_qty = order.get('filled_quantity', 0)
                            avg_price = float(order.get('average_price', 0))
                            
                            if transaction_type == 'BUY':
                                remaining_qty = filled_qty
                                while remaining_qty > 0 and pending_sells:
                                    sell_order, sell_remaining = pending_sells[0]
                                    sell_price = float(sell_order.get('average_price', 0))
                                    match_qty = min(remaining_qty, sell_remaining)
                                    pnl = (sell_price - avg_price) * match_qty
                                    today_orderbook_pnl += pnl
                                    today_orderbook_trades += 1
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
                                while remaining_qty > 0 and pending_buys:
                                    buy_order, buy_remaining = pending_buys[0]
                                    buy_price = float(buy_order.get('average_price', 0))
                                    match_qty = min(remaining_qty, buy_remaining)
                                    pnl = (avg_price - buy_price) * match_qty
                                    today_orderbook_pnl += pnl
                                    today_orderbook_trades += 1
                                    remaining_qty -= match_qty
                                    buy_remaining -= match_qty
                                    if buy_remaining == 0:
                                        pending_buys.pop(0)
                                    else:
                                        pending_buys[0] = (buy_order, buy_remaining)
                                if remaining_qty > 0:
                                    pending_sells.append((order, remaining_qty))
                    
                    logger.debug(
                        f"Today's orderbook P&L: ₹{today_orderbook_pnl:.2f} "
                        f"({today_orderbook_trades} trades)"
                    )
            except Exception as orderbook_error:
                logger.debug(f"Could not get today's P&L from orderbook: {orderbook_error}")
            
            # Get active positions for today's unrealized P&L
            today_unrealized_pnl = 0.0
            today_active_trades = 0
            try:
                from src.database.repository import PositionRepository
                position_repo = PositionRepository(db_manager)
                active_positions = position_repo.get_active_positions()
                
                for position in active_positions:
                    # Check if position was entered today
                    entry_time = position.entry_time
                    if entry_time:
                        # Convert to IST if needed
                        from src.utils.date_utils import IST
                        if isinstance(entry_time, datetime):
                            if entry_time.tzinfo:
                                entry_time = entry_time.astimezone(IST)
                            else:
                                entry_time = IST.localize(entry_time)
                        elif isinstance(entry_time, str):
                            entry_time = datetime.fromisoformat(entry_time)
                            if entry_time.tzinfo is None:
                                entry_time = IST.localize(entry_time)
                        
                        if entry_time.date() == end_date_only:
                            unrealized = position.unrealized_pnl or 0.0
                            today_unrealized_pnl += unrealized
                            today_active_trades += 1
            except Exception as pos_error:
                logger.warning(f"Error getting active positions for today's P&L: {pos_error}")
            
            # Combine today's P&L: database trades + orderbook trades + unrealized
            # Prefer orderbook data if available (more up-to-date), otherwise use database
            if today_str in daily_data_dict:
                db_pnl = daily_data_dict[today_str]["live_pnl"]
                db_trades = daily_data_dict[today_str]["live_trades"]
                
                # If orderbook has data, use it (it's more current and includes all today's trades)
                # Otherwise, use database data
                if abs(today_orderbook_pnl) > 0.01 or today_orderbook_trades > 0:
                    # Orderbook has data - use it and add unrealized
                    daily_data_dict[today_str]["live_pnl"] = today_orderbook_pnl + today_unrealized_pnl
                    daily_data_dict[today_str]["live_trades"] = today_orderbook_trades + today_active_trades
                    logger.debug(
                        f"Today's ({today_str}) P&L from orderbook: ₹{today_orderbook_pnl:.2f} "
                        f"({today_orderbook_trades} trades) + unrealized: ₹{today_unrealized_pnl:.2f} "
                        f"({today_active_trades} positions) = ₹{daily_data_dict[today_str]['live_pnl']:.2f}"
                    )
                else:
                    # No orderbook data - use database data and add unrealized
                    daily_data_dict[today_str]["live_pnl"] = db_pnl + today_unrealized_pnl
                    daily_data_dict[today_str]["live_trades"] = db_trades + today_active_trades
                    logger.debug(
                        f"Today's ({today_str}) P&L from database: ₹{db_pnl:.2f} "
                        f"({db_trades} trades) + unrealized: ₹{today_unrealized_pnl:.2f} "
                        f"({today_active_trades} positions) = ₹{daily_data_dict[today_str]['live_pnl']:.2f}"
                    )
            
            # Fill in missing dates with zero values
            daily_data = []
            current_date = start_date_only
            while current_date <= end_date_only:
                date_str = current_date.strftime("%Y-%m-%d")
                if date_str in daily_data_dict:
                    daily_data.append(daily_data_dict[date_str])
                else:
                    daily_data.append({
                        "date": date_str,
                        "paper_pnl": 0.0,
                        "live_pnl": 0.0,
                        "paper_trades": 0,
                        "live_trades": 0
                    })
                current_date += timedelta(days=1)
            
            # Calculate summary
            total_paper_pnl = sum(d["paper_pnl"] for d in daily_data)
            total_live_pnl = sum(d["live_pnl"] for d in daily_data)
            total_paper_trades = sum(d["paper_trades"] for d in daily_data)
            total_live_trades = sum(d["live_trades"] for d in daily_data)
            
            return jsonify({
                "success": True,
                "data": daily_data,
                "summary": {
                    "total_days": len(daily_data),
                    "total_paper_pnl": total_paper_pnl,
                    "total_live_pnl": total_live_pnl,
                    "total_paper_trades": total_paper_trades,
                    "total_live_trades": total_live_trades
                }
            })
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error fetching daily P&L from database: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/logs", methods=["GET"])
def get_live_trader_logs():
    """
    Get recent log entries related to Live Trader for a specific segment.
    
    Query params:
    - segment: Segment name (NIFTY, BANKNIFTY, SENSEX) - required
    - mode: Mode type (PAPER or LIVE) - required
    - lines: Number of lines to fetch (default: 100, max: 1000)
    """
    try:
        segment = request.args.get("segment", "").upper()
        mode = request.args.get("mode", "").upper()
        lines = request.args.get("lines", "100")
        
        if not segment or segment not in ["NIFTY", "BANKNIFTY", "SENSEX"]:
            return jsonify({
                "success": False,
                "error": "Invalid segment. Must be NIFTY, BANKNIFTY, or SENSEX"
            }), 400
        
        if not mode or mode not in ["PAPER", "LIVE"]:
            return jsonify({
                "success": False,
                "error": "Invalid mode. Must be PAPER or LIVE"
            }), 400
        
        try:
            num_lines = int(lines)
            num_lines = min(max(num_lines, 1), 1000)  # Clamp between 1 and 1000
        except ValueError:
            num_lines = 100
        
        # Get log file path - use segment-specific log file
        # Always show the latest date's log (today or previous trading day)
        from src.utils.date_utils import get_current_ist_time
        log_dir = Path(__file__).parent.parent.parent / "logs"
        ist_now = get_current_ist_time()
        today = ist_now.strftime("%Y-%m-%d")
        today_log_file = log_dir / f"{mode}_{segment}_{today}.log"
        
        log_file = None
        log_date = None
        
        # Check if today's file exists and has data
        if today_log_file.exists():
            try:
                # Check if file has content
                with today_log_file.open("r", encoding="utf-8", errors="ignore") as f:
                    if f.read(1):  # Check if file is not empty
                        log_file = today_log_file
                        log_date = today
                        logger.debug(f"Using today's ({today}) log file for {mode} {segment}")
            except Exception as e:
                logger.warning(f"Today's log file exists but couldn't read it: {e}")
        
        # If today's log is not available, get previous trading day's log
        if not log_file:
            from datetime import timedelta
            prev_date = ist_now.date() - timedelta(days=1)
            while prev_date.weekday() >= 5:  # Skip weekends (Saturday=5, Sunday=6)
                prev_date -= timedelta(days=1)
            
            prev_date_str = prev_date.strftime("%Y-%m-%d")
            prev_log_file = log_dir / f"{mode}_{segment}_{prev_date_str}.log"
            
            if prev_log_file.exists():
                try:
                    # Check if file has content
                    with prev_log_file.open("r", encoding="utf-8", errors="ignore") as f:
                        if f.read(1):  # Check if file is not empty
                            log_file = prev_log_file
                            log_date = prev_date_str
                            logger.debug(f"Using previous trading day's ({prev_date_str}) log file for {mode} {segment}")
                except Exception as e:
                    logger.warning(f"Previous day's log file exists but couldn't read it: {e}")
            
            # Fallback: find most recent log file
            if not log_file:
                pattern = f"{mode}_{segment}_*.log"
                matching_files = sorted(log_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
                if matching_files:
                    log_file = matching_files[0]
                    # Extract date from filename
                    try:
                        log_date = log_file.stem.split('_')[-1]  # Extract date from filename
                    except:
                        pass
                    logger.debug(f"Using most recent log file: {log_file.name}")
        
        if not log_file or not log_file.exists():
            return jsonify({
                "success": True,
                "logs": [],
                "message": f"No log file found for {mode} {segment}",
                "date": None
            })
        
        # Read last N lines from log file
        log_entries = []
        try:
            with log_file.open("r", encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()
                # Get last num_lines
                recent_lines = all_lines[-num_lines:] if len(all_lines) > num_lines else all_lines
                
                for line in recent_lines:
                    line = line.strip()
                    if not line:
                        continue
                    log_entries.append(line)
        except Exception as e:
            logger.error(f"Error reading log file: {e}", exc_info=True)
            return jsonify({"success": False, "error": f"Error reading log file: {str(e)}"}), 500
        
        # Return last 100 entries (or less)
        return jsonify({
            "success": True,
            "logs": log_entries[-100:],  # Limit to 100 entries for UI
            "total_found": len(log_entries),
            "segment": segment,
            "mode": mode,
            "date": log_date,
            "file_path": str(log_file.name) if log_file else None
        })
    except Exception as e:
        logger.error(f"Error fetching logs: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/logs/download", methods=["GET"])
def download_log_file():
    """
    Download log file for a specific segment and mode.
    
    Query params:
    - segment: Segment name (NIFTY, BANKNIFTY, SENSEX) - required
    - mode: Mode type (PAPER or LIVE) - required
    """
    try:
        segment = request.args.get("segment", "").upper()
        mode = request.args.get("mode", "").upper()
        
        if not segment or segment not in ["NIFTY", "BANKNIFTY", "SENSEX"]:
            return jsonify({
                "success": False,
                "error": "Invalid segment. Must be NIFTY, BANKNIFTY, or SENSEX"
            }), 400
        
        if not mode or mode not in ["PAPER", "LIVE"]:
            return jsonify({
                "success": False,
                "error": "Invalid mode. Must be PAPER or LIVE"
            }), 400
        
        # Get log file path - use the same logic as get_live_trader_logs
        from src.utils.date_utils import get_current_ist_time
        log_dir = Path(__file__).parent.parent.parent / "logs"
        ist_now = get_current_ist_time()
        today = ist_now.strftime("%Y-%m-%d")
        today_log_file = log_dir / f"{mode}_{segment}_{today}.log"
        
        log_file = None
        
        # Check if today's file exists
        if today_log_file.exists():
            log_file = today_log_file
        else:
            # Get previous trading day's log
            from datetime import timedelta
            prev_date = ist_now.date() - timedelta(days=1)
            while prev_date.weekday() >= 5:  # Skip weekends
                prev_date -= timedelta(days=1)
            
            prev_date_str = prev_date.strftime("%Y-%m-%d")
            prev_log_file = log_dir / f"{mode}_{segment}_{prev_date_str}.log"
            
            if prev_log_file.exists():
                log_file = prev_log_file
            else:
                # Fallback: find most recent log file
                pattern = f"{mode}_{segment}_*.log"
                matching_files = sorted(log_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
                if matching_files:
                    log_file = matching_files[0]
        
        if not log_file or not log_file.exists():
            return jsonify({
                "success": False,
                "error": f"No log file found for {mode} {segment}"
            }), 404
        
        # Send file for download
        from flask import send_file
        return send_file(
            str(log_file),
            as_attachment=True,
            download_name=log_file.name,
            mimetype='text/plain'
        )
    except Exception as e:
        logger.error(f"Error downloading log file: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/ps-vs-data", methods=["GET"])
def get_ps_vs_data():
    """
    Get PS/VS time series data for a specific segment.
    
    Always shows the latest available data:
    - If today's data is available, shows it (even after market hours)
    - If today's data is not available, shows the previous trading day's data
    
    Query params:
    - segment: Segment name (NIFTY, BANKNIFTY, SENSEX) - required
    - hours: Number of hours of data to fetch (default: 10, max: 24)
              Note: This is only used for filtering today's data. Previous day's data is shown in full.
    """
    try:
        segment = request.args.get("segment", "").upper()
        hours = request.args.get("hours", "10")
        
        if not segment or segment not in ["NIFTY", "BANKNIFTY", "SENSEX"]:
            return jsonify({
                "success": False,
                "error": "Invalid segment. Must be NIFTY, BANKNIFTY, or SENSEX"
            }), 400
        
        try:
            num_hours = int(hours)
            num_hours = min(max(num_hours, 1), 24)  # Clamp between 1 and 24
        except ValueError:
            num_hours = 10
        
        # Get PS/VS data file path
        from src.live_trader.execution import LOG_DIR
        from src.utils.date_utils import get_current_ist_time
        ps_vs_dir = LOG_DIR / "ps_vs_data"
        
        # Use IST time to match the timestamp format used when saving files
        ist_now = get_current_ist_time()
        today = ist_now.strftime("%Y-%m-%d")
        today_file_path = ps_vs_dir / f"ps_vs_{segment}_{today}.json"
        
        # Check if today's file exists and has data
        use_today = False
        file_path = None
        
        if today_file_path.exists():
            try:
                with open(today_file_path, 'r', encoding='utf-8') as f:
                    today_data = json.load(f)
                if today_data and len(today_data) > 0:
                    use_today = True
                    file_path = today_file_path
                    data_date = today
                    logger.debug(f"Using today's ({today}) PS/VS data for {segment}: {len(today_data)} points")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Today's file exists but couldn't read it: {e}")
        
        # If today's data is not available, find the most recent available file
        if not use_today:
            # First, try to find the most recent file (this will get the latest date available, e.g., 26th Dec)
            pattern = f"ps_vs_{segment}_*.json"
            matching_files = sorted(ps_vs_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            
            if matching_files:
                # Use the most recent file (should be the latest date, e.g., 26th Dec)
                file_path = matching_files[0]
                # Extract date from filename
                try:
                    data_date = file_path.stem.split('_')[-1]  # Extract date from filename
                    logger.debug(f"Using most recent file: {file_path.name} (date: {data_date})")
                except Exception as e:
                    logger.warning(f"Could not extract date from filename {file_path.name}: {e}")
                    # Try to get date from file modification time as fallback
                    try:
                        mtime = file_path.stat().st_mtime
                        data_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                    except:
                        pass
            else:
                # No files found - try previous trading day as fallback
                prev_date = ist_now.date() - timedelta(days=1)
                while prev_date.weekday() >= 5:  # Skip weekends (Saturday=5, Sunday=6)
                    prev_date -= timedelta(days=1)
                
                prev_date_str = prev_date.strftime("%Y-%m-%d")
                prev_file_path = ps_vs_dir / f"ps_vs_{segment}_{prev_date_str}.json"
                
                if prev_file_path.exists():
                    try:
                        with open(prev_file_path, 'r', encoding='utf-8') as f:
                            prev_data = json.load(f)
                        if prev_data and len(prev_data) > 0:
                            file_path = prev_file_path
                            data_date = prev_date_str
                            logger.debug(f"Using previous trading day's ({prev_date_str}) PS/VS data for {segment}: {len(prev_data)} points")
                    except (json.JSONDecodeError, IOError) as e:
                        logger.warning(f"Previous day's file exists but couldn't read it: {e}")
        
        if not file_path or not file_path.exists():
            return jsonify({
                "success": True,
                "data": [],
                "message": f"No PS/VS data found for {segment}"
            })
        
        # Load data
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # If using today's data, filter by hours (user preference)
            # If using previous day's data, show all data (full trading day)
            if use_today:
                # Filter to last N hours (use IST to match timestamp format)
                cutoff_time = ist_now - timedelta(hours=num_hours)
                # Make cutoff_time timezone-naive for comparison if timestamps are naive
                if cutoff_time.tzinfo is not None:
                    cutoff_time = cutoff_time.replace(tzinfo=None)
                
                filtered_data = []
                for d in data:
                    try:
                        d_timestamp = datetime.fromisoformat(d["timestamp"])
                        # Make timezone-naive if needed for comparison
                        if d_timestamp.tzinfo is not None:
                            d_timestamp = d_timestamp.replace(tzinfo=None)
                        if d_timestamp >= cutoff_time:
                            filtered_data.append(d)
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Skipping invalid data point in PS/VS file: {e}")
                        continue
                
                logger.debug(f"Filtered today's data to last {num_hours} hours: {len(filtered_data)} points")
            else:
                # For previous day's data, return all data (full trading day)
                filtered_data = data
                logger.debug(f"Returning full previous trading day data: {len(filtered_data)} points")
            
            return jsonify({
                "success": True,
                "data": filtered_data,
                "segment": segment,
                "total_points": len(filtered_data),
                "hours": num_hours if use_today else None,
                "date": today if use_today else data_date
            })
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading PS/VS data file: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "error": f"Error reading PS/VS data file: {str(e)}"
            }), 500
            
    except Exception as e:
        logger.error(f"Error fetching PS/VS data: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


def init_live_trader_panel(app, kite_client: Optional[KiteClient] = None, dashboard_instance: Optional[Any] = None):
    """
    Initialize Live Trader panel routes and bind the shared Kite client.
    
    Args:
        app: Flask application instance
        kite_client: Kite client instance (can be None initially)
        dashboard_instance: Optional Dashboard instance for fallback access to kite_client
    """
    global _kite_client, _dashboard_instance
    _kite_client = kite_client
    _dashboard_instance = dashboard_instance
    if dashboard_instance:
        logger.info("✅ Dashboard instance stored for Kite client fallback access")
    if kite_client:
        logger.info(f"✅ Kite client initialized in Live Trader panel (authenticated: {kite_client.is_authenticated() if hasattr(kite_client, 'is_authenticated') else 'unknown'})")

    try:
        # Log blueprint info before registration
        logger.info(f"Registering Live Trader blueprint with url_prefix='/live'")
        
        app.register_blueprint(live_trader_bp)
        logger.info("✅ Live Trader panel routes registered successfully")
        
        # Log all registered routes for debugging
        logger.info("Registered Live Trader routes:")
        live_routes_found = False
        for rule in app.url_map.iter_rules():
            if 'live_trader' in rule.endpoint or '/live' in rule.rule:
                live_routes_found = True
                logger.info(f"  {rule.rule} -> {rule.endpoint} [{', '.join(rule.methods - {'HEAD', 'OPTIONS'})}]")
        
        if not live_routes_found:
            logger.warning("⚠️ No /live routes found after registration! Listing all routes:")
            for rule in app.url_map.iter_rules():
                if rule.endpoint != 'static':
                    logger.warning(f"  {rule.rule} -> {rule.endpoint}")
    except Exception as e:
        logger.error(f"❌ Failed to register Live Trader blueprint: {e}", exc_info=True)
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise


