# Quick Start Guide

## Local Development

### Windows
```batch
start_local.bat
```

### Linux/Mac
```bash
chmod +x start_local.sh
./start_local.sh
```

### Manual Start
```bash
# Set environment variables
export HOST=127.0.0.1
export PORT=5000
export DEBUG=true

# Run
python main.py
```

**Access:** http://127.0.0.1:5000

---

## Azure App Service

### Quick Deploy

1. **Create App Service** (Azure Portal)
   - Runtime: Python 3.11
   - OS: Linux

2. **Set Application Settings**
   ```
   HOST = 0.0.0.0
   DEBUG = false
   ENVIRONMENT = prod
   ```

3. **Set Startup Command**
   ```
   python main.py
   ```
   (Or use `bash startup.sh` if you prefer the script)

4. **Deploy Code**
   - Use Deployment Center → Connect to Git
   - Or use Azure CLI (see DEPLOYMENT.md)

### Azure CLI Quick Deploy
```bash
az webapp create \
  --name your-app-name \
  --resource-group your-rg \
  --plan your-plan \
  --runtime "PYTHON|3.11"

az webapp config appsettings set \
  --name your-app-name \
  --resource-group your-rg \
  --settings HOST=0.0.0.0 DEBUG=false ENVIRONMENT=prod

az webapp config set \
  --name your-app-name \
  --resource-group your-rg \
  --startup-file "python main.py"
```

---

## Docker

### Build & Run
```bash
docker build -t disciplined-trader .
docker run -p 5000:5000 disciplined-trader
```

### With Environment Variables
```bash
docker run -p 5000:5000 \
  -e HOST=0.0.0.0 \
  -e PORT=5000 \
  -e DEBUG=false \
  disciplined-trader
```

---

## Environment Variables

| Variable | Local | Azure | Description |
|----------|-------|-------|-------------|
| `HOST` | `127.0.0.1` | `0.0.0.0` | Server bind address |
| `PORT` | `5000` | Auto | Server port |
| `DEBUG` | `true` | `false` | Debug mode |
| `ENVIRONMENT` | `dev` | `prod` | Environment |

---

## Troubleshooting

### Port Already in Use
```bash
# Change port
export PORT=5001
python main.py
```

### Azure Won't Start
- Check logs: `az webapp log tail --name your-app --resource-group your-rg`
- Verify startup command: `startup.sh` or `python main.py`
- Ensure `HOST=0.0.0.0` (not `127.0.0.1`)

### Health Check
```bash
curl http://localhost:5000/api/health
```

---

For detailed instructions, see [DEPLOYMENT.md](docs/DEPLOYMENT.md)

