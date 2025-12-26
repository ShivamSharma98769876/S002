# Automated Risk Management System for Zerodha Options Trading

An automated risk management system for option buying on Zerodha that monitors manual trades and enforces strict risk controls without interfering with trade entry/exit decisions.

## Features

- **Daily Loss Protection**: Auto-exit all positions when daily loss reaches ₹5,000 (configurable)
- **Trailing Stop Loss**: Automatic trailing SL on profits
- **Cycle-wise Profit Protection**: Lock profit from completed trades
- **Real-time Monitoring**: WebSocket-based live position tracking
- **Beautiful Dashboard**: Modern UI for monitoring and control

## Project Structure

```
disciplined-Trader/
├── src/
│   ├── api/              # Zerodha Kite Connect API integration
│   ├── database/         # Database models and operations
│   ├── config/           # Configuration management
│   ├── utils/            # Utility functions
│   ├── risk_management/  # Risk management logic
│   └── ui/               # User interface
├── tests/                # Test files
├── logs/                 # Application logs
├── data/                 # Data files and database
└── tasks/                # Development tasks and sub-tasks

```

## Setup Instructions

### 1. Create Virtual Environment

```bash
python -m venv venv

# On Windows
venv\Scripts\activate

# On Linux/Mac
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configuration

1. Copy `config/config.example.json` to `config/config.json`
2. Copy `config/admin_config.example.json` to `config/admin_config.json`
3. Update configuration files with your settings

### 4. Zerodha API Setup

1. Register your app at https://kite.trade/apps/
2. Get your API key and API secret
3. Update `config/config.json` with your credentials

### 5. Run the Application

```bash
python main.py
```

## Configuration

- **config/config.json**: User-configurable parameters
- **config/admin_config.json**: Locked risk parameters (admin only)

## Development

### Code Formatting

```bash
black src/
flake8 src/
pylint src/
```

### Running Tests

```bash
pytest tests/
pytest --cov=src tests/
```

## License

Proprietary - All rights reserved

## Disclaimer

This system manages risk only and does not make trading decisions. The system provider is not liable for trading losses. Use at your own risk.

