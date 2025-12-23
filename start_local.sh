#!/bin/bash
# Local Linux/Mac startup script for Disciplined Trader
# This script sets up environment variables for local development

echo "Starting Disciplined Trader (Local Development)..."
echo ""

# Set environment variables for local development
export HOST=127.0.0.1
export PORT=5000
export DEBUG=true
export ENVIRONMENT=dev

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Run the application
echo "Starting application..."
python main.py

