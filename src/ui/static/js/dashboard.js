// Dashboard JavaScript for real-time updates

let updateInterval;
let positionsUpdateInterval; // Separate interval for positions and P&L
let cumulativePnlInterval; // Interval for cumulative P&L
let dailyFullUpdateInterval; // Interval for daily full update check
let connectivityInterval; // Interval for connectivity checks
let authStatusInterval; // Interval for auth status checks
let userProfileInterval; // Interval for user profile updates
let pnlCalendarData = {};
let pnlFilters = {
    segment: 'all',
    type: 'combined',
    symbol: '',
    dateRange: null
};

// Track authentication state
let isAuthenticated = false;

// Define showAuthModal early so it's available for inline onclick handlers
// This must be defined before the HTML tries to use it
window.showAuthModal = function showAuthModal() {
    console.log('[Auth] Attempting to show auth modal');
    const modal = document.getElementById('authModal');
    if (!modal) {
        console.error('[Auth] Auth modal element not found!');
        alert('Authentication modal not found. Please refresh the page.');
        return;
    }
    
    console.log('[Auth] Modal element found, displaying...');
    
    // Remove any inline display:none that might be set
    modal.removeAttribute('style');
    
    // Set all styles explicitly
    modal.style.display = 'flex';
    modal.style.position = 'fixed';
    modal.style.top = '0';
    modal.style.left = '0';
    modal.style.width = '100%';
    modal.style.height = '100%';
    modal.style.backgroundColor = 'rgba(0,0,0,0.5)';
    modal.style.zIndex = '10000';
    modal.style.justifyContent = 'center';
    modal.style.alignItems = 'center';
    modal.style.visibility = 'visible';
    modal.style.opacity = '1';
    
    // Ensure modal content is visible and prevent clicks from closing modal
    const modalContent = modal.querySelector('div');
    if (modalContent) {
        modalContent.style.display = 'block';
        console.log('[Auth] Modal content displayed');
        
        // Prevent clicks inside modal content from closing the modal
        modalContent.onclick = function(e) {
            e.stopPropagation();
        };
    }
    
    // Add click handler to close modal when clicking backdrop (but not the modal content)
    modal.onclick = function(e) {
        if (e.target === modal) {
            console.log('[Auth] Clicked backdrop, closing modal');
            hideAuthModal();
        }
    };
    
    // Pre-populate form fields with stored values (from localStorage and server)
    populateAuthFormFields();
    
    // Update Kite Connect link with API key if available
    updateKiteConnectLink();
    
    console.log('[Auth] Auth modal should now be visible');
    console.log('[Auth] Modal computed style:', window.getComputedStyle(modal).display);
    
    // Force a reflow to ensure display
    void modal.offsetHeight;
};

// LocalStorage functions for credential storage
function saveAuthCredentials(apiKey, apiSecret, accessToken, requestToken = null) {
    try {
        if (apiKey) localStorage.setItem('zerodha_api_key', apiKey);
        if (apiSecret) localStorage.setItem('zerodha_api_secret', apiSecret);
        if (accessToken) localStorage.setItem('zerodha_access_token', accessToken);
        if (requestToken) localStorage.setItem('zerodha_request_token', requestToken);
        console.log('[Auth] Credentials saved to localStorage');
    } catch (error) {
        console.error('[Auth] Error saving credentials:', error);
    }
}

function getAuthCredentials() {
    try {
        return {
            apiKey: localStorage.getItem('zerodha_api_key') || '',
            apiSecret: localStorage.getItem('zerodha_api_secret') || '',
            accessToken: localStorage.getItem('zerodha_access_token') || '',
            requestToken: localStorage.getItem('zerodha_request_token') || ''
        };
    } catch (error) {
        console.error('[Auth] Error reading credentials:', error);
        return { apiKey: '', apiSecret: '', accessToken: '', requestToken: '' };
    }
}

function clearAuthCredentials() {
    try {
        localStorage.removeItem('zerodha_api_key');
        localStorage.removeItem('zerodha_api_secret');
        localStorage.removeItem('zerodha_access_token');
        localStorage.removeItem('zerodha_request_token');
        console.log('[Auth] Credentials cleared from localStorage');
    } catch (error) {
        console.error('[Auth] Error clearing credentials:', error);
    }
}

// Try to auto-connect if credentials are available
async function tryAutoConnect() {
    const credentials = getAuthCredentials();
    
    // If we have API key, secret, and access token, try to auto-connect
    if (credentials.apiKey && credentials.apiSecret && credentials.accessToken) {
        console.log('[Auth] Auto-connecting with stored credentials...');
        
        // Check if already authenticated
        try {
            const statusResponse = await fetch('/api/auth/status');
            if (statusResponse.ok) {
                const statusData = await statusResponse.json();
                if (statusData.authenticated) {
                    console.log('[Auth] Already authenticated, skipping auto-connect');
                    return;
                }
            }
        } catch (e) {
            // Continue with auto-connect
        }
        
        // Try to connect with stored credentials
        try {
            const response = await fetch('/api/auth/set-access-token', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    api_key: credentials.apiKey,
                    api_secret: credentials.apiSecret,
                    access_token: credentials.accessToken
                })
            });
            
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    console.log('[Auth] Auto-connected successfully');
                    hideAuthModal();
                    await checkAuthStatus();
                    if (typeof addNotification === 'function') {
                        addNotification('Auto-connected with saved credentials', 'success');
                    }
                }
            }
        } catch (error) {
            console.log('[Auth] Auto-connect failed, user will need to authenticate manually:', error);
        }
    }
}

// Pre-populate authentication form fields with stored values
async function populateAuthFormFields() {
    // First, try to get from localStorage (fastest)
    const localCredentials = getAuthCredentials();
    
    // Then try to get from server (may have more recent values)
    let serverDetails = {};
    try {
        const response = await fetch('/api/auth/details');
        if (response.ok) {
            const data = await safeJsonResponse(response);
            if (data.success && data.details) {
                serverDetails = data.details;
            }
        }
    } catch (error) {
        console.error('Error fetching auth details from server:', error);
    }
    
    // Use server values if available, otherwise fall back to localStorage
    const apiKey = serverDetails.api_key || localCredentials.apiKey;
    const apiSecret = serverDetails.api_secret || localCredentials.apiSecret;
    const accessToken = serverDetails.access_token || localCredentials.accessToken;
    const requestToken = serverDetails.request_token && serverDetails.request_token !== 'Not stored after authentication' 
        ? serverDetails.request_token 
        : localCredentials.requestToken;
    
    // Populate API Key field (for Request Token form)
    const apiKeyField = document.getElementById('apiKey');
    if (apiKeyField && apiKey) {
        apiKeyField.value = apiKey;
    }
    
    // Populate API Secret field (for Request Token form)
    const apiSecretField = document.getElementById('apiSecret');
    if (apiSecretField && apiSecret) {
        apiSecretField.value = apiSecret;
    }
    
    // Populate Request Token field
    const requestTokenField = document.getElementById('requestToken');
    if (requestTokenField && requestToken) {
        requestTokenField.value = requestToken;
    }
    
    // Populate Access Token form fields (for direct access token method)
    const accessTokenApiKeyField = document.getElementById('accessTokenApiKey');
    if (accessTokenApiKeyField && apiKey) {
        accessTokenApiKeyField.value = apiKey;
    }
    
    const accessTokenApiSecretField = document.getElementById('accessTokenApiSecret');
    if (accessTokenApiSecretField && apiSecret) {
        accessTokenApiSecretField.value = apiSecret;
    }
    
    const accessTokenField = document.getElementById('accessToken');
    if (accessTokenField && accessToken) {
        accessTokenField.value = accessToken;
    }
}

// Update Kite Connect link with API key
function updateKiteConnectLink() {
    const apiKeyField = document.getElementById('apiKey');
    const kiteConnectLink = document.getElementById('kiteConnectLink');
    
    if (apiKeyField && kiteConnectLink) {
        // Set initial link if API key is already populated
        if (apiKeyField.value.trim()) {
            kiteConnectLink.href = `https://kite.trade/connect/login?api_key=${apiKeyField.value.trim()}`;
        }
        
        // Update link when API key changes
        apiKeyField.addEventListener('input', function() {
            const apiKey = this.value.trim();
            if (apiKey) {
                kiteConnectLink.href = `https://kite.trade/connect/login?api_key=${apiKey}`;
            } else {
                kiteConnectLink.href = 'https://kite.trade/connect/login';
            }
        });
    }
}

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    initializePnlCalendar();
    initializeCumulativePnlChart();
    setupEventListeners();
    
    // Check auth status first, then start updates only if authenticated
    checkAuthStatus().then(() => {
        if (isAuthenticated) {
            startUpdates();
        } else {
            // Not authenticated - ensure auth button is visible and clickable
            const authStatusEl = document.getElementById('authStatus');
            if (authStatusEl) {
                authStatusEl.style.display = 'block';
                authStatusEl.onclick = showAuthModal;
                authStatusEl.style.cursor = 'pointer';
                console.log('[Auth] Auth button visible and ready');
            }
        }
    }).catch(error => {
        console.error('[Auth] Error checking auth status:', error);
        // On error, ensure auth button is visible
        const authStatusEl = document.getElementById('authStatus');
        if (authStatusEl) {
            authStatusEl.style.display = 'block';
            authStatusEl.style.cursor = 'pointer';
            authStatusEl.removeAttribute('onclick');
            authStatusEl.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                console.log('[Auth] Auth button clicked (error case)');
                showAuthModal();
            }, { once: false });
        }
    });
});

// Setup event listeners
function setupEventListeners() {
    const tradeDateFilter = document.getElementById('tradeDateFilter');
    if (tradeDateFilter) {
        // Set default date to today
        tradeDateFilter.value = new Date().toISOString().split('T')[0];
        tradeDateFilter.addEventListener('change', updateTrades);
    }
    
    const showAllTrades = document.getElementById('showAllTrades');
    if (showAllTrades) {
        showAllTrades.addEventListener('change', toggleTradeFilter);
        // Initialize: show only current day trades (checkbox unchecked by default)
        // Date filter is already visible and set to today
    }
}

// Helper function to safely parse JSON responses
async function safeJsonResponse(response) {
    const contentType = response.headers.get('content-type');
    if (!contentType || !contentType.includes('application/json')) {
        const text = await response.text();
        console.error('Non-JSON response received:', {
            status: response.status,
            statusText: response.statusText,
            contentType: contentType,
            preview: text.substring(0, 200)
        });
        throw new Error(`Server returned ${response.status} ${response.statusText}. Expected JSON but got ${contentType || 'unknown'}`);
    }
    return await response.json();
}

// Request throttling - prevent too many simultaneous requests
let pendingRequests = new Set();
let lastRequestTime = {};

async function throttledFetch(url, options = {}, minInterval = 500) {
    // Check if request was made recently
    const now = Date.now();
    const lastTime = lastRequestTime[url] || 0;
    if (now - lastTime < minInterval) {
        console.log(`[Throttle] Skipping ${url} - too soon after last request`);
        return null;
    }
    
    // If request is already pending, skip
    if (pendingRequests.has(url)) {
        console.log(`[Throttle] Skipping ${url} - already pending`);
        return null;
    }
    
    pendingRequests.add(url);
    lastRequestTime[url] = now;
    
    try {
        const response = await fetch(url, options);
        return response;
    } finally {
        // Remove from pending after response
        setTimeout(() => {
            pendingRequests.delete(url);
        }, minInterval);
    }
}

// Cache for cumulative P&L (only Day refreshes frequently)
let cumulativePnlCache = {
    data: null,
    lastFullUpdate: null,
    lastDayUpdate: null
};

