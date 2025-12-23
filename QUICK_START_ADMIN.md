# Quick Start: Access Admin Panel

## 🚀 Quick Steps

### 1. Make sure application is running
```bash
python main.py
```

### 2. Open Admin Panel
**URL**: `http://127.0.0.1:5000/admin/panel`

Or from main dashboard, you can navigate to the admin panel.

### 3. Login
- **Password**: `admin123` (default)
- Click "Login"

### 4. Change Configuration
- View all parameters
- Modify locked parameters (requires admin password)
- View version history
- Check audit logs

## 📋 Default Admin Password

**Password**: `admin123`

⚠️ **Change this password in production!**

## 🔒 Locked Parameters (Admin Only)

These can only be changed by admin:
- `daily_loss_limit` - Daily loss limit (₹5,000 default)
- `trailing_sl_activation` - Trailing SL activation threshold (₹5,000)
- `trailing_sl_increment` - Trailing SL increment (₹10,000)
- `loss_warning_threshold` - Warning threshold (0.9 = 90%)
- `trading_block_enabled` - Trading block enabled (true/false)

## 📝 How to Change a Parameter

1. **Login** to admin panel
2. **Find** the parameter you want to change
3. **Enter** new value
4. **Enter** admin password (for locked parameters)
5. **Click** "Update"
6. **Verify** in version history

## 🔗 Direct Links

- **Main Dashboard**: http://127.0.0.1:5000
- **Admin Panel**: http://127.0.0.1:5000/admin/panel

## 💡 Tips

- All changes are logged in audit trail
- Version history shows all previous values
- Locked parameters require admin password to change
- Unlocked parameters can be changed by any user

