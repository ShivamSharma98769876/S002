"""
Backtesting Panel Routes
Provides API endpoints for backtesting functionality
"""

from flask import Blueprint, request, jsonify, render_template
from datetime import datetime, timedelta, date
from typing import Dict, Any
from src.utils.logger import get_logger
from src.api.kite_client import KiteClient
from src.backtesting.data_fetcher import HistoricalDataFetcher
from src.backtesting.backtest_engine import BacktestEngine
import traceback

logger = get_logger("ui")

backtest_bp = Blueprint('backtest', __name__, url_prefix='/backtest')

# Store kite_client globally for route handlers
_kite_client = None


def get_kite_client():
    """Get the kite client instance"""
    return _kite_client


@backtest_bp.route('/expiries', methods=['GET'])
def get_expiries():
    """Get latest expiry dates for all segments"""
    try:
        kite_client = get_kite_client()
        if not kite_client or not kite_client.is_authenticated():
            return jsonify({"error": "Kite client not authenticated"}), 401
        
        from datetime import date
        from src.utils.logger import get_logger
        from src.utils.premium_fetcher import get_exchange_for_segment
        logger = get_logger("ui")
        
        # Map segments to base names
        segment_map = {
            "NIFTY": "NIFTY",
            "BANKNIFTY": "BANKNIFTY",
            "SENSEX": "SENSEX"
        }
        
        expiries = {}
        today = date.today()
        
        # Helper function to get date from expiry (handles both datetime and date objects)
        def get_expiry_date(expiry_obj):
            if isinstance(expiry_obj, date):
                return expiry_obj
            elif hasattr(expiry_obj, 'date'):
                return expiry_obj.date()
            else:
                return expiry_obj
        
        # Cache instruments by exchange
        instruments_cache = {}
        
        for segment, base_name in segment_map.items():
            # Get correct exchange for segment
            exchange = get_exchange_for_segment(segment)
            
            # Get instruments from the correct exchange (cache by exchange)
            if exchange not in instruments_cache:
                instruments_cache[exchange] = kite_client.kite.instruments(exchange)
            
            instruments = instruments_cache[exchange]
            
            # Filter for options (CE or PE) of this segment
            segment_options = [
                inst for inst in instruments
                if inst['name'] == base_name and
                inst['instrument_type'] in ['CE', 'PE'] and
                get_expiry_date(inst['expiry']) >= today
            ]
            
            if segment_options:
                # Get unique expiry dates
                unique_expiries = sorted(set(get_expiry_date(inst['expiry']) for inst in segment_options))
                # Get the latest (nearest) expiry
                latest_expiry = unique_expiries[0] if unique_expiries else None
                expiries[segment] = latest_expiry.strftime("%Y-%m-%d") if latest_expiry else None
            else:
                expiries[segment] = None
        
        return jsonify(expiries)
    except Exception as e:
        logger.error(f"Error fetching expiries: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    return _kite_client


@backtest_bp.route('/')
def backtest_page():
    """Backtesting page"""
    return render_template('backtest.html')


@backtest_bp.route('/run', methods=['POST'])
def run_backtest():
    """Run backtest"""
    try:
        kite_client = get_kite_client()
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        # Validate required fields
        required_fields = ['segments', 'from_date', 'to_date']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Get segments (can be single string or list)
        segments = data.get('segments', [])
        if isinstance(segments, str):
            segments = [segments]
        elif not isinstance(segments, list) or len(segments) == 0:
            return jsonify({"error": "At least one segment must be selected"}), 400
        
        # Note: Yahoo Finance doesn't require authentication, but we check anyway for consistency
        # Authentication check is optional for backtesting since we use Yahoo Finance
        if kite_client and not kite_client.is_authenticated():
            logger.warning("Kite client not authenticated, but continuing with Yahoo Finance for backtesting")
        
        # Parse dates (date-only, without time)
        try:
            from_date = datetime.strptime(data['from_date'], "%Y-%m-%d")
            to_date = datetime.strptime(data['to_date'], "%Y-%m-%d")
        except ValueError as e:
            return jsonify({"error": f"Invalid date format: {str(e)}"}), 400
        
        # Validate date range (allow same-day backtest)
        if from_date > to_date:
            return jsonify({"error": "from_date cannot be after to_date"}), 400
        
        if (to_date - from_date).days > 365:
            return jsonify({"error": "Date range cannot exceed 365 days"}), 400
        
        # Get parameters
        time_interval = data.get('time_interval', '5minute')  # Default to 5minute
        rsi_period = data.get('rsi_period', 9)
        price_strength_ema = data.get('price_strength_ema', 3)  # Default to 3
        volume_strength_wma = data.get('volume_strength_wma', 21)  # Default to 21 (matches TradingView)
        initial_capital = float(data.get('initial_capital', 100000))
        stop_loss = data.get('stop_loss')  # Optional, defaults to 50 in backtest engine
        if stop_loss is not None:
            stop_loss = float(stop_loss)
        trade_regime = data.get('trade_regime', 'Buy')  # Default to 'Buy' for backward compatibility
        # Validate trade_regime
        if trade_regime not in ['Buy', 'Sell']:
            return jsonify({"error": f"Invalid trade_regime: {trade_regime}. Must be 'Buy' or 'Sell'"}), 400
        # Get segment-specific expiries (new format)
        segment_expiries = data.get('segment_expiries', {})  # Dict of segment -> expiry
        # Legacy support: if old 'expiry' field exists, use it for all segments
        legacy_expiry = data.get('expiry')  # Optional, for backward compatibility
        
        # Validate time interval
        valid_intervals = ['3minute', '5minute', '15minute', '30minute', '1hour']
        if time_interval not in valid_intervals:
            return jsonify({"error": f"Invalid time interval: {time_interval}. Must be one of: {', '.join(valid_intervals)}"}), 400
        
        # Validate segments
        valid_segments = ['NIFTY', 'SENSEX', 'BANKNIFTY']
        for segment in segments:
            if segment not in valid_segments:
                return jsonify({"error": f"Invalid segment: {segment}. Must be one of: {', '.join(valid_segments)}"}), 400
        
        # Initialize backtesting components
        # Yahoo Finance doesn't require Kite client, but we pass it for potential future use
        data_fetcher = HistoricalDataFetcher(kite_client=kite_client)
        backtest_engine = BacktestEngine(data_fetcher)
        
        # Run backtests for each segment
        all_results = {}
        combined_trades = []
        combined_summary = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_profit": 0.0,
            "total_loss": 0.0,
            "net_pnl": 0.0,
            "max_drawdown": 0.0,
            "max_profit": 0.0,
            "initial_capital": initial_capital,
            "final_capital": 0.0  # Will accumulate final capital from all segments
        }
        
        for segment in segments:
            try:
                # Get expiry for this segment (prefer segment-specific, fallback to legacy)
                segment_expiry = segment_expiries.get(segment) if segment_expiries else None
                if not segment_expiry and legacy_expiry:
                    segment_expiry = legacy_expiry
                
                logger.info(f"Running backtest: {segment} from {from_date.date()} to {to_date.date()} with expiry {segment_expiry}")
                
                result = backtest_engine.run_backtest(
                    segment=segment,
                    from_date=from_date,
                    to_date=to_date,
                    time_interval=time_interval,
                    rsi_period=rsi_period,
                    price_strength_ema=price_strength_ema,
                    volume_strength_wma=volume_strength_wma,
                    initial_capital=initial_capital,
                    expiry=segment_expiry,
                    stop_loss=stop_loss,
                    trade_regime=trade_regime
                )
                
                if result is None:
                    logger.error(f"Backtest returned None for segment: {segment}")
                    continue
                
                # Convert result to dictionary
                result_dict = result.to_dict()
                all_results[segment] = result_dict
                
                # Combine trades (add segment info)
                for trade in result_dict.get('trades', []):
                    trade['segment'] = segment
                    combined_trades.append(trade)
                
                # Combine summary metrics
                summary = result_dict.get('summary', {})
                combined_summary['total_trades'] += summary.get('total_trades', 0)
                combined_summary['winning_trades'] += summary.get('winning_trades', 0)
                combined_summary['losing_trades'] += summary.get('losing_trades', 0)
                combined_summary['total_profit'] += summary.get('total_profit', 0.0)
                combined_summary['total_loss'] += summary.get('total_loss', 0.0)
                combined_summary['net_pnl'] += summary.get('net_pnl', 0.0)
                # For combined capital, we need to track each segment's capital separately
                # final_capital should be the sum of all segment final capitals
                segment_final_capital = summary.get('final_capital', initial_capital)
                combined_summary['final_capital'] += segment_final_capital
                
                if summary.get('max_drawdown', 0.0) > combined_summary['max_drawdown']:
                    combined_summary['max_drawdown'] = summary.get('max_drawdown', 0.0)
                
                if summary.get('max_profit', 0.0) > combined_summary['max_profit']:
                    combined_summary['max_profit'] = summary.get('max_profit', 0.0)
                
                logger.info(f"Backtest completed for {segment}: {result.total_trades} trades")
            except Exception as segment_error:
                logger.error(f"Error running backtest for segment {segment}: {segment_error}", exc_info=True)
                # Continue with other segments instead of failing completely
                all_results[segment] = {
                    "trades": [],
                    "summary": {
                        "total_trades": 0,
                        "winning_trades": 0,
                        "losing_trades": 0,
                        "total_profit": 0.0,
                        "total_loss": 0.0,
                        "net_pnl": 0.0,
                        "max_drawdown": 0.0,
                        "max_profit": 0.0,
                        "win_rate": 0.0,
                        "profit_factor": 0.0,
                        "start_date": from_date.isoformat(),
                        "end_date": to_date.isoformat(),
                        "initial_capital": initial_capital,
                        "final_capital": initial_capital,
                        "return_pct": 0.0,
                        "error": str(segment_error)
                    }
                }
        
        # Calculate combined metrics
        if combined_summary['total_trades'] > 0:
            combined_summary['win_rate'] = (combined_summary['winning_trades'] / combined_summary['total_trades']) * 100
        else:
            combined_summary['win_rate'] = 0.0
        
        if combined_summary['total_loss'] > 0:
            combined_summary['profit_factor'] = combined_summary['total_profit'] / combined_summary['total_loss']
        elif combined_summary['total_profit'] > 0:
            combined_summary['profit_factor'] = None  # Use None instead of inf for JSON compatibility
        else:
            combined_summary['profit_factor'] = 0.0
        
        # Calculate return percentage based on total initial capital
        total_initial_capital = initial_capital * len(segments)
        if total_initial_capital > 0:
            combined_summary['return_pct'] = ((combined_summary['final_capital'] - total_initial_capital) / total_initial_capital) * 100
        else:
            combined_summary['return_pct'] = 0.0
        combined_summary['start_date'] = from_date.isoformat()
        combined_summary['end_date'] = to_date.isoformat()
        
        # Sort trades by entry time (if any trades exist)
        if combined_trades:
            try:
                combined_trades.sort(key=lambda x: x.get('entry_time') or '')
            except Exception as e:
                logger.warning(f"Error sorting trades: {e}")
        
        # Create combined result
        combined_result = {
            "trades": combined_trades,
            "summary": combined_summary,
            "segment_results": all_results
        }
        
        logger.info(f"All backtests completed: {combined_summary['total_trades']} total trades across {len(segments)} segments")
        
        return jsonify({
            "success": True,
            "result": combined_result,
            "segments_tested": segments
        })
        
    except ImportError as e:
        logger.error(f"Import error: {e}", exc_info=True)
        return jsonify({
            "error": f"Required library not installed: {str(e)}. Please install yfinance: pip install yfinance"
        }), 500
    except Exception as e:
        logger.error(f"Error running backtest: {e}", exc_info=True)
        error_msg = str(e)
        # Don't include full traceback in response for security, but log it
        return jsonify({
            "error": error_msg,
            "error_type": type(e).__name__
        }), 500