// Start real-time updates (only called after authentication)
function startUpdates() {
    if (!isAuthenticated) {
        console.log('[Updates] Cannot start updates: not authenticated');
        return;
    }
    
    console.log('[Updates] Starting updates - authenticated');
    
    // Clear any existing intervals first
    stopUpdates();
    
    // Initial update
    updateAll();
    
    // Set up intervals - REDUCED FREQUENCY to prevent "Too many requests"
    updateInterval = setInterval(() => {
        if (isAuthenticated) {
            updateAll();
        } else {
            console.log('[Updates] Stopping updates - no longer authenticated');
            stopUpdates();
        }
    }, 10000); // Update every 10 seconds (was 2 seconds)
    
    // Daily Loss Used is updated via updateStatus() which is called in updateAll()
    
    // Update cumulative P&L - Day every 5 minutes, others once per day
    updateCumulativePnl(true); // Initial full update
    cumulativePnlInterval = setInterval(() => {
        if (isAuthenticated) {
            updateCumulativePnl(false); // Day-only update
        } else {
            stopUpdates();
        }
    }, 5 * 60 * 1000); // Every 5 minutes for Day
    
    // Full update check once per day (check every hour)
    dailyFullUpdateInterval = setInterval(() => {
        if (isAuthenticated) {
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            if (!cumulativePnlCache.lastFullUpdate || cumulativePnlCache.lastFullUpdate < today) {
                console.log('[Cumulative P&L] Daily full update triggered');
                updateCumulativePnl(true);
            }
        }
    }, 60 * 60 * 1000); // Check every hour
    
    // Check connectivity status every 15 seconds (was 2 seconds)
    checkConnectivity();
    connectivityInterval = setInterval(() => {
        if (isAuthenticated) {
            checkConnectivity();
        } else {
            stopUpdates();
        }
    }, 15000);
    
    // Check auth status every 60 seconds (was 10 seconds)
    authStatusInterval = setInterval(checkAuthStatus, 60000);
    
    // Update user profile every 5 minutes (was 30 seconds)
    updateUserProfile();
    userProfileInterval = setInterval(() => {
        if (isAuthenticated) {
            updateUserProfile();
        } else {
            stopUpdates();
        }
    }, 5 * 60 * 1000);
}

// Stop all updates (when user logs out)
function stopUpdates() {
    console.log('[Updates] Stopping all updates');
    
    // Clear all intervals
    if (cumulativePnlInterval) {
        clearInterval(cumulativePnlInterval);
        cumulativePnlInterval = null;
    }
    if (dailyFullUpdateInterval) {
        clearInterval(dailyFullUpdateInterval);
        dailyFullUpdateInterval = null;
    }
    if (connectivityInterval) {
        clearInterval(connectivityInterval);
        connectivityInterval = null;
    }
    if (authStatusInterval) {
        clearInterval(authStatusInterval);
        authStatusInterval = null;
    }
    if (userProfileInterval) {
        clearInterval(userProfileInterval);
        userProfileInterval = null;
    }
    if (updateInterval) {
        clearInterval(updateInterval);
        updateInterval = null;
    }
    if (positionsUpdateInterval) {
        clearInterval(positionsUpdateInterval);
        positionsUpdateInterval = null;
    }
    // Clear any other intervals that might be running
    // Note: We can't easily track all setInterval calls, but the main ones are cleared above
}

// Removed updatePositionsAndPnl and updateCurrentPnl - no longer needed
// Daily Loss Used is updated via updateStatus() which is called in updateAll()

// Check connectivity status
async function checkConnectivity() {
    if (!isAuthenticated) {
        // Show not connected when not authenticated
        const statusText = document.getElementById('statusText');
        if (statusText) {
            statusText.textContent = 'Not Connected';
        }
        updateStatusIndicator(false);
        return;
    }
    try {
        const response = await throttledFetch('/api/connectivity');
        if (!response) return; // Request was throttled
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        const statusIndicator = document.getElementById('statusIndicator');
        const statusText = document.getElementById('statusText');
        const heartIcon = document.getElementById('heartIcon');
        
        if (data.connected && data.api_connected) {
            // Connected - Green pumping heart
            if (heartIcon) {
                heartIcon.classList.remove('disconnected');
                heartIcon.classList.add('connected');
            }
            if (statusText) {
                let message = 'Connected';
                if (data.websocket_connected) {
                    message += ' | WebSocket Active';
                }
                statusText.textContent = message;
            }
            if (statusIndicator) {
                statusIndicator.title = data.status_message || 'System Connected - Positions Updating';
            }
        } else {
            // Disconnected - Red static heart
            if (heartIcon) {
                heartIcon.classList.remove('connected');
                heartIcon.classList.add('disconnected');
            }
            if (statusText) {
                statusText.textContent = data.status_message || 'Disconnected';
            }
            if (statusIndicator) {
                statusIndicator.title = data.status_message || 'System Disconnected';
            }
        }
    } catch (error) {
        console.error('Error checking connectivity:', error);
        // Show disconnected state on error
        const heartIcon = document.getElementById('heartIcon');
        if (heartIcon) {
            heartIcon.classList.remove('connected');
            heartIcon.classList.add('disconnected');
        }
        updateStatusIndicator(false);
    }
}

// Update all dashboard data
async function updateAll() {
    if (!isAuthenticated) {
        return; // Don't fetch if not authenticated
    }
    try {
        await Promise.all([
            updateStatus(),
            updatePositions(),
            updateTrades(),
            updateDailyStats()
        ]);
        // Connectivity is checked separately every 2 seconds
        // Heart icon animation is controlled by checkConnectivity()
    } catch (error) {
        console.error('Error updating dashboard:', error);
        // On error, show disconnected state
        const heartIcon = document.getElementById('heartIcon');
        if (heartIcon) {
            heartIcon.classList.remove('connected');
            heartIcon.classList.add('disconnected');
        }
        updateStatusIndicator(false);
    }
}

// Update user profile (User ID and Name)
async function updateUserProfile() {
    try {
        console.log('[User Profile] Fetching user profile...');
        const response = await throttledFetch('/api/user/profile', {}, 5000);
        if (!response) {
            console.log('[User Profile] Request throttled');
            return;
        }
        
        if (!response.ok) {
            const statusText = response.status === 401 ? 'Not authenticated' : `HTTP ${response.status}`;
            console.log(`[User Profile] ${statusText} - hiding user info`);
            // Not authenticated or error - hide user info
            const userInfo = document.getElementById('userInfo');
            const authStatus = document.getElementById('authStatus');
            if (userInfo) {
                userInfo.style.display = 'none';
            }
            if (authStatus) {
                authStatus.style.display = 'block';
            }
            return;
        }
        
        const data = await safeJsonResponse(response);
        console.log('[User Profile] Response received:', data);
        
        if (data.success && data.profile) {
            const userInfo = document.getElementById('userInfo');
            const authStatus = document.getElementById('authStatus');
            const userName = document.getElementById('userName');
            const userId = document.getElementById('userId');
            
            if (!userInfo || !userName || !userId) {
                console.error('[User Profile] DOM elements not found:', { userInfo: !!userInfo, userName: !!userName, userId: !!userId });
                return;
            }
            
            // Show user info, hide auth status
            userInfo.style.display = 'block';
            if (authStatus) {
                authStatus.style.display = 'none';
            }
            
            // Update user name and ID - handle various field name possibilities
            const displayName = data.profile.user_shortname || data.profile.user_name || 'User';
            const userIdValue = data.profile.user_id || 'N/A';
            
            if (displayName === 'User' && userIdValue === 'N/A') {
                console.warn('[User Profile] No user data found in profile:', data.profile);
                // Try to get from raw_profile if available
                if (data.raw_profile) {
                    console.log('[User Profile] Trying raw_profile:', data.raw_profile);
                    const rawName = data.raw_profile.user_name || data.raw_profile.username || data.raw_profile.name || 'User';
                    const rawId = data.raw_profile.user_id || data.raw_profile.userid || 'N/A';
                    userName.textContent = `👤 ${rawName}`;
                    userId.textContent = `ID: ${rawId}`;
                    userInfo.title = `User: ${rawName}\nUser ID: ${rawId}`;
                    console.log('[User Profile] Updated from raw_profile:', { rawName, rawId });
                    return;
                }
            }
            
            userName.textContent = `👤 ${displayName}`;
            userId.textContent = `ID: ${userIdValue}`;
            
            // Add title for hover tooltip
            const tooltip = `User: ${data.profile.user_name || displayName}\nEmail: ${data.profile.email || 'N/A'}\nUser ID: ${userIdValue}`;
            userInfo.title = tooltip;
            
            console.log('[User Profile] Successfully updated:', { displayName, userIdValue });
        } else {
            console.warn('[User Profile] Invalid response structure:', data);
            // Hide user info if not authenticated
            const userInfo = document.getElementById('userInfo');
            const authStatus = document.getElementById('authStatus');
            if (userInfo) {
                userInfo.style.display = 'none';
            }
            if (authStatus) {
                authStatus.style.display = 'block';
            }
        }
    } catch (error) {
        console.error('[User Profile] Error updating user profile:', error);
        // Hide user info on error
        const userInfo = document.getElementById('userInfo');
        const authStatus = document.getElementById('authStatus');
        if (userInfo) {
            userInfo.style.display = 'none';
        }
        if (authStatus) {
            authStatus.style.display = 'block';
        }
    }
}

// Authentication functions
async function checkAuthStatus() {
    try {
        const response = await throttledFetch('/api/auth/status', {}, 10000);
        if (!response) return; // Request was throttled
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        const authStatusEl = document.getElementById('authStatus');
        const statusText = document.getElementById('statusText');
        const wasAuthenticated = isAuthenticated;
        
        if (data.authenticated) {
            isAuthenticated = true;
            
            if (authStatusEl) {
                authStatusEl.style.display = 'none'; // Hide auth button
            }
            
            // Show user info
            const userInfo = document.getElementById('userInfo');
            if (userInfo) {
                userInfo.style.display = 'flex';
            }
            
            // Update status text
            if (statusText) {
                statusText.textContent = 'Connected';
            }
            updateStatusIndicator(true);
            
            // Fetch user profile when authenticated
            updateUserProfile();
            
            // Start updates if not already started
            if (!wasAuthenticated) {
                startUpdates();
            }
        } else {
            isAuthenticated = false;
            
            if (authStatusEl) {
                authStatusEl.textContent = '🔒 Not Authenticated';
                authStatusEl.style.background = '#dc3545';
                authStatusEl.onclick = showAuthModal;
                authStatusEl.style.cursor = 'pointer';
                authStatusEl.style.display = 'block'; // Show auth button
            }
            
            // Hide user info when not authenticated
            const userInfo = document.getElementById('userInfo');
            if (userInfo) {
                userInfo.style.display = 'none';
            }
            
            // Update status text
            if (statusText) {
                statusText.textContent = 'Not Connected';
            }
            updateStatusIndicator(false);
            
            // Stop updates if was authenticated before
            if (wasAuthenticated) {
                stopUpdates();
            }
        }
    } catch (error) {
        console.error('Error checking auth status:', error);
        isAuthenticated = false;
        const statusText = document.getElementById('statusText');
        if (statusText) {
            statusText.textContent = 'Error';
        }
        updateStatusIndicator(false);
    }
}

// showAuthModal is already defined above as window.showAuthModal
// It's available globally for inline onclick handlers

function hideAuthModal() {
    console.log('[Auth] Hiding auth modal');
    const modal = document.getElementById('authModal');
    const errorEl = document.getElementById('authError');
    const errorElRequest = document.getElementById('authErrorRequest');
    
    // Clear Request Token form fields
    const apiKeyInput = document.getElementById('apiKey');
    const apiSecretInput = document.getElementById('apiSecret');
    const requestTokenInput = document.getElementById('requestToken');
    
    // Clear Access Token form fields
    const accessTokenApiKeyInput = document.getElementById('accessTokenApiKey');
    const accessTokenApiSecretInput = document.getElementById('accessTokenApiSecret');
    const accessTokenInput = document.getElementById('accessToken');
    
    // Hide generated access token display
    const accessTokenDisplay = document.getElementById('accessTokenDisplay');
    
    if (modal) {
        modal.style.display = 'none';
        modal.style.visibility = 'hidden';
        modal.onclick = null; // Remove click handler
    }
    if (errorEl) errorEl.style.display = 'none';
    if (errorElRequest) errorElRequest.style.display = 'none';
    if (apiKeyInput) apiKeyInput.value = '';
    if (apiSecretInput) apiSecretInput.value = '';
    if (requestTokenInput) requestTokenInput.value = '';
    if (accessTokenApiKeyInput) accessTokenApiKeyInput.value = '';
    if (accessTokenApiSecretInput) accessTokenApiSecretInput.value = '';
    if (accessTokenInput) accessTokenInput.value = '';
    if (accessTokenDisplay) accessTokenDisplay.style.display = 'none';
}

