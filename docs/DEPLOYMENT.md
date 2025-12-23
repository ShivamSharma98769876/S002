# Deployment Guide

This guide explains how to deploy the Disciplined Trader application to both local and Azure environments.

## Table of Contents

1. [Local Development](#local-development)
2. [Azure App Service Deployment](#azure-app-service-deployment)
3. [Docker Deployment](#docker-deployment)
4. [Environment Variables](#environment-variables)
5. [Troubleshooting](#troubleshooting)

---

## Local Development

### Windows

1. **Using Batch Script (Recommended)**
   ```batch
   start_local.bat
   ```

2. **Manual Start**
   ```batch
   set HOST=127.0.0.1
   set PORT=5000
   set DEBUG=true
   python main.py
   ```

### Linux/Mac

1. **Using Shell Script (Recommended)**
   ```bash
   chmod +x start_local.sh
   ./start_local.sh
   ```

2. **Manual Start**
   ```bash
   export HOST=127.0.0.1
   export PORT=5000
   export DEBUG=true
   python main.py
   ```

### Access the Application

- Dashboard: http://127.0.0.1:5000
- API: http://127.0.0.1:5000/api

---

## Azure App Service Deployment

### Prerequisites

1. Azure account with App Service access
2. Azure CLI installed (optional)
3. Application code ready for deployment

### Method 1: Azure Portal (Recommended for First-Time Setup)

1. **Create App Service**
   - Go to Azure Portal → Create Resource → Web App
   - Choose:
     - Runtime stack: Python 3.11
     - Operating System: Linux (recommended) or Windows
     - App Service Plan: Choose based on your needs

2. **Configure Application Settings**
   - Go to Configuration → Application settings
   - Add the following:
     ```
     HOST = 0.0.0.0
     PORT = (Azure sets this automatically, but you can override)
     DEBUG = false
     ENVIRONMENT = prod
     ```

3. **Configure Startup Command**
   - Go to Configuration → General settings
   - Set Startup Command (choose one):
     
     **Option 1: Direct Python (Recommended - Simplest)**
     ```
     python main.py
     ```
     
     **Option 2: Using startup script**
     ```
     bash startup.sh
     ```
     
     **Note:** Azure App Service automatically installs dependencies from `requirements.txt`, so Option 1 is usually sufficient.

4. **Deploy Code**
   - Use Azure Portal → Deployment Center
   - Connect to your Git repository
   - Or use FTP/VS Code extension

### Method 2: Azure CLI

```bash
# Login to Azure
az login

# Create resource group
az group create --name disciplined-trader-rg --location eastus

# Create App Service Plan
az appservice plan create \
  --name disciplined-trader-plan \
  --resource-group disciplined-trader-rg \
  --sku B1 \
  --is-linux

# Create Web App
az webapp create \
  --name disciplined-trader-app \
  --resource-group disciplined-trader-rg \
  --plan disciplined-trader-plan \
  --runtime "PYTHON|3.11"

# Configure app settings
az webapp config appsettings set \
  --name disciplined-trader-app \
  --resource-group disciplined-trader-rg \
  --settings \
    HOST=0.0.0.0 \
    DEBUG=false \
    ENVIRONMENT=prod

# Set startup command (choose one)
# Option 1: Direct Python (Recommended)
az webapp config set \
  --name disciplined-trader-app \
  --resource-group disciplined-trader-rg \
  --startup-file "python main.py"

# Option 2: Using startup script
# az webapp config set \
#   --name disciplined-trader-app \
#   --resource-group disciplined-trader-rg \
#   --startup-file "bash startup.sh"

# Deploy from local directory
az webapp deployment source config-zip \
  --name disciplined-trader-app \
  --resource-group disciplined-trader-rg \
  --src deployment.zip
```

### Method 3: GitHub Actions / Azure DevOps

1. **Set up Secrets**
   - In your repository settings, add:
     - `AZURE_WEBAPP_PUBLISH_PROFILE` (download from Azure Portal)

2. **Use the provided `azure-deploy.yml`**
   - Update `AZURE_WEBAPP_NAME` in the file
   - Push to main/master branch to trigger deployment

### Important Azure Configuration

1. **Always-on** (Recommended)
   - Configuration → General settings → Always On: Enabled
   - Prevents the app from going to sleep

2. **Health Check Endpoint**
   - Ensure `/api/health` endpoint exists (or update Dockerfile healthcheck)

3. **Logging**
   - Enable Application Logging in Azure Portal
   - Logs are available in Log Stream

4. **File Persistence**
   - Azure App Service file system is ephemeral
   - Consider using Azure Blob Storage for data files
   - Or use Azure Database for persistent storage

---

## Docker Deployment

### Build Docker Image

```bash
docker build -t disciplined-trader:latest .
```

### Run Locally

```bash
docker run -d \
  -p 5000:5000 \
  -e HOST=0.0.0.0 \
  -e PORT=5000 \
  -e DEBUG=false \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config:/app/config \
  --name disciplined-trader \
  disciplined-trader:latest
```

### Deploy to Azure Container Instances

```bash
# Create resource group
az group create --name disciplined-trader-rg --location eastus

# Create container instance
az container create \
  --resource-group disciplined-trader-rg \
  --name disciplined-trader-container \
  --image disciplined-trader:latest \
  --dns-name-label disciplined-trader \
  --ports 5000 \
  --environment-variables \
    HOST=0.0.0.0 \
    PORT=5000 \
    DEBUG=false \
    ENVIRONMENT=prod \
  --cpu 2 \
  --memory 4
```

### Deploy to Azure Container Apps

```bash
# Create Container App Environment
az containerapp env create \
  --name disciplined-trader-env \
  --resource-group disciplined-trader-rg \
  --location eastus

# Create Container App
az containerapp create \
  --name disciplined-trader-app \
  --resource-group disciplined-trader-rg \
  --environment disciplined-trader-env \
  --image disciplined-trader:latest \
  --target-port 5000 \
  --ingress external \
  --env-vars \
    HOST=0.0.0.0 \
    PORT=5000 \
    DEBUG=false \
    ENVIRONMENT=prod
```

---

## Environment Variables

### Required Variables

| Variable | Local Default | Azure Default | Description |
|----------|---------------|---------------|-------------|
| `HOST` | `127.0.0.1` | `0.0.0.0` | Server bind address |
| `PORT` | `5000` | Auto-set by Azure | Server port |
| `DEBUG` | `true` | `false` | Enable debug mode |
| `ENVIRONMENT` | `dev` | `prod` | Environment name |

### Optional Variables

- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `KITE_API_KEY`: Kite Connect API key (if not in config.json)
- `KITE_API_SECRET`: Kite Connect API secret (if not in config.json)
- `DATABASE_URL`: Database connection string (if using external DB)

### Setting Environment Variables

**Local (.env file)**
```bash
# Copy example
cp .env.example .env

# Edit .env with your values
```

**Azure Portal**
- Configuration → Application settings → Add new setting

**Azure CLI**
```bash
az webapp config appsettings set \
  --name your-app-name \
  --resource-group your-rg \
  --settings KEY=VALUE
```

---

## Troubleshooting

### Application Won't Start on Azure

1. **Check Logs**
   ```bash
   az webapp log tail --name your-app-name --resource-group your-rg
   ```

2. **Verify Startup Command**
   - Ensure `startup.sh` has execute permissions
   - Or use direct command: `python main.py`

3. **Check Port Binding**
   - Azure sets `PORT` automatically
   - Ensure app binds to `0.0.0.0`, not `127.0.0.1`

### Port Already in Use (Local)

```bash
# Find process using port 5000
# Windows
netstat -ano | findstr :5000

# Linux/Mac
lsof -i :5000

# Kill process or change PORT
export PORT=5001
```

### Database/File Access Issues

- **Azure**: Use Azure Blob Storage or Database for persistent data
- **Local**: Ensure `data/` and `logs/` directories exist and are writable

### Kite API Authentication

- Ensure `config/config.json` has correct Kite credentials
- Or set environment variables if using them

### Health Check Failing

- Verify `/api/health` endpoint exists
- Or update Dockerfile healthcheck command

---

## Best Practices

1. **Never commit `.env` file** - Use `.env.example` as template
2. **Use Azure Key Vault** for sensitive credentials in production
3. **Enable Application Insights** for monitoring in Azure
4. **Set up Auto-scaling** based on traffic
5. **Use Staging Slots** for zero-downtime deployments
6. **Regular Backups** of configuration and data files

---

## Support

For issues or questions:
1. Check application logs: `logs/app.log`
2. Check Azure Log Stream in Portal
3. Review this documentation
4. Contact support team

