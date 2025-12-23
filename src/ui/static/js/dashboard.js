// Dashboard JavaScript for real-time updates

let updateInterval;
let positionsUpdateInterval; // Separate interval for positions and P&L
let pnlChart;

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    initializeChart();
    checkAuthStatus();
    startUpdates();
    setupEventListeners();
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

// Start real-time updates
function startUpdates() {
    updateAll();
    updateInterval = setInterval(updateAll, 2000); // Update every 2 seconds
    
    // Update positions and current P&L every 3 seconds
    updatePositionsAndPnl();
    positionsUpdateInterval = setInterval(updatePositionsAndPnl, 3000);
    
    // Check connectivity status every 2 seconds
    checkConnectivity();
    setInterval(checkConnectivity, 2000);
    // Check auth status every 10 seconds
    setInterval(checkAuthStatus, 10000);
}

// Update positions and current P&L together (runs every 3 seconds)
async function updatePositionsAndPnl() {
    try {
        // Update positions list
        await updatePositions();
        
        // Update current P&L from status endpoint
        await updateCurrentPnl();
    } catch (error) {
        console.error('Error updating positions and P&L:', error);
    }
}

// Update only the current P&L value
async function updateCurrentPnl() {
    try {
        const response = await fetch('/api/status');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.error) {
            console.error('Status error:', data.error);
            return;
        }
        
        // Update current P&L
        const currentPnl = data.profit_protection?.current_positions_pnl || 0;
        const currentPnlEl = document.getElementById('currentPnl');
        if (currentPnlEl) {
            currentPnlEl.textContent = formatCurrency(currentPnl);
            currentPnlEl.className = 'card-value ' + (currentPnl >= 0 ? 'positive' : 'negative');
            currentPnlEl.title = `Current Positions P&L: ${formatCurrency(currentPnl)}`;
        }
        
        // Calculate Total Day P&L = Protected Profit + Current Positions P&L
        // Get protected profit from the same status response
        const protectedProfit = data.profit_protection?.protected_profit || 0;
        const finalTotalPnl = protectedProfit + currentPnl;
        
        const totalPnlEl = document.getElementById('totalPnl');
        if (totalPnlEl) {
            totalPnlEl.textContent = formatCurrency(finalTotalPnl);
            totalPnlEl.className = 'card-value ' + (finalTotalPnl >= 0 ? 'positive' : 'negative');
            totalPnlEl.title = `Total Daily P&L: ${formatCurrency(finalTotalPnl)} (Protected: ${formatCurrency(protectedProfit)} + Current: ${formatCurrency(currentPnl)})`;
        }
    } catch (error) {
        console.error('Error updating current P&L:', error);
    }
}

// Check connectivity status
async function checkConnectivity() {
    try {
        const response = await fetch('/api/connectivity');
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

// Authentication functions
async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/status');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        const authStatusEl = document.getElementById('authStatus');
        if (authStatusEl) {
            if (data.authenticated) {
                authStatusEl.textContent = '✅ Authenticated';
                authStatusEl.style.background = '#28a745';
                authStatusEl.onclick = null;
                authStatusEl.style.cursor = 'default';
            } else {
                authStatusEl.textContent = '🔒 Not Authenticated';
                authStatusEl.style.background = '#dc3545';
                authStatusEl.onclick = showAuthModal;
                authStatusEl.style.cursor = 'pointer';
            }
        }
    } catch (error) {
        console.error('Error checking auth status:', error);
    }
}

