# Azure App Service Startup Command Guide

## Quick Answer

For **Azure App Service with code deployment** (not Docker), use:

```
python main.py
```

This is the simplest and recommended approach.

---

## Why `python main.py`?

1. ✅ **Simplest** - No script needed
2. ✅ **Azure auto-installs dependencies** - From `requirements.txt`
3. ✅ **Environment variables work** - Set in Azure Portal → Configuration
4. ✅ **Less to maintain** - One less file to manage

---

## Startup Command Options

### Option 1: Direct Python (Recommended) ⭐

**In Azure Portal:**
- Configuration → General settings → Startup Command
- Enter: `python main.py`

**Via Azure CLI:**
```bash
az webapp config set \
  --name your-app-name \
  --resource-group your-rg \
  --startup-file "python main.py"
```

### Option 2: Using Startup Script (Optional)

**In Azure Portal:**
- Configuration → General settings → Startup Command
- Enter: `bash startup.sh`

**Via Azure CLI:**
```bash
az webapp config set \
  --name your-app-name \
  --resource-group your-rg \
  --startup-file "bash startup.sh"
```

**When to use Option 2:**
- You need custom environment setup
- You need to run pre-startup commands
- You have complex initialization logic

---

## Required Application Settings

Set these in Azure Portal → Configuration → Application settings:

| Setting | Value | Required |
|---------|-------|----------|
| `HOST` | `0.0.0.0` | ✅ Yes |
| `DEBUG` | `false` | ✅ Yes |
| `ENVIRONMENT` | `prod` | Optional |
| `PORT` | (Auto-set by Azure) | ❌ No need to set |

---

## Complete Setup Example

### Step 1: Create App Service
```bash
az webapp create \
  --name disciplined-trader-app \
  --resource-group disciplined-trader-rg \
  --plan disciplined-trader-plan \
  --runtime "PYTHON|3.11"
```

### Step 2: Set Application Settings
```bash
az webapp config appsettings set \
  --name disciplined-trader-app \
  --resource-group disciplined-trader-rg \
  --settings \
    HOST=0.0.0.0 \
    DEBUG=false \
    ENVIRONMENT=prod
```

### Step 3: Set Startup Command
```bash
az webapp config set \
  --name disciplined-trader-app \
  --resource-group disciplined-trader-rg \
  --startup-file "python main.py"
```

### Step 4: Deploy Code
- Use Deployment Center in Azure Portal
- Or use Git push, FTP, or VS Code extension

---

## Important Notes

1. **`HOST=0.0.0.0` is required** - Azure won't work with `127.0.0.1`
2. **`PORT` is auto-set** - Azure provides this automatically
3. **Dependencies auto-install** - Azure reads `requirements.txt` automatically
4. **Always-on** - Enable in Configuration → General settings to prevent sleep
5. **Startup command format** - Use `python main.py` not `./main.py` or `python3 main.py`

---

## Troubleshooting

### App Won't Start

1. **Check logs:**
   ```bash
   az webapp log tail --name your-app --resource-group your-rg
   ```

2. **Verify startup command:**
   - Should be: `python main.py`
   - Not: `startup.sh` (missing `bash` or `python`)
   - Not: `./main.py` (won't work)

3. **Check application settings:**
   - `HOST` must be `0.0.0.0`
   - `DEBUG` should be `false` for production

4. **Verify requirements.txt exists:**
   - Azure needs this to install dependencies

### Port Issues

- Azure sets `PORT` automatically
- Don't hardcode port in code
- Use `os.getenv("PORT", "5000")` (already done in `main.py`)

---

## Summary

**For Azure App Service code deployment:**

✅ **Use:** `python main.py`  
❌ **Don't use:** `startup.sh` (without `bash`)  
✅ **Set:** `HOST=0.0.0.0` in Application Settings  
✅ **Let Azure:** Auto-install dependencies and set PORT

That's it! Simple and effective. 🚀

