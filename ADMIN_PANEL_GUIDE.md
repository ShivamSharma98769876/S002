# Admin Panel Guide

## How to Access Admin Panel

### Step 1: Start the Application
```bash
python main.py
```

### Step 2: Open Admin Panel in Browser
Navigate to: **`http://127.0.0.1:5000/admin/panel`**

Or click the link: [http://127.0.0.1:5000/admin/panel](http://127.0.0.1:5000/admin/panel)

### Step 3: Login
- **Default Admin Password**: `admin123`
- Enter the password and click "Login"

## What You Can Do in Admin Panel

### 1. View All Parameters
- See all risk management parameters
- View which parameters are **locked** (admin-only) or **unlocked** (user-editable)
- See current values

### 2. Modify Locked Parameters
Locked parameters that only admins can change:
- **daily_loss_limit** (₹5,000 default)
- **trailing_sl_activation** (₹5,000 default)
- **trailing_sl_increment** (₹10,000 default)
- **loss_warning_threshold** (0.9 = 90% default)
- **trading_block_enabled** (true/false)

**To Change a Locked Parameter**:
1. Find the parameter in the list
2. Enter new value in the input field
3. Enter admin password again (for security)
4. Click "Update"
5. Changes are logged in version history

### 3. View Version History
- See all changes made to parameters
- View who made the change and when
- Track old values → new values

### 4. View Audit Logs
- See all admin actions
- Track parameter changes
- Monitor system access

### 5. Change Admin Password
- Change the default admin password
- Use a strong password for production

## Default Admin Password

**⚠️ IMPORTANT**: The default password is `admin123`

**Change it immediately in production!**

To change password:
1. Login to admin panel
2. Use the "Change Password" feature (if available)
3. Or modify the code in `src/security/access_control.py`

## Admin Panel Features

### Locked Parameters (Admin Only)
These require admin password to modify:
- `daily_loss_limit` - Daily loss limit in ₹
- `trailing_sl_activation` - Profit threshold to activate trailing SL
- `trailing_sl_increment` - Increment amount for trailing SL
- `loss_warning_threshold` - Warning threshold (0-1, e.g., 0.9 = 90%)
- `trading_block_enabled` - Enable/disable trading block

### Unlocked Parameters (User Editable)
These can be modified by any authenticated user:
- `notification_channels` - Email, SMS, etc.
- `log_level` - DEBUG, INFO, WARNING, etc.
- Other user preferences

## API Endpoints

The admin panel uses these API endpoints:

- `POST /admin/login` - Admin login
- `POST /admin/logout` - Admin logout
- `GET /admin/parameters` - Get all parameters
- `PUT /admin/parameters/<name>` - Update parameter
- `GET /admin/versions` - Get version history
- `GET /admin/audit-logs` - Get audit logs
- `POST /admin/change-password` - Change admin password

## Security Notes

1. **Change Default Password**: The default `admin123` password should be changed
2. **Strong Password**: Use a strong password in production
3. **HTTPS**: Use HTTPS in production (not HTTP)
4. **Session Timeout**: Admin sessions expire after 24 hours
5. **Audit Trail**: All changes are logged

## Troubleshooting

### Can't Access Admin Panel
- Make sure application is running
- Check URL: `http://127.0.0.1:5000/admin/panel`
- Check browser console for errors

### Login Fails
- Default password is: `admin123`
- Check if password was changed
- Check browser console for error messages

### Can't Update Parameters
- Make sure you're logged in as admin
- Enter admin password when updating locked parameters
- Check audit logs for error details

## Quick Reference

| Action | URL | Method |
|--------|-----|--------|
| Admin Panel | `/admin/panel` | GET |
| Admin Login | `/admin/login` | POST |
| View Parameters | `/admin/parameters` | GET |
| Update Parameter | `/admin/parameters/<name>` | PUT |
| View Versions | `/admin/versions` | GET |
| View Audit Logs | `/admin/audit-logs` | GET |

## Example: Changing Daily Loss Limit

1. Go to `http://127.0.0.1:5000/admin/panel`
2. Login with password: `admin123`
3. Find "daily_loss_limit" parameter
4. Enter new value (e.g., `6000`)
5. Enter admin password: `admin123`
6. Click "Update"
7. Verify change in version history

## Important Reminders

- ⚠️ **Change default password** before production use
- ⚠️ **Locked parameters** affect risk management - change carefully
- ⚠️ **All changes are logged** - cannot be undone (but can be reverted)
- ⚠️ **Version history** tracks all changes for audit

