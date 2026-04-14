/**
 * Main Application – orchestrates the AI Time Machine dashboard.
 */

const App = {
    symbol: 'SPY',
    timeframe: '1h',
    isLoading: false,
    lastAnalysis: null,
    refreshInterval: null,

    /**
     * Initialize the application.
     */
    async init() {
        console.log('🚀 AI Time Machine initializing...');

        // Initialize chart
        ChartManager.init('chart-container');

        // Bind events
        this.bindEvents();

        // Update clock
        this.startClock();

        // Check backend health
        try {
            const health = await api.getHealth();
            console.log('✅ Backend connected:', health);
            this.setStatus('ONLINE', true);
        } catch (e) {
            console.warn('⚠️ Backend not available:', e.message);
            this.setStatus('OFFLINE', false);
        }

        // Load initial data
        await this.loadMarketData();
        await this.loadTradeHistory();
        await this.loadPerformance();
    },

    /**
     * Bind all event listeners.
     */
    bindEvents() {
        // Analyze button
        document.getElementById('btn-run-analysis').addEventListener('click', () => {
            this.runAnalysis();
        });

        // Symbol selector
        document.getElementById('symbol-select').addEventListener('change', (e) => {
            this.symbol = e.target.value;
            this.loadMarketData();
        });

        // Timeframe buttons
        document.querySelectorAll('.tf-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.timeframe = e.target.dataset.tf;
                this.loadMarketData();
            });
        });

        // Keyboard shortcut: Enter to analyze
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                this.runAnalysis();
            }
        });
    },

    /**
     * Load and display market data + chart.
     */
    async loadMarketData() {
        try {
            // First try getting data; if empty, ingest
            let data = await api.getMarketData(this.symbol, this.timeframe, 200);

            if (!data.candles || data.candles.length === 0) {
                console.log('No cached data, fetching from yfinance...');
                await api.fetchHistory(this.symbol, this.timeframe);
                data = await api.getMarketData(this.symbol, this.timeframe, 200);
            }

            if (data.candles && data.candles.length > 0) {
                ChartManager.update(data.candles, data.features);

                // Update price display
                const latest = data.candles[data.candles.length - 1];
                const prev = data.candles.length > 1 ? data.candles[data.candles.length - 2] : latest;
                const change = ((latest.close - prev.close) / prev.close) * 100;
                Components.updatePrice(latest.close, change);
            }
        } catch (e) {
            console.error('Failed to load market data:', e);
        }
    },

    /**
     * Run the full analysis pipeline.
     */
    async runAnalysis() {
        if (this.isLoading) return;

        this.showLoading(true);
        this.isLoading = true;

        try {
            // Run full analysis
            const result = await api.runAnalysis(this.symbol, this.timeframe);
            this.lastAnalysis = result;

            console.log('📊 Analysis result:', result);

            // Update all panels
            Components.updateDecision(result.decision);
            Components.updateContext(result.context, result.behavior);
            Components.updateScenarios(result.scenarios, result.simulation);
            Components.updateDNA(result.dna, result.uncertainty, result.meta);
            Components.updatePerformance(null, result.weights);

            // Update price
            if (result.current_price) {
                Components.updatePrice(result.current_price, null);
            }

            // Update chart with markers
            await this.loadMarketData();
            if (result.decision) {
                ChartManager.addMarkers(result.decision);
                if (result.decision.direction !== 'NO_TRADE') {
                    ChartManager.addLevels(result.decision);
                }
            }

            // Reload trade history
            await this.loadTradeHistory();
            await this.loadPerformance();

        } catch (e) {
            console.error('Analysis failed:', e);
            alert('Analysis failed. Is the backend running? (python run.py)');
        } finally {
            this.isLoading = false;
            this.showLoading(false);
        }
    },

    /**
     * Load trade history.
     */
    async loadTradeHistory() {
        try {
            const data = await api.getTrades(this.symbol, 50);
            Components.updateTrades(data.trades);
        } catch (e) {
            // Silent fail – just log
            console.debug('Could not load trade history');
        }
    },

    /**
     * Load performance data.
     */
    async loadPerformance() {
        try {
            const data = await api.getPerformance(this.symbol);
            Components.updatePerformance(data.performance, null);
        } catch (e) {
            console.debug('Could not load performance data');
        }
    },

    /**
     * Show/hide loading overlay.
     */
    showLoading(show) {
        const overlay = document.getElementById('loading-overlay');
        if (show) {
            overlay.classList.add('active');
        } else {
            overlay.classList.remove('active');
        }
    },

    /**
     * Set system status indicator.
     */
    setStatus(text, online) {
        const el = document.getElementById('system-status');
        const dot = el.querySelector('.status-dot');
        const span = el.querySelector('span');

        span.textContent = text;
        dot.style.background = online ? 'var(--accent-green)' : 'var(--accent-red)';
        if (!online) dot.classList.remove('pulse');
    },

    /**
     * Start the footer clock.
     */
    startClock() {
        const update = () => {
            const now = new Date();
            document.getElementById('footer-time').textContent = now.toLocaleString('en-US', {
                weekday: 'short',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            });
        };
        update();
        setInterval(update, 1000);
    },
};

// ── BOOT ──
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
