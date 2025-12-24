# Azure CSV Backup Configuration

This document explains how to configure Azure Blob Storage backup for CSV files to prevent data loss in Azure App Service.

## Overview

Azure App Service has **ephemeral storage**, meaning files can be lost during:
- App restarts
- Scaling events
- Deployments
- Instance recycling

The CSV backup system automatically:
- ✅ **Backs up** CSV files to Azure Blob Storage after writing
- ✅ **Restores** CSV files from Azure Blob Storage if local file is missing
- ✅ **Works seamlessly** - no code changes needed in your trading logic
- ✅ **Optional** - gracefully falls back if Azure Blob Storage is not configured

## Setup Instructions

### Step 1: Create Azure Storage Account

1. Go to [Azure Portal](https://portal.azure.com)
2. Create a new **Storage Account**
3. Choose:
   - **Performance**: Standard
   - **Account kind**: StorageV2 (general purpose v2)
   - **Replication**: LRS (Locally Redundant Storage) is sufficient
4. Note the **Storage Account Name**

### Step 2: Get Connection String

1. In your Storage Account, go to **Access Keys**
2. Click **Show** next to one of the connection strings
3. Copy the **Connection string** (starts with `DefaultEndpointsProtocol=https;...`)

### Step 3: Configure in Azure App Service

**Option A: Azure Portal**
1. Go to your App Service → **Configuration** → **Application settings**
2. Add new setting:
   - **Name**: `AZURE_STORAGE_CONNECTION_STRING`
   - **Value**: (paste the connection string from Step 2)
3. Click **Save**

**Option B: Azure CLI**
```bash
az webapp config appsettings set \
  --name your-app-name \
  --resource-group your-rg \
  --settings AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=..."
```

### Step 4: Install Dependencies

The `azure-storage-blob` package is already in `requirements.txt`. Azure App Service will automatically install it during deployment.

For local testing:
```bash
pip install azure-storage-blob
```

## How It Works

### Automatic Backup
When a CSV file is written (e.g., `log_trade()`):
1. File is written to local filesystem: `data/live_trader/live_trades_2025-12-24.csv`
2. File is automatically backed up to Azure Blob Storage
3. If backup fails, it's logged but doesn't affect the application

### Automatic Restore
When a CSV file is read and doesn't exist locally:
1. System checks Azure Blob Storage for the file
2. If found, downloads and restores it locally
3. Application continues normally with restored file

### Container Structure
Files are stored in Azure Blob Storage container: `csv-backups`

Blob names preserve directory structure:
- `data/live_trader/live_trades_2025-12-24.csv`
- `data/live_trader/open_positions_2025-12-24.csv`

## Verification

### Check if Backup is Enabled

Look for this log message on startup:
```
✅ CSV backup to Azure Blob Storage enabled
```

If you see:
```
AZURE_STORAGE_CONNECTION_STRING not set. CSV backup disabled.
```

Then backup is disabled (but CSV files still work locally).

### Check Backed Up Files

You can verify files are backed up in Azure Portal:
1. Go to your Storage Account
2. Navigate to **Containers** → `csv-backups`
3. You should see your CSV files listed

## Cost Estimate

Azure Blob Storage pricing (approximate):
- **Storage**: ~$0.0184 per GB/month (Hot tier)
- **Transactions**: ~$0.004 per 10,000 operations

For typical usage:
- 100 CSV files × 50 KB = ~5 MB
- Monthly cost: **< $0.01** (essentially free)

## Troubleshooting

### Backup Not Working

1. **Check Connection String**
   - Verify `AZURE_STORAGE_CONNECTION_STRING` is set correctly
   - Check for typos or missing characters

2. **Check Logs**
   - Look for error messages in application logs
   - Check Azure Portal → Log Stream

3. **Verify Container**
   - Container `csv-backups` is created automatically
   - Check in Azure Portal → Storage Account → Containers

### Restore Not Working

1. **Check if File Exists in Blob Storage**
   - Verify in Azure Portal → Storage Account → Containers → csv-backups

2. **Check File Path**
   - Blob name should match: `data/live_trader/live_trades_YYYY-MM-DD.csv`
   - Path separators are normalized (Windows `\` becomes `/`)

### Local Development

CSV backup is **optional** and **disabled by default** if:
- `AZURE_STORAGE_CONNECTION_STRING` is not set
- Azure Blob Storage SDK is not installed

The application works normally without backup - CSV files are just stored locally.

## Security

- Connection string is stored as an **Application Setting** (encrypted at rest)
- Blob Storage uses **HTTPS** for all operations
- Container is **private** by default (only accessible with connection string)

## Best Practices

1. **Regular Backups**: Files are backed up automatically after each write
2. **Monitor Storage**: Check Azure Portal periodically to verify backups
3. **Test Restore**: After deployment, verify files are restored correctly
4. **Keep Connection String Secure**: Never commit to Git

## Disabling Backup

To disable CSV backup:
1. Remove `AZURE_STORAGE_CONNECTION_STRING` from Application Settings
2. Restart the app
3. CSV files will work locally only (no backup/restore)

---

**Note**: This backup system is **transparent** - your existing CSV code doesn't need any changes. Backup and restore happen automatically in the background.

