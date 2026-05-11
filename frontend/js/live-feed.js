/**
 * Live tick feed — connects to /api/v1/feed/ws and updates the last
 * candle on the chart in real time as Dhan ticks arrive.
 *
 * Markup contract: a #live-indicator element is toggled .on/.off/.connecting.
 */

const LiveFeed = {
    ws: null,
    reconnectTimer: null,
    backoff: 800,           // ms, doubles up to 30s
    symbol: null,
    timeframe: '1h',
    lastCandle: null,       // { time, open, high, low, close } – mutable
    candleSeconds: 3600,    // window length for the active candle in seconds
    onTickHandlers: [],

    _wsBase() {
        // In dev (localhost) talk to the local uvicorn server. In production
        // the backend lives on Render, NOT Vercel — `location.host` would
        // route the WS to the static-site host where there's no ws endpoint.
        const isLocal = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
        if (isLocal) return `ws://localhost:8001/api/v1/feed/ws`;
        return `wss://ai-time-machine-api.onrender.com/api/v1/feed/ws`;
    },

    setIndicator(state, label) {
        const el = document.getElementById('live-indicator');
        if (!el) return;
        el.classList.remove('on', 'off', 'connecting');
        el.classList.add(state);
        const txt = el.querySelector('.live-text');
        if (txt) txt.textContent = label || (state === 'on' ? 'LIVE' : state === 'connecting' ? 'CONNECTING' : 'OFFLINE');
    },

    /**
     * Set or change the active symbol/timeframe. Re-uses the existing socket
     * via the {action:"switch"} message, otherwise opens one.
     */
    subscribe(symbol, timeframe) {
        this.symbol = symbol;
        this.timeframe = timeframe || this.timeframe;
        this.candleSeconds = this._tfSeconds(this.timeframe);
        this.lastCandle = null; // will be set from the next chart.update()

        if (this.ws && this.ws.readyState === 1) {
            this.ws.send(JSON.stringify({ action: 'switch', symbol }));
            this.setIndicator('connecting');
            return;
        }
        this._openWs();
    },

    _openWs() {
        if (!this.symbol) return;
        clearTimeout(this.reconnectTimer);
        this.setIndicator('connecting');

        const url = `${this._wsBase()}?symbol=${encodeURIComponent(this.symbol)}`;
        try {
            this.ws = new WebSocket(url);
        } catch (e) {
            console.warn('Live feed WebSocket open failed', e);
            this._scheduleReconnect();
            return;
        }

        this.ws.onopen = () => {
            this.backoff = 800;
            this.setIndicator('connecting');
        };
        this.ws.onmessage = (ev) => {
            let data;
            try { data = JSON.parse(ev.data); } catch (_) { return; }
            if (data.error) {
                console.warn('Live feed error:', data.error);
                this.setIndicator('off', 'OFFLINE');
                return;
            }
            if (data.event === 'subscribed') {
                this.setIndicator('on');
                return;
            }
            if (typeof data.ltp === 'number') {
                this._applyTick(data);
            }
        };
        this.ws.onclose = () => {
            this.setIndicator('off');
            this._scheduleReconnect();
        };
        this.ws.onerror = () => {
            // onclose follows; reconnect path is handled there
        };
    },

    _scheduleReconnect() {
        if (this.reconnectTimer) return;
        const delay = this.backoff;
        this.backoff = Math.min(this.backoff * 1.6, 30000);
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this._openWs();
        }, delay);
    },

    _tfSeconds(tf) {
        const map = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400 };
        return map[tf] || 3600;
    },

    /**
     * Called from ChartManager.update to seed the in-memory current candle.
     * The chart already has the last candle drawn; we just need its values
     * so subsequent ticks can mutate it in place.
     */
    seedFromCandles(candles) {
        if (!candles || candles.length === 0) { this.lastCandle = null; return; }
        const last = candles[candles.length - 1];
        const t = Math.floor(new Date(last.timestamp).getTime() / 1000);
        this.lastCandle = {
            time: t,
            open: last.open,
            high: last.high,
            low: last.low,
            close: last.close,
        };
    },

    _applyTick(tick) {
        if (!this.lastCandle) return;
        if (typeof window.ChartManager === 'undefined' || !window.ChartManager.candleSeries) return;

        const ltp = tick.ltp;
        const now = Math.floor(Date.now() / 1000);
        const startTs = this.lastCandle.time;

        // If the LTP arrived for a new candle window, roll the candle forward.
        // We aim for the boundary that aligns with the timeframe.
        const elapsed = now - startTs;
        if (elapsed >= this.candleSeconds) {
            const newStart = startTs + Math.floor(elapsed / this.candleSeconds) * this.candleSeconds;
            this.lastCandle = {
                time: newStart,
                open: ltp,
                high: ltp,
                low: ltp,
                close: ltp,
            };
        } else {
            this.lastCandle.high = Math.max(this.lastCandle.high, ltp);
            this.lastCandle.low = Math.min(this.lastCandle.low, ltp);
            this.lastCandle.close = ltp;
        }

        try {
            window.ChartManager.candleSeries.update({
                time: this.lastCandle.time,
                open: this.lastCandle.open,
                high: this.lastCandle.high,
                low: this.lastCandle.low,
                close: this.lastCandle.close,
            });
        } catch (e) {
            // Series rejected the update — usually means stale time. Silent.
        }

        // Update the live price ticker if Components exposes one
        try {
            if (window.Components && typeof window.Components.updatePrice === 'function') {
                window.Components.updatePrice(ltp, null, /*live=*/true);
            }
        } catch (_) {}

        // Notify any other interested handler
        this.onTickHandlers.forEach(h => { try { h(tick); } catch (_) {} });
    },
};

window.LiveFeed = LiveFeed;
