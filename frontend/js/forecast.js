/**
 * Forecast renderer — overlays Monte Carlo projections on the chart.
 *
 * Visual layers (back-to-front):
 *   1. ~30 sampled individual paths as faint thin lines (the "cloud")
 *   2. p5 / p95 outer band as dashed lines
 *   3. p25 / p75 inner band as dotted lines
 *   4. Mean projection line, brighter, thicker
 *   5. "NOW" vertical separator at the join point
 *   6. Horizontal target levels for Bullish / Neutral / Bearish scenarios
 */

const Forecast = {
    series: [],
    priceLines: [],
    ghostSeries: null,    // second candlestick series for predicted candles
    isVisible: true,
    lastForecast: null,

    init() {
        const btn = document.getElementById('forecast-toggle');
        if (btn) {
            btn.addEventListener('click', () => this.toggle());
            btn.classList.toggle('on', this.isVisible);
        }
    },

    toggle() {
        this.isVisible = !this.isVisible;
        const btn = document.getElementById('forecast-toggle');
        if (btn) btn.classList.toggle('on', this.isVisible);
        if (this.isVisible) {
            if (this.lastForecast) this.draw(this.lastForecast);
            else this.runAndDraw();
        } else {
            this.clear();
        }
    },

    clear() {
        if (!window.ChartManager || !window.ChartManager.chart) return;
        for (const s of this.series) {
            try { window.ChartManager.chart.removeSeries(s); } catch (_) {}
        }
        this.series = [];
        if (this.ghostSeries) {
            try { window.ChartManager.chart.removeSeries(this.ghostSeries); } catch (_) {}
            this.ghostSeries = null;
        }
        const candleSeries = window.ChartManager.candleSeries;
        if (candleSeries) {
            for (const pl of this.priceLines) {
                try { candleSeries.removePriceLine(pl); } catch (_) {}
            }
        }
        this.priceLines = [];
        const banner = document.getElementById('next-session-banner');
        if (banner) banner.innerHTML = '';
    },

    /**
     * Runs the forecast for the active App symbol/timeframe and draws.
     */
    async runAndDraw() {
        if (!window.App) return;
        try {
            const data = await api.getForecast({
                symbol: App.symbol,
                timeframe: App.timeframe,
                steps: 40,
                sims: 200,
                samples: 30,
            });
            if (data.error) {
                console.warn('forecast:', data.error);
                return;
            }
            this.lastForecast = data;
            if (this.isVisible) this.draw(data);
        } catch (e) {
            console.warn('forecast fetch failed', e);
        }
    },

    draw(data) {
        if (!window.ChartManager || !window.ChartManager.chart || !window.ChartManager.candleSeries) return;
        this.clear();

        const chart = window.ChartManager.chart;
        const bands = data.bands || [];
        const paths = data.paths || [];
        if (bands.length === 0) return;

        // ── 1. Sampled individual paths (faint cloud) ──
        for (const p of paths) {
            const line = chart.addLineSeries({
                color: 'rgba(124,210,255,0.10)',
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
            });
            line.setData(p.map(pt => ({ time: pt.t, value: pt.v })));
            this.series.push(line);
        }

        // ── 2. Outer band p5 / p95 (dashed) ──
        const p5 = chart.addLineSeries({
            color: 'rgba(244,114,182,0.55)', lineWidth: 1, lineStyle: 1, // dashed
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        p5.setData(bands.map(b => ({ time: b.t, value: b.p5 })));
        this.series.push(p5);

        const p95 = chart.addLineSeries({
            color: 'rgba(124,210,255,0.55)', lineWidth: 1, lineStyle: 1,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        p95.setData(bands.map(b => ({ time: b.t, value: b.p95 })));
        this.series.push(p95);

        // ── 3. Inner band p25 / p75 (dotted, more saturated) ──
        const p25 = chart.addLineSeries({
            color: 'rgba(244,114,182,0.35)', lineWidth: 1, lineStyle: 2, // dotted
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        p25.setData(bands.map(b => ({ time: b.t, value: b.p25 })));
        this.series.push(p25);

        const p75 = chart.addLineSeries({
            color: 'rgba(124,210,255,0.35)', lineWidth: 1, lineStyle: 2,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        p75.setData(bands.map(b => ({ time: b.t, value: b.p75 })));
        this.series.push(p75);

        // ── 4. Mean line (bright) ──
        const mean = chart.addLineSeries({
            color: '#a78bfa',
            lineWidth: 2,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        mean.setData(bands.map(b => ({ time: b.t, value: b.mean })));
        this.series.push(mean);

        // ── 4b. GHOST CANDLES — predicted next session as faded candles ──
        const predicted = data.predicted_candles || [];
        if (predicted.length > 0) {
            this.ghostSeries = chart.addCandlestickSeries({
                upColor:        'rgba(0, 255, 136, 0.18)',
                downColor:      'rgba(255, 86, 86, 0.18)',
                borderUpColor:   'rgba(0, 255, 136, 0.65)',
                borderDownColor: 'rgba(255, 86, 86, 0.65)',
                wickUpColor:     'rgba(0, 255, 136, 0.45)',
                wickDownColor:   'rgba(255, 86, 86, 0.45)',
                priceLineVisible: false,
                lastValueVisible: false,
            });
            this.ghostSeries.setData(predicted.map(c => ({
                time: c.t, open: c.open, high: c.high, low: c.low, close: c.close,
            })));
        }

        // ── 5. Scenario target horizontal lines ──
        const candleSeries = window.ChartManager.candleSeries;
        const summary = data.summary || {};
        const scenarios = data.scenarios || [];

        for (const sc of scenarios) {
            const colour = sc.label === 'BULLISH' ? '#00ff88'
                         : sc.label === 'BEARISH' ? '#ff5656'
                         : '#a78bfa';
            const pl = candleSeries.createPriceLine({
                price: sc.expected_price,
                color: colour,
                lineWidth: 1,
                lineStyle: 2, // dotted
                axisLabelVisible: true,
                title: `${sc.label} ${(sc.probability * 100).toFixed(0)}%  →  ${sc.expected_price}`,
            });
            this.priceLines.push(pl);
        }

        // ── 6. Update sidebar caption ──
        this.renderSidebar(summary, scenarios);

        // ── 7. Headline "next session" banner ──
        this.renderNextSession(data.next_session, summary, data.current_price);

        // Auto-scroll the chart so the future is in view
        try {
            chart.timeScale().scrollToRealTime();
            chart.timeScale().fitContent();
        } catch (_) {}
    },

    renderNextSession(ns, summary, currentPrice) {
        const el = document.getElementById('next-session-banner');
        if (!el || !ns) return;
        const arrow = ns.direction === 'UP' ? '↑' : ns.direction === 'DOWN' ? '↓' : '→';
        const cls   = ns.direction === 'UP' ? 'ns-up' : ns.direction === 'DOWN' ? 'ns-down' : 'ns-flat';
        const pct   = ns.expected_pct;
        const sign  = pct >= 0 ? '+' : '';
        const fmt   = (v) => Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        const dom = (summary.bullish_probability >= summary.bearish_probability && summary.bullish_probability >= summary.neutral_probability)
            ? { name: 'BULLISH', p: summary.bullish_probability }
            : (summary.bearish_probability >= summary.neutral_probability)
                ? { name: 'BEARISH', p: summary.bearish_probability }
                : { name: 'NEUTRAL', p: summary.neutral_probability };

        el.innerHTML = `
          <div class="ns-card ${cls}">
            <div class="ns-arrow">${arrow}</div>
            <div class="ns-main">
                <div class="ns-title">${ns.label}</div>
                <div class="ns-line">
                    <span>open <b>₹${fmt(ns.open)}</b></span>
                    <span>expected close <b>₹${fmt(ns.expected_close)}</b></span>
                    <span class="ns-pct">${sign}${pct.toFixed(2)}%</span>
                </div>
                <div class="ns-range">
                    range <b>₹${fmt(ns.expected_low)}</b> — <b>₹${fmt(ns.expected_high)}</b>
                    <span class="ns-dom">${dom.name} ${(dom.p * 100).toFixed(0)}%</span>
                </div>
            </div>
          </div>`;
    },

    renderSidebar(summary, scenarios) {
        const el = document.getElementById('forecast-summary');
        if (!el) return;
        const dom = scenarios.reduce((a, s) => s.probability > (a?.probability ?? -1) ? s : a, null);
        const probLine = scenarios.map(s => {
            const dot = s.label === 'BULLISH' ? '🟢' : s.label === 'BEARISH' ? '🔴' : '⚪';
            return `<span class="fc-prob"><b>${dot} ${s.label}</b> ${(s.probability * 100).toFixed(0)}% · ₹${s.expected_price.toLocaleString()}</span>`;
        }).join('');
        el.innerHTML = `
          <div class="fc-row">${probLine}</div>
          <div class="fc-row fc-meta">
              <span>regime <b>${summary.regime}</b></span>
              <span>phase <b>${summary.phase}</b></span>
              <span>dna <b>${summary.dna_direction || '—'}</b> ${summary.dna_confidence ? `(${(summary.dna_confidence*100).toFixed(0)}%)` : ''}</span>
              <span>bias <b class="${summary.simulation_bias > 0 ? 'pnl-pos' : summary.simulation_bias < 0 ? 'pnl-neg' : ''}">${summary.simulation_bias > 0 ? '+' : ''}${summary.simulation_bias}</b></span>
          </div>
          <div class="fc-row fc-meta">
              <span>5–95% range  <b>₹${summary.p5_final?.toLocaleString()} – ₹${summary.p95_final?.toLocaleString()}</b></span>
              <span>mean projection  <b>₹${summary.mean_final?.toLocaleString()}</b></span>
          </div>`;
    },
};

window.Forecast = Forecast;
document.addEventListener('DOMContentLoaded', () => Forecast.init());
