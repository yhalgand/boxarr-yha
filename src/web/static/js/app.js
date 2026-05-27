/**
 * Boxarr Frontend Application
 * Unified JavaScript for all pages
 */

// Get base path from injected variable (set in base.html)
const BASE_PATH = window.BOXARR_BASE_PATH || '';
const DEFAULT_MARKET = String(window.BOXARR_MARKET || 'us').toLowerCase();
const DEFAULT_PROVIDER = window.BOXARR_PROVIDER || 'mojo';

function getConfiguredMarkets() {
    const markets = window.BOXARR_MARKETS || {};
    return markets && typeof markets === 'object' ? markets : {};
}

function getMarketDefinition(market) {
    const normalized = String(market || '').trim().toLowerCase();
    const markets = getConfiguredMarkets();
    return markets[normalized] || null;
}

function getHistoricalCapabilities(market = getCurrentMarket()) {
    const definition = getMarketDefinition(market) || {};
    const historical = definition?.capabilities?.historical || {};
    const currentYear = new Date().getFullYear();
    const minYear = Number.isFinite(Number(historical.min_year)) ? Number(historical.min_year) : 1982;
    const maxYear = Number.isFinite(Number(historical.max_year)) ? Number(historical.max_year) : currentYear;
    return { minYear, maxYear };
}

function providerForMarket(market) {
    const definition = getMarketDefinition(market);
    if (definition && definition.provider) {
        return String(definition.provider).toLowerCase();
    }
    return String(market || 'us').toLowerCase() === 'fr' ? 'jpboxoffice' : 'mojo';
}

function marketForProvider(provider) {
    const normalizedProvider = String(provider || 'mojo').toLowerCase();
    const markets = getConfiguredMarkets();
    for (const [marketKey, definition] of Object.entries(markets)) {
        if (String(definition?.provider || '').toLowerCase() === normalizedProvider) {
            return marketKey;
        }
    }
    if (normalizedProvider === 'jpboxoffice_fr' || normalizedProvider === 'jpboxoffice') {
        return 'fr';
    }
    return 'us';
}

function normalizeMarket(market) {
    const value = String(market || '').trim().toLowerCase();
    const markets = getConfiguredMarkets();
    if (markets[value]) {
        return value;
    }
    if (value === 'fr' || value === 'us') {
        return value;
    }
    for (const [marketKey, definition] of Object.entries(markets)) {
        if (String(definition?.provider || '').toLowerCase() === value) {
            return marketKey;
        }
    }
    return DEFAULT_MARKET;
}

function getUrlMarket() {
    const params = new URL(window.location.href).searchParams;
    const urlMarket = params.get('market');
    if (urlMarket) {
        return normalizeMarket(urlMarket);
    }
    const urlProvider = params.get('provider');
    if (urlProvider) {
        return marketForProvider(urlProvider);
    }
    return null;
}

function getCurrentMarket() {
    return normalizeMarket(
        getUrlMarket() || localStorage.getItem('boxarr-market') || DEFAULT_MARKET
    );
}

function getCurrentProvider() {
    return providerForMarket(getCurrentMarket());
}

function setMarketPreference(market) {
    const normalizedMarket = normalizeMarket(market);
    localStorage.setItem('boxarr-market', normalizedMarket);
    window.BOXARR_MARKET = normalizedMarket;
    window.BOXARR_PROVIDER = providerForMarket(normalizedMarket);

    const url = new URL(window.location.href);
    url.searchParams.set('market', normalizedMarket);
    url.searchParams.delete('provider');
    window.location.href = url.toString();
}

function apiUrlWithMarket(endpoint, market = getCurrentMarket()) {
    const url = new URL(apiUrl(endpoint), window.location.origin);
    url.searchParams.set('market', normalizeMarket(market));
    return url.toString();
}

function pageUrlWithMarket(path, market = getCurrentMarket()) {
    const url = new URL(makeUrl(path), window.location.origin);
    url.searchParams.set('market', normalizeMarket(market));
    url.searchParams.delete('provider');
    return url.toString();
}

// URL helper functions
function makeUrl(path) {
    // Ensure path starts with /
    if (!path.startsWith('/')) {
        path = '/' + path;
    }
    return BASE_PATH + path;
}

function apiUrl(endpoint) {
    // Ensure endpoint starts with /
    if (!endpoint.startsWith('/')) {
        endpoint = '/' + endpoint;
    }
    return makeUrl('/api' + endpoint);
}

// Helper to check if current path matches a given path (handling base path)
function isCurrentPath(targetPath) {
    const currentPath = window.location.pathname;
    const expectedPath = makeUrl(targetPath);
    return currentPath === expectedPath;
}

// Helper to get path without base
function getPathWithoutBase() {
    const currentPath = window.location.pathname;
    if (BASE_PATH && currentPath.startsWith(BASE_PATH)) {
        return currentPath.substring(BASE_PATH.length);
    }
    return currentPath;
}

// Safe URL construction that prevents double-prefixing
function safeUrl(path) {
    // If path is already absolute and contains base path, return as-is
    if (BASE_PATH && path.startsWith(BASE_PATH)) {
        return path;
    }
    // Otherwise use makeUrl to add base path
    return makeUrl(path);
}

// Scheduler Debug Functions (Global scope for onclick handlers)
function toggleSchedulerDebug() {
    const content = document.getElementById('schedulerDebugContent');
    const icon = document.querySelector('.collapse-icon');
    
    if (content && icon) {
        if (content.style.display === 'none') {
            content.style.display = 'block';
            icon.textContent = '▼';
            refreshSchedulerStatus();
        } else {
            content.style.display = 'none';
            icon.textContent = '▶';
        }
    }
}

// Auto-Add Options Functions
function toggleAutoAddOptions() {
    const checkbox = document.getElementById('autoAdd');
    const options = document.getElementById('autoAddOptions');
    
    if (checkbox && options) {
        if (checkbox.checked) {
            options.classList.add('active');
        } else {
            options.classList.remove('active');
        }
    }
}

function toggleGenreFilter() {
    const checkbox = document.getElementById('genreFilterEnabled');
    const options = document.getElementById('genreFilterOptions');
    
    if (checkbox && options) {
        if (checkbox.checked) {
            options.classList.add('active');
        } else {
            options.classList.remove('active');
        }
    }
}

function toggleRatingFilter() {
    const checkbox = document.getElementById('ratingFilterEnabled');
    const options = document.getElementById('ratingFilterOptions');
    
    if (checkbox && options) {
        if (checkbox.checked) {
            options.classList.add('active');
        } else {
            options.classList.remove('active');
        }
    }
}

function toggleLanguageFilter() {
    const checkbox = document.getElementById('languageFilterEnabled');
    const options = document.getElementById('languageFilterOptions');

    if (checkbox && options) {
        if (checkbox.checked) {
            options.classList.add('active');
        } else {
            options.classList.remove('active');
        }
    }
}

function updateLanguageMode() {
    const mode = document.querySelector('input[name="boxarr_features_auto_add_language_filter_mode"]:checked');
    const label = document.getElementById('languageListLabel');
    const languageCheckboxes = document.querySelectorAll('[name^="language_"]');

    if (mode && label) {
        if (mode.value === 'whitelist') {
            label.textContent = 'Allowed Languages';
            languageCheckboxes.forEach(checkbox => {
                checkbox.checked = checkbox.dataset.languageWhitelist === 'true';
            });
        } else {
            label.textContent = 'Excluded Languages';
            languageCheckboxes.forEach(checkbox => {
                checkbox.checked = checkbox.dataset.languageBlacklist === 'true';
            });
        }
    }
}

// Auto-Tag toggle
function toggleAutoTag() {
    const checkbox = document.getElementById('autoTagEnabled');
    const input = document.getElementById('autoTagText');
    if (checkbox && input) {
        input.disabled = !checkbox.checked;
    }
}

// Minimum Availability toggle
function toggleMinimumAvailability() {
    const checkbox = document.getElementById('minAvailabilityEnabled');
    const select = document.getElementById('minimumAvailability');
    if (checkbox && select) {
        const enabled = checkbox.checked;
        select.disabled = !enabled;
        // Subtle UI cue by changing opacity
        select.style.opacity = enabled ? '1' : '0.6';
    }
}

function updateGenreMode() {
    const mode = document.querySelector('input[name="boxarr_features_auto_add_genre_filter_mode"]:checked');
    const label = document.getElementById('genreListLabel');
    const genreCheckboxes = document.querySelectorAll('[name^="genre_"]');
    
    if (mode && label) {
        if (mode.value === 'whitelist') {
            label.textContent = 'Allowed Genres';
            // Clear all and set from whitelist data
            genreCheckboxes.forEach(checkbox => {
                checkbox.checked = checkbox.dataset.genreWhitelist === 'true';
            });
        } else {
            label.textContent = 'Excluded Genres';
            // Clear all and set from blacklist data
            genreCheckboxes.forEach(checkbox => {
                checkbox.checked = checkbox.dataset.genreBlacklist === 'true';
            });
        }
    }
}

