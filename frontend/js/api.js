/**
 * API Client – handles all communication with the FastAPI backend.
 */

const API_BASE = 'http://localhost:8000/api/v1';

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

    async getDNALibrary(symbol) {
        const params = new URLSearchParams();
        if (symbol) params.set('symbol', symbol);
        return this.request(`/system/dna?${params}`);
    },
};