function switchAuthTab(tab) {
    const accessTokenTab = document.getElementById('tabAccessToken');
    const requestTokenTab = document.getElementById('tabRequestToken');
    const accessTokenForm = document.getElementById('accessTokenForm');
    const requestTokenForm = document.getElementById('requestTokenForm');
    
    if (tab === 'accessToken') {
        // Show access token form
        if (accessTokenForm) accessTokenForm.style.display = 'block';
        if (requestTokenForm) requestTokenForm.style.display = 'none';
        
        // Update tab styles
        if (accessTokenTab) {
            accessTokenTab.style.background = 'var(--primary-color)';
            accessTokenTab.style.color = 'white';
        }
        if (requestTokenTab) {
            requestTokenTab.style.background = '#e9ecef';
            requestTokenTab.style.color = '#666';
        }
    } else {
        // Show request token form
        if (accessTokenForm) accessTokenForm.style.display = 'none';
        if (requestTokenForm) requestTokenForm.style.display = 'block';
        
        // Update tab styles
        if (requestTokenTab) {
            requestTokenTab.style.background = 'var(--primary-color)';
            requestTokenTab.style.color = 'white';
        }
        if (accessTokenTab) {
            accessTokenTab.style.background = '#e9ecef';
            accessTokenTab.style.color = '#666';
        }
    }
}

async function authenticateWithAccessToken(event) {
    event.preventDefault();
    const apiKey = document.getElementById('accessTokenApiKey').value.trim();
    const apiSecret = document.getElementById('accessTokenApiSecret').value.trim();
    const accessToken = document.getElementById('accessToken').value.trim();
    const errorEl = document.getElementById('authError');
    
    if (!apiKey) {
        if (errorEl) {
            errorEl.textContent = 'Please enter an API key';
            errorEl.style.display = 'block';
        }
        return;
    }
    
    if (!apiSecret) {
        if (errorEl) {
            errorEl.textContent = 'Please enter an API secret';
            errorEl.style.display = 'block';
        }
        return;
    }
    
    if (!accessToken) {
        if (errorEl) {
            errorEl.textContent = 'Please enter an access token';
            errorEl.style.display = 'block';
        }
        return;
    }
    
    try {
        if (errorEl) errorEl.style.display = 'none';
        
        const response = await fetch('/api/auth/set-access-token', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                api_key: apiKey,
                api_secret: apiSecret,
                access_token: accessToken
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.success) {
            // Save credentials to localStorage
            saveAuthCredentials(apiKey, apiSecret, accessToken);
            
            // Update stored values and refresh auth details
            await updateAuthDetails();
            
            hideAuthModal();
            // Check auth status which will start updates if authenticated
            await checkAuthStatus();
            if (typeof addNotification === 'function') {
                addNotification('Successfully connected with access token!', 'success');
            }
            // Refresh data after authentication
            setTimeout(() => {
                if (isAuthenticated) {
                    updateAll();
                }
            }, 2000);
        } else {
            if (errorEl) {
                errorEl.textContent = data.error || 'Connection failed';
                errorEl.style.display = 'block';
            }
        }
    } catch (error) {
        console.error('Set access token error:', error);
        if (errorEl) {
            errorEl.textContent = 'Error: ' + error.message;
            errorEl.style.display = 'block';
        }
    }
}

async function authenticateWithRequestToken(event) {
    event.preventDefault();
    const apiKey = document.getElementById('apiKey').value.trim();
    const apiSecret = document.getElementById('apiSecret').value.trim();
    const requestToken = document.getElementById('requestToken').value.trim();
    const errorEl = document.getElementById('authErrorRequest');
    const submitBtn = document.getElementById('authSubmitBtn');
    const accessTokenDisplay = document.getElementById('accessTokenDisplay');
    const generatedAccessToken = document.getElementById('generatedAccessToken');
    
    if (!apiKey) {
        if (errorEl) {
            errorEl.textContent = 'Please enter an API key';
            errorEl.style.display = 'block';
        }
        return;
    }
    
    if (!apiSecret) {
        if (errorEl) {
            errorEl.textContent = 'Please enter an API secret';
            errorEl.style.display = 'block';
        }
        return;
    }
    
    if (!requestToken) {
        if (errorEl) {
            errorEl.textContent = 'Please enter a request token';
            errorEl.style.display = 'block';
        }
        return;
    }
    
    try {
        if (errorEl) errorEl.style.display = 'none';
        if (accessTokenDisplay) accessTokenDisplay.style.display = 'none';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Generating...';
        }
        
        const response = await fetch('/api/auth/authenticate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                api_key: apiKey,
                api_secret: apiSecret,
                request_token: requestToken
            })
        });
        
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.success && data.access_token) {
            // Save credentials to localStorage
            saveAuthCredentials(apiKey, apiSecret, data.access_token, requestToken);
            
            // Display the generated access token
            if (generatedAccessToken) {
                generatedAccessToken.value = data.access_token;
            }
            if (accessTokenDisplay) {
                accessTokenDisplay.style.display = 'block';
            }
            
            // Update stored values and refresh auth details
            await updateAuthDetails();
            
            // Wait a moment to show the access token, then close modal and connect
            setTimeout(async () => {
                hideAuthModal();
                // Check auth status which will start updates if authenticated
                await checkAuthStatus();
                if (typeof addNotification === 'function') {
                    addNotification('Successfully authenticated with Zerodha! Access token generated and saved.', 'success');
                }
                // Refresh data after authentication
                setTimeout(() => {
                    if (isAuthenticated) {
                        updateAll();
                    }
                }, 2000);
            }, 2000);
        } else {
            if (errorEl) {
                errorEl.textContent = data.error || 'Authentication failed';
                errorEl.style.display = 'block';
            }
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Generate & Connect';
            }
        }
    } catch (error) {
        console.error('Authentication error:', error);
        if (errorEl) {
            errorEl.textContent = 'Error: ' + error.message;
            errorEl.style.display = 'block';
        }
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Generate & Connect';
        }
    }
}

// Make functions globally available
window.showAuthModal = showAuthModal;
window.hideAuthModal = hideAuthModal;
window.switchAuthTab = switchAuthTab;
window.authenticateWithAccessToken = authenticateWithAccessToken;
window.authenticateWithRequestToken = authenticateWithRequestToken;

// Update system status
async function updateStatus() {
    if (!isAuthenticated) {
        return; // Don't fetch if not authenticated
    }
    try {
        const response = await throttledFetch('/api/status', {}, 2000);
        if (!response) return; // Request was throttled
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.error) {
            console.error('Status error:', data.error);
            return;
        }
        
        // Update Daily Loss Used widget (only widget remaining)
        const lossProtection = data.loss_protection || {};
        const dailyLoss = lossProtection.daily_loss || 0;
        const lossLimit = lossProtection.daily_loss_limit || 5000;
        updateValue('dailyLossUsed', formatCurrency(dailyLoss), 'loss-card');
        document.getElementById('lossUsed').textContent = formatCurrency(dailyLoss);
        document.getElementById('lossLimit').textContent = formatCurrency(lossLimit);
        
        // Update progress bar
        const lossPercentage = Math.min((dailyLoss / lossLimit) * 100, 100);
        document.getElementById('lossProgress').style.width = lossPercentage + '%';
        
    } catch (error) {
        console.error('Error updating status:', error);
    }
}

// Update P&L status indicator
function updatePnlStatus(status, message) {
    // Log P&L status with timestamp for debugging
    const timestamp = new Date().toLocaleTimeString();
    if (status === 'connected') {
        console.log(`[${timestamp}] ✅ P&L Status: ${message}`);
    } else {
        console.warn(`[${timestamp}] ⚠️ P&L Status: ${message}`);
    }
}

// Update positions table (disabled - Active Positions section removed)
async function updatePositions() {
    // Active Positions section has been removed from the dashboard
    // This function is kept for backward compatibility but does nothing
    return;
}


// Sync orders from Zerodha and create trade records
async function syncOrdersFromZerodha() {
    if (!confirm('This will fetch all completed orders from Zerodha and create trade records. Continue?')) {
        return;
    }
    
    const btn = document.getElementById('syncOrdersBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Syncing...';
    
    try {
        const response = await fetch('/api/orders/sync', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await safeJsonResponse(response);
        
        if (data.success) {
            addNotification(
                `✅ Order sync completed! Created ${data.trades_created || 0} trade records`,
                'success'
            );
            // Refresh trades immediately
            setTimeout(() => {
                updateTrades();
                updateStatus();
            }, 1000);
        } else {
            addNotification(`Failed to sync orders: ${data.error || 'Unknown error'}`, 'danger');
        }
    } catch (error) {
        console.error('Error syncing orders:', error);
        addNotification('Error syncing orders: ' + (error.message || 'Unknown error'), 'danger');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

// Make function globally available
window.syncOrdersFromZerodha = syncOrdersFromZerodha;

// Toggle trade filter (all vs date)
function toggleTradeFilter() {
    const showAll = document.getElementById('showAllTrades').checked;
    const dateFilter = document.getElementById('tradeDateFilter');
    
    if (showAll) {
        dateFilter.style.display = 'none';
        updateTrades();
    } else {
        dateFilter.style.display = 'block';
        // Set to today's date if not already set
        if (!dateFilter.value) {
            dateFilter.value = new Date().toISOString().split('T')[0];
        }
        updateTrades();
    }
}

// Make function globally available
window.toggleTradeFilter = toggleTradeFilter;

// Update trades table
async function updateTrades() {
    if (!isAuthenticated) {
        return; // Don't fetch if not authenticated
    }
    const showAll = document.getElementById('showAllTrades').checked;
    const dateFilter = document.getElementById('tradeDateFilter');
    
    let url = '/api/trades';
    if (showAll) {
        url += '?all=true';
    } else {
        const date = dateFilter ? dateFilter.value : new Date().toISOString().split('T')[0];
        url += `?date=${date}`;
    }
    
    try {
        const response = await throttledFetch(url, {}, 5000);
        if (!response) return; // Request was throttled
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.error) {
            console.error('Trades error:', data.error);
            return;
        }
        
        const tbody = document.getElementById('tradesBody');
        const trades = data.trades || data; // Support both new format (with summary) and old format
        
        if (trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No trades found</td></tr>';
            // Clear summary if no trades
            updateTradeSummary({});
            return;
        }
        
        // Update summary if available
        if (data.summary) {
            updateTradeSummary(data.summary);
        }
        
        // Check if we have any open positions to determine if we need to hide exit columns
        const hasOpenPositions = trades.some(trade => trade.is_open === true);
        
        tbody.innerHTML = trades.map(trade => {
            // Get transaction type (BUY or SELL) - use transaction_type from backend, fallback to quantity sign
            const transactionType = trade.transaction_type || (trade.quantity > 0 ? 'BUY' : 'SELL');
            const typeClass = transactionType === 'BUY' ? 'positive' : 'negative';
            const buyTooltip = "BUY: Buy options (SL = entry_premium - stop_loss points)";
            const sellTooltip = "SELL: Sell options (SL = entry_premium + stop_loss% of premium)";
            const typeBadge = transactionType === 'BUY' 
                ? `<span style="color: #10b981; font-weight: 600; font-size: 12px; cursor: help;" title="${buyTooltip}">BUY</span>` 
                : `<span style="color: #ef4444; font-weight: 600; font-size: 12px; cursor: help;" title="${sellTooltip}">SELL</span>`;
            
            // Format times in IST
            const entryTime = formatDateTimeIST(trade.entry_time);
            const isOpen = trade.is_open === true;
            const exitTime = isOpen ? '-' : formatDateTimeIST(trade.exit_time);
            const exitPrice = isOpen ? '-' : `₹${(trade.exit_price || 0).toFixed(2)}`;
            
            // Display quantity with proper sign (negative for SELL, positive for BUY)
            // For SELL trades, quantity should be negative (e.g., -150)
            const quantity = trade.quantity || 0;
            const quantityDisplay = quantity !== 0 ? (quantity > 0 ? `+${quantity}` : `${quantity}`) : '0';
            
            // For open positions, use unrealized P&L; for closed, use realized P&L
            const pnl = trade.realized_pnl || 0;
            
            return `
            <tr>
                <td>${trade.trading_symbol || '-'}</td>
                <td>${entryTime}</td>
                <td>${exitTime}</td>
                <td>₹${(trade.entry_price || 0).toFixed(2)}</td>
                <td>${exitPrice}</td>
                <td class="${typeClass}" style="font-weight: 600;">${quantityDisplay}</td>
                <td class="${pnl >= 0 ? 'positive' : 'negative'}">
                    ${formatCurrency(pnl)}
                </td>
                <td>${typeBadge}</td>
            </tr>
            `;
        }).join('');
    } catch (error) {
        console.error('Error updating trades:', error);
        const tbody = document.getElementById('tradesBody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">Error loading trades</td></tr>';
        }
        updateTradeSummary({});
    }
}

// Update trade summary
function updateTradeSummary(summary) {
    if (!summary || Object.keys(summary).length === 0) {
        document.getElementById('totalTrades').textContent = '0';
        document.getElementById('totalProfit').textContent = '₹0.00';
        document.getElementById('totalLoss').textContent = '₹0.00';
        document.getElementById('netPnl').textContent = '₹0.00';
        document.getElementById('winRate').textContent = '0%';
        return;
    }
    
    const totalTradesEl = document.getElementById('totalTrades');
    totalTradesEl.textContent = summary.total_trades || 0;
    totalTradesEl.style.color = '#10b981'; // Green color for Total Trades
    
    document.getElementById('totalProfit').textContent = formatCurrency(summary.total_profit || 0);
    document.getElementById('totalLoss').textContent = formatCurrency(summary.total_loss || 0);
    
    const netPnl = summary.total_pnl || 0;
    const netPnlEl = document.getElementById('netPnl');
    netPnlEl.textContent = formatCurrency(netPnl);
    netPnlEl.style.color = netPnl >= 0 ? '#10b981' : '#ef4444';
    
    const winRate = summary.total_trades > 0 
        ? ((summary.profitable_trades || 0) / summary.total_trades * 100).toFixed(1)
        : 0;
    const winRateEl = document.getElementById('winRate');
    winRateEl.textContent = winRate + '%';
    // Green if positive (>= 50%), red otherwise
    winRateEl.style.color = parseFloat(winRate) >= 50 ? '#10b981' : '#ef4444';
}

// Update daily stats
async function updateDailyStats() {
    if (!isAuthenticated) {
        return; // Don't fetch if not authenticated
    }
    try {
        const response = await throttledFetch('/api/daily-stats', {}, 5000);
        if (!response) return; // Request was throttled
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.error) {
            console.error('Daily stats error:', data.error);
            return;
        }
        
    } catch (error) {
        console.error('Error updating daily stats:', error);
    }
}


// Helper functions
function updateValue(id, value, className) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = value;
    }
}

