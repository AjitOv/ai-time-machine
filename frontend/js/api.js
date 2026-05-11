/**
 * API Client – handles all communication with the FastAPI backend.
 */

// Auto-detect: use localhost for dev, Render for production
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8001/api/v1'
    : 'https://ai-time-machine-api.onrender.com/api/v1';

const api = {
    /**
     * Generic fetch wrapper with error handling.
     */
    async request(endpoint, options = {}) {
        const url = `${API_BASE}${endpoint}`;
        try {
            const response = await fetch(url, {
                headers: { 'Content-Type': 'application/json' },
                ...options,
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return await response.json();
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            throw error;
        }
    },

    // ── MARKET ──
    async getMarketData(symbol, timeframe = '1h', limit = 200) {
        const params = new URLSearchParams({ timeframe, limit });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/market/data?${params}`);
    },

    async fetchHistory(symbol, timeframe = '1h') {
        const params = new URLSearchParams({ timeframe });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/market/history?${params}`);
    },

    async ingestAll(symbol) {
        const params = new URLSearchParams();
        if (symbol) params.set('symbol', symbol);
        return this.request(`/market/ingest?${params}`, { method: 'POST' });
    },

    // ── ANALYSIS ──
    async runAnalysis(symbol, timeframe = '1h') {
        const params = new URLSearchParams({ timeframe });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/analysis/run?${params}`, { method: 'POST' });
    },

    async getContext(symbol, timeframe = '1h') {
        const params = new URLSearchParams({ timeframe });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/analysis/context?${params}`);
    },

    async getBehavior(symbol, timeframe = '1h') {
        const params = new URLSearchParams({ timeframe });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/analysis/behavior?${params}`);
    },

    async getDecision() {
        return this.request('/analysis/decision');
    },

    // ── SIMULATION ──
    async runSimulation(symbol, timeframe = '1h', numSims = 100, steps = 50) {
        const params = new URLSearchParams({
            timeframe,
            num_simulations: numSims,
            forecast_steps: steps,
        });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/simulation/run?${params}`, { method: 'POST' });
    },

    async getScenarios(symbol, timeframe = '1h') {
        const params = new URLSearchParams({ timeframe });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/simulation/scenarios?${params}`);
    },

    async getForecast({ symbol, timeframe = '1h', steps = 40, sims = 200, samples = 30 } = {}) {
        const params = new URLSearchParams({ timeframe, num_simulations: sims, forecast_steps: steps, sample_paths: samples });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/simulation/forecast?${params}`, { method: 'POST' });
    },

    // ── BACKTEST ──
    async runBacktest({ symbol, timeframe = '1h', warmup = 100, max_bars = 600 } = {}) {
        const params = new URLSearchParams({ timeframe, warmup, max_bars });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/backtest/run?${params}`, { method: 'POST' });
    },
    async seedDnaFromBacktest({ symbol, timeframe = '1h', warmup = 100, max_bars = 600, include_losses = true } = {}) {
        const params = new URLSearchParams({ timeframe, warmup, max_bars, include_losses });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/backtest/seed-dna?${params}`, { method: 'POST' });
    },

    // ── DATA IMPORT ──
    async importData({ path, symbol, timeframe = '', pin = true } = {}) {
        const params = new URLSearchParams({ path, symbol, pin });
        if (timeframe) params.set('timeframe', timeframe);
        return this.request(`/data/import?${params}`, { method: 'POST' });
    },
    async listCache() { return this.request('/data/cache'); },

    // ── SYSTEM ──
    async getHealth() {
        return this.request('/system/health');
    },

    async getPerformance(symbol) {
        const params = new URLSearchParams();
        if (symbol) params.set('symbol', symbol);
        return this.request(`/system/performance?${params}`);
    },

    async getWeights() {
        return this.request('/system/weights');
    },

    async getTrades(symbol, limit = 50) {
        const params = new URLSearchParams({ limit });
        if (symbol) params.set('symbol', symbol);
        return this.request(`/system/trades?${params}`);
    },

    async getActivity({ limit = 50, only_actionable = false } = {}) {
        const params = new URLSearchParams({ limit });
        if (only_actionable) params.set('only_actionable', 'true');
        return this.request(`/system/activity?${params}`);
    },

    async getDNALibrary(symbol) {
        const params = new URLSearchParams();
        if (symbol) params.set('symbol', symbol);
        return this.request(`/system/dna?${params}`);
    },

    // ── SCANNER ──
    async scanOpportunities({ universe = 'nifty50', timeframe = '1h', limit = 10, only_actionable = false, refresh = false } = {}) {
        const params = new URLSearchParams({ universe, timeframe, limit });
        if (only_actionable) params.set('only_actionable', 'true');
        if (refresh) params.set('refresh', 'true');
        return this.request(`/scanner/scan?${params}`);
    },

    // ── ACTIVITY ──
    async getActivity({ limit = 50, only_actionable = false } = {}) {
        const params = new URLSearchParams({ limit });
        if (only_actionable) params.set('only_actionable', 'true');
        return this.request(`/system/activity?${params}`);
    },

    // ── SYMBOLS ──
    async searchSymbols({ q = '', limit = 20, exchange = null, type = null } = {}) {
        const params = new URLSearchParams({ q, limit });
        if (exchange) params.set('exchange', exchange);
        if (type) params.set('type', type);
        return this.request(`/symbols/search?${params}`);
    },

    // ── PAPER LOOP ──
    async loopStatus()    { return this.request('/system/loop/status'); },
    async loopStart()     { return this.request('/system/loop/start',     { method: 'POST' }); },
    async loopStop()      { return this.request('/system/loop/stop',      { method: 'POST' }); },
    async loopScanOnce()  { return this.request('/system/loop/scan-once', { method: 'POST' }); },
    async loopResolveOnce(){ return this.request('/system/loop/resolve-once', { method: 'POST' }); },
    async openPositions() { return this.request('/system/open-positions'); },
    async paperTrades({ status = 'all', limit = 100 } = {}) {
        const params = new URLSearchParams({ status, limit });
        return this.request(`/system/paper-trades?${params}`);
    },

    // ── DHAN TOKEN ──
    async dhanTokenInfo() { return this.request('/system/dhan-token-info'); },
    async dhanTokenUpdate({ access_token, client_id }) {
        return this.request('/system/dhan-token', {
            method: 'POST',
            body: JSON.stringify({ access_token, client_id }),
        });
    },
};