function showAuthModal() {
    const modal = document.getElementById('authModal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function hideAuthModal() {
    const modal = document.getElementById('authModal');
    const errorEl = document.getElementById('authError');
    const errorElRequest = document.getElementById('authErrorRequest');
    const tokenInput = document.getElementById('requestToken');
    const accessTokenInput = document.getElementById('accessToken');
    
    if (modal) modal.style.display = 'none';
    if (errorEl) errorEl.style.display = 'none';
    if (errorElRequest) errorElRequest.style.display = 'none';
    if (tokenInput) tokenInput.value = '';
    if (accessTokenInput) accessTokenInput.value = '';
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
    const accessToken = document.getElementById('accessToken').value.trim();
    const errorEl = document.getElementById('authError');
    
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
            body: JSON.stringify({access_token: accessToken})
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.success) {
            hideAuthModal();
            checkAuthStatus();
            if (typeof addNotification === 'function') {
                addNotification('Successfully connected with access token!', 'success');
            }
            // Refresh data after authentication
            setTimeout(() => updateAll(), 2000);
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
    const requestToken = document.getElementById('requestToken').value.trim();
    const errorEl = document.getElementById('authErrorRequest');
    
    if (!requestToken) {
        if (errorEl) {
            errorEl.textContent = 'Please enter a request token';
            errorEl.style.display = 'block';
        }
        return;
    }
    
    try {
        if (errorEl) errorEl.style.display = 'none';
        
        const response = await fetch('/api/auth/authenticate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({request_token: requestToken})
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.success) {
            hideAuthModal();
            checkAuthStatus();
            if (typeof addNotification === 'function') {
                addNotification('Successfully authenticated with Zerodha!', 'success');
            }
            // Refresh data after authentication
            setTimeout(() => updateAll(), 2000);
        } else {
            if (errorEl) {
                errorEl.textContent = data.error || 'Authentication failed';
                errorEl.style.display = 'block';
            }
        }
    } catch (error) {
        console.error('Authentication error:', error);
        if (errorEl) {
            errorEl.textContent = 'Error: ' + error.message;
            errorEl.style.display = 'block';
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
    try {
        const response = await fetch('/api/status');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.error) {
            console.error('Status error:', data.error);
            // Show error status
            updatePnlStatus('error', 'Error loading P&L data');
            return;
        }
        
        // Update protected profit
        const protectedProfit = data.profit_protection?.protected_profit || 0;
        updateValue('protectedProfit', formatCurrency(protectedProfit), 'profit-card');
        
        // Update current P&L with clear status
        const currentPnl = data.profit_protection?.current_positions_pnl || 0;
        const currentPnlEl = document.getElementById('currentPnl');
        if (currentPnlEl) {
            currentPnlEl.textContent = formatCurrency(currentPnl);
            currentPnlEl.className = 'card-value ' + (currentPnl >= 0 ? 'positive' : 'negative');
            currentPnlEl.title = `Current Positions P&L: ${formatCurrency(currentPnl)}`;
        }
        
        // Calculate Total Day P&L = Protected Profit + Current Positions P&L
        // Always calculate from the displayed values to ensure perfect sync
        const totalPnl = protectedProfit + currentPnl;
        
        // Log for debugging if backend value doesn't match calculated value
        const backendTotalPnl = data.profit_protection?.total_daily_pnl;
        if (backendTotalPnl !== undefined && backendTotalPnl !== null && Math.abs(backendTotalPnl - totalPnl) > 0.01) {
            console.warn('Total P&L mismatch detected:', {
                backend: backendTotalPnl,
                calculated: totalPnl,
                protectedProfit: protectedProfit,
                currentPnl: currentPnl,
                difference: totalPnl - backendTotalPnl
            });
        }
        
        const totalPnlEl = document.getElementById('totalPnl');
        if (totalPnlEl) {
            totalPnlEl.textContent = formatCurrency(totalPnl);
            totalPnlEl.className = 'card-value ' + (totalPnl >= 0 ? 'positive' : 'negative');
            totalPnlEl.title = `Total Daily P&L: ${formatCurrency(totalPnl)} (Protected: ${formatCurrency(protectedProfit)} + Current: ${formatCurrency(currentPnl)})`;
        }
        updateValue('totalPnl', formatCurrency(totalPnl), 'total-card');
        
        // Update booked profit
        const bookedProfit = data.booked_profit || 0;
        updateValue('bookedProfit', formatCurrency(bookedProfit), 'booked-card');
        
        // Update net position P&L with clear status
        const netPositionPnl = data.net_position_pnl || 0;
        const netPnlEl = document.getElementById('netPositionPnl');
        if (netPnlEl) {
            netPnlEl.textContent = formatCurrency(netPositionPnl);
            netPnlEl.className = 'card-value ' + (netPositionPnl >= 0 ? 'positive' : 'negative');
            netPnlEl.title = `Net Position P&L: ${formatCurrency(netPositionPnl)}`;
        }
        
        // Update P&L status indicator
        const pnlStatus = data.connectivity?.connected ? 'connected' : 'disconnected';
        const pnlStatusMessage = data.connectivity?.connected ? 'P&L Updated Successfully' : 'P&L Update Failed - Check Connection';
        updatePnlStatus(pnlStatus, pnlStatusMessage);
        
        // Update loss protection
        const lossProtection = data.loss_protection || {};
        const dailyLoss = lossProtection.daily_loss || 0;
        const lossLimit = lossProtection.daily_loss_limit || 5000;
        updateValue('dailyLossUsed', formatCurrency(dailyLoss), 'loss-card');
        document.getElementById('lossUsed').textContent = formatCurrency(dailyLoss);
        document.getElementById('lossLimit').textContent = formatCurrency(lossLimit);
        
        // Update progress bar
        const lossPercentage = Math.min((dailyLoss / lossLimit) * 100, 100);
        document.getElementById('lossProgress').style.width = lossPercentage + '%';
        
        // Update trailing SL
        const trailingSl = data.trailing_sl || {};
        const trailingSlActive = trailingSl.trailing_sl_active || false;
        const trailingSlLevel = trailingSl.trailing_sl_level;
        const trailingSlStatusEl = document.getElementById('trailingSlStatus');
        trailingSlStatusEl.textContent = trailingSlActive ? 'Active' : 'Inactive';
        trailingSlStatusEl.className = 'card-value ' + (trailingSlActive ? 'active' : '');
        document.getElementById('trailingSlLevel').textContent = 
            trailingSlLevel ? formatCurrency(trailingSlLevel) : '-';
        
        // Update trading status
        const tradingStatus = data.trading_blocked ? 'Blocked' : 'Active';
        const tradingStatusEl = document.getElementById('tradingStatus');
        tradingStatusEl.textContent = tradingStatus;
        tradingStatusEl.className = 'card-value ' + (data.trading_blocked ? 'blocked' : 'active');
        
    } catch (error) {
        console.error('Error updating status:', error);
        updatePnlStatus('error', 'Error: ' + error.message);
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

// Update positions table
async function updatePositions() {
    try {
        const response = await fetch('/api/positions');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.error) {
            console.error('Positions error:', data.error);
            return;
        }
        
        const tbody = document.getElementById('positionsBody');
        const positionCount = document.getElementById('positionCount');
        
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No active positions</td></tr>';
            positionCount.textContent = '0';
            return;
        }
        
        positionCount.textContent = data.length;
        tbody.innerHTML = data.map(pos => {
            const quantityChange = pos.quantity_change || 0;
            const quantityChangeClass = quantityChange > 0 ? 'positive' : quantityChange < 0 ? 'negative' : '';
            
            // Display quantity with sign (negative for SELL positions)
            const quantity = pos.quantity;
            const quantityDisplay = quantityChange !== 0 
                ? `${quantity > 0 ? '+' : ''}${quantity} <span class="quantity-change ${quantityChangeClass}">(${quantityChange > 0 ? '+' : ''}${quantityChange})</span>`
                : `${quantity > 0 ? '+' : ''}${quantity}`;
            
            // Determine position type from quantity sign
            const positionType = quantity > 0 ? 'BUY' : 'SELL';
            const typeClass = positionType === 'BUY' ? 'positive' : 'negative';
            const typeLabel = positionType === 'BUY' ? '<span style="color: #10b981; font-size: 11px;">BUY</span>' : '<span style="color: #ef4444; font-size: 11px;">SELL</span>';
            
            return `
            <tr>
                <td>${pos.trading_symbol}</td>
                <td>${pos.exchange}</td>
                <td>₹${pos.entry_price.toFixed(2)}</td>
                <td>₹${pos.current_price ? pos.current_price.toFixed(2) : '-'}</td>
                <td class="${typeClass}">${quantityDisplay} ${typeLabel}</td>
                <td class="${pos.unrealized_pnl >= 0 ? 'positive' : 'negative'}">
                    ${formatCurrency(pos.unrealized_pnl)}
                </td>
                <td>
                    <button class="btn btn-primary" onclick="exitPosition(${pos.id})" style="padding: 6px 12px; font-size: 12px;">
                        Exit
                    </button>
                </td>
            </tr>
            `;
        }).join('');
    } catch (error) {
        console.error('Error updating positions:', error);
        const tbody = document.getElementById('positionsBody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-state">Error loading positions</td></tr>';
        }
    }
}

// Clear positions cache and fetch fresh from Zerodha
async function clearPositionsCache() {
    if (!confirm('Are you sure you want to clear the cache and fetch fresh positions from Zerodha? This will remove all cached positions.')) {
        return;
    }
    
    const btn = document.getElementById('clearCacheBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Clearing...';
    
    try {
        const response = await fetch('/api/positions/clear-cache', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await safeJsonResponse(response);
        
        if (data.success) {
            addNotification(
                `Cache cleared! ${data.synced_count || 0} fresh positions fetched from Zerodha`,
                'success'
            );
            // Refresh positions immediately
            setTimeout(() => {
                updatePositions();
                updateStatus();
            }, 500);
        } else {
            addNotification(`Failed to clear cache: ${data.error || 'Unknown error'}`, 'danger');
        }
    } catch (error) {
        console.error('Error clearing cache:', error);
        addNotification('Error clearing cache: ' + (error.message || 'Unknown error'), 'danger');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

// Make function globally available
window.clearPositionsCache = clearPositionsCache;

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
        const response = await fetch(url);
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
        
        tbody.innerHTML = trades.map(trade => {
            // Get transaction type (BUY or SELL) - use transaction_type from backend, fallback to quantity sign
            const transactionType = trade.transaction_type || (trade.quantity > 0 ? 'BUY' : 'SELL');
            const typeClass = transactionType === 'BUY' ? 'positive' : 'negative';
            const typeBadge = transactionType === 'BUY' 
                ? '<span style="color: #10b981; font-weight: 600; font-size: 12px;">BUY</span>' 
                : '<span style="color: #ef4444; font-weight: 600; font-size: 12px;">SELL</span>';
            
            // Format times in IST
            const entryTime = formatDateTimeIST(trade.entry_time);
            const exitTime = formatDateTimeIST(trade.exit_time);
            
            // Display quantity with proper sign (negative for SELL, positive for BUY)
            // For SELL trades, quantity should be negative (e.g., -150)
            const quantity = trade.quantity || 0;
            const quantityDisplay = quantity !== 0 ? (quantity > 0 ? `+${quantity}` : `${quantity}`) : '0';
            
            return `
            <tr>
                <td>${trade.trading_symbol || '-'}</td>
                <td>${entryTime}</td>
                <td>${exitTime}</td>
                <td>₹${(trade.entry_price || 0).toFixed(2)}</td>
                <td>₹${(trade.exit_price || 0).toFixed(2)}</td>
                <td class="${typeClass}" style="font-weight: 600;">${quantityDisplay}</td>
                <td class="${trade.is_profit ? 'positive' : 'negative'}">
                    ${formatCurrency(trade.realized_pnl || 0)}
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
    
    document.getElementById('totalTrades').textContent = summary.total_trades || 0;
    document.getElementById('totalProfit').textContent = formatCurrency(summary.total_profit || 0);
    document.getElementById('totalLoss').textContent = formatCurrency(summary.total_loss || 0);
    
    const netPnl = summary.total_pnl || 0;
    const netPnlEl = document.getElementById('netPnl');
    netPnlEl.textContent = formatCurrency(netPnl);
    netPnlEl.style.color = netPnl >= 0 ? '#10b981' : '#ef4444';
    
    const winRate = summary.total_trades > 0 
        ? ((summary.profitable_trades || 0) / summary.total_trades * 100).toFixed(1)
        : 0;
    document.getElementById('winRate').textContent = winRate + '%';
}

// Update daily stats
async function updateDailyStats() {
    try {
        const response = await fetch('/api/daily-stats');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await safeJsonResponse(response);
        
        if (data.error) {
            console.error('Daily stats error:', data.error);
            return;
        }
        
        // Update chart if needed
        if (pnlChart) {
            // Add data point to chart
            const now = new Date();
            pnlChart.data.labels.push(now.toLocaleTimeString());
            pnlChart.data.datasets[0].data.push(data.total_unrealized_pnl || 0);
            pnlChart.data.datasets[1].data.push(data.protected_profit || 0);
            pnlChart.data.datasets[2].data.push((data.total_unrealized_pnl || 0) + (data.protected_profit || 0));
            
            // Keep only last 50 data points
            if (pnlChart.data.labels.length > 50) {
                pnlChart.data.labels.shift();
                pnlChart.data.datasets.forEach(dataset => dataset.data.shift());
            }
            
            pnlChart.update('none');
        }
    } catch (error) {
        console.error('Error updating daily stats:', error);
    }
}

// Initialize chart
function initializeChart() {
    const ctx = document.getElementById('pnlChart');
    if (!ctx) return;
    
    pnlChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Current P&L',
                    data: [],
                    borderColor: 'rgb(37, 99, 235)',
                    backgroundColor: 'rgba(37, 99, 235, 0.1)',
                    tension: 0.4
                },
                {
                    label: 'Protected Profit',
                    data: [],
                    borderColor: 'rgb(16, 185, 129)',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    tension: 0.4
                },
                {
                    label: 'Total P&L',
                    data: [],
                    borderColor: 'rgb(245, 158, 11)',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                },
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    ticks: {
                        callback: function(value) {
                            return '₹' + value.toLocaleString('en-IN');
                        }
                    }
                }
            },
            animation: {
                duration: 0
            }
        }
    });
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
                <li><strong>Clear Cache & Refresh:</strong> Force refresh positions from Zerodha API</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                You bought 50 lots of NIFTY 25000CE at ₹100<br>
                Current price: ₹120<br>
                P&L: +₹1,000 (50 lots × ₹20 profit per lot)
            </div>
            
            <div class="help-note">
                <strong>Note:</strong> Positions update automatically every 3 seconds. Use "Clear Cache & Refresh" if you notice stale data.
            </div>
        `
    },
    'trade-history': {
        title: 'Trade History (All Inactive Trades)',
        content: `
            <h3>What is Trade History?</h3>
            <p>This section shows all your completed (closed) trades for the selected date, with detailed P&L information.</p>
            
            <h3>Information shown:</h3>
            <ul>
                <li><strong>Symbol:</strong> Trading symbol of the completed trade</li>
                <li><strong>Entry/Exit Time:</strong> When you entered and exited the position (IST)</li>
                <li><strong>Entry/Exit Price:</strong> Prices at which you entered and exited</li>
                <li><strong>Quantity:</strong> Number of lots/units traded</li>
                <li><strong>P&L:</strong> Realized profit or loss from this trade</li>
                <li><strong>Type:</strong> BUY or SELL transaction type</li>
            </ul>
            
            <h3>Features:</h3>
            <ul>
                <li><strong>Sync Orders from Zerodha:</strong> Fetch all completed orders and create trade records</li>
                <li><strong>Show All Trades:</strong> Toggle to show all trades or filter by date</li>
                <li><strong>Trade Summary:</strong> Shows total trades, profit, loss, net P&L, and win rate</li>
            </ul>
            
            <div class="help-example">
                <strong>Example:</strong><br>
                Trade 1: NIFTY 25000CE, Entry: ₹100, Exit: ₹120, Quantity: 50, P&L: +₹1,000<br>
                Trade 2: BANKNIFTY 50000PE, Entry: ₹80, Exit: ₹70, Quantity: 25, P&L: -₹250<br>
                <strong>Net P&L: ₹750</strong>
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

// Make functions globally available
window.showHelp = showHelp;
window.closeHelp = closeHelp;