@backtest_bp.route('/status', methods=['GET'])
def get_status():
    """Get backtesting system status"""
    try:
        # Check if yfinance is available
        try:
            import yfinance as yf
            yfinance_available = True
        except ImportError:
            yfinance_available = False
        
        kite_client = get_kite_client()
        authenticated = False
        if kite_client:
            authenticated = kite_client.is_authenticated()
        
        return jsonify({
            "authenticated": authenticated,
            "yfinance_available": yfinance_available,
            "status": "ready" if yfinance_available else "yfinance_not_installed",
            "data_source": "Yahoo Finance"
        })
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({"error": str(e)}), 500


@backtest_bp.route('/debug/indices', methods=['GET'])
def debug_indices():
    """Debug endpoint to list available indices"""
    try:
        kite_client = get_kite_client()
        
        if not kite_client or not kite_client.is_authenticated():
            return jsonify({
                "error": "Kite client not authenticated",
                "authenticated": False
            }), 401
        
        indices_info = {}
        
        for exchange in ['NSE', 'BSE']:
            try:
                instruments = kite_client.kite.instruments(exchange)
                indices = [
                    {
                        "name": inst.get('name'),
                        "token": inst.get('instrument_token'),
                        "exchange": inst.get('exchange'),
                        "instrument_type": inst.get('instrument_type')
                    }
                    for inst in instruments
                    if inst.get('instrument_type', '').upper() == 'INDEX'
                ]
                indices_info[exchange] = indices
                logger.info(f"Found {len(indices)} indices in {exchange}")
            except Exception as e:
                logger.error(f"Error fetching instruments from {exchange}: {e}")
                indices_info[exchange] = {"error": str(e)}
        
        return jsonify({
            "success": True,
            "indices": indices_info
        })
    except Exception as e:
        logger.error(f"Error in debug_indices: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def init_backtest_panel(app, kite_client: KiteClient = None):
    """Initialize backtesting panel routes"""
    global _kite_client
    _kite_client = kite_client
    
    # Register blueprint
    app.register_blueprint(backtest_bp)
    
    logger.info("Backtesting panel routes registered")