function refreshSchedulerStatus() {
    fetch(apiUrlWithMarket('/scheduler/status'))
        .then(response => response.json())
        .then(data => {
            // Update service status
            const serviceStatus = document.getElementById('debugServiceStatus');
            const statusBadge = document.getElementById('schedulerStatusBadge');
            
            if (serviceStatus) {
                if (data.running && data.jobs && data.jobs.length > 0) {
                    serviceStatus.innerHTML = '<span style="color: #48bb78;">✓ Running</span>';
                    if (statusBadge) {
                        statusBadge.innerHTML = '🟢';
                        statusBadge.title = 'Scheduler is running';
                    }
                } else if (data.running) {
                    serviceStatus.innerHTML = '<span style="color: #f6ad55;">⚠ Running (No Jobs)</span>';
                    if (statusBadge) {
                        statusBadge.innerHTML = '🟡';
                        statusBadge.title = 'Scheduler running but no jobs scheduled';
                    }
                } else {
                    serviceStatus.innerHTML = '<span style="color: #f56565;">✗ Not Running</span>';
                    if (statusBadge) {
                        statusBadge.innerHTML = '🔴';
                        statusBadge.title = 'Scheduler is not running';
                    }
                }
            }
            
            // Update next run
            const nextRun = document.getElementById('debugNextRun');
            if (nextRun) {
                if (data.next_run_time) {
                    const nextTime = new Date(data.next_run_time);
                    const timeUntil = data.time_until_next;
                    if (timeUntil) {
                        nextRun.innerHTML = `${nextTime.toLocaleString()} <small>(in ${timeUntil.days}d ${timeUntil.hours}h ${timeUntil.minutes}m)</small>`;
                    } else {
                        nextRun.innerHTML = nextTime.toLocaleString();
                    }
                } else {
                    nextRun.innerHTML = 'No scheduled runs';
                }
            }
            
            // Update last run
            const lastRun = document.getElementById('debugLastRun');
            if (lastRun) {
                if (data.last_run) {
                    const lastTime = new Date(data.last_run.timestamp);
                    lastRun.innerHTML = `${lastTime.toLocaleString()} <small>(${data.last_run.matched_count}/${data.last_run.total_count} matched)</small>`;
                } else {
                    lastRun.innerHTML = 'No previous runs';
                }
            }
            
            // Update active jobs
            const activeJobs = document.getElementById('debugActiveJobs');
            if (activeJobs) {
                activeJobs.innerHTML = data.jobs ? data.jobs.length : '0';
            }
            
            // Update timezone
            const timezone = document.getElementById('debugTimezone');
            if (timezone) {
                timezone.innerHTML = data.timezone || 'Unknown';
            }
        })
        .catch(error => {
            console.error('Error fetching scheduler status:', error);
            const serviceStatus = document.getElementById('debugServiceStatus');
            if (serviceStatus) {
                serviceStatus.innerHTML = '<span style="color: #f56565;">Error loading status</span>';
            }
        });
}

function triggerScheduler() {
    if (!confirm('Manually trigger box office update now?')) return;
    
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Triggering...';
    
    fetch(apiUrlWithMarket('/scheduler/trigger'), { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert(`Update completed! Found ${data.movies_found} movies, added ${data.movies_added || 0} new movies.`);
                refreshSchedulerStatus();
            } else {
                alert(`Update failed: ${data.message}`);
            }
        })
        .catch(error => {
            alert(`Error: ${error.message}`);
        })
        .finally(() => {
            btn.disabled = false;
            btn.textContent = '▶ Trigger Now';
        });
}

function reloadScheduler() {
    if (!confirm('Reload scheduler with current settings?')) return;
    
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Reloading...';
    
    fetch(apiUrlWithMarket('/scheduler/reload'), { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert(`Scheduler reloaded! Next run: ${new Date(data.next_run).toLocaleString()}`);
                refreshSchedulerStatus();
            } else {
                alert(`Reload failed: ${data.message}`);
            }
        })
        .catch(error => {
            alert(`Error: ${error.message}`);
        })
        .finally(() => {
            btn.disabled = false;
            btn.textContent = '🔄 Reload';
        });
}

