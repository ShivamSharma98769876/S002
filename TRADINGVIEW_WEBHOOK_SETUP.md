# TradingView Webhook Integration Setup Guide

This guide explains how to set up automated trading from TradingView charts to Kite (Zerodha) using webhooks.

## Overview

The system receives webhook alerts from TradingView and automatically executes trades in your Kite account. This allows you to:
- Use TradingView's powerful charting and indicators
- Automatically execute trades when your strategy conditions are met
- Combine TradingView signals with your existing risk management system

## Architecture

```
TradingView Chart → Alert → Webhook → Your Server → Kite API → Order Execution
```

## Prerequisites

1. **TradingView Account** (Pro or higher for webhook alerts)
2. **Kite Connect API** credentials configured
3. **Public URL** for webhook endpoint (use ngrok for local testing)
4. **Python dependencies** installed

## Step 1: Install Dependencies

```bash
pip install flask flask-cors
```

## Step 2: Configure Webhook Secret (Optional but Recommended)

Add a webhook secret to your `config/config.json`:

```json
{
  "webhook_secret": "your-secret-key-here"
}
```

This will enable signature verification for added security.

## Step 3: Set Up Public URL (ngrok for Local Testing)

If running locally, use ngrok to expose your webhook endpoint:

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 5001
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok.io`)

## Step 4: Start Webhook Server

Run the webhook server:

```python
from src.api.kite_client import KiteClient
from src.config.config_manager import ConfigManager
from src.api.tradingview_webhook import start_webhook_server

# Initialize Kite client
config_manager = ConfigManager()
kite_client = KiteClient(config_manager)
kite_client.set_access_token("your-access-token")

# Start webhook server
start_webhook_server(
    kite_client=kite_client,
    config_manager=config_manager,
    host="0.0.0.0",
    port=5001
)
```

Or use the provided script:

```bash
python scripts/start_webhook_server.py
```

## Step 5: Create TradingView Alert

### 5.1 Create Your Strategy in TradingView

1. Open TradingView and create a chart for NIFTY, BANKNIFTY, or SENSEX
2. Add your indicators and set up your strategy conditions
3. Create a Pine Script or use built-in alerts

### 5.2 Set Up Alert

1. Click the **Alert** button (bell icon) on your chart
2. Configure alert conditions:
   - **Condition**: Your strategy condition (e.g., "RSI crosses above 70")
   - **Alert Frequency**: "Once Per Bar Close" (recommended)
   - **Expiration**: Set as needed

3. **Webhook URL**: Enter your webhook endpoint:
   ```
   https://your-domain.com/webhook/tradingview
   ```
   Or for local testing with ngrok:
   ```
   https://abc123.ngrok.io/webhook/tradingview
   ```

### 5.3 Configure Webhook Message

In the alert settings, configure the webhook message. Use this format:

#### For BUY Signal (CE - Call Option):
```json
{
  "action": "BUY",
  "symbol": "NIFTY",
  "option_type": "CE",
  "strike": {{close}},
  "quantity": 50,
  "strategy": "My Strategy"
}
```

#### For BUY Signal (PE - Put Option):
```json
{
  "action": "BUY",
  "symbol": "NIFTY",
  "option_type": "PE",
  "strike": {{close}},
  "quantity": 50,
  "strategy": "My Strategy"
}
```

#### For SELL Signal (Exit):
```json
{
  "action": "SELL",
  "symbol": "NIFTY",
  "option_type": "CE",
  "strike": {{close}},
  "quantity": 50,
  "strategy": "My Strategy"
}
```

### 5.4 Using Pine Script Variables

In TradingView Pine Script, you can use variables in the webhook message:

```pinescript
// Example Pine Script alert
if (rsi > 70 and price_strength > volume_strength)
    alert("BUY CE", alert.freq_once_per_bar)
```

Webhook message:
```json
{
  "action": "BUY",
  "symbol": "NIFTY",
  "option_type": "CE",
  "strike": {{close}},
  "quantity": 50,
  "stop_loss": {{close}} * 0.95,
  "target": {{close}} * 1.10
}
```

## Step 6: Test the Integration

### 6.1 Test Webhook Endpoint

Use curl to test:

```bash
curl -X POST http://localhost:5001/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{
    "action": "BUY",
    "symbol": "NIFTY",
    "option_type": "CE",
    "strike": 24000,
    "quantity": 50
  }'
