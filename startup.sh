#!/bin/bash
# Azure App Service startup script (Optional)
# 
# NOTE: For Azure App Service code deployment, you can use either:
# 1. Direct: "python main.py" (Recommended - Azure auto-installs dependencies)
# 2. Script: "bash startup.sh" (Use this if you need custom setup)
#
# Azure App Service automatically:
# - Installs dependencies from requirements.txt
# - Sets PORT environment variable
# - Provides Python runtime

echo "Starting Disciplined Trader on Azure..."
echo ""

# Azure App Service automatically sets PORT environment variable
# We use 0.0.0.0 to bind to all interfaces (required for Azure)
export HOST=0.0.0.0
export DEBUG=false
export ENVIRONMENT=prod

# Note: Azure App Service automatically installs from requirements.txt
# Only install manually if you need custom behavior
# if [ -f "requirements.txt" ]; then
#     echo "Installing dependencies..."
#     pip install --quiet --no-cache-dir -r requirements.txt
# fi

# Run the application
echo "Starting application on port ${PORT}..."
python main.py

