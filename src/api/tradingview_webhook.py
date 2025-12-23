"""
TradingView Webhook Integration
Receives webhook alerts from TradingView and executes trades via Kite Connect

Setup:
1. Create a TradingView alert with webhook URL
2. Configure webhook message format (see TRADINGVIEW_WEBHOOK_SETUP.md)
3. Start the webhook server
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from typing import Dict, Any, Optional
from datetime import datetime
import json
import hmac
import hashlib
from src.api.kite_client import KiteClient
from src.live_trader.execution import LiveExecutionClient
from src.utils.logger import get_logger
from src.utils.exceptions import OrderExecutionError, AuthenticationError
from src.config.config_manager import ConfigManager

logger = get_logger("tradingview_webhook")


class TradingViewWebhookHandler:
    """
    Handles TradingView webhook alerts and executes trades
    """
    
    def __init__(self, kite_client: KiteClient, config_manager: ConfigManager):
        if not kite_client or not kite_client.is_authenticated():
            raise AuthenticationError("Kite client must be authenticated")
        
        self.kite_client = kite_client
        self.config_manager = config_manager
        self.execution_client = LiveExecutionClient(kite_client, mode="LIVE")
        
        # Get webhook secret from config file directly
        try:
            import json
            config_path = config_manager.config_dir / "config.json"
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config_data = json.load(f)
                self.webhook_secret = config_data.get("webhook_secret", "")
            else:
                self.webhook_secret = ""
        except:
            self.webhook_secret = ""
        
        # Map TradingView symbols to segments
        self.symbol_map = {
            "NIFTY": "NIFTY",
            "BANKNIFTY": "BANKNIFTY",
            "SENSEX": "SENSEX",
            "^NSEI": "NIFTY",
            "^NSEBANK": "BANKNIFTY",
            "^BSESN": "SENSEX",
        }
        
        logger.info("TradingView Webhook Handler initialized")
    
    def verify_webhook_signature(self, payload: str, signature: str) -> bool:
        """
        Verify webhook signature if secret is configured
        """
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured - skipping signature verification")
            return True
        
        try:
            expected_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}")
            return False
    
    def parse_webhook_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse TradingView webhook payload
        
        Expected format:
        {
            "action": "BUY" or "SELL",
            "symbol": "NIFTY" or "BANKNIFTY" or "SENSEX",
            "option_type": "CE" or "PE",
            "strike": 24000,
            "quantity": 50,
            "expiry": "2024-01-25" (optional),
            "stop_loss": 100.0 (optional),
            "target": 200.0 (optional),
            "strategy": "Strategy Name" (optional)
        }
        """
        try:
            # Handle both JSON and form-encoded data
            if isinstance(data, str):
                data = json.loads(data)
            
            parsed = {
                "action": data.get("action", "").upper(),
                "symbol": data.get("symbol", "").upper(),
                "option_type": data.get("option_type", "").upper(),
                "strike": int(float(data.get("strike", 0))),
                "quantity": int(data.get("quantity", 50)),
                "expiry": data.get("expiry"),
                "stop_loss": float(data.get("stop_loss", 0)) if data.get("stop_loss") else None,
                "target": float(data.get("target", 0)) if data.get("target") else None,
                "strategy": data.get("strategy", "TradingView"),
                "timestamp": datetime.now().isoformat()
            }
            
            # Map symbol to segment
            segment = self.symbol_map.get(parsed["symbol"], parsed["symbol"])
            parsed["segment"] = segment
            
            return parsed
            
        except Exception as e:
            logger.error(f"Error parsing webhook payload: {e}")
            raise ValueError(f"Invalid webhook payload: {str(e)}")
    
    def execute_trade(self, parsed_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute trade based on parsed webhook data
        """
        try:
            action = parsed_data["action"]
            segment = parsed_data["segment"]
            option_type = parsed_data["option_type"]
            strike = parsed_data["strike"]
            quantity = parsed_data["quantity"]
            expiry = parsed_data.get("expiry")
            
            if action == "BUY":
                # Place entry order
                result = self.execution_client.place_entry_order(
                    segment=segment,
                    strike=strike,
                    option_type=option_type,
                    quantity=quantity,
                    expiry=expiry
                )
                
                logger.info(
                    f"✅ TradingView BUY order executed: {result.get('tradingsymbol')} "
                    f"@ {result.get('entry_price')} | Order ID: {result.get('order_id')}"
                )
                
                return {
                    "success": True,
                    "action": "BUY",
                    "order_id": result.get("order_id"),
                    "tradingsymbol": result.get("tradingsymbol"),
                    "entry_price": result.get("entry_price"),
                    "quantity": quantity,
                    "message": f"BUY order placed successfully"
                }
            
            elif action == "SELL":
                # Square off position
                position_key = f"{segment}_{strike}_{option_type}"
                result = self.execution_client.square_off_position(
                    position_key=position_key,
                    reason=f"TradingView SELL signal"
                )
                
                logger.info(
                    f"✅ TradingView SELL order executed: P&L ₹{result.get('pnl_value', 0):.2f} "
                    f"| Order ID: {result.get('order_id')}"
                )
                
                return {
                    "success": True,
                    "action": "SELL",
                    "order_id": result.get("order_id"),
                    "exit_price": result.get("exit_price"),
                    "pnl_value": result.get("pnl_value"),
                    "pnl_points": result.get("pnl_points"),
                    "message": f"SELL order executed successfully"
                }
            
            else:
                raise ValueError(f"Unknown action: {action}. Must be BUY or SELL")
                
        except OrderExecutionError as e:
            logger.error(f"Order execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to execute order"
            }
        except Exception as e:
            logger.error(f"Unexpected error executing trade: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": "Unexpected error occurred"
            }
    
    def handle_webhook(self, data: Dict[str, Any], signature: Optional[str] = None) -> Dict[str, Any]:
        """
        Main webhook handler
        """
        try:
            # Verify signature if provided
            if signature:
                payload_str = json.dumps(data, sort_keys=True)
                if not self.verify_webhook_signature(payload_str, signature):
                    logger.warning("Webhook signature verification failed")
                    return {
                        "success": False,
                        "error": "Invalid signature",
                        "message": "Webhook signature verification failed"
                    }
            
            # Parse payload
            parsed_data = self.parse_webhook_payload(data)
            
            # Execute trade
            result = self.execute_trade(parsed_data)
            
            return result
            
        except ValueError as e:
            logger.error(f"Invalid webhook data: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Invalid webhook payload"
            }
        except Exception as e:
            logger.error(f"Error handling webhook: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": "Error processing webhook"
            }


def create_webhook_app(kite_client: KiteClient, config_manager: ConfigManager) -> Flask:
    """
    Create Flask app for TradingView webhook endpoint
    """
    app = Flask(__name__)
    CORS(app)  # Enable CORS for webhook requests
    handler = TradingViewWebhookHandler(kite_client, config_manager)
    
    @app.route('/webhook/tradingview', methods=['POST'])
    def webhook_endpoint():
        """
        TradingView webhook endpoint
        """
        try:
            # Get request data
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form.to_dict()
            
            # Get signature from header if present
            signature = request.headers.get('X-Signature', '')
            
            logger.info(f"Received TradingView webhook: {json.dumps(data, indent=2)}")
            
            # Handle webhook
            result = handler.handle_webhook(data, signature if signature else None)
            
            # Return response
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code
            
        except Exception as e:
            logger.error(f"Error in webhook endpoint: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "error": str(e),
                "message": "Internal server error"
            }), 500
    
    @app.route('/webhook/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            "status": "healthy",
            "service": "TradingView Webhook",
            "timestamp": datetime.now().isoformat()
        }), 200
    
    return app


def start_webhook_server(
    kite_client: KiteClient,
    config_manager: ConfigManager,
    host: str = "0.0.0.0",
    port: int = 5001,
    debug: bool = False
):
    """
    Start the webhook server
    """
    app = create_webhook_app(kite_client, config_manager)
    
    logger.info(f"Starting TradingView webhook server on http://{host}:{port}")
    logger.info(f"Webhook endpoint: http://{host}:{port}/webhook/tradingview")
    logger.info(f"Health check: http://{host}:{port}/webhook/health")
    
    app.run(host=host, port=port, debug=debug, threaded=True)

