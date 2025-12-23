# Deployment Configuration Changes

This document summarizes the changes made to support both local and Azure deployments.

## Changes Made

### 1. Updated `main.py`
- Added environment variable support for `HOST`, `PORT`, and `DEBUG`
- Default behavior:
  - **Local (dev)**: `HOST=127.0.0.1`, `PORT=5000`, `DEBUG=true`
  - **Azure (prod)**: `HOST=0.0.0.0`, `PORT` from Azure, `DEBUG=false`
- Azure App Service automatically sets `PORT` environment variable

### 2. Added Health Check Endpoint
- Added `/api/health` endpoint in `src/ui/dashboard.py`
- Required for Docker health checks and Azure load balancers
- Returns HTTP 200 when healthy, 503 when unhealthy

### 3. Created Startup Scripts

#### `start_local.bat` (Windows)
- Sets local development environment variables
- Activates virtual environment if present
- Starts the application

#### `start_local.sh` (Linux/Mac)
- Same as Windows script but for Unix systems
- Make executable: `chmod +x start_local.sh`

#### `startup.sh` (Azure - Optional)
- Optional Azure App Service startup script
- Sets production environment variables
- **Note:** Azure auto-installs dependencies, so `python main.py` is usually sufficient
- Use `bash startup.sh` if you need custom setup, otherwise use `python main.py` directly

### 4. Created Docker Support

#### `Dockerfile`
- Multi-stage Python 3.11 image
- Exposes port 5000
- Includes health check
- Production-ready configuration

#### `.dockerignore`
- Excludes unnecessary files from Docker build
- Reduces image size

### 5. Created Deployment Files

#### `azure-deploy.yml`
- GitHub Actions workflow for Azure deployment
- Automatically deploys on push to main/master
- Update `AZURE_WEBAPP_NAME` before use

#### `.env.example`
- Template for environment variables
- Copy to `.env` and customize

### 6. Documentation

#### `docs/DEPLOYMENT.md`
- Comprehensive deployment guide
- Covers local, Azure, and Docker deployments
- Troubleshooting section

#### `QUICK_START.md`
- Quick reference for common tasks
- Fast commands for each environment

## Usage

### Local Development

**Windows:**
```batch
start_local.bat
```

**Linux/Mac:**
```bash
./start_local.sh
```

**Manual:**
```bash
export HOST=127.0.0.1
export PORT=5000
export DEBUG=true
python main.py
```

### Azure App Service

1. **Via Portal:**
   - Set Application Settings: `HOST=0.0.0.0`, `DEBUG=false`
   - Set Startup Command: `startup.sh`
   - Deploy code

2. **Via CLI:**
   ```bash
   az webapp config appsettings set \
     --name your-app \
     --resource-group your-rg \
     --settings HOST=0.0.0.0 DEBUG=false
   
   # Set startup command (recommended: direct Python)
   az webapp config set \
     --name your-app \
     --resource-group your-rg \
     --startup-file "python main.py"
   
   # Or use startup script (optional)
   # az webapp config set \
   #   --name your-app \
   #   --resource-group your-rg \
   #   --startup-file "bash startup.sh"
   ```

### Docker

```bash
# Build
docker build -t disciplined-trader .

# Run
docker run -p 5000:5000 disciplined-trader
```

## Environment Variables

| Variable | Local Default | Azure Default | Purpose |
|----------|---------------|---------------|---------|
| `HOST` | `127.0.0.1` | `0.0.0.0` | Server bind address |
| `PORT` | `5000` | Auto (Azure sets) | Server port |
| `DEBUG` | `true` | `false` | Flask debug mode |
| `ENVIRONMENT` | `dev` | `prod` | Environment name |

## Key Differences: Local vs Azure

| Aspect | Local | Azure |
|--------|-------|-------|
| **Host** | `127.0.0.1` (localhost only) | `0.0.0.0` (all interfaces) |
| **Port** | Fixed `5000` | Dynamic (Azure sets `PORT`) |
| **Debug** | `true` (auto-reload) | `false` (production) |
| **Startup** | `start_local.bat/sh` | `startup.sh` |
| **Access** | `http://127.0.0.1:5000` | `https://your-app.azurewebsites.net` |

## Important Notes

1. **Azure requires `HOST=0.0.0.0`** - Binding to `127.0.0.1` won't work
2. **Azure sets `PORT` automatically** - Don't hardcode it
3. **Always-on** - Enable in Azure Portal to prevent sleep
4. **File persistence** - Azure file system is ephemeral, use Blob Storage for data
5. **Health check** - `/api/health` endpoint is available for monitoring

## Next Steps

1. Test locally using `start_local.bat` or `start_local.sh`
2. Create Azure App Service
3. Configure environment variables
4. Deploy using `startup.sh`
5. Monitor using `/api/health` endpoint

For detailed instructions, see `docs/DEPLOYMENT.md`