function formatCurrency(amount) {
    return '₹' + Math.abs(amount).toLocaleString('en-IN', { 
        minimumFractionDigits: 2, 
        maximumFractionDigits: 2 
    }) + (amount < 0 ? ' (Loss)' : '');
}

function formatDateTime(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleString('en-IN', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatDateTimeIST(dateString) {
    if (!dateString) return '-';
    try {
        // Parse ISO string from backend
        // Backend sends ISO string with timezone (e.g., "2025-11-13T18:12:32+05:30")
        const date = new Date(dateString);
        
        // Check if date is valid
        if (isNaN(date.getTime())) {
            return '-';
        }
        
        // The ISO string from backend already includes timezone info
        // When we parse it with new Date(), it converts to browser's local time
        // But we want to display it as IST, so we need to format it correctly
        
        // Get the date components in IST
        // Use toLocaleString with IST timezone to ensure correct display
        const istDate = new Date(date.toLocaleString('en-US', {timeZone: 'Asia/Kolkata'}));
        
        // Format in IST timezone (explicitly specify IST)
        return date.toLocaleString('en-IN', {
            timeZone: 'Asia/Kolkata',
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });
    } catch (error) {
        console.error('Error formatting date:', dateString, error);
        return '-';
    }
}

function updateStatusIndicator(connected) {
    const heartIcon = document.getElementById('heartIcon');
    const statusText = document.getElementById('statusText');
    
    if (connected) {
        if (heartIcon) {
            heartIcon.classList.remove('disconnected');
            heartIcon.classList.add('connected');
        }
        if (statusText) {
            statusText.textContent = 'Connected';
        }
    } else {
        if (heartIcon) {
            heartIcon.classList.remove('connected');
            heartIcon.classList.add('disconnected');
        }
        if (statusText) {
            statusText.textContent = 'Disconnected';
        }
    }
}

function closeNotifications() {
    document.getElementById('notificationsPanel').classList.remove('show');
}

// Add notification
function addNotification(message, type = 'info') {
    const panel = document.getElementById('notificationsPanel');
    const list = document.getElementById('notificationsList');
    
    if (!panel || !list) return;
    
    panel.classList.add('show');
    
    const notification = document.createElement('div');
    notification.className = `notification-item ${type}`;
    notification.innerHTML = `
        <div>${message}</div>
        <div class="notification-time">${new Date().toLocaleTimeString()}</div>
    `;
    
    list.insertBefore(notification, list.firstChild);
    
    // Keep only last 10 notifications
    while (list.children.length > 10) {
        list.removeChild(list.lastChild);
    }
    
    // Auto-close after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
            if (list.children.length === 0) {
                panel.classList.remove('show');
            }
        }
    }, 5000);
}