```

Expected response:
```json
{
  "success": true,
  "action": "BUY",
  "order_id": "12345678",
  "tradingsymbol": "NIFTY25JAN24000CE",
  "entry_price": 150.50,
  "quantity": 50,
  "message": "BUY order placed successfully"
}
```

### 6.2 Test from TradingView

1. Create a test alert in TradingView
2. Trigger the alert manually or wait for conditions
3. Check server logs for webhook receipt
4. Verify order in Kite

## Webhook Payload Format

### Required Fields

- `action`: "BUY" or "SELL"
- `symbol`: "NIFTY", "BANKNIFTY", or "SENSEX"
- `option_type`: "CE" or "PE"
- `strike`: Strike price (integer)
- `quantity`: Quantity in units (integer)

### Optional Fields

- `expiry`: Expiry date in "YYYY-MM-DD" format (defaults to nearest expiry)
- `stop_loss`: Stop loss price (float)
- `target`: Target price (float)
- `strategy`: Strategy name (string)

### Example Payloads

**Buy CE Option:**
```json
{
  "action": "BUY",
  "symbol": "NIFTY",
  "option_type": "CE",
  "strike": 24000,
  "quantity": 50,
  "expiry": "2024-01-25",
  "stop_loss": 140.0,
  "target": 180.0,
  "strategy": "RSI Divergence"
}
```

**Buy PE Option:**
```json
{
  "action": "BUY",
  "symbol": "BANKNIFTY",
  "option_type": "PE",
  "strike": 48000,
  "quantity": 25,
  "strategy": "Price Strength Crossover"
}
```

**Sell/Exit:**
```json
{
  "action": "SELL",
  "symbol": "NIFTY",
  "option_type": "CE",
  "strike": 24000,
  "quantity": 50
}
```

## Security Considerations

1. **Webhook Secret**: Always use a webhook secret for production
2. **HTTPS**: Use HTTPS for webhook endpoints (ngrok provides this)
3. **IP Whitelisting**: Consider whitelisting TradingView IPs if possible
4. **Rate Limiting**: Implement rate limiting to prevent abuse
5. **Validation**: Always validate webhook payloads before execution

## Troubleshooting

### Webhook Not Receiving Alerts

1. Check webhook URL is correct and accessible
2. Verify ngrok is running (if using local testing)
3. Check TradingView alert logs
4. Verify alert conditions are being met

### Orders Not Executing

1. Check Kite authentication is valid
2. Verify sufficient margin/balance
3. Check server logs for errors
4. Verify instrument exists for strike/expiry

### Invalid Payload Errors

1. Check JSON format is correct
2. Verify all required fields are present
3. Check data types (strike and quantity must be integers)
4. Verify symbol mapping (NIFTY, BANKNIFTY, SENSEX)

## Advanced Usage

### Multiple Strategies

You can use the `strategy` field to identify different strategies:

```json
{
  "action": "BUY",
  "symbol": "NIFTY",
  "option_type": "CE",
  "strike": 24000,
  "quantity": 50,
  "strategy": "Strategy A"
}
```

### Dynamic Strike Selection

Use TradingView's `{{close}}` or calculate ITM strikes:

```json
{
  "action": "BUY",
  "symbol": "NIFTY",
  "option_type": "CE",
  "strike": {{close}} + 100,
  "quantity": 50
}
```

### Stop Loss and Targets

The system accepts stop_loss and target but currently logs them. You can extend the handler to place GTT orders:

```json
{
  "action": "BUY",
  "symbol": "NIFTY",
  "option_type": "CE",
  "strike": 24000,
  "quantity": 50,
  "stop_loss": 140.0,
  "target": 180.0
}
```

## Integration with Existing System

The webhook handler integrates with your existing:
- Risk management system
- Position tracking
- Order execution
- Logging and notifications

All trades executed via webhook are logged and tracked the same way as manual trades.

## Support

For issues or questions:
1. Check server logs: `logs/app.log`
2. Review TradingView alert logs
3. Test webhook endpoint manually
4. Verify Kite API connectivity

## Example Pine Script Alert

```pinescript
//@version=5
indicator("Auto Trade Alert", overlay=true)

// Your strategy conditions
rsi = ta.rsi(close, 14)
price_strength = ta.ema(close, 3)
volume_strength = ta.sma(volume, 6)

buy_ce = ta.crossover(price_strength, volume_strength) and close > open
buy_pe = ta.crossunder(price_strength, volume_strength) and close < open

if buy_ce
    alert("BUY CE", alert.freq_once_per_bar)

if buy_pe
    alert("BUY PE", alert.freq_once_per_bar)
```

Webhook message for CE:
```json
{
  "action": "BUY",
  "symbol": "NIFTY",
  "option_type": "CE",
  "strike": {{close}},
  "quantity": 50
}
```

Webhook message for PE:
```json
{
  "action": "BUY",
  "symbol": "NIFTY",
  "option_type": "PE",
  "strike": {{close}},
  "quantity": 50
}
```

