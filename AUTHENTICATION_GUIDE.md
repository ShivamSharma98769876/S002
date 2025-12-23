# Zerodha Authentication Guide

## How to Authenticate via Dashboard UI

The dashboard supports **two authentication methods**:

### Method 1: Direct Access Token (Recommended if you have one)

If you already have an access token from a previous session:

1. **Open the Dashboard**: Go to `http://127.0.0.1:5000`

2. **Click on "🔒 Not Authenticated"** button in the header

3. **Select "Access Token (Direct)" tab** (default)

4. **Enter your access token** in the input field

5. **Click "Connect"**

6. **Done!** You'll see "✅ Authenticated" and your positions will load

### Method 2: Request Token (OAuth Flow)

If you need to generate a new access token:

#### Step 1: Get Request Token from Zerodha

1. **Go to Zerodha Kite Connect Login**:
   - Visit: `https://kite.trade/connect/login?api_key=YOUR_API_KEY`
   - Replace `YOUR_API_KEY` with your actual API key from `config/config.json`
   - Or click the link in the authentication modal (pre-filled with your API key)

2. **Login with your Zerodha credentials**

3. **Authorize the application**

4. **Copy the request token** from the redirect URL
   - The URL will look like: `http://your-redirect-url/?request_token=XXXXXX&action=login&status=success`
   - Copy the `request_token` value (the `XXXXXX` part)

#### Step 2: Authenticate in Dashboard

1. **Open the Dashboard**: Go to `http://127.0.0.1:5000`

2. **Click on "🔒 Not Authenticated"** button in the header

3. **Select "Request Token (OAuth)" tab**

4. **Enter your request token** in the input field

5. **Click "Authenticate"**

6. **Wait for confirmation**
   - If successful, you'll see "✅ Authenticated" in the header
   - The dashboard will automatically refresh to show your positions
   - **Save the access token** shown in the response for future use

## Authentication Status

The dashboard shows your authentication status in the header:
- **🔒 Not Authenticated** (Red) - Click to authenticate
- **✅ Authenticated** (Green) - You're logged in

## API Endpoints

### Check Authentication Status
```
GET /api/auth/status
```

**Response:**
```json
{
  "authenticated": true,
  "has_access_token": true
}
```

### Authenticate with Request Token
```
POST /api/auth/authenticate
Content-Type: application/json

{
  "request_token": "your_request_token_here"
}
```

**Success Response:**
```json
{
  "success": true,
  "message": "Authentication successful",
  "access_token": "your_access_token"
}
```

### Set Access Token Directly
```
POST /api/auth/set-access-token
Content-Type: application/json

{
  "access_token": "your_access_token_here"
}
```

**Success Response:**
```json
{
  "success": true,
  "message": "Connected successfully",
  "authenticated": true
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "Error message here"
}
```

## Troubleshooting

### Issue: "Not authenticated" error
**Solution**: 
1. Make sure you've entered the correct request token
2. Request tokens expire quickly - get a fresh one if it's old
3. Check that your API key and secret are correct in `config/config.json`

### Issue: "Authentication failed" error
**Possible causes:**
1. Invalid request token
2. Expired request token (get a new one)
3. Incorrect API key/secret in config
4. Network connectivity issues

**Solution:**
1. Get a fresh request token from Zerodha
2. Verify your API credentials in `config/config.json`
3. Check application logs for detailed error messages

### Issue: Authentication modal doesn't open
**Solution:**
1. Check browser console for JavaScript errors
2. Make sure JavaScript is enabled
3. Try refreshing the page

### Issue: "Kite client not initialized" error
**Solution:**
- This shouldn't happen in normal operation
- Restart the application if you see this error

## Quick Authentication Flows

### Flow 1: Direct Access Token (Fastest)
```
1. Open Dashboard (http://127.0.0.1:5000)
   ↓
2. Click "🔒 Not Authenticated"
   ↓
3. Enter Access Token (already have one)
   ↓
4. Click "Connect"
   ↓
5. Done! ✅
```

### Flow 2: Request Token (OAuth)
```
1. Get Request Token from Zerodha
   ↓
2. Open Dashboard (http://127.0.0.1:5000)
   ↓
3. Click "🔒 Not Authenticated"
   ↓
4. Switch to "Request Token (OAuth)" tab
   ↓
5. Enter Request Token
   ↓
6. Click "Authenticate"
   ↓
7. Save the Access Token for next time
   ↓
8. See "✅ Authenticated" status
   ↓
9. Dashboard shows your positions
```

## Notes

- **Access Token Method (Recommended)**:
  - Use this if you already have an access token
  - Faster - no need to go through OAuth flow
  - Access tokens are valid until revoked or expired
  - Save your access token securely for future use

- **Request Token Method (OAuth)**:
  - Use this to generate a new access token
  - Request tokens expire quickly - use them immediately
  - After authentication, save the returned access token
  - Use the saved access token next time (Method 1)

- **Token Persistence**:
  - Access tokens persist until the app restarts
  - For production, consider storing access tokens securely
  - You can reuse the same access token multiple times

- **Authentication is required** to fetch positions and place orders

## Security Reminders

- ⚠️ Never share your request tokens or access tokens
- ⚠️ Keep your API key and secret secure
- ⚠️ Don't commit tokens to version control
- ⚠️ Use HTTPS in production