// Manual exit position
async function exitPosition(positionId) {
    if (!confirm('Are you sure you want to exit this position?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/positions/${positionId}/exit`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await safeJsonResponse(response);
        if (data.success) {
            addNotification(`Position exit order placed: ${data.order_id}`, 'success');
            // Refresh positions
            setTimeout(updatePositions, 2000);
        } else {
            addNotification(`Failed to exit position: ${data.error}`, 'danger');
        }
    } catch (error) {
        console.error('Error exiting position:', error);
        addNotification('Error exiting position', 'danger');
    }
}

// Export for use by notification system
window.addNotification = addNotification;
window.exitPosition = exitPosition;

// Help System
const helpContent = {
    'protected-profit': {
        title: 'Protected Profit',
        content: `
            <h3>What is Protected Profit?</h3>
            <p>Protected Profit represents the cumulative P&L from all completed trades for the day. This includes both profitable and loss-making trades.</p>
            
            <h3>How it works:</h3>
            <ul>
                <li>When you close a trade, its realized P&L is added to Protected Profit</li>
                <li>Protected Profit includes ALL completed trades (profit + loss combined)</li>
                <li>This value is "locked" and separate from your current live positions</li>
                <li>Daily loss limit applies only to live positions, NOT to protected profit</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                Trade A closes with ₹8,000 profit → Protected Profit = ₹8,000<br>
                Trade B closes with ₹-3,000 loss → Protected Profit = ₹5,000 (₹8,000 - ₹3,000)<br>
                Trade C is still open with ₹-2,000 unrealized → Protected Profit remains ₹5,000
            </div>
            
            <div class="help-note">
                <strong>Note:</strong> Protected Profit resets at the start of each new trading day.
            </div>
        `
    },
    'current-pnl': {
        title: 'Current Positions P&L',
        content: `
            <h3>What is Current Positions P&L?</h3>
            <p>This shows the unrealized (unlocked) profit or loss from all your currently active/open positions.</p>
            
            <h3>Key points:</h3>
            <ul>
                <li>This value changes in real-time as market prices move</li>
                <li>Only includes positions that are still open (not yet closed)</li>
                <li>This is the P&L that is NOT yet protected</li>
                <li>Daily loss limit applies to this value</li>
                <li>Updates every 3 seconds automatically</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                You have 2 open positions:<br>
                Position 1: +₹3,000 unrealized profit<br>
                Position 2: -₹1,000 unrealized loss<br>
                Current Positions P&L = ₹2,000
            </div>
            
            <div class="help-note">
                <strong>Important:</strong> This P&L becomes "Protected Profit" only after you close the positions.
            </div>
        `
    },
    'total-pnl': {
        title: 'Total Day P&L',
        content: `
            <h3>What is Total Day P&L?</h3>
            <p>This is the complete picture of your trading day - combining both protected profit from closed trades and unrealized P&L from open positions.</p>
            
            <h3>Calculation:</h3>
            <p><strong>Total Day P&L = Protected Profit + Current Positions P&L</strong></p>
            
            <h3>What it shows:</h3>
            <ul>
                <li>Your overall performance for the entire trading day</li>
                <li>Combines completed trades (locked) + active positions (unlocked)</li>
                <li>This is your true net position for the day</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                Protected Profit (from closed trades): ₹5,000<br>
                Current Positions P&L (from open trades): ₹2,000<br>
                <strong>Total Day P&L = ₹7,000</strong>
            </div>
            
            <div class="help-note">
                <strong>Tip:</strong> This is the most important metric to track your overall daily performance.
            </div>
        `
    },
    'booked-profit': {
        title: 'Booked Profit',
        content: `
            <h3>What is Booked Profit?</h3>
            <p>Booked Profit represents the total profit from all completed trades that ended with a profit (excluding losses).</p>
            
            <h3>Key differences from Protected Profit:</h3>
            <ul>
                <li><strong>Booked Profit:</strong> Only profitable trades (excludes losses)</li>
                <li><strong>Protected Profit:</strong> All completed trades (profit + loss combined)</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                Trade A: +₹8,000 profit<br>
                Trade B: -₹3,000 loss<br>
                Trade C: +₹2,000 profit<br>
                <br>
                Booked Profit = ₹10,000 (only profitable trades)<br>
                Protected Profit = ₹7,000 (all trades combined)
            </div>
        `
    },
    'net-position-pnl': {
        title: 'Net Position P&L',
        content: `
            <h3>What is Net Position P&L?</h3>
            <p>This shows the combined unrealized P&L from all your currently active positions, accounting for both BUY and SELL positions.</p>
            
            <h3>How it's calculated:</h3>
            <ul>
                <li>Sums up the unrealized P&L from all open positions</li>
                <li>Accounts for both long (BUY) and short (SELL) positions</li>
                <li>Shows the net effect of all your active trades</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                BUY Position 1: +₹5,000<br>
                SELL Position 2: +₹2,000<br>
                BUY Position 3: -₹1,000<br>
                <strong>Net Position P&L = ₹6,000</strong>
            </div>
            
            <div class="help-note">
                <strong>Note:</strong> This is similar to "Current Positions P&L" but may be calculated differently based on position types.
            </div>
        `
    },
    'daily-loss': {
        title: 'Daily Loss Used',
        content: `
            <h3>What is Daily Loss Used?</h3>
            <p>This tracks how much of your daily loss limit you've consumed from your current open positions.</p>
            
            <h3>How it works:</h3>
            <ul>
                <li>Shows the total unrealized loss from all active positions</li>
                <li>Compares it against your daily loss limit (default: ₹5,000)</li>
                <li>When you reach the limit, trading will be automatically blocked</li>
                <li>Protected Profit is NOT included in this calculation</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                Daily Loss Limit: ₹5,000<br>
                Current unrealized loss from open positions: ₹3,000<br>
                <strong>Daily Loss Used: ₹3,000 (60% of limit)</strong><br>
                Remaining: ₹2,000 before auto-exit triggers
            </div>
            
            <div class="help-note">
                <strong>Important:</strong> The loss limit applies only to live positions. Your protected profit from closed trades is safe and not affected.
            </div>
        `
    },
    'trailing-sl': {
        title: 'Trailing Stop Loss',
        content: `
            <h3>What is Trailing Stop Loss?</h3>
            <p>Trailing Stop Loss is an advanced risk management feature that automatically adjusts your stop loss as your position moves in profit.</p>
            
            <h3>How it works:</h3>
            <ul>
                <li>Activates when your total unrealized profit reaches ₹5,000</li>
                <li>As profit increases, the stop loss "trails" behind at a safe distance</li>
                <li>If price reverses, it exits automatically to lock in profits</li>
                <li>Prevents giving back large profits in volatile markets</li>
            </ul>
            
            <h3>Activation:</h3>
            <ul>
                <li><strong>Trigger:</strong> When Current Positions P&L reaches ₹5,000</li>
                <li><strong>Increment:</strong> Adjusts every ₹10,000 profit increase</li>
                <li><strong>Status:</strong> Shows "Active" when trailing SL is engaged</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                Your positions reach ₹5,000 profit → Trailing SL activates<br>
                Profit increases to ₹15,000 → Stop loss moves to ₹5,000<br>
                If price drops to ₹5,000 → Auto-exit triggers, locking ₹5,000 profit
            </div>
            
            <div class="help-note">
                <strong>Note:</strong> Trailing SL only applies to live positions. It does not affect your protected profit from closed trades.
            </div>
        `
    },
    'trading-status': {
        title: 'Trading Status',
        content: `
            <h3>What is Trading Status?</h3>
            <p>This shows whether the system is currently allowing new trades or if trading has been blocked due to risk limits.</p>
            
            <h3>Status Types:</h3>
            <ul>
                <li><strong>Active:</strong> Trading is allowed, no risk limits have been hit</li>
                <li><strong>Blocked:</strong> Trading is temporarily disabled due to risk limits</li>
            </ul>
            
            <h3>When trading gets blocked:</h3>
            <ul>
                <li>Daily loss limit is reached (₹5,000 unrealized loss)</li>
                <li>System automatically exits all positions when limit is hit</li>
                <li>Trading remains blocked until the next trading day</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                You have open positions with ₹-5,000 unrealized loss<br>
                → Daily loss limit hit<br>
                → All positions auto-exited<br>
                → Trading Status: <strong>Blocked</strong>
            </div>
            
            <div class="help-note">
                <strong>Important:</strong> Even if trading is blocked, your protected profit from earlier closed trades remains safe.
            </div>
        `
    },
    'active-positions': {
        title: 'Active Positions',
        content: `
            <h3>What are Active Positions?</h3>
            <p>This section displays all your currently open positions from Zerodha, showing real-time P&L and position details.</p>
            
            <h3>Information shown:</h3>
            <ul>
                <li><strong>Symbol:</strong> Trading symbol of the instrument</li>
                <li><strong>Exchange:</strong> Exchange where the instrument is traded (NFO, BFO, etc.)</li>
                <li><strong>Entry Price:</strong> Average price at which you entered the position</li>
                <li><strong>Current Price:</strong> Latest market price (updates every 3 seconds)</li>
                <li><strong>Quantity:</strong> Number of lots/units (positive for BUY, negative for SELL)</li>
                <li><strong>P&L:</strong> Unrealized profit or loss for this position</li>
            </ul>
            
            <h3>Actions available:</h3>
            <ul>
                <li><strong>Exit:</strong> Manually close a position anytime</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                You bought 50 lots of NIFTY 25000CE at ₹100<br>
                Current price: ₹120<br>
                P&L: +₹1,000 (50 lots × ₹20 profit per lot)
            </div>
            
            <div class="help-note">
                <strong>Note:</strong> Positions update automatically every 3 seconds.
            </div>
        `
    },
    'trade-history': {
        title: 'Trade History (All Trades)',
        content: `
            <h3>What is Trade History?</h3>
            <p>This section shows all your trades (both open and closed) for the selected date, with detailed P&L information.</p>
            
            <h3>Information shown:</h3>
            <ul>
                <li><strong>Symbol:</strong> Trading symbol of the trade</li>
                <li><strong>Entry Time:</strong> When you entered the position (IST)</li>
                <li><strong>Exit Time:</strong> When you exited the position (IST) - shown as "-" for open positions</li>
                <li><strong>Entry Price:</strong> Price at which you entered</li>
                <li><strong>Exit Price:</strong> Price at which you exited - shown as "-" for open positions</li>
                <li><strong>Quantity:</strong> Number of lots/units traded (negative for SELL, positive for BUY)</li>
                <li><strong>P&L:</strong> Realized profit/loss for closed trades, unrealized P&L for open positions</li>
                <li><strong>Type:</strong> BUY or SELL transaction type</li>
            </ul>
            
            <h3>Trade Types & Stop Loss:</h3>
            <div class="help-note" style="background: #e0f2fe; border-left: 4px solid #0284c7; padding: 12px; margin: 16px 0;">
                <strong>BUY:</strong> Buy options<br>
                <em>Stop Loss = entry_premium - stop_loss points</em><br><br>
                <strong>SELL:</strong> Sell options<br>
                <em>Stop Loss = entry_premium + stop_loss% of premium</em>
            </div>
            
            <h3>Features:</h3>
            <ul>
                <li><strong>Sync Orders from Zerodha:</strong> Fetch all completed orders and create trade records</li>
                <li><strong>Show All Trades:</strong> Toggle to show all trades or filter by date</li>
                <li><strong>Trade Summary:</strong> Shows total trades, profit, loss, net P&L (including unrealized), and win rate</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                Closed Trade: NIFTY 25000CE, Entry: ₹100, Exit: ₹120, Quantity: 50, P&L: +₹1,000<br>
                Open Position: BANKNIFTY 50000PE, Entry: ₹80, Exit: -, Quantity: -25, P&L: +₹150 (unrealized)<br>
                <strong>Net P&L: ₹1,150 (includes both realized and unrealized)</strong>
            </div>
            
            <div class="help-note">
                <strong>Tip:</strong> Use "Sync Orders from Zerodha" to ensure all your completed trades are captured in the system.
            </div>
        `
    },
    'pnl-chart': {
        title: 'P&L Chart',
        content: `
            <h3>What is the P&L Chart?</h3>
            <p>This visual chart displays your profit and loss progression throughout the trading day, showing how your P&L has changed over time.</p>
            
            <h3>What it shows:</h3>
            <ul>
                <li><strong>X-Axis:</strong> Time progression throughout the day</li>
                <li><strong>Y-Axis:</strong> P&L amount in rupees</li>
                <li><strong>Lines:</strong> Different lines for Protected Profit, Current P&L, and Total P&L</li>
            </ul>
            
            <h3>Chart lines:</h3>
            <ul>
                <li><strong>Protected Profit:</strong> Cumulative P&L from closed trades (locked)</li>
                <li><strong>Current P&L:</strong> Unrealized P&L from open positions (unlocked)</li>
                <li><strong>Total P&L:</strong> Combined total (Protected + Current)</li>
            </ul>
            
            <h3>How to use it:</h3>
            <ul>
                <li>Hover over data points to see exact values at specific times</li>
                <li>Track your performance trends throughout the day</li>
                <li>Identify when profits were locked vs. when they were unrealized</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                Morning: Protected Profit = ₹0, Current P&L = ₹0<br>
                After closing Trade A: Protected Profit = ₹5,000, Current P&L = ₹0<br>
                After opening Trade B: Protected Profit = ₹5,000, Current P&L = ₹2,000<br>
                Chart shows the progression of these values over time
            </div>
            
            <div class="help-note">
                <strong>Note:</strong> The chart updates automatically as your positions and trades change throughout the day.
            </div>
        `
    }
};

// Show help modal
function showHelp(helpId) {
    const modal = document.getElementById('helpModal');
    const title = document.getElementById('helpModalTitle');
    const body = document.getElementById('helpModalBody');
    
    if (!modal || !title || !body) return;
    
    const content = helpContent[helpId];
    if (!content) {
        console.error('Help content not found for:', helpId);
        return;
    }
    
    title.textContent = content.title;
    body.innerHTML = content.content;
    modal.style.display = 'flex';
    
    // Close on background click
    modal.onclick = function(e) {
        if (e.target === modal) {
            closeHelp();
        }
    };
    
    // Close on Escape key
    document.addEventListener('keydown', function escapeHandler(e) {
        if (e.key === 'Escape') {
            closeHelp();
            document.removeEventListener('keydown', escapeHandler);
        }
    });
}

// Close help modal
function closeHelp() {
    const modal = document.getElementById('helpModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Date Range Picker State
let dateRangePickerState = {
    fromDate: null,
    toDate: null,
    fromMonth: new Date(),
    toMonth: new Date()
};

// Initialize P&L Calendar with Date Range Picker
function initializePnlCalendar() {
    const calendarContainer = document.getElementById('pnlCalendarHeatmap');
    if (!calendarContainer) return; // Calendar not on this page
    
    // Set default date range (last 6 months)
    const endDate = new Date();
    const startDate = new Date();
    startDate.setMonth(startDate.getMonth() - 6);
    
    dateRangePickerState.fromDate = startDate;
    dateRangePickerState.toDate = endDate;
    dateRangePickerState.fromMonth = new Date(startDate);
    dateRangePickerState.toMonth = new Date(endDate);
    
    updateDateRangeDisplay();
    
    // Setup date range picker button
    const dateRangeBtn = document.getElementById('pnlDateRangeBtn');
    if (dateRangeBtn) {
        dateRangeBtn.addEventListener('click', () => {
            openDateRangePicker();
        });
    }
    
    // Load initial data
    loadPnlCalendarData();
    
    // Setup filter handlers
    const applyBtn = document.getElementById('applyPnlFilters');
    if (applyBtn) {
        applyBtn.addEventListener('click', () => {
            console.log('[P&L Filters] Apply button clicked');
            // Read filter values from form inputs
            updatePnlFilters();
            loadPnlCalendarData();
        });
    }
    
    // Update filters on change (auto-apply for type)
    const pnlType = document.getElementById('pnlType');
    if (pnlType) {
        pnlType.addEventListener('change', () => {
            updatePnlFilters();
            loadPnlCalendarData();
        });
    }
}

// Update filter values from form inputs
function updatePnlFilters() {
    const segmentEl = document.getElementById('pnlSegment');
    const symbolEl = document.getElementById('pnlSymbol');
    const typeEl = document.getElementById('pnlType');
    
    if (segmentEl) {
        pnlFilters.segment = segmentEl.value;
    }
    if (symbolEl) {
        pnlFilters.symbol = symbolEl.value.trim().toUpperCase();
    }
    if (typeEl) {
        pnlFilters.type = typeEl.value;
    }
    
    console.log('[P&L Filters] Updated filters:', pnlFilters);
}

function updateDateRangeDisplay() {
    const display = document.getElementById('pnlDateRangeDisplay');
    const hiddenInput = document.getElementById('pnlDateRange');
    
    if (dateRangePickerState.fromDate && dateRangePickerState.toDate) {
        const fromStr = formatDateForInput(dateRangePickerState.fromDate);
        const toStr = formatDateForInput(dateRangePickerState.toDate);
        const displayText = `${fromStr} ~ ${toStr}`;
        
        if (display) display.textContent = displayText;
        if (hiddenInput) hiddenInput.value = displayText;
    } else {
        if (display) display.textContent = 'Select Date Range';
        if (hiddenInput) hiddenInput.value = '';
    }
}

function formatDateForInput(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function openDateRangePicker() {
    const modal = document.getElementById('dateRangePickerModal');
    if (modal) {
        modal.style.display = 'flex';
        renderCalendars();
    }
}

function closeDateRangePicker() {
    const modal = document.getElementById('dateRangePickerModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function setQuickDateRange(option) {
    const today = new Date();
    let fromDate, toDate;
    
    switch(option) {
        case 'last7':
            fromDate = new Date(today);
            fromDate.setDate(today.getDate() - 6);
            toDate = new Date(today);
            break;
        case 'last30':
            fromDate = new Date(today);
            fromDate.setDate(today.getDate() - 29);
            toDate = new Date(today);
            break;
        case 'prevFY':
            // Previous Financial Year (April 1 to March 31)
            const currentYear = today.getFullYear();
            const currentMonth = today.getMonth();
            if (currentMonth >= 3) { // April onwards
                fromDate = new Date(currentYear - 1, 3, 1); // April 1 of previous year
                toDate = new Date(currentYear, 2, 31); // March 31 of current year
            } else {
                fromDate = new Date(currentYear - 2, 3, 1); // April 1 of year before previous
                toDate = new Date(currentYear - 1, 2, 31); // March 31 of previous year
            }
            break;
        case 'currentFY':
            // Current Financial Year (April 1 to today or March 31)
            const currYear = today.getFullYear();
            const currMonth = today.getMonth();
            if (currMonth >= 3) { // April onwards
                fromDate = new Date(currYear, 3, 1); // April 1 of current year
                toDate = new Date(today);
            } else {
                fromDate = new Date(currYear - 1, 3, 1); // April 1 of previous year
                toDate = new Date(today);
            }
            break;
    }
    
    dateRangePickerState.fromDate = fromDate;
    dateRangePickerState.toDate = toDate;
    dateRangePickerState.fromMonth = new Date(fromDate);
    dateRangePickerState.toMonth = new Date(toDate);
    
    renderCalendars();
}

function changeMonth(calendar, months) {
    if (calendar === 'from') {
        dateRangePickerState.fromMonth.setMonth(dateRangePickerState.fromMonth.getMonth() + months);
    } else {
        dateRangePickerState.toMonth.setMonth(dateRangePickerState.toMonth.getMonth() + months);
    }
    renderCalendars();
}

function renderCalendars() {
    renderCalendar('from', dateRangePickerState.fromMonth, dateRangePickerState.fromDate);
    renderCalendar('to', dateRangePickerState.toMonth, dateRangePickerState.toDate);
    
    // Update month displays
    const fromMonthDisplay = document.getElementById('fromMonthDisplay');
    const toMonthDisplay = document.getElementById('toMonthDisplay');
    
    if (fromMonthDisplay) {
        fromMonthDisplay.textContent = dateRangePickerState.fromMonth.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    }
    if (toMonthDisplay) {
        toMonthDisplay.textContent = dateRangePickerState.toMonth.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    }
}

function renderCalendar(type, month, selectedDate) {
    const container = document.getElementById(type + 'Calendar');
    if (!container) return;
    
    const year = month.getFullYear();
    const monthIndex = month.getMonth();
    
    // First day of month
    const firstDay = new Date(year, monthIndex, 1);
    const lastDay = new Date(year, monthIndex + 1, 0);
    const daysInMonth = lastDay.getDate();
    const startingDayOfWeek = firstDay.getDay();
    
    // Previous month's last days
    const prevMonth = new Date(year, monthIndex, 0);
    const prevMonthDays = prevMonth.getDate();
    
    let html = '<div class="calendar-weekdays">';
    const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    weekdays.forEach(day => {
        html += `<div class="calendar-weekday">${day}</div>`;
    });
    html += '</div><div class="calendar-days">';
    
    // Previous month's trailing days
    for (let i = startingDayOfWeek - 1; i >= 0; i--) {
        const day = prevMonthDays - i;
        html += `<div class="calendar-day other-month" onclick="selectDate('${type}', ${year}, ${monthIndex - 1}, ${day})">${day}</div>`;
    }
    
    // Current month's days
    for (let day = 1; day <= daysInMonth; day++) {
        const date = new Date(year, monthIndex, day);
        const isToday = isSameDay(date, new Date());
        const isSelected = selectedDate && isSameDay(date, selectedDate);
        const isInRange = isDateInRange(date, dateRangePickerState.fromDate, dateRangePickerState.toDate);
        
        let classes = 'calendar-day';
        if (isSelected) classes += ' selected';
        if (isInRange) classes += ' in-range';
        if (isToday) classes += ' today';
        
        html += `<div class="${classes}" onclick="selectDate('${type}', ${year}, ${monthIndex}, ${day})">${day}</div>`;
    }
    
    // Next month's leading days
    const totalCells = 42; // 6 weeks * 7 days
    const cellsUsed = startingDayOfWeek + daysInMonth;
    const remainingCells = totalCells - cellsUsed;
    
    for (let day = 1; day <= remainingCells && day <= 14; day++) {
        html += `<div class="calendar-day other-month" onclick="selectDate('${type}', ${year}, ${monthIndex + 1}, ${day})">${day}</div>`;
    }
    
    html += '</div>';
    container.innerHTML = html;
}

function selectDate(type, year, month, day) {
    const date = new Date(year, month, day);
    
    if (type === 'from') {
        dateRangePickerState.fromDate = date;
        // If from date is after to date, update to date
        if (dateRangePickerState.toDate && date > dateRangePickerState.toDate) {
            dateRangePickerState.toDate = new Date(date);
        }
        dateRangePickerState.fromMonth = new Date(date);
    } else {
        dateRangePickerState.toDate = date;
        // If to date is before from date, update from date
        if (dateRangePickerState.fromDate && date < dateRangePickerState.fromDate) {
            dateRangePickerState.fromDate = new Date(date);
        }
        dateRangePickerState.toMonth = new Date(date);
    }
    
    renderCalendars();
}

function isSameDay(date1, date2) {
    if (!date1 || !date2) return false;
    return date1.getFullYear() === date2.getFullYear() &&
           date1.getMonth() === date2.getMonth() &&
           date1.getDate() === date2.getDate();
}

function isDateInRange(date, fromDate, toDate) {
    if (!date || !fromDate || !toDate) return false;
    return date >= fromDate && date <= toDate;
}

function applyDateRange() {
    console.log('[Date Range Picker] Apply button clicked');
    console.log('[Date Range Picker] From date:', dateRangePickerState.fromDate);
    console.log('[Date Range Picker] To date:', dateRangePickerState.toDate);
    
    if (dateRangePickerState.fromDate && dateRangePickerState.toDate) {
        updateDateRangeDisplay();
        closeDateRangePicker();
        console.log('[Date Range Picker] Loading P&L calendar data...');
        loadPnlCalendarData();
    } else {
        console.warn('[Date Range Picker] Dates not selected');
        alert('Please select both From and To dates');
    }
}

async function loadPnlCalendarData() {
    try {
        console.log('[P&L Calendar] Loading data...');
        
        if (!dateRangePickerState.fromDate || !dateRangePickerState.toDate) {
            console.warn('[P&L Calendar] Date range not set');
            return;
        }
        
        // Ensure filters are up to date
        updatePnlFilters();
        
        const startStr = formatDateForInput(dateRangePickerState.fromDate);
        const endStr = formatDateForInput(dateRangePickerState.toDate);
        const daysDiff = Math.ceil((dateRangePickerState.toDate - dateRangePickerState.fromDate) / (1000 * 60 * 60 * 24));
        
        console.log('[P&L Calendar] Date range:', startStr, 'to', endStr, `(${daysDiff + 1} days)`);
        console.log('[P&L Calendar] Filters:', pnlFilters);
        
        // Update date range display
        const dateRangeText = document.getElementById('pnlDateRangeText');
        if (dateRangeText) {
            dateRangeText.textContent = `${startStr} to ${endStr}`;
        }
        
        // Fetch data
        let result = { success: false, data: [] };
        try {
            const apiUrl = `/live/trades/daily-pnl?days=${daysDiff + 1}`;
            console.log('[P&L Calendar] Fetching from:', apiUrl);
            
            const response = await fetch(apiUrl);
            if (response.ok) {
                result = await response.json();
                console.log('[P&L Calendar] Data received:', result.success ? `${result.data?.length || 0} days` : 'Failed');
            } else {
                console.warn('[P&L Calendar] API returned non-OK status:', response.status);
                const errorText = await response.text();
                console.warn('[P&L Calendar] Error response:', errorText);
            }
        } catch (fetchError) {
            console.error('[P&L Calendar] Error fetching P&L data:', fetchError);
        }
        
        // Always render calendar, even if no data
        pnlCalendarData = {};
        if (result.success && result.data && Array.isArray(result.data)) {
            // Apply filters to the data
            let filteredData = result.data;
            
            // Filter by segment and symbol if needed (these would need backend support)
            // For now, we'll filter on the frontend if we have trade-level data
            // Note: The current API only returns daily aggregates, so segment/symbol filtering
            // would need to be implemented on the backend
            
            filteredData.forEach(day => {
                pnlCalendarData[day.date] = day;
            });
            
            console.log('[P&L Calendar] Processed', filteredData.length, 'days of data');
        } else {
            console.warn('[P&L Calendar] No data received or invalid response');
        }
        
        // Calculate Realised P&L summary
        let totalRealisedPnl = 0.0;
        let totalPaperPnl = 0.0;
        let totalLivePnl = 0.0;
        let totalTrades = 0;
        
        if (result.success && result.data && Array.isArray(result.data)) {
            result.data.forEach(day => {
                totalPaperPnl += parseFloat(day.paper_pnl || 0);
                totalLivePnl += parseFloat(day.live_pnl || 0);
                totalTrades += parseInt(day.paper_trades || 0) + parseInt(day.live_trades || 0);
            });
        }
        
        totalRealisedPnl = totalPaperPnl + totalLivePnl;
        
        console.log('[P&L Calendar] Summary - Realised:', totalRealisedPnl, 'Paper:', totalPaperPnl, 'Live:', totalLivePnl, 'Trades:', totalTrades);
        
        // Update Realised P&L summary
        updateRealisedPnlSummary(totalRealisedPnl, totalPaperPnl, totalLivePnl, totalTrades);
        
        // Always render calendar grid for the selected period
        console.log('[P&L Calendar] Rendering calendar...');
        renderPnlCalendar(dateRangePickerState.fromDate, dateRangePickerState.toDate);
        console.log('[P&L Calendar] Calendar rendered');
    } catch (error) {
        console.error('Error loading P&L calendar data:', error);
        // Still render empty grid on error
        pnlCalendarData = {};
        updateRealisedPnlSummary(0, 0, 0, 0);
        renderPnlCalendar(dateRangePickerState.fromDate, dateRangePickerState.toDate);
    }
}

function formatCurrency(amount) {
    if (amount === null || amount === undefined || isNaN(amount)) {
        return '₹0.00';
    }
    
    const absAmount = Math.abs(amount);
    let formatted;
    
    if (absAmount >= 100000) {
        formatted = '₹' + (amount / 100000).toFixed(2) + 'L';
    } else if (absAmount >= 1000) {
        formatted = '₹' + (amount / 1000).toFixed(2) + 'k';
    } else {
        formatted = '₹' + amount.toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }
    
    return formatted;
}

function updateRealisedPnlSummary(totalRealisedPnl, totalPaperPnl, totalLivePnl, totalTrades) {
    const realisedPnlEl = document.getElementById('realisedPnlValue');
    const paperPnlEl = document.getElementById('paperPnlValue');
    const livePnlEl = document.getElementById('livePnlValue');
    const totalTradesEl = document.getElementById('totalTradesCount');
    
    if (realisedPnlEl) {
        realisedPnlEl.textContent = formatCurrency(totalRealisedPnl);
        realisedPnlEl.style.color = totalRealisedPnl >= 0 ? '#10b981' : '#ef4444';
    }
    
    if (paperPnlEl) {
        paperPnlEl.textContent = formatCurrency(totalPaperPnl);
        paperPnlEl.style.color = totalPaperPnl >= 0 ? '#10b981' : '#ef4444';
    }
    
    if (livePnlEl) {
        livePnlEl.textContent = formatCurrency(totalLivePnl);
        livePnlEl.style.color = totalLivePnl >= 0 ? '#10b981' : '#ef4444';
    }
    
    if (totalTradesEl) {
        totalTradesEl.textContent = totalTrades;
    }
}

function renderPnlCalendar(startDate, endDate) {
    const container = document.getElementById('pnlCalendarHeatmap');
    if (!container) return;
    
    container.innerHTML = '';
    
    // Group days by month
    const months = {};
    const current = new Date(startDate);
    
    while (current <= endDate) {
        const year = current.getFullYear();
        const month = current.getMonth();
        const key = `${year}-${month}`;
        
        if (!months[key]) {
            months[key] = {
                year,
                month,
                days: []
            };
        }
        
        months[key].days.push(new Date(current));
        current.setDate(current.getDate() + 1);
    }
    
    // Render each month in chronological order
    const sortedMonthKeys = Object.keys(months).sort((a, b) => {
        const [yearA, monthA] = a.split('-').map(Number);
        const [yearB, monthB] = b.split('-').map(Number);
        
        // First compare by year
        if (yearA !== yearB) {
            return yearA - yearB;
        }
        // Then by month
        return monthA - monthB;
    });
    
    sortedMonthKeys.forEach(key => {
        const monthData = months[key];
        const monthColumn = document.createElement('div');
        monthColumn.className = 'pnl-month-column';
        
        // Month header
        const monthHeader = document.createElement('div');
        monthHeader.className = 'pnl-month-header';
        monthHeader.textContent = new Date(monthData.year, monthData.month, 1)
            .toLocaleDateString('en-US', { month: 'short' }).toUpperCase();
        monthColumn.appendChild(monthHeader);
        
        // Week rows
        const weekRows = [];
        let currentWeek = [];
        
        // Add empty cells for days before month start
        const firstDay = monthData.days[0];
        const firstDayOfWeek = firstDay.getDay(); // 0 = Sunday, 6 = Saturday
        for (let i = 0; i < firstDayOfWeek; i++) {
            currentWeek.push(null);
        }
        
        // Add days
        monthData.days.forEach(day => {
            if (currentWeek.length === 7) {
                weekRows.push(currentWeek);
                currentWeek = [];
            }
            currentWeek.push(day);
        });
        
        // Fill remaining week
        while (currentWeek.length < 7) {
            currentWeek.push(null);
        }
        weekRows.push(currentWeek);
        
        // Render week rows
        weekRows.forEach(week => {
            const weekRow = document.createElement('div');
            weekRow.className = 'pnl-week-row';
            
            week.forEach(day => {
                const dayCell = document.createElement('div');
                dayCell.className = 'pnl-day-cell';
                
                if (day) {
                    const dateStr = formatDateForInput(day);
                    const dayData = pnlCalendarData[dateStr];
                    
                    if (dayData) {
                        const pnlType = pnlFilters.type;
                        let pnl = 0;
                        
                        if (pnlType === 'combined') {
                            pnl = dayData.paper_pnl + dayData.live_pnl;
                        } else if (pnlType === 'paper') {
                            pnl = dayData.paper_pnl;
                        } else if (pnlType === 'live') {
                            pnl = dayData.live_pnl;
                        }
                        
                        // Determine color based on P&L
                        if (pnl > 0) {
                            if (pnl < 1000) {
                                dayCell.className += ' profit-small';
                            } else if (pnl < 5000) {
                                dayCell.className += ' profit-medium';
                            } else {
                                dayCell.className += ' profit-large';
                            }
                        } else if (pnl < 0) {
                            if (pnl > -1000) {
                                dayCell.className += ' loss-small';
                            } else if (pnl > -5000) {
                                dayCell.className += ' loss-medium';
                            } else {
                                dayCell.className += ' loss-large';
                            }
                        } else {
                            dayCell.className += ' no-data';
                        }
                        
                        // Enhanced tooltip with formatted currency
                        const formattedPnl = formatCurrency(pnl);
                        dayCell.title = `${dateStr}: ${formattedPnl}`;
                        dayCell.setAttribute('data-pnl', pnl);
                        dayCell.setAttribute('data-date', dateStr);
                        
                        // Enhanced hover tooltip (better styling)
                        dayCell.addEventListener('mouseenter', function(e) {
                            // Remove any existing tooltip
                            const existingTooltip = document.getElementById('pnlDayTooltip');
                            if (existingTooltip) {
                                existingTooltip.remove();
                            }
                            
                            const tooltip = document.createElement('div');
                            tooltip.id = 'pnlDayTooltip';
                            tooltip.style.cssText = `
                                position: fixed;
                                background: rgba(15, 23, 42, 0.95);
                                color: white;
                                padding: 8px 12px;
                                border-radius: 6px;
                                font-size: 12px;
                                font-weight: 500;
                                pointer-events: none;
                                z-index: 10000;
                                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
                                border: 1px solid rgba(255, 255, 255, 0.1);
                                white-space: nowrap;
                            `;
                            tooltip.textContent = `${dateStr}: ${formattedPnl}`;
                            document.body.appendChild(tooltip);
                            
                            const rect = dayCell.getBoundingClientRect();
                            const tooltipX = rect.left + rect.width / 2 - tooltip.offsetWidth / 2;
                            const tooltipY = rect.top - tooltip.offsetHeight - 8;
                            
                            // Ensure tooltip stays within viewport
                            tooltip.style.left = Math.max(8, Math.min(tooltipX, window.innerWidth - tooltip.offsetWidth - 8)) + 'px';
                            tooltip.style.top = Math.max(8, tooltipY) + 'px';
                        });
                        
                        dayCell.addEventListener('mouseleave', function() {
                            const tooltip = document.getElementById('pnlDayTooltip');
                            if (tooltip) {
                                tooltip.remove();
                            }
                        });
                        
                        // Click handler for details
                        dayCell.addEventListener('click', () => {
                            showDayDetails(dateStr, dayData);
                        });
                    } else {
                        dayCell.className += ' no-data';
                        dayCell.title = dateStr + '\nNo data';
                    }
                } else {
                    dayCell.className += ' no-data';
                    dayCell.style.visibility = 'hidden';
                }
                
                weekRow.appendChild(dayCell);
            });
            
            monthColumn.appendChild(weekRow);
        });
        
        container.appendChild(monthColumn);
    });
}

function showDayDetails(dateStr, dayData) {
    const pnlType = pnlFilters.type;
    let pnl = 0;
    
    if (pnlType === 'combined') {
        pnl = dayData.paper_pnl + dayData.live_pnl;
    } else if (pnlType === 'paper') {
        pnl = dayData.paper_pnl;
    } else if (pnlType === 'live') {
        pnl = dayData.live_pnl;
    }
    
    alert(`Date: ${dateStr}\n` +
          `Paper P&L: ₹${dayData.paper_pnl.toLocaleString('en-IN', {minimumFractionDigits: 2})}\n` +
          `Live P&L: ₹${dayData.live_pnl.toLocaleString('en-IN', {minimumFractionDigits: 2})}\n` +
          `Total P&L: ₹${pnl.toLocaleString('en-IN', {minimumFractionDigits: 2})}\n` +
          `Paper Trades: ${dayData.paper_trades}\n` +
          `Live Trades: ${dayData.live_trades}`);
}

// Cumulative P&L Chart - Radial Bar Chart (Spiral-like)
let cumulativePnlChart = null;
let cumulativePnlCanvas = null;
let cumulativePnlCtx = null;
let cumulativePnlData = {
    allTime: 0,
    year: 0,
    month: 0,
    week: 0,
    day: 0
};

function initializeCumulativePnlChart() {
    const canvas = document.getElementById('cumulativePnlChart');
    if (!canvas) return;
    
    cumulativePnlCanvas = canvas;
    cumulativePnlCtx = canvas.getContext('2d');
    
    // Set canvas size based on container
    function resizeCanvas() {
        const container = canvas.parentElement;
        const size = Math.min(container.clientWidth, container.clientHeight, 400);
        // Account for device pixel ratio for crisp rendering
        const dpr = window.devicePixelRatio || 1;
        const displaySize = size;
        canvas.width = displaySize * dpr;
        canvas.height = displaySize * dpr;
        canvas.style.width = displaySize + 'px';
        canvas.style.height = displaySize + 'px';
        cumulativePnlCtx.scale(dpr, dpr);
        drawRadialBarChart();
    }
    
    // Initial resize
    resizeCanvas();
    
    // Resize on window resize
    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(resizeCanvas, 100);
    });
}

function drawRadialBarChart() {
    if (!cumulativePnlCtx || !cumulativePnlCanvas) return;
    
    const ctx = cumulativePnlCtx;
    const canvas = cumulativePnlCanvas;
    // Use display size (not scaled size) for calculations
        const displaySize = parseInt(canvas.style.width) || 480; // Updated to match new size
    const centerX = displaySize / 2;
    const centerY = displaySize / 2;
    const maxRadius = Math.min(centerX, centerY) - 20;
    
    // Clear canvas (use display size)
    ctx.clearRect(0, 0, displaySize, displaySize);
    
    // Get all values (use absolute values for proportional sizing)
    const values = {
        allTime: Math.abs(cumulativePnlData.allTime) || 0,
        year: Math.abs(cumulativePnlData.year) || 0,
        month: Math.abs(cumulativePnlData.month) || 0,
        week: Math.abs(cumulativePnlData.week) || 0,
        day: Math.abs(cumulativePnlData.day) || 0
    };
    
    // Use Year as baseline (100%) - all arcs are proportional to Year
    const baselineValue = Math.max(values.year, 1); // Ensure at least 1 to avoid division by zero
    const maxArcPercentage = 0.92; // Never draw full circle (max 92% of full circle)
    
    // Define layers (from outer to inner) - each arc's length is proportional to its percentage of Year
    // All arcs have the same line width
    const lineWidth = 12; // Increased width for better visibility
    
    // Calculate proper radii for concentric circles with consistent spacing
    // Order matches legend: Cumulative (outermost), Year, Month, Week, Day (innermost)
    const radiusSpacing = 28; // Space between each arc
    const layers = [
        { 
            value: cumulativePnlData.allTime,
            absValue: values.allTime,
            label: 'Cumulative Profit', 
            color: 'rgba(34, 197, 94, 0.8)', 
            borderColor: '#22c55e', // Bright green for cumulative
            radius: maxRadius
        },
        { 
            value: cumulativePnlData.year,
            absValue: values.year,
            label: 'Year', 
            color: 'rgba(37, 99, 235, 0.8)', 
            borderColor: '#2563eb', // Blue
            radius: maxRadius - radiusSpacing
        },
        { 
            value: cumulativePnlData.month,
            absValue: values.month,
            label: 'Month', 
            color: 'rgba(139, 92, 246, 0.8)', 
            borderColor: '#8b5cf6', // Purple
            radius: maxRadius - (radiusSpacing * 2)
        },
        { 
            value: cumulativePnlData.week,
            absValue: values.week,
            label: 'Week', 
            color: 'rgba(20, 184, 166, 0.8)', 
            borderColor: '#14b8a6', // Teal - matching legend
            radius: maxRadius - (radiusSpacing * 3)
        },
        { 
            value: cumulativePnlData.day,
            absValue: values.day,
            label: 'Day', 
            color: 'rgba(249, 115, 22, 0.8)', 
            borderColor: '#f97316', // Orange - matching legend
            radius: maxRadius - (radiusSpacing * 4)
        }
    ];
    
    // Start angle (top, like the reference image)
    const startAngle = -Math.PI / 2; // Start from top (12 o'clock)
    const fullCircle = Math.PI * 2;
    
    // Draw each layer as an arc (never full circle)
    // Arc length is proportional to the percentage of Year (baseline = 100%)
    layers.forEach((layer, index) => {
        if (layer.absValue > 0 && baselineValue > 0) {
            // Calculate arc length proportional to Year (baseline = 100%)
            // Arc length = (value / baselineValue) * maxArcPercentage * fullCircle
            const percentageOfYear = layer.absValue / baselineValue;
            const arcPercentage = Math.min(percentageOfYear * maxArcPercentage, maxArcPercentage);
            const arcLength = arcPercentage * fullCircle;
            const endAngle = startAngle + arcLength;
            
            // Determine color based on profit/loss
            const isPositive = layer.value >= 0;
            const strokeColor = isPositive ? layer.borderColor : 'rgba(239, 68, 68, 1)'; // Red for negative
            
            // Draw the arc
            ctx.beginPath();
            ctx.arc(centerX, centerY, layer.radius, startAngle, endAngle);
            ctx.strokeStyle = strokeColor;
            ctx.lineWidth = lineWidth;
            ctx.lineCap = 'round'; // Rounded ends like the reference image
            ctx.stroke();
        } else {
            // If value is zero, show a green dot at the starting point
            const dotX = centerX + layer.radius * Math.cos(startAngle);
            const dotY = centerY + layer.radius * Math.sin(startAngle);
            ctx.beginPath();
            ctx.arc(dotX, dotY, 4, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(16, 185, 129, 1)'; // Green dot
            ctx.fill();
        }
    });
    
    // Center dot removed as per user request
    
    // Store layer data for tooltip (including angle information)
    cumulativePnlCanvas._layers = layers.map(layer => {
        const arcPercentage = layer.absValue > 0 
            ? Math.min((layer.absValue / baselineValue) * maxArcPercentage, maxArcPercentage)
            : 0;
        const arcLength = arcPercentage * fullCircle;
        return {
            ...layer,
            startAngle: startAngle,
            endAngle: startAngle + arcLength,
            arcPercentage: arcPercentage
        };
    });
}

async function updateCumulativePnl(fullUpdate = false) {
    if (!isAuthenticated) {
        return; // Don't fetch if not authenticated
    }
    
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    
    // Check if we need a full update (once per day)
    const needsFullUpdate = fullUpdate || 
                           !cumulativePnlCache.lastFullUpdate || 
                           cumulativePnlCache.lastFullUpdate < today;
    
    // Check if we need a Day update (every 5 minutes)
    const fiveMinutesAgo = now.getTime() - (5 * 60 * 1000);
    const needsDayUpdate = !cumulativePnlCache.lastDayUpdate || 
                          cumulativePnlCache.lastDayUpdate < fiveMinutesAgo;
    
    // If we have cached data and don't need updates, use cache
    if (cumulativePnlCache.data && !needsFullUpdate && !needsDayUpdate) {
        console.log('[Cumulative P&L] Using cached data');
        updateCumulativePnlDisplay(cumulativePnlCache.data);
        return;
    }
    
    try {
        // Use day_only parameter for frequent Day updates
        const url = needsFullUpdate ? '/api/cumulative-pnl' : '/api/cumulative-pnl?day_only=true';
        // Throttle: full updates every 60s, day-only every 5s
        const minInterval = needsFullUpdate ? 60000 : 5000;
        const response = await throttledFetch(url, {}, minInterval);
        if (!response) {
            // Request was throttled, use cache if available
            if (cumulativePnlCache.data) {
                updateCumulativePnlDisplay(cumulativePnlCache.data);
            }
            return;
        }
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (!data.success) {
            console.error('Cumulative P&L API error:', data.error || 'Unknown error');
            // Show error message to user
            const errorMsg = document.getElementById('cumulativePnlError');
            if (errorMsg) {
                errorMsg.textContent = `Error: ${data.error || 'Failed to load data'}`;
                errorMsg.style.display = 'block';
            }
            // Use cached data if available
            if (cumulativePnlCache.data) {
                updateCumulativePnlDisplay(cumulativePnlCache.data);
            }
            return;
        }
        
        if (!data.metrics) {
            console.error('Invalid cumulative P&L data: missing metrics', data);
            // Use cached data if available
            if (cumulativePnlCache.data) {
                updateCumulativePnlDisplay(cumulativePnlCache.data);
            }
            return;
        }
        
        // Update cache
        if (needsFullUpdate) {
            // Full update - cache all metrics
            cumulativePnlCache.data = data.metrics;
            cumulativePnlCache.lastFullUpdate = now;
            cumulativePnlCache.lastDayUpdate = now; // Also update Day timestamp
            console.log('[Cumulative P&L] Full update - cached all metrics');
        } else if (needsDayUpdate) {
            // Day-only update - merge Day value with cached data
            if (cumulativePnlCache.data) {
                cumulativePnlCache.data.day = data.metrics.day;
                cumulativePnlCache.lastDayUpdate = now;
                console.log('[Cumulative P&L] Day-only update - updated Day metric');
            } else {
                // No cache, do full update
                try {
                    const fullResponse = await fetch('/api/cumulative-pnl');
                    if (fullResponse.ok) {
                        const fullData = await safeJsonResponse(fullResponse);
                        if (fullData.success && fullData.metrics) {
                            cumulativePnlCache.data = fullData.metrics;
                            cumulativePnlCache.lastFullUpdate = now;
                            cumulativePnlCache.lastDayUpdate = now;
                        }
                    }
                } catch (fetchError) {
                    console.debug(`Error fetching full cumulative P&L: ${fetchError}`);
                    // Continue with empty cache
                }
            }
        }
        
        console.log('Cumulative P&L data received:', cumulativePnlCache.data);
        
        // Update display with cached data
        if (cumulativePnlCache.data) {
            updateCumulativePnlDisplay(cumulativePnlCache.data);
        }
        
    } catch (error) {
        console.error('Error updating cumulative P&L:', error);
        // Use cached data if available
        if (cumulativePnlCache.data) {
            updateCumulativePnlDisplay(cumulativePnlCache.data);
        }
    }
}

// Update the display with metrics data
function updateCumulativePnlDisplay(metrics) {
    try {
        // Hide error message if data is valid
        const errorMsg = document.getElementById('cumulativePnlError');
        if (errorMsg) {
            errorMsg.style.display = 'none';
        }
        
        // Store actual values for tooltip
        const actualValues = [
            metrics.all_time.value,
            metrics.year.value,
            metrics.month.value,
            metrics.week.value,
            metrics.day.value
        ];
        
        // Update radial bar chart data
        cumulativePnlData = {
            allTime: metrics.all_time.value,
            year: metrics.year.value,
            month: metrics.month.value,
            week: metrics.week.value,
            day: metrics.day.value
        };
        
        // Redraw radial bar chart
        drawRadialBarChart();
        
        // Add hover interaction with tooltips
        if (cumulativePnlCanvas) {
            let tooltip = null;
            
            // Create tooltip element
            function createTooltip() {
                if (tooltip) return tooltip;
                tooltip = document.createElement('div');
                tooltip.id = 'cumulativePnlTooltip';
                tooltip.style.cssText = `
                    position: absolute;
                    background: rgba(15, 23, 42, 0.95);
                    color: white;
                    padding: 10px 14px;
                    border-radius: 8px;
                    font-size: 13px;
                    font-weight: 500;
                    pointer-events: none;
                    z-index: 10000;
                    display: none;
                    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    line-height: 1.5;
                `;
                document.body.appendChild(tooltip);
                return tooltip;
            }
            
            cumulativePnlCanvas.onmousemove = function(e) {
                if (!cumulativePnlCanvas._layers) return;
                
                const rect = cumulativePnlCanvas.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                const displaySize = parseInt(cumulativePnlCanvas.style.width) || 400;
                const centerX = displaySize / 2;
                const centerY = displaySize / 2;
                const dx = x - centerX;
                const dy = y - centerY;
                const distance = Math.sqrt(dx * dx + dy * dy);
                const angle = Math.atan2(dy, dx);
                
                // Normalize angle to 0-2π range
                let normalizedAngle = angle < 0 ? angle + Math.PI * 2 : angle;
                
                // Find which layer is hovered based on distance and angle
                let hoveredLayer = null;
                const tolerance = 15; // Pixel tolerance for hover detection
                
                for (const layer of cumulativePnlCanvas._layers) {
                    const radiusDiff = Math.abs(distance - layer.radius);
                    
                    // Check if mouse is near this layer's radius
                    if (radiusDiff <= tolerance) {
                        // Check if angle is within the arc range
                        if (layer.absValue > 0 && layer.arcPercentage > 0) {
                            let layerStartNormalized = layer.startAngle < 0 ? layer.startAngle + Math.PI * 2 : layer.startAngle;
                            let layerEndNormalized = layer.endAngle < 0 ? layer.endAngle + Math.PI * 2 : layer.endAngle;
                            
                            // Handle wrap-around case
                            let isWithinArc = false;
                            if (layerEndNormalized > layerStartNormalized) {
                                isWithinArc = normalizedAngle >= layerStartNormalized && normalizedAngle <= layerEndNormalized;
                            } else {
                                // Arc wraps around
                                isWithinArc = normalizedAngle >= layerStartNormalized || normalizedAngle <= layerEndNormalized;
                            }
                            
                            if (isWithinArc) {
                                hoveredLayer = layer;
                                break;
                            }
                        } else {
                            // For zero values, check if near the starting point
                            const dotX = centerX + layer.radius * Math.cos(layer.startAngle);
                            const dotY = centerY + layer.radius * Math.sin(layer.startAngle);
                            const dotDistance = Math.sqrt((x - dotX) * (x - dotX) + (y - dotY) * (y - dotY));
                            if (dotDistance <= tolerance) {
                                hoveredLayer = layer;
                                break;
                            }
                        }
                    }
                }
                
                if (hoveredLayer) {
                    cumulativePnlCanvas.style.cursor = 'pointer';
                    
                    // Show tooltip
                    const tooltipEl = createTooltip();
                    const value = hoveredLayer.value;
                    const formattedValue = formatCurrency(value);
                    tooltipEl.innerHTML = `<strong>${hoveredLayer.label}</strong><br>P&L: ${formattedValue}`;
                    tooltipEl.style.display = 'block';
                    tooltipEl.style.left = (e.clientX + 15) + 'px';
                    tooltipEl.style.top = (e.clientY - 40) + 'px';
                } else {
                    cumulativePnlCanvas.style.cursor = 'default';
                    if (tooltip) {
                        tooltip.style.display = 'none';
                    }
                }
            };
            
            cumulativePnlCanvas.onmouseleave = function() {
                cumulativePnlCanvas.style.cursor = 'default';
                if (tooltip) {
                    tooltip.style.display = 'none';
                }
            };
        }
        
        // Update metric items
        updateMetricItem('all-time', metrics.all_time);
        updateMetricItem('year', metrics.year);
        updateMetricItem('month', metrics.month);
        updateMetricItem('week', metrics.week);
        updateMetricItem('day', metrics.day);
    } catch (error) {
        console.error('Error updating cumulative P&L display:', error);
    }
}

function updateMetricItem(id, metric) {
    // Calculate percentage relative to Year (baseline) - matching the chart design
    const yearValue = Math.abs(cumulativePnlData.year) || 1;
    const currentValue = Math.abs(metric.value) || 0;
    const percentage = yearValue > 0 ? (currentValue / yearValue) * 100 : 0;
    
    // Update value
    const valueEl = document.getElementById(`value-${id}`);
    if (valueEl) {
        const formattedValue = formatCurrency(metric.value);
        valueEl.textContent = formattedValue;
        // Keep the base class but color will be set by CSS based on metric ID
        valueEl.className = 'metric-value ' + (metric.value >= 0 ? 'positive' : 'negative');
    }
    
    // Update percentage
    const percentageEl = document.getElementById(`percentage-${id}`);
    if (percentageEl) {
        if (id === 'all-time') {
            // For All Time, show percentage relative to Year
            percentageEl.textContent = yearValue > 0 ? `(${percentage.toFixed(2)}%)` : '';
        } else if (id === 'year') {
            // Year is always 100%
            percentageEl.textContent = '(100.00%)';
        } else {
            percentageEl.textContent = `(${percentage.toFixed(2)}%)`;
        }
    }
    
    // Update label if provided
    const labelEl = document.getElementById(`label-${id}`);
    if (labelEl && metric.label) {
        labelEl.textContent = metric.label;
    }
}

// Auth Details Functions
function toggleAuthDetails() {
    const widget = document.getElementById('authDetailsWidget');
    const content = document.getElementById('authDetailsContent');
    const chevron = document.getElementById('authDetailsChevron');
    
    if (content.style.display === 'none') {
        content.style.display = 'block';
        widget.classList.add('expanded');
        updateAuthDetails();
    } else {
        content.style.display = 'none';
        widget.classList.remove('expanded');
    }
}

async function updateAuthDetails() {
    try {
        const response = await fetch('/api/auth/details');
        if (!response.ok) return;
        
        const data = await safeJsonResponse(response);
        if (!data.success || !data.details) return;
        
        const details = data.details;
        
        // Update each field - display full values (stored after authentication)
        const fields = {
            'authApiKey': details.api_key || '-',
            'authApiSecret': details.api_secret || '-',
            'authAccessToken': details.access_token || '-',
            'authRequestToken': details.request_token || 'Not stored after authentication',
            'authEmail': details.email || '-',
            'authBroker': details.broker || '-',
            'authUserId': details.user_id || '-',
            'authAccountName': details.account_name || '-'
        };
        
        for (const [id, value] of Object.entries(fields)) {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = value;
            }
        }
    } catch (error) {
        console.error('Error updating auth details:', error);
    }
}

// Make functions globally available
window.showHelp = showHelp;
window.closeHelp = closeHelp;
window.openDateRangePicker = openDateRangePicker;
window.closeDateRangePicker = closeDateRangePicker;
window.setQuickDateRange = setQuickDateRange;
window.changeMonth = changeMonth;
window.selectDate = selectDate;
window.applyDateRange = applyDateRange;
window.toggleAuthDetails = toggleAuthDetails;

