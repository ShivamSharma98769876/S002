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
    Get daily P&L aggregated by date and mode (PAPER vs LIVE).
    
    Query params:
    - days: Number of days to look back (default: 7)
    """
    try:
        days = int(request.args.get("days", 7))
        if days < 1 or days > 365:
            days = 7
        
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # Initialize data structure
        daily_data = {}
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            daily_data[date_str] = {
                "date": date_str,
                "paper_pnl": 0.0,
                "live_pnl": 0.0,
                "paper_trades": 0,
                "live_trades": 0
            }
            current_date += timedelta(days=1)
        
        # Scan all CSV files in the date range
        for date_str in daily_data.keys():
            file_path = LOG_DIR / f"live_trades_{date_str}.csv"
            
            if not file_path.exists():
                continue
            
            try:
                with file_path.open("r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        mode = row.get("mode", "PAPER").upper()
                        pnl_value = float(row.get("pnl_value", 0) or 0)
                        
                        if mode == "PAPER":
                            daily_data[date_str]["paper_pnl"] += pnl_value
                            daily_data[date_str]["paper_trades"] += 1
                        elif mode == "LIVE":
                            daily_data[date_str]["live_pnl"] += pnl_value
                            daily_data[date_str]["live_trades"] += 1
            except Exception as csv_error:
                logger.warning(f"Error reading CSV for {date_str}: {csv_error}")
                continue
        
        # Convert to sorted list
        result = sorted(daily_data.values(), key=lambda x: x["date"])
        
        return jsonify({
            "success": True,
            "data": result,
            "summary": {
                "total_days": len(result),
                "total_paper_pnl": sum(d["paper_pnl"] for d in result),
                "total_live_pnl": sum(d["live_pnl"] for d in result),
                "total_paper_trades": sum(d["paper_trades"] for d in result),
                "total_live_trades": sum(d["live_trades"] for d in result)
            }
        })
    except Exception as e:
        logger.error(f"Error fetching daily P&L: {e}", exc_info=True)
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
        log_dir = Path(__file__).parent.parent.parent / "logs"
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"{mode}_{segment}_{today}.log"
        
        # If today's file doesn't exist, try to find the most recent one
        if not log_file.exists():
            # Find most recent log file for this segment and mode
            pattern = f"{mode}_{segment}_*.log"
            matching_files = sorted(log_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            if matching_files:
                log_file = matching_files[0]
            else:
                return jsonify({
                    "success": True,
                    "logs": [],
                    "message": f"No log file found for {mode} {segment}"
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
            "mode": mode
        })
    except Exception as e:
        logger.error(f"Error fetching logs: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@live_trader_bp.route("/ps-vs-data", methods=["GET"])
def get_ps_vs_data():
    """
    Get PS/VS time series data for a specific segment.
    
    Query params:
    - segment: Segment name (NIFTY, BANKNIFTY, SENSEX) - required
    - hours: Number of hours of data to fetch (default: 10, max: 24)
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
        ps_vs_dir = LOG_DIR / "ps_vs_data"
        today = datetime.now().strftime("%Y-%m-%d")
        file_path = ps_vs_dir / f"ps_vs_{segment}_{today}.json"
        
        # If today's file doesn't exist, try to find the most recent one
        if not file_path.exists():
            pattern = f"ps_vs_{segment}_*.json"
            matching_files = sorted(ps_vs_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            if matching_files:
                file_path = matching_files[0]
            else:
                return jsonify({
                    "success": True,
                    "data": [],
                    "message": f"No PS/VS data found for {segment}"
                })
        
        # Load and filter data
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Filter to last N hours
            cutoff_time = datetime.now() - timedelta(hours=num_hours)
            filtered_data = [
                d for d in data 
                if datetime.fromisoformat(d["timestamp"]) >= cutoff_time
            ]
            
            return jsonify({
                "success": True,
                "data": filtered_data,
                "segment": segment,
                "total_points": len(filtered_data),
                "hours": num_hours
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