(function() {
    'use strict';

    // Global state
    let statusCheckInterval = null;
    let isModalOpen = false;
    let connectionTested = false;

    // ==========================================
    // Core Functions
    // ==========================================

    /**
     * Check connection status to API
     */
    function checkConnection() {
        const statusDot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');
        
        // Skip if elements don't exist (e.g., on setup page)
        if (!statusDot || !statusText) return;
        
        fetch(apiUrlWithMarket('/health'))
            .then(response => {
                if (response.ok) {
                    statusDot.classList.add('connected');
                    statusDot.classList.remove('error');
                    statusText.textContent = 'Connected';
                } else {
                    throw new Error('Connection failed');
                }
            })
            .catch(error => {
                if (statusDot) {
                    statusDot.classList.add('error');
                    statusDot.classList.remove('connected');
                }
                if (statusText) {
                    statusText.textContent = 'Disconnected';
                }
            });
    }

    /**
     * Check for application updates
     */
    function checkForUpdates() {
        fetch(apiUrlWithMarket('/config/check-update'))
            .then(response => response.json())
            .then(data => {
                if (data.update_available) {
                    const notification = document.getElementById('updateNotification');
                    const updateText = document.getElementById('updateText');
                    
                    if (notification) {
                        // Set the changelog URL
                        if (data.changelog_url) {
                            notification.href = data.changelog_url;
                        } else if (data.release_url) {
                            notification.href = data.release_url;
                        }
                        
                        // Update the text
                        if (updateText) {
                            updateText.textContent = "See what's changed";
                        }
                        
                        // Show the notification
                        notification.classList.add('show');
                        
                        // Log for debugging
                        console.log(`Update available: v${data.current_version} → v${data.latest_version}`);
                    }
                }
            })
            .catch(error => {
                console.error('Error checking for updates:', error);
            });
    }

    /**
     * Show a temporary message to the user
     */
    function showMessage(message, type = 'info') {
        console.log(`[${type}] ${message}`);
        
        // Create toast notification
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 1rem 1.5rem;
            background: ${type === 'success' ? '#48bb78' : type === 'error' ? '#f56565' : '#667eea'};
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 10000;
            animation: slideIn 0.3s ease;
        `;
        
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // ==========================================
    // Dashboard Functions
    // ==========================================

    window.updateCurrentWeek = function() {
        const modal = document.getElementById('progressModal');
        const progressMessage = document.getElementById('progressMessage');
        const progressLog = document.getElementById('progressLog');
        const progressFooter = document.getElementById('progressFooter');
        
        if (modal) {
            modal.classList.add('show');
            isModalOpen = true;
        }
        
        // Clear previous log and set initial message
        if (progressLog) progressLog.innerHTML = '';
        if (progressMessage) progressMessage.textContent = 'Fetching box office data from Box Office Mojo...';
        if (progressFooter) progressFooter.style.display = 'none';
        
        // Add log entry
        function addLogEntry(message, type = 'info') {
            if (progressLog) {
                const entry = document.createElement('div');
                entry.style.color = type === 'error' ? '#f56565' : type === 'success' ? '#48bb78' : '#718096';
                entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
                progressLog.appendChild(entry);
                progressLog.scrollTop = progressLog.scrollHeight;
            }
        }
        
        addLogEntry('Starting box office update...');
        
        fetch(apiUrlWithMarket('/scheduler/trigger'), { method: 'POST' })
            .then(response => {
                addLogEntry('Received response from server');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    addLogEntry(`Found ${data.movies_found || 0} movies`, 'success');
                    if (data.movies_added && data.movies_added > 0) {
                        addLogEntry(`Added ${data.movies_added} new movies to Radarr`, 'success');
                    }
                    if (progressMessage) progressMessage.textContent = '✅ Update completed successfully!';
                    addLogEntry('Update completed!', 'success');
                    if (progressFooter) progressFooter.style.display = 'block';
                    setTimeout(() => window.location.reload(), 2000);
                } else {
                    const errorMsg = data.message || data.error || 'Unknown error occurred';
                    if (progressMessage) progressMessage.textContent = '❌ Update failed';
                    addLogEntry(`Error: ${errorMsg}`, 'error');
                    
                    // Provide helpful error messages
                    if (errorMsg.includes('connection') || errorMsg.includes('Connection')) {
                        addLogEntry('Please check your Radarr connection settings', 'error');
                    } else if (errorMsg.includes('API')) {
                        addLogEntry('Please verify your Radarr API key', 'error');
                    }
                    
                    if (progressFooter) progressFooter.style.display = 'block';
                }
            })
            .catch(error => {
                if (progressMessage) progressMessage.textContent = '❌ Network error';
                addLogEntry(`Network error: ${error.message}`, 'error');
                addLogEntry('Please check if the Boxarr server is running', 'error');
                if (progressFooter) progressFooter.style.display = 'block';
            });
    };

    // Global variables for historical week selection
    let selectedHistoricalWeekUrl = null;
    let selectedHistoricalWeekText = null;

    window.showHistoricalWeekModal = function(weekUrl, weekText) {
        selectedHistoricalWeekUrl = weekUrl;
        selectedHistoricalWeekText = weekText;
        
        const modal = document.getElementById('historicalWeekModal');
        const weekTextEl = document.getElementById('selectedWeekText');
        
        if (weekTextEl) {
            weekTextEl.textContent = weekText;
        }
        
        if (modal) {
            modal.classList.add('show');
            isModalOpen = true;
        }
    };

    window.closeHistoricalWeekModal = function() {
        const modal = document.getElementById('historicalWeekModal');
        if (modal) {
            modal.classList.remove('show');
            isModalOpen = false;
        }
        selectedHistoricalWeekUrl = null;
        selectedHistoricalWeekText = null;
    };

    window.fetchHistoricalWeek = function() {
        if (!selectedHistoricalWeekUrl) return;
        
        const weekMatch = selectedHistoricalWeekUrl.match(/\/(\d{4})W(\d{2})/);
        
        if (!weekMatch) {
            showMessage('Invalid week format', 'error');
            return;
        }
        
        const year = weekMatch[1];
        const week = weekMatch[2];
        
        closeHistoricalWeekModal();
        
        const modal = document.getElementById('progressModal');
        const progressTitle = document.getElementById('progressTitle');
        const progressMessage = document.getElementById('progressMessage');
        const progressLog = document.getElementById('progressLog');
        const progressFooter = document.getElementById('progressFooter');
        
        if (modal) {
            modal.classList.add('show');
            isModalOpen = true;
        }
        if (progressTitle) {
            progressTitle.textContent = `Fetching ${selectedHistoricalWeekText}`;
        }
        
        // Clear previous log and set initial message
        if (progressLog) progressLog.innerHTML = '';
        if (progressMessage) progressMessage.textContent = `Fetching box office data for ${selectedHistoricalWeekText}...`;
        if (progressFooter) progressFooter.style.display = 'none';
        
        // Add log entry helper
        function addLogEntry(message, type = 'info') {
            if (progressLog) {
                const entry = document.createElement('div');
                entry.style.color = type === 'error' ? '#f56565' : type === 'success' ? '#48bb78' : '#718096';
                entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
                progressLog.appendChild(entry);
                progressLog.scrollTop = progressLog.scrollHeight;
            }
        }
        
        addLogEntry(`Starting historical data fetch for ${selectedHistoricalWeekText}`);
        
        fetch(apiUrlWithMarket('/scheduler/update-week'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                year: parseInt(year), 
                week: parseInt(week),
                market: getCurrentMarket(),
            })
        })
        .then(response => {
            addLogEntry('Received response from server');
            return response.json();
        })
        .then(data => {
            if (data.success) {
                addLogEntry(`Found ${data.movies_found || 0} movies`, 'success');
                if (data.movies_added && data.movies_added > 0) {
                    addLogEntry(`Added ${data.movies_added} new movies to Radarr`, 'success');
                }
                if (progressMessage) progressMessage.textContent = '✅ Historical week fetched successfully!';
                addLogEntry('Update completed!', 'success');
                if (progressFooter) progressFooter.style.display = 'block';
                setTimeout(() => window.location.href = safeUrl(selectedHistoricalWeekUrl), 2000);
            } else {
                const errorMsg = data.message || data.error || 'Unknown error occurred';
                if (progressMessage) progressMessage.textContent = '❌ Fetch failed';
                addLogEntry(`Error: ${errorMsg}`, 'error');
                
                // Provide helpful error messages
                if (errorMsg.includes('already exists')) {
                    addLogEntry('This week has already been fetched', 'error');
                } else if (errorMsg.includes('not found')) {
                    addLogEntry('No box office data available for this week', 'error');
                }
                
                if (progressFooter) progressFooter.style.display = 'block';
            }
        })
        .catch(error => {
            if (progressMessage) progressMessage.textContent = '❌ Network error';
            addLogEntry(`Network error: ${error.message}`, 'error');
            addLogEntry('Please check if the Boxarr server is running', 'error');
            if (progressFooter) progressFooter.style.display = 'block';
        });
    };

    window.showHistoricalUpdate = function() {
        const modal = document.getElementById('historicalModal');
        if (modal) {
            modal.classList.add('show');
            isModalOpen = true;
        }
    };

    window.closeHistoricalUpdate = function() {
        const modal = document.getElementById('historicalModal');
        if (modal) {
            modal.classList.remove('show');
            isModalOpen = false;
        }
    };

    window.updateHistoricalWeek = function() {
        const year = document.getElementById('historicalYear').value;
        const week = document.getElementById('historicalWeek').value;
        
        closeHistoricalUpdate();
        
        const modal = document.getElementById('progressModal');
        const progressTitle = document.getElementById('progressTitle');
        const progressMessage = document.getElementById('progressMessage');
        const progressLog = document.getElementById('progressLog');
        const progressFooter = document.getElementById('progressFooter');
        
        if (modal) {
            modal.classList.add('show');
            isModalOpen = true;
        }
        if (progressTitle) {
            progressTitle.textContent = `Updating Week ${week}, ${year}`;
        }
        
        // Clear previous log and set initial message
        if (progressLog) progressLog.innerHTML = '';
        if (progressMessage) progressMessage.textContent = `Fetching box office data for Week ${week}, ${year}...`;
        if (progressFooter) progressFooter.style.display = 'none';
        
        // Add log entry helper
        function addLogEntry(message, type = 'info') {
            if (progressLog) {
                const entry = document.createElement('div');
                entry.style.color = type === 'error' ? '#f56565' : type === 'success' ? '#48bb78' : '#718096';
                entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
                progressLog.appendChild(entry);
                progressLog.scrollTop = progressLog.scrollHeight;
            }
        }
        
        addLogEntry(`Starting historical data fetch for Week ${week}, ${year}`);
        
        fetch(apiUrlWithMarket('/scheduler/update-week'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                year: parseInt(year), 
                week: parseInt(week),
                market: getCurrentMarket(),
            })
        })
        .then(response => {
            addLogEntry('Received response from server');
            return response.json();
        })
        .then(data => {
            if (data.success) {
                addLogEntry(`Found ${data.movies_found || 0} movies`, 'success');
                if (data.movies_added && data.movies_added > 0) {
                    addLogEntry(`Added ${data.movies_added} new movies to Radarr`, 'success');
                }
                if (progressMessage) progressMessage.textContent = '✅ Historical week updated successfully!';
                addLogEntry('Update completed!', 'success');
                if (progressFooter) progressFooter.style.display = 'block';
                setTimeout(() => window.location.href = pageUrlWithMarket(`/${year}W${String(week).padStart(2, '0')}`), 2000);
            } else {
                const errorMsg = data.message || data.error || 'Unknown error occurred';
                if (progressMessage) progressMessage.textContent = '❌ Update failed';
                addLogEntry(`Error: ${errorMsg}`, 'error');
                
                // Provide helpful error messages
                if (errorMsg.includes('already exists')) {
                    addLogEntry('This week has already been fetched', 'error');
                } else if (errorMsg.includes('not found')) {
                    addLogEntry('No box office data available for this week', 'error');
                }
                
                if (progressFooter) progressFooter.style.display = 'block';
            }
        })
        .catch(error => {
            if (progressMessage) progressMessage.textContent = '❌ Network error';
            addLogEntry(`Network error: ${error.message}`, 'error');
            addLogEntry('Please check if the Boxarr server is running', 'error');
            if (progressFooter) progressFooter.style.display = 'block';
        });
    };

    window.closeProgressModal = function() {
        const modal = document.getElementById('progressModal');
        if (modal) {
            modal.classList.remove('show');
            isModalOpen = false;
        }
        window.location.reload();
    };

    window.deleteWeek = function(year, week) {
        if (confirm(`Are you sure you want to delete Week ${week}, ${year}?`)) {
            fetch(apiUrlWithMarket(`/weeks/${year}/W${week}/delete`), { method: 'DELETE' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showMessage('Week deleted successfully', 'success');
                        setTimeout(() => window.location.reload(), 1000);
                    } else {
                        showMessage('Failed to delete week: ' + (data.message || data.error || 'Unknown error'), 'error');
                    }
                })
                .catch(error => {
                    showMessage('Error deleting week: ' + error.message, 'error');
                });
        }
    };

    window.changePageSize = function(newSize) {
        const urlParams = new URLSearchParams(window.location.search);
        urlParams.set('per_page', newSize);
        urlParams.set('page', '1'); // Reset to first page when changing page size
        window.location.href = pageUrlWithMarket(`/dashboard?${urlParams.toString()}`);
    };

    // ==========================================
    // Weekly Page Functions
    // ==========================================

    function updateMovieStatuses() {
        const movieCards = document.querySelectorAll('.movie-card[data-movie-id]');
        const movieIds = Array.from(movieCards)
            .map(card => card.dataset.movieId)
            .filter(id => id && id !== '');
        
        if (movieIds.length === 0) return;
        
        fetch(apiUrlWithMarket('/movies/status'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ movie_ids: movieIds })
        })
        .then(response => response.json())
        .then(data => {
            if (data.statuses) {
                Object.entries(data.statuses).forEach(([movieId, status]) => {
                    const card = document.querySelector(`.movie-card[data-movie-id="${movieId}"]`);
                    if (card) {
                        const statusBadge = card.querySelector('.status-badge');
                        if (statusBadge) {
                            // Update status based on response
                            statusBadge.className = 'status-badge';
                            if (status.has_file) {
                                statusBadge.classList.add('downloaded');
                                statusBadge.innerHTML = '✓ Downloaded';
                            } else if (status.status === 'In Cinemas') {
                                statusBadge.classList.add('in-cinemas');
                                statusBadge.innerHTML = '🎬 In Cinemas';
                            } else {
                                statusBadge.classList.add('missing');
                                statusBadge.innerHTML = '⬇ Missing';
                            }
                        }
                        
                        // Update quality profile if changed
                        const qualityInfo = card.querySelector('.quality-profile');
                        if (qualityInfo && status.quality_profile_name) {
                            qualityInfo.textContent = status.quality_profile_name;
                        }
                    }
                });
            }
        })
        .catch(error => {
            console.error('Error updating statuses:', error);
        });
    }

    // Root Folder Mapping Functions
    let rootFolderMappings = [];
    let availableRootFolders = [];
    let mappingIdCounter = 0;
    let rootFolderMappingModified = false;
    let originalRootFolderConfig = null;
    
    window.toggleRootFolderMapping = function() {
        const checkbox = document.getElementById('rootFolderMappingEnabled');
        const controls = document.getElementById('rootFolderMappingControls');
        
        if (checkbox && controls) {
            controls.style.display = checkbox.checked ? 'block' : 'none';
            rootFolderMappingModified = true; // Mark as modified when toggled
            
            // Load available root folders if enabling
            if (checkbox.checked) {
                loadAvailableRootFolders();
                loadExistingMappings();
            }
        }
    }
    
    window.loadAvailableRootFolders = function(preserveSelection = false) {
        const folderSelect = document.getElementById('newMappingFolder');
        const previous = preserveSelection && folderSelect ? folderSelect.value : '';
        fetch(apiUrlWithMarket('/movies/root-folders/available'))
            .then(response => response.json())
            .then(data => {
                availableRootFolders = data.folders || [];
                // Update the new mapping folder dropdown
                if (folderSelect) {
                    folderSelect.innerHTML = '<option value="">Select folder...</option>';
                    availableRootFolders.forEach(folder => {
                        const option = document.createElement('option');
                        option.value = folder;
                        option.textContent = folder;
                        folderSelect.appendChild(option);
                    });
                    if (previous && availableRootFolders.includes(previous)) {
                        folderSelect.value = previous;
                    }
                }
            })
            .catch(error => {
                console.error('Error loading root folders:', error);
                availableRootFolders = [];
            });
    }
    
    window.loadExistingMappings = function() {
        // Load existing mappings from configuration if any
        // This would be populated from the server configuration
        if (rootFolderMappings.length > 0) {
            renderMappingsList();
        }
    }
    
    function reindexMappingPriorities() {
        rootFolderMappings.forEach((m, i) => { m.priority = i; });
    }

    window.addRootFolderMapping = function() {
        const genresSelect = document.getElementById('newMappingGenres');
        const folderSelect = document.getElementById('newMappingFolder');
        
        if (!genresSelect || !folderSelect) return;
        
        // Get selected genres
        const selectedGenres = Array.from(genresSelect.selectedOptions).map(opt => opt.value);
        const folder = folderSelect.value;
        const priority = rootFolderMappings.length; // implicit order index (0-based)
        
        if (selectedGenres.length === 0) {
            showMessage('Please select at least one genre', 'error');
            return;
        }
        
        if (!folder) {
            showMessage('Please select a root folder', 'error');
            return;
        }
        
        // Add to mappings array
        const mapping = {
            id: ++mappingIdCounter,
            genres: selectedGenres,
            root_folder: folder,
            priority: priority
        };
        
        rootFolderMappings.push(mapping);
        rootFolderMappingModified = true; // Mark as modified when adding
        
        // Reset form
        genresSelect.selectedIndex = -1;
        folderSelect.value = '';
        // priority managed automatically
        
        // Re-render list
        renderMappingsList();
        
        showMessage('Rule added successfully', 'success');
    }
    
    window.removeRootFolderMapping = function(mappingId) {
        rootFolderMappings = rootFolderMappings.filter(m => m.id !== mappingId);
        rootFolderMappingModified = true; // Mark as modified when removing
        renderMappingsList();
    }
    
    window.moveMapping = function(mappingId, direction) {
        const index = rootFolderMappings.findIndex(m => m.id === mappingId);
        if (index === -1) return;
        
        if (direction === 'up' && index > 0) {
            [rootFolderMappings[index], rootFolderMappings[index - 1]] = 
            [rootFolderMappings[index - 1], rootFolderMappings[index]];
        } else if (direction === 'down' && index < rootFolderMappings.length - 1) {
            [rootFolderMappings[index], rootFolderMappings[index + 1]] = 
            [rootFolderMappings[index + 1], rootFolderMappings[index]];
        }
        
        // Keep priorities aligned with new order
        reindexMappingPriorities();
        rootFolderMappingModified = true; // Mark as modified when reordering
        renderMappingsList();
    }
    
    window.renderMappingsList = function() {
        const container = document.getElementById('mappingsList');
        if (!container) return;
        
        if (rootFolderMappings.length === 0) {
            container.innerHTML = `
                <div class="empty-state" style="text-align: center; padding: 2rem; color: var(--text-muted);">
                    No rules configured yet. Add your first rule above!
                </div>
            `;
            return;
        }
        
        // Add table header with tooltips (only once, before first item)
        const tableHeader = rootFolderMappings.length > 0 ? `
            <div style="display: grid; grid-template-columns: 2fr auto 2fr 100px 120px; gap: 1rem; padding: 0.5rem 0.75rem; margin-bottom: 0.5rem; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); border-bottom: 1px solid var(--border-color);">
                <div title="Movie genres that trigger this rule">Genres</div>
                <div></div>
                <div title="Destination folder in Radarr">Target Folder</div>
                <div title="Order index (top to bottom)">Priority</div>
                <div title="Reorder or remove rules" style="text-align: center;">Actions</div>
            </div>
        ` : '';
        
        const rulesHtml = rootFolderMappings.map((mapping, index) => {
            // Check if folder exists in available folders
            const folderExists = availableRootFolders.includes(mapping.root_folder);
            const warningIcon = !folderExists && availableRootFolders.length > 0 ? 
                `<span style="color: #ffa500; margin-left: 0.25rem;" title="Warning: This folder may not exist in Radarr">⚠</span>` : '';
            
            return `
            <div class="mapping-rule" style="display: grid; grid-template-columns: 2fr auto 2fr 100px 120px; gap: 1rem; align-items: center; padding: 0.75rem; margin-bottom: 0.5rem; background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: 6px; transition: background 0.2s;">
                <div style="font-weight: 500; color: var(--text-primary);">
                    ${mapping.genres.join(', ')}
                </div>
                <div style="color: var(--text-muted); text-align: center;">
                    →
                </div>
                <div style="display: flex; align-items: center; color: var(--primary-color);">
                    <span>${mapping.root_folder}</span>
                    ${warningIcon}
                </div>
                <div>
                    <span style="display: inline-block; padding: 0.25rem 0.5rem; background: var(--bg-tertiary); border-radius: 4px; font-size: 0.85rem; color: var(--text-secondary); font-weight: 500;">
                        ${index}
                    </span>
                </div>
                <div style="display: flex; gap: 0.25rem; justify-content: flex-end;">
                    ${index > 0 ? 
                        `<button type="button" class="btn btn-sm" onclick="moveMapping(${mapping.id}, 'up')" 
                                title="Move rule up (higher priority)" 
                                style="padding: 0.375rem 0.5rem; background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--text-primary); border-radius: 4px; transition: all 0.2s;">
                            ↑
                        </button>` : 
                        `<div style="width: 35px;"></div>`
                    }
                    ${index < rootFolderMappings.length - 1 ? 
                        `<button type="button" class="btn btn-sm" onclick="moveMapping(${mapping.id}, 'down')" 
                                title="Move rule down (lower priority)" 
                                style="padding: 0.375rem 0.5rem; background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--text-primary); border-radius: 4px; transition: all 0.2s;">
                            ↓
                        </button>` : 
                        `<div style="width: 35px;"></div>`
                    }
                    <button type="button" class="btn btn-sm" onclick="removeRootFolderMapping(${mapping.id})" 
                            title="Remove this rule" 
                            style="padding: 0.375rem 0.5rem; background: #dc3545; color: white; border: 1px solid #dc3545; border-radius: 4px; transition: all 0.2s;">
                        ✕
                    </button>
                </div>
            </div>
            `;
        }).join('');
        
        const helpText = rootFolderMappings.length > 0 ? `
            <div style="margin-top: 1rem; padding: 0.75rem; background: var(--bg-tertiary); border-radius: 4px; font-size: 0.85rem; color: var(--text-muted);">
                <span style="margin-right: 0.5rem;">ℹ️</span>
                Rules are evaluated from top to bottom. The first matching rule wins.
            </div>
        ` : '';
        
        const html = tableHeader + rulesHtml + helpText;
        
        container.innerHTML = html;
        
        // Add hover effects to buttons after rendering
        container.querySelectorAll('button').forEach(btn => {
            if (!btn.style.background.includes('#dc3545')) {
                btn.addEventListener('mouseenter', function() {
                    this.style.background = 'var(--bg-tertiary)';
                });
                btn.addEventListener('mouseleave', function() {
                    this.style.background = 'var(--bg-secondary)';
                });
            }
        });
    }
    
    window.collectRootFolderMappings = function() {
        // Ensure priorities are aligned to current order before collecting
        reindexMappingPriorities();
        return rootFolderMappings.map(m => ({
            genres: m.genres,
            root_folder: m.root_folder,
            priority: m.priority
        }));
    }
    
    // Keep the original function
    window.addToRadarr = function(title, year, buttonElement) {
        if (confirm(`Add "${title}" to Radarr?`)) {
            // Show loading state immediately
            showMessage('Adding movie to Radarr...', 'info');
            
            // Update button to show loading state
            if (buttonElement) {
                const originalText = buttonElement.textContent;
                buttonElement.disabled = true;
                buttonElement.innerHTML = '<span style="display: inline-block; animation: spin 1s linear infinite;">⏳</span> Adding...';
                buttonElement.style.opacity = '0.7';
            }
            
            fetch(apiUrlWithMarket('/movies/add'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, year })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showMessage('✅ Movie added successfully! Updating status...', 'success');
                    
                    // Force immediate status update instead of waiting for page reload
                    setTimeout(() => {
                        updateMovieStatuses();
                        // Give status update time to complete, then reload
                        setTimeout(() => window.location.reload(), 1000);
                    }, 500);
                } else {
                    // Restore button on error
                    if (buttonElement) {
                        buttonElement.disabled = false;
                        buttonElement.textContent = 'Add to Radarr';
                        buttonElement.style.opacity = '1';
                    }
                    
                    // Use the improved error messages from the API
                    let errorMsg = data.message || 'Failed to add movie';
                    if (data.error) {
                        errorMsg = data.error;
                    }
                    showMessage('❌ ' + errorMsg, 'error');
                }
            })
            .catch(error => {
                // Restore button on network error
                if (buttonElement) {
                    buttonElement.disabled = false;
                    buttonElement.textContent = 'Add to Radarr';
                    buttonElement.style.opacity = '1';
                }
                
                let errorMsg = 'Network error';
                if (error.message.includes('fetch')) {
                    errorMsg = 'Could not reach Boxarr server';
                }
                showMessage('❌ ' + errorMsg + ': ' + error.message, 'error');
            });
        }
    };

    window.upgradeQuality = function(movieId, buttonElement) {
        if (confirm('Upgrade this movie to Ultra-HD quality?')) {
            // Disable button immediately to prevent double-clicks
            if (buttonElement) {
                buttonElement.disabled = true;
                buttonElement.textContent = 'Processing...';
            }
            
            fetch(apiUrlWithMarket(`/movies/${movieId}/upgrade`), {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showMessage('Quality profile upgraded successfully!', 'success');
                    
                    // Replace button with "Upgrading" label
                    if (buttonElement) {
                        const upgradingLabel = document.createElement('span');
                        upgradingLabel.className = 'upgrade-status';
                        upgradingLabel.style.cssText = 'color: #667eea; font-weight: 600; padding: 0.5rem;';
                        upgradingLabel.textContent = '⚡ Upgrading...';
                        buttonElement.parentNode.replaceChild(upgradingLabel, buttonElement);
                    }
                    
                    updateMovieStatuses();
                } else {
                    showMessage('Failed to upgrade: ' + (data.error || 'Unknown error'), 'error');
                    // Re-enable button on failure
                    if (buttonElement) {
                        buttonElement.disabled = false;
                        buttonElement.textContent = 'Upgrade to Ultra-HD';
                    }
                }
            })
            .catch(error => {
                showMessage('Error upgrading quality: ' + error.message, 'error');
                // Re-enable button on error
                if (buttonElement) {
                    buttonElement.disabled = false;
                    buttonElement.textContent = 'Upgrade to Ultra-HD';
                }
            });
        }
    };

    // ==========================================
    // Setup Page Functions
    // ==========================================

    window.testConnection = function() {
        const url = document.getElementById('radarrUrl').value;
        const apiKey = document.getElementById('radarrApiKey').value;
        
        if (!url || !apiKey) {
            showMessage('Please enter Radarr URL and API Key', 'error');
            return;
        }
        
        const testButton = document.getElementById('testButtonText');
        const testSpinner = document.getElementById('testButtonSpinner');
        const testResults = document.getElementById('testResults');
        
        if (testButton) testButton.textContent = 'Testing...';
        if (testSpinner) testSpinner.style.display = 'inline-block';
        
        fetch(apiUrlWithMarket('/config/test'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, api_key: apiKey })
        })
        .then(response => response.json())
        .then(data => {
            if (testButton) testButton.textContent = 'Test Connection';
            if (testSpinner) testSpinner.style.display = 'none';
            
            if (data.success) {
                connectionTested = true;
                const saveBtn = document.getElementById('saveBtn');
                if (saveBtn) saveBtn.disabled = false;
                
                if (testResults) {
                    testResults.innerHTML = '<div class="success-message">✓ Connected successfully!</div>';
                    testResults.classList.add('success');
                }
                
                // Populate dropdowns
                if (data.root_folders) {
                    const rootFolder = document.getElementById('rootFolder');
                    if (rootFolder) {
                        const currentValue = rootFolder.value; // Preserve current selection
                        rootFolder.innerHTML = '<option value="">Select root folder...</option>';
                        data.root_folders.forEach(folder => {
                            const selected = folder.path === currentValue ? ' selected' : '';
                            rootFolder.innerHTML += `<option value="${folder.path}"${selected}>${folder.path}</option>`;
                        });
                    }
                }
                
                if (data.profiles) {
                    const defaultProfile = document.getElementById('defaultProfile');
                    const upgradeProfile = document.getElementById('upgradeProfile');
                    
                    if (defaultProfile) {
                        const currentValue = defaultProfile.value; // Preserve current selection
                        defaultProfile.innerHTML = '<option value="">Select default quality...</option>';
                        data.profiles.forEach(profile => {
                            const selected = profile.name === currentValue ? ' selected' : '';
                            defaultProfile.innerHTML += `<option value="${profile.name}"${selected}>${profile.name}</option>`;
                        });
                    }
                    
                    if (upgradeProfile) {
                        const currentValue = upgradeProfile.value; // Preserve current selection
                        upgradeProfile.innerHTML = '<option value="">Select upgrade quality...</option>';
                        data.profiles.forEach(profile => {
                            const selected = profile.name === currentValue ? ' selected' : '';
                            upgradeProfile.innerHTML += `<option value="${profile.name}"${selected}>${profile.name}</option>`;
                        });
                    }
                }
                
                // Show quality section
                const qualitySection = document.getElementById('qualitySection');
                if (qualitySection) qualitySection.classList.add('show');
            } else {
                connectionTested = false;
                const saveBtn = document.getElementById('saveBtn');
                if (saveBtn) saveBtn.disabled = true;
                
                if (testResults) {
                    testResults.innerHTML = `<div class="error-message">✗ ${data.error || 'Connection failed'}</div>`;
                    testResults.classList.add('error');
                }
            }
        })
        .catch(error => {
            if (testButton) testButton.textContent = 'Test Connection';
            if (testSpinner) testSpinner.style.display = 'none';
            if (testResults) {
                testResults.innerHTML = `<div class="error-message">✗ Connection error: ${error.message}</div>`;
                testResults.classList.add('error');
            }
        });
    };

    window.saveConfiguration = function() {
        // Don't require connection test if we already have valid credentials
        const radarrUrl = document.getElementById('radarrUrl');
        const radarrApiKey = document.getElementById('radarrApiKey');
        
        if (!radarrUrl.value || !radarrApiKey.value) {
            showMessage('Please enter Radarr URL and API Key', 'error');
            return;
        }
        
        const form = document.getElementById('setupForm');
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        const formData = new FormData(form);
        const config = {};
        
        // Get scheduler settings from the dropdowns
        const schedulerDay = document.getElementById('schedulerDay');
        const schedulerTime = document.getElementById('schedulerTime');
        
        // URL base is now configured via environment variable only - don't save it
        // config.boxarr_url_base = document.getElementById('urlBase')?.value || '';
        
        // Handle checkboxes explicitly (unchecked ones don't appear in FormData)
        config.boxarr_scheduler_enabled = document.getElementById('schedulerEnabled')?.checked || false;
        config.boxarr_features_auto_add = document.getElementById('autoAdd')?.checked || false;
        config.boxarr_features_quality_upgrade = document.getElementById('qualityUpgrade')?.checked || false;
        // Auto-tag settings
        config.boxarr_features_auto_tag_enabled = document.getElementById('autoTagEnabled')?.checked || false;
        const autoTagInput = document.getElementById('autoTagText');
        config.boxarr_features_auto_tag_text = (autoTagInput && autoTagInput.value) ? autoTagInput.value : 'boxarr';
        
        // Box office fetch limit
        config.boxarr_features_box_office_limit = parseInt(document.getElementById('boxOfficeLimit')?.value || '10');
        // Handle new auto-add advanced options
        config.boxarr_features_auto_add_limit = parseInt(document.getElementById('autoAddLimit')?.value || '10');
        config.boxarr_features_auto_add_genre_filter_enabled = document.getElementById('genreFilterEnabled')?.checked || false;
        config.boxarr_features_auto_add_genre_filter_mode = document.querySelector('input[name="boxarr_features_auto_add_genre_filter_mode"]:checked')?.value || 'blacklist';
        config.boxarr_features_auto_add_rating_filter_enabled = document.getElementById('ratingFilterEnabled')?.checked || false;
        config.boxarr_features_auto_add_ignore_rereleases = document.getElementById('ignoreRereleasesEnabled')?.checked || false;
        
        // Collect genre checkboxes based on mode
        const genreMode = config.boxarr_features_auto_add_genre_filter_mode;
        const genreWhitelist = [];
        const genreBlacklist = [];
        document.querySelectorAll('[name^="genre_"]').forEach(checkbox => {
            if (checkbox.checked) {
                if (genreMode === 'whitelist') {
                    genreWhitelist.push(checkbox.value);
                } else {
                    genreBlacklist.push(checkbox.value);
                }
            }
        });
        config.boxarr_features_auto_add_genre_whitelist = genreWhitelist;
        config.boxarr_features_auto_add_genre_blacklist = genreBlacklist;
        
        // Collect rating checkboxes
        const ratingWhitelist = [];
        document.querySelectorAll('[name^="rating_"]').forEach(checkbox => {
            if (checkbox.checked) {
                ratingWhitelist.push(checkbox.value);
            }
        });
        config.boxarr_features_auto_add_rating_whitelist = ratingWhitelist;

        // Language filter settings
        config.boxarr_features_auto_add_language_filter_enabled = document.getElementById('languageFilterEnabled')?.checked || false;
        config.boxarr_features_auto_add_language_filter_mode = document.querySelector('input[name="boxarr_features_auto_add_language_filter_mode"]:checked')?.value || 'whitelist';

        // Collect language checkboxes based on mode
        const languageMode = config.boxarr_features_auto_add_language_filter_mode;
        const languageWhitelist = [];
        const languageBlacklist = [];
        document.querySelectorAll('[name^="language_"]').forEach(checkbox => {
            if (checkbox.checked) {
                if (languageMode === 'whitelist') {
                    languageWhitelist.push(checkbox.value);
                } else {
                    languageBlacklist.push(checkbox.value);
                }
            }
        });
        config.boxarr_features_auto_add_language_whitelist = languageWhitelist;
        config.boxarr_features_auto_add_language_blacklist = languageBlacklist;

        // Handle other form fields
        for (let [key, value] of formData.entries()) {
            if (!key.startsWith('boxarr_features_') && !key.startsWith('genre_') && !key.startsWith('rating_') && !key.startsWith('language_')) {
                config[key] = value;
            }
        }
        
        // Collect root folder mappings only if modified
        if (rootFolderMappingModified) {
            const rootFolderMappingEnabled = document.getElementById('rootFolderMappingEnabled')?.checked || false;
            if (rootFolderMappingEnabled) {
                const mappings = collectRootFolderMappings();
                
                config.radarr_root_folder_config = {
                    enabled: true,
                    mappings: mappings
                };
            } else {
                config.radarr_root_folder_config = {
                    enabled: false,
                    mappings: []
                };
            }
        }
        // If not modified, don't include radarr_root_folder_config in the payload
        
        // Convert scheduler day and time to cron format
        if (schedulerDay && schedulerTime) {
            // APScheduler uses different day numbering than standard cron:
            // APScheduler: Monday=0, Tuesday=1, ..., Saturday=5, Sunday=6
            // HTML form uses: Sunday=0, Monday=1, ..., Saturday=6
            // We need to convert from HTML form values to APScheduler values
            const dayMapping = {
                '0': '6', // Sunday: 0 -> 6
                '1': '0', // Monday: 1 -> 0
                '2': '1', // Tuesday: 2 -> 1
                '3': '2', // Wednesday: 3 -> 2
                '4': '3', // Thursday: 4 -> 3
                '5': '4', // Friday: 5 -> 4
                '6': '5'  // Saturday: 6 -> 5
            };
            const apschedulerDay = dayMapping[schedulerDay.value] || schedulerDay.value;
            const cronString = `0 ${schedulerTime.value} * * ${apschedulerDay}`;
            config.boxarr_scheduler_cron = cronString;
        } else {
            // Default: Tuesday at 11 PM (APScheduler day 1)
            config.boxarr_scheduler_cron = "0 23 * * 1";
        }
        
        showMessage('Saving configuration...', 'info');
        
        fetch(apiUrlWithMarket('/config/save'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showMessage('✓ Configuration saved successfully! Redirecting...', 'success');
                setTimeout(() => {
                    window.location.href = pageUrlWithMarket('/dashboard');
                }, 1500);
            } else {
                showMessage('Failed to save: ' + (data.error || 'Unknown error'), 'error');
            }
        })
        .catch(error => {
            showMessage('Error saving configuration: ' + error.message, 'error');
        });
    };

    function setMarketModalMessage(message, type = 'info') {
        const container = document.getElementById('marketModalMessage');
        if (!container) return;
        container.style.display = 'block';
        container.className = `status-message status-${type}`;
        container.textContent = message;
    }

    function clearMarketModalMessage() {
        const container = document.getElementById('marketModalMessage');
        if (!container) return;
        container.style.display = 'none';
        container.textContent = '';
        container.className = 'status-message';
    }

    function normalizeMarketTagsInput(value) {
        if (!value) return null;
        const parts = String(value)
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean);
        return parts.length ? parts : null;
    }

    function normalizeOptionalBooleanSelect(value) {
        if (value === undefined || value === null || value === '') {
            return '';
        }
        return Boolean(value) ? 'true' : 'false';
    }

    function parseProviderConfigInput(value) {
        const text = String(value || '').trim();
        if (!text) return {};
        return JSON.parse(text);
    }

    function getJpboxofficeCountrySpecs() {
        const countries = window.BOXARR_JPBOXOFFICE_COUNTRIES || {};
        return countries && typeof countries === 'object' ? countries : {};
    }

    function getJpboxofficeCountryLabel(country) {
        const spec = getJpboxofficeCountrySpecs()[String(country || '').trim().toLowerCase()];
        return spec && spec.label ? spec.label : String(country || '').trim().toUpperCase();
    }

    function syncJpboxofficeCountryProviderConfig(providerConfigInput, country) {
        if (!providerConfigInput) return;
        const normalizedCountry = String(country || '').trim().toLowerCase();
        if (!normalizedCountry) return;

        let parsed = {};
        try {
            parsed = parseProviderConfigInput(providerConfigInput.value);
        } catch (_) {
            parsed = {};
        }
        parsed.country = normalizedCountry;
        providerConfigInput.value = JSON.stringify(parsed, null, 2);
    }

    function toggleMarketModal(show) {
        const modal = document.getElementById('marketModal');
        if (!modal) return;
        modal.classList.toggle('show', show);
        modal.setAttribute('aria-hidden', show ? 'false' : 'true');
    }

    window.closeMarketEditor = function() {
        toggleMarketModal(false);
        clearMarketModalMessage();
    };

    window.openMarketEditor = function(marketKey = null) {
        clearMarketModalMessage();
        const modal = document.getElementById('marketModal');
        if (!modal) return;

        const isEdit = Boolean(marketKey);
        const markets = window.BOXARR_MARKETS || {};
        const previews = window.BOXARR_MARKET_PREVIEWS || {};
        const preview = isEdit ? (previews[marketKey] || {}) : {};
        const definition = isEdit ? (preview.definition || markets[marketKey] || {}) : {};
        const overrides = isEdit ? (preview.overrides || definition.overrides || {}) : {};

        modal.dataset.mode = isEdit ? 'edit' : 'create';
        modal.dataset.market = isEdit ? marketKey : '';

        const title = document.getElementById('marketModalTitle');
        const subtitle = document.getElementById('marketModalSubtitle');
        const keyInput = document.getElementById('marketKeyInput');
        const labelInput = document.getElementById('marketLabelInput');
        const providerInput = document.getElementById('marketProviderInput');
        const countryGroup = document.getElementById('marketJpboxofficeCountryGroup');
        const countryInput = document.getElementById('marketJpboxofficeCountryInput');
        const enabledInput = document.getElementById('marketEnabledInput');
        const providerConfigInput = document.getElementById('marketProviderConfigInput');
        const fetchLimitInput = document.getElementById('marketFetchLimitInput');
        const addLimitInput = document.getElementById('marketAddLimitInput');
        const autoAddInput = document.getElementById('marketAutoAddInput');
        const cleanupInput = document.getElementById('marketCleanupInput');
        const autoTagTextInput = document.getElementById('marketAutoTagTextInput');
        const tagsInput = document.getElementById('marketTagsInput');
        const rootFolderInput = document.getElementById('marketRootFolderInput');
        const qualityProfileDefaultInput = document.getElementById('marketQualityProfileDefaultInput');
        const qualityProfileUpgradeInput = document.getElementById('marketQualityProfileUpgradeInput');
        const minimumAvailabilityEnabledInput = document.getElementById('marketMinimumAvailabilityEnabledInput');
        const minimumAvailabilityInput = document.getElementById('marketMinimumAvailabilityInput');
        const monitorOptionInput = document.getElementById('marketMonitorOptionInput');
        const searchOnAddInput = document.getElementById('marketSearchOnAddInput');
        const languageFilterEnabledInput = document.getElementById('marketLanguageFilterEnabledInput');
        const languageFilterModeInput = document.getElementById('marketLanguageFilterModeInput');
        const languageWhitelistInput = document.getElementById('marketLanguageWhitelistInput');
        const languageBlacklistInput = document.getElementById('marketLanguageBlacklistInput');
        const ignoreRereleasesInput = document.getElementById('marketIgnoreRereleasesInput');

        if (title) title.textContent = isEdit ? `Edit market ${marketKey}` : 'Add market';
        if (subtitle) {
            subtitle.textContent = isEdit
                ? 'Update the market definition and save it back to local.yaml.'
                : 'Create a new market definition in local.yaml.';
        }

        if (keyInput) {
            keyInput.value = isEdit ? marketKey : '';
            keyInput.disabled = isEdit;
        }
        if (labelInput) labelInput.value = definition.label || '';
        if (providerInput) providerInput.value = definition.provider || 'mojo';
        if (countryInput) {
            const providerCountry = definition.provider_config && definition.provider_config.country
                ? String(definition.provider_config.country).trim().toLowerCase()
                : '';
            if (providerCountry && getJpboxofficeCountrySpecs()[providerCountry]) {
                countryInput.value = providerCountry;
            } else if (providerInput && providerInput.value === 'jpboxoffice' && !countryInput.value) {
                countryInput.value = 'fr';
            }
        }
        if (countryGroup) {
            countryGroup.style.display = providerInput && providerInput.value === 'jpboxoffice' ? 'block' : 'none';
        }
        if (enabledInput) enabledInput.value = String(definition.enabled !== false);
        if (providerConfigInput) {
            providerConfigInput.value = definition.provider_config
                ? JSON.stringify(definition.provider_config, null, 2)
                : '';
        }
        if (fetchLimitInput) fetchLimitInput.value = overrides.box_office_fetch_limit ?? '';
        if (addLimitInput) addLimitInput.value = overrides.maximum_movies_to_add ?? '';
        if (autoAddInput) {
            autoAddInput.value =
                overrides.auto_add_enabled === undefined || overrides.auto_add_enabled === null
                    ? ''
                    : String(Boolean(overrides.auto_add_enabled));
        }
        if (cleanupInput) cleanupInput.value = overrides.cleanup_protect_tag || '';
        if (autoTagTextInput) autoTagTextInput.value = overrides.auto_tag_text || '';
        if (tagsInput) {
            const tagsValue = overrides.tags || [];
            tagsInput.value = Array.isArray(tagsValue) ? tagsValue.join(', ') : '';
        }
        if (rootFolderInput) rootFolderInput.value = overrides.root_folder || '';
        if (qualityProfileDefaultInput) qualityProfileDefaultInput.value = overrides.quality_profile_default || '';
        if (qualityProfileUpgradeInput) qualityProfileUpgradeInput.value = overrides.quality_profile_upgrade || '';
        if (minimumAvailabilityEnabledInput) {
            minimumAvailabilityEnabledInput.value = normalizeOptionalBooleanSelect(overrides.minimum_availability_enabled);
        }
        if (minimumAvailabilityInput) {
            minimumAvailabilityInput.value = overrides.minimum_availability || '';
        }
        if (monitorOptionInput) monitorOptionInput.value = overrides.monitor_option || '';
        if (searchOnAddInput) {
            searchOnAddInput.value = normalizeOptionalBooleanSelect(overrides.search_on_add);
        }
        if (languageFilterEnabledInput) {
            languageFilterEnabledInput.value = normalizeOptionalBooleanSelect(overrides.language_filter_enabled);
        }
        if (languageFilterModeInput) languageFilterModeInput.value = overrides.language_filter_mode || '';
        if (languageWhitelistInput) {
            languageWhitelistInput.value = Array.isArray(overrides.language_whitelist)
                ? overrides.language_whitelist.join(', ')
                : '';
        }
        if (languageBlacklistInput) {
            languageBlacklistInput.value = Array.isArray(overrides.language_blacklist)
                ? overrides.language_blacklist.join(', ')
                : '';
        }
        if (ignoreRereleasesInput) {
            ignoreRereleasesInput.value = normalizeOptionalBooleanSelect(overrides.ignore_rereleases);
        }

        if (providerInput) {
            providerInput.onchange = function() {
                if (!countryGroup || !countryInput || !providerConfigInput) return;
                const isJpboxoffice = providerInput.value === 'jpboxoffice';
                countryGroup.style.display = isJpboxoffice ? 'block' : 'none';
                if (isJpboxoffice) {
                    if (!countryInput.value) {
                        countryInput.value = 'fr';
                    }
                    syncJpboxofficeCountryProviderConfig(providerConfigInput, countryInput.value);
                    if (isEdit && !labelInput.value.trim()) {
                        labelInput.value = `${getJpboxofficeCountryLabel(countryInput.value)} Box Office`;
                    }
                }
            };
        }
        if (countryInput) {
            countryInput.onchange = function() {
                if (providerInput && providerInput.value === 'jpboxoffice' && providerConfigInput) {
                    syncJpboxofficeCountryProviderConfig(providerConfigInput, countryInput.value);
                    if (isEdit && !labelInput.value.trim()) {
                        labelInput.value = `${getJpboxofficeCountryLabel(countryInput.value)} Box Office`;
                    }
                }
            };
        }

        toggleMarketModal(true);
    };

    window.saveMarketEditor = function() {
        const modal = document.getElementById('marketModal');
        if (!modal) return;

        const mode = modal.dataset.mode || 'create';
        const marketKey = (document.getElementById('marketKeyInput')?.value || modal.dataset.market || '').trim().toLowerCase();
        const label = (document.getElementById('marketLabelInput')?.value || '').trim();
        const provider = document.getElementById('marketProviderInput')?.value || 'mojo';
        const country = document.getElementById('marketJpboxofficeCountryInput')?.value || '';
        const enabled = document.getElementById('marketEnabledInput')?.value === 'true';
        const providerConfigRaw = document.getElementById('marketProviderConfigInput')?.value || '';
        const fetchLimitRaw = document.getElementById('marketFetchLimitInput')?.value || '';
        const addLimitRaw = document.getElementById('marketAddLimitInput')?.value || '';
        const autoAddRaw = document.getElementById('marketAutoAddInput')?.value || '';
        const cleanupProtectTag = (document.getElementById('marketCleanupInput')?.value || '').trim();
        const autoTagText = (document.getElementById('marketAutoTagTextInput')?.value || '').trim();
        const tagsRaw = document.getElementById('marketTagsInput')?.value || '';
        const rootFolder = (document.getElementById('marketRootFolderInput')?.value || '').trim();
        const qualityProfileDefault = (document.getElementById('marketQualityProfileDefaultInput')?.value || '').trim();
        const qualityProfileUpgrade = (document.getElementById('marketQualityProfileUpgradeInput')?.value || '').trim();
        const minimumAvailabilityEnabledRaw = document.getElementById('marketMinimumAvailabilityEnabledInput')?.value || '';
        const minimumAvailabilityRaw = document.getElementById('marketMinimumAvailabilityInput')?.value || '';
        const monitorOption = (document.getElementById('marketMonitorOptionInput')?.value || '').trim();
        const searchOnAddRaw = document.getElementById('marketSearchOnAddInput')?.value || '';
        const languageFilterEnabledRaw = document.getElementById('marketLanguageFilterEnabledInput')?.value || '';
        const languageFilterMode = document.getElementById('marketLanguageFilterModeInput')?.value || '';
        const languageWhitelistRaw = document.getElementById('marketLanguageWhitelistInput')?.value || '';
        const languageBlacklistRaw = document.getElementById('marketLanguageBlacklistInput')?.value || '';
        const ignoreRereleasesRaw = document.getElementById('marketIgnoreRereleasesInput')?.value || '';

        if (!marketKey) {
            setMarketModalMessage('Market key is required.', 'error');
            return;
        }
        if (mode === 'create' && !label) {
            setMarketModalMessage('Label is required.', 'error');
            return;
        }
        if (mode === 'create' && !provider) {
            setMarketModalMessage('Provider is required.', 'error');
            return;
        }

        const payload = {
            enabled,
        };
        if (label) {
            payload.label = label;
        }
        if (provider) {
            payload.provider = provider;
        }

        if (mode === 'create') {
            payload.market = marketKey;
        }

        if (providerConfigRaw.trim()) {
            try {
                payload.provider_config = parseProviderConfigInput(providerConfigRaw);
                if (provider === 'jpboxoffice' && country) {
                    payload.provider_config.country = country;
                }
            } catch (error) {
                setMarketModalMessage('Provider config must be valid JSON.', 'error');
                return;
            }
        } else if (mode === 'create') {
            payload.provider_config = provider === 'jpboxoffice' && country ? { country } : {};
        }

        if (fetchLimitRaw !== '') {
            payload.box_office_fetch_limit = parseInt(fetchLimitRaw, 10);
        }
        if (addLimitRaw !== '') {
            payload.maximum_movies_to_add = parseInt(addLimitRaw, 10);
        }
        if (autoAddRaw !== '') {
            payload.auto_add_enabled = autoAddRaw === 'true';
        }
        if (cleanupProtectTag) {
            payload.cleanup_protect_tag = cleanupProtectTag;
        }
        if (autoTagText) {
            payload.auto_tag_text = autoTagText;
        }
        const tags = normalizeMarketTagsInput(tagsRaw);
        if (tags) {
            payload.tags = tags;
        }

        const setOptionalString = (key, value) => {
            if (value) {
                payload[key] = value;
            } else if (mode === 'edit') {
                payload[key] = null;
            }
        };
        const setOptionalBoolean = (key, rawValue) => {
            if (rawValue !== '') {
                payload[key] = rawValue === 'true';
            } else if (mode === 'edit') {
                payload[key] = null;
            }
        };
        const setOptionalList = (key, rawValue) => {
            const parsed = normalizeMarketTagsInput(rawValue);
            if (parsed && parsed.length) {
                payload[key] = parsed;
            } else if (mode === 'edit') {
                payload[key] = null;
            }
        };

        setOptionalString('root_folder', rootFolder);
        setOptionalString('quality_profile_default', qualityProfileDefault);
        setOptionalString('quality_profile_upgrade', qualityProfileUpgrade);
        setOptionalBoolean('minimum_availability_enabled', minimumAvailabilityEnabledRaw);
        setOptionalString('minimum_availability', minimumAvailabilityRaw);
        setOptionalString('monitor_option', monitorOption);
        setOptionalBoolean('search_on_add', searchOnAddRaw);
        setOptionalBoolean('language_filter_enabled', languageFilterEnabledRaw);
        setOptionalString('language_filter_mode', languageFilterMode);
        setOptionalList('language_whitelist', languageWhitelistRaw);
        setOptionalList('language_blacklist', languageBlacklistRaw);
        setOptionalBoolean('ignore_rereleases', ignoreRereleasesRaw);

        const method = mode === 'edit' ? 'PUT' : 'POST';
        const endpoint = mode === 'edit'
            ? apiUrl(`/config/markets/${encodeURIComponent(marketKey)}`)
            : apiUrl('/config/markets');

        const saveButton = document.getElementById('marketSaveButtonText');
        const saveSpinner = document.getElementById('marketSaveButtonSpinner');
        if (saveButton) saveButton.textContent = 'Saving...';
        if (saveSpinner) saveSpinner.style.display = 'inline-block';

        fetch(endpoint, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
            .then(async (response) => {
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || data.message || 'Unable to save market');
                }
                return data;
            })
            .then(() => {
                showMessage('Market saved successfully. Reloading...', 'success');
                setTimeout(() => window.location.reload(), 500);
            })
            .catch((error) => {
                setMarketModalMessage(error.message, 'error');
            })
            .finally(() => {
                if (saveButton) saveButton.textContent = 'Save market';
                if (saveSpinner) saveSpinner.style.display = 'none';
            });
    };

    window.toggleMarketEnabled = function(marketKey, enabled) {
        const action = enabled ? 'enable' : 'disable';
        if (!confirm(`${enabled ? 'Enable' : 'Disable'} market "${marketKey}"?`)) {
            return;
        }

        fetch(apiUrl(`/config/markets/${encodeURIComponent(marketKey)}/${action}`), {
            method: 'POST',
        })
            .then(async (response) => {
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || data.message || 'Unable to update market');
                }
                return data;
            })
            .then(() => {
                showMessage(`Market "${marketKey}" updated.`, 'success');
                setTimeout(() => window.location.reload(), 500);
            })
            .catch((error) => {
                showMessage(`Error: ${error.message}`, 'error');
            });
    };

    window.toggleScheduler = function() {
        const checkbox = document.getElementById('schedulerEnabled');
        const controls = document.querySelector('.scheduler-controls');
        if (controls) {
            controls.classList.toggle('active', checkbox.checked);
        }
    };

    // ==========================================
    // Setup Page Helper Functions
    // ==========================================
    
    function resetConnectionTest() {
        connectionTested = false;
        const saveBtn = document.getElementById('saveBtn');
        if (saveBtn) saveBtn.disabled = true;
        const qualitySection = document.getElementById('qualitySection');
        if (qualitySection) qualitySection.classList.remove('show');
        const testResults = document.getElementById('testResults');
        if (testResults) testResults.classList.remove('show');
    }

    // ==========================================
    // Initialize on DOM Load
    // ==========================================

    document.addEventListener('DOMContentLoaded', function() {
        const urlMarket = getUrlMarket();
        if (!urlMarket) {
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('market', DEFAULT_MARKET);
            currentUrl.searchParams.delete('provider');
            window.location.replace(currentUrl.toString());
            return;
        }

        localStorage.setItem('boxarr-market', urlMarket);

        window.BOXARR_MARKET = urlMarket;
        window.BOXARR_PROVIDER = getCurrentProvider();
        const marketTabUs = document.getElementById('marketTabUs');
        const marketTabFr = document.getElementById('marketTabFr');
        if (marketTabUs && marketTabFr) {
            marketTabUs.classList.toggle('active', urlMarket === 'us');
            marketTabFr.classList.toggle('active', urlMarket === 'fr');
        }

        // Check connection status
        checkConnection();
        setInterval(checkConnection, 30000);
        
        // Check for updates (only once on page load)
        checkForUpdates();
        
        // Initialize page-specific features
        const path = getPathWithoutBase();
        
        if (path.includes('W') && !isCurrentPath('/dashboard')) {
            // Weekly page - start status updates
            updateMovieStatuses();
            // More frequent updates initially (every 5 seconds for first minute)
            let updateCount = 0;
            statusCheckInterval = setInterval(() => {
                updateMovieStatuses();
                updateCount++;
                // After 12 updates (1 minute), switch to 30 second intervals
                if (updateCount >= 12) {
                    clearInterval(statusCheckInterval);
                    statusCheckInterval = setInterval(updateMovieStatuses, 30000);
                }
            }, 5000);
        }

        // Overview page - hydrate Radarr statuses once after load
        if (isCurrentPath('/overview')) {
            updateMovieStatuses();
        }
        
        // Setup page specific initialization
        if (isCurrentPath('/setup')) {
            // Rehydrate root-folder mapping UI from server state
            loadAvailableRootFolders();
            fetch(apiUrlWithMarket('/config/root-folders'))
                .then(r => r.json())
                .then(data => {
                    const cfg = data?.config || { enabled: false, mappings: [] };
                    originalRootFolderConfig = cfg;
                    const checkbox = document.getElementById('rootFolderMappingEnabled');
                    if (checkbox) {
                        checkbox.checked = !!cfg.enabled;
                        const controls = document.getElementById('rootFolderMappingControls');
                        if (controls) controls.style.display = checkbox.checked ? 'block' : 'none';
                    }
                    // Build client list from server mappings
                    rootFolderMappings = (cfg.mappings || []).map(m => ({
                        id: ++mappingIdCounter,
                        genres: m.genres || [],
                        root_folder: m.root_folder,
                        priority: parseInt(m.priority || 0)
                    }));
                    renderMappingsList();
                    rootFolderMappingModified = false; // freshly loaded state
                })
                .catch(() => { /* ignore */ });
            const radarrUrl = document.getElementById('radarrUrl');
            const radarrApiKey = document.getElementById('radarrApiKey');
            const saveBtn = document.getElementById('saveBtn');
            const setupForm = document.getElementById('setupForm');
            
            // Add form submit handler
            if (setupForm) {
                setupForm.addEventListener('submit', function(e) {
                    e.preventDefault();
                    saveConfiguration();
                });
            }
            
            // Add listeners to reset connection test when credentials change
            if (radarrUrl) radarrUrl.addEventListener('input', resetConnectionTest);
            if (radarrApiKey) radarrApiKey.addEventListener('input', resetConnectionTest);
            
            // Check if already configured and auto-test
            if (radarrUrl && radarrApiKey && saveBtn) {
                const url = radarrUrl.value;
                const apiKey = radarrApiKey.value;
                
                // If we have credentials, check if it's a pre-configured setup
                if (url && apiKey && apiKey.trim().length > 10) {
                    // For editing existing config, enable save button but still test to get profiles
                    connectionTested = true;
                    saveBtn.disabled = false;
                    
                    // Auto-test to refresh quality profiles
                    setTimeout(() => {
                        window.testConnection();
                    }, 500);
                } else {
                    // New setup - disable save button until tested
                    saveBtn.disabled = true;
                }
            }

            // Initialize minimum availability toggle state and handler
            try {
                toggleMinimumAvailability();
                const minAvailCheckbox = document.getElementById('minAvailabilityEnabled');
                if (minAvailCheckbox) {
                    minAvailCheckbox.addEventListener('change', toggleMinimumAvailability);
                }
            } catch (_) { /* ignore */ }
        }
        
        // Add CSS animations if not present
        if (!document.getElementById('boxarrAnimations')) {
            const style = document.createElement('style');
            style.id = 'boxarrAnimations';
            style.textContent = `
                @keyframes slideIn {
                    from { transform: translateX(100%); opacity: 0; }
                    to { transform: translateX(0); opacity: 1; }
                }
                @keyframes slideOut {
                    from { transform: translateX(0); opacity: 1; }
                    to { transform: translateX(100%); opacity: 0; }
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `;
            document.head.appendChild(style);
        }
        
        // Handle Escape key for modals
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && isModalOpen) {
                const modals = document.querySelectorAll('.modal.show');
                modals.forEach(modal => modal.classList.remove('show'));
                isModalOpen = false;
            }
        });
    });

    // Cleanup on page unload
    window.addEventListener('beforeunload', function() {
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
        }
    });

    // Initialize scheduler debug on page load if present
    if (document.getElementById('schedulerDebugContent')) {
        refreshSchedulerStatus();
    }

    // Advanced Settings toggler
    window.toggleAdvancedSettings = function () {
        const content = document.getElementById('advancedSettingsContent');
        const chevron = document.getElementById('advancedSettingsChevron');
        if (!content || !chevron) return;
        const open = content.style.display !== 'none';
        content.style.display = open ? 'none' : 'block';
        chevron.textContent = open ? '▸' : '▾';
    };

    // Refresh root folders near the mapping select
    window.refreshRootFolders = function () {
        loadAvailableRootFolders(true);
    };

    window.refreshStoredMovieStatuses = async function (buttonEl) {
        const originalText = buttonEl ? buttonEl.textContent : 'Refresh Radarr Status';

        if (buttonEl) {
            buttonEl.disabled = true;
            buttonEl.textContent = 'Refreshing...';
        }

        try {
            const response = await fetch(apiUrlWithMarket('/movies/refresh-stored-status'), {
                method: 'POST'
            });
            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.detail || data.message || 'Failed to refresh movie data');
            }

            showMessage(
                `Refreshed ${data.movies_refreshed || 0} movie entries across ${data.weeks_updated || 0} weeks`,
                'success'
            );
            setTimeout(() => window.location.reload(), 800);
        } catch (error) {
            showMessage('Failed to refresh stored movie data: ' + error.message, 'error');
            if (buttonEl) {
                buttonEl.disabled = false;
                buttonEl.textContent = originalText;
            }
            return;
        }

        if (buttonEl) {
            buttonEl.disabled = false;
            buttonEl.textContent = originalText;
        }
    };

    // Toggle ignore status for a movie
    window.toggleIgnore = async function (tmdbId, title, buttonEl) {
        if (!tmdbId) return;

        const card = buttonEl.closest('.movie-card');
        const isCurrentlyIgnored = window.IGNORED_TMDB_IDS && window.IGNORED_TMDB_IDS.has(tmdbId);

        buttonEl.disabled = true;
        const origText = buttonEl.textContent;
        buttonEl.textContent = isCurrentlyIgnored ? 'Unignoring...' : 'Ignoring...';

        try {
            let response;
            if (isCurrentlyIgnored) {
                response = await fetch(apiUrlWithMarket('/movies/ignore/' + tmdbId), {
                    method: 'DELETE'
                });
            } else {
                response = await fetch(apiUrlWithMarket('/movies/ignore'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tmdb_id: tmdbId, title: title })
                });
            }

            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.detail || data.message || 'Failed');
            }

            // Update local state
            const ignoreBtn = card.querySelector('.ignore-btn');
            const unignoreBtn = card.querySelector('.unignore-btn');
            const addBtn = card.querySelector('.add-to-radarr');
            const upgradeBtn = card.querySelector('.upgrade');

            if (isCurrentlyIgnored) {
                // Unignoring
                window.IGNORED_TMDB_IDS.delete(tmdbId);
                card.classList.remove('ignored');
                const badge = card.querySelector('.ignored-badge');
                if (badge) badge.remove();
                // Show ignore btn + action buttons, hide unignore btn
                if (ignoreBtn) ignoreBtn.style.display = '';
                if (unignoreBtn) unignoreBtn.style.display = 'none';
                if (addBtn) addBtn.style.display = '';
                if (upgradeBtn) upgradeBtn.style.display = '';
            } else {
                // Ignoring
                window.IGNORED_TMDB_IDS.add(tmdbId);
                card.classList.add('ignored');
                if (!card.querySelector('.ignored-badge')) {
                    const badge = document.createElement('div');
                    badge.className = 'ignored-badge';
                    badge.textContent = 'Ignored';
                    card.appendChild(badge);
                }
                // Show unignore btn, hide ignore btn + action buttons
                if (ignoreBtn) ignoreBtn.style.display = 'none';
                if (unignoreBtn) unignoreBtn.style.display = '';
                if (addBtn) addBtn.style.display = 'none';
                if (upgradeBtn) upgradeBtn.style.display = 'none';
            }
        } catch (err) {
            buttonEl.textContent = origText;
            showToast('Error: ' + err.message, 'error');
        } finally {
            buttonEl.disabled = false;
        }
    };

    function resetBoxarrBatchState(prefix) {
        window[`${prefix}Results`] = [];
        window[`${prefix}Failures`] = [];
    }

    async function runBoxarrUpdate(year, week, market, prefix) {
        const normalizedMarket = normalizeMarket(market || getCurrentMarket());
        const response = await fetch(apiUrlWithMarket('/scheduler/update-week', normalizedMarket), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                year: parseInt(year),
                week: parseInt(week),
                market: normalizedMarket,
            }),
        });

        const data = await response.json();
        const entry = { year: parseInt(year), week: parseInt(week), market: normalizedMarket, ...data };

        if (!response.ok || !data.success) {
            window[`${prefix}Failures`].push(entry);
            return entry;
        }

        window[`${prefix}Results`].push(entry);
        return entry;
    }

    window.boxarrWeek = async function (year, week, market = getCurrentMarket()) {
        const normalizedMarket = normalizeMarket(market || getCurrentMarket());
        resetBoxarrBatchState('boxarrWeek');
        return runBoxarrUpdate(year, week, normalizedMarket, 'boxarrWeek');
    };

    window.boxarrTest = async function (items, delayMs = 500, market = getCurrentMarket()) {
        const normalizedMarket = normalizeMarket(market || getCurrentMarket());
        resetBoxarrBatchState('boxarrTest');
        for (const item of items || []) {
            const [year, week] = item;
            await runBoxarrUpdate(year, week, normalizedMarket, 'boxarrTest');
            if (delayMs > 0) {
                await new Promise(resolve => setTimeout(resolve, delayMs));
            }
        }
        return {
            results: window.boxarrTestResults,
            failures: window.boxarrTestFailures,
        };
    };

    window.boxarrWeeksForYear = async function (year, weeks, delayMs = 500, market = getCurrentMarket()) {
        const normalizedMarket = normalizeMarket(market || getCurrentMarket());
        resetBoxarrBatchState('boxarrWeeksForYear');
        for (const week of weeks || []) {
            await runBoxarrUpdate(year, week, normalizedMarket, 'boxarrWeeksForYear');
            if (delayMs > 0) {
                await new Promise(resolve => setTimeout(resolve, delayMs));
            }
        }
        return {
            results: window.boxarrWeeksForYearResults,
            failures: window.boxarrWeeksForYearFailures,
        };
    };

    window.boxarrOneYear = async function (year, delayMs = 500, market = getCurrentMarket()) {
        const normalizedMarket = normalizeMarket(market || getCurrentMarket());
        const weeks = Array.from({ length: 53 }, (_, idx) => idx + 1);
        resetBoxarrBatchState('boxarrOneYear');
        for (const week of weeks) {
            await runBoxarrUpdate(year, week, normalizedMarket, 'boxarrOneYear');
            if (delayMs > 0) {
                await new Promise(resolve => setTimeout(resolve, delayMs));
            }
        }
        return {
            results: window.boxarrOneYearResults,
            failures: window.boxarrOneYearFailures,
        };
    };

    window.boxarrYearsRange = async function (
        startYear,
        endYear,
        delayMs = 500,
        startWeek = 1,
        endWeek = 53,
        market = getCurrentMarket()
    ) {
        const normalizedMarket = normalizeMarket(market || getCurrentMarket());
        resetBoxarrBatchState('boxarrYearsRange');
        for (let year = startYear; year <= endYear; year++) {
            const firstWeek = year === startYear ? startWeek : 1;
            const lastWeek = year === endYear ? endWeek : 53;
            for (let week = firstWeek; week <= lastWeek; week++) {
                await runBoxarrUpdate(year, week, normalizedMarket, 'boxarrYearsRange');
                if (delayMs > 0) {
                    await new Promise(resolve => setTimeout(resolve, delayMs));
                }
            }
        }
        return {
            results: window.boxarrYearsRangeResults,
            failures: window.boxarrYearsRangeFailures,
        };
    };

})();
