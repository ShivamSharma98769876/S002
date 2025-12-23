"""
Script to start TradingView webhook server
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.api.kite_client import KiteClient
from src.config.config_manager import ConfigManager
from src.api.tradingview_webhook import start_webhook_server
from src.utils.logger import get_logger

logger = get_logger("webhook_server")


def main():
    """Main entry point"""
    try:
        # Load configuration
        config_manager = ConfigManager()
        user_config = config_manager.get_user_config()
        
        # Initialize Kite client
        kite_client = KiteClient(config_manager)
        
        # Set access token (should be in config.json)
        # Read directly from config file since it's not in UserConfig model
        import json
        config_path = config_manager.config_dir / "config.json"
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        
        access_token = config_data.get("access_token")
        if not access_token:
            logger.error("Access token not found in config. Please add it to config/config.json")
            sys.exit(1)
        
        kite_client.set_access_token(access_token)
        
        if not kite_client.is_authenticated():
            logger.error("Kite client authentication failed")
            sys.exit(1)
        
        logger.info("✅ Kite client authenticated successfully")
        
        # Get webhook server configuration
        host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
        port = int(os.getenv("WEBHOOK_PORT", "5001"))
        debug = os.getenv("WEBHOOK_DEBUG", "False").lower() == "true"
        
        # Start webhook server
        logger.info(f"Starting TradingView webhook server...")
        start_webhook_server(
            kite_client=kite_client,
            config_manager=config_manager,
            host=host,
            port=port,
            debug=debug
        )
        
    except KeyboardInterrupt:
        logger.info("Webhook server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to start webhook server: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

