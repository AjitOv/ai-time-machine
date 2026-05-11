/**
 * Chart Module – TradingView Lightweight Charts integration.
 */

const ChartManager = {
    chart: null,
    candleSeries: null,
    ema11Line: null,
    ema21Line: null,
    ema50Line: null,
    volumeSeries: null,

    /**
     * Initialize the chart in the container.
     */
    init(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        this.chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: container.clientHeight || 320,
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: 'rgba(232, 236, 244, 0.5)',
                fontSize: 11,
                fontFamily: "'Inter', sans-serif",
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: { color: 'rgba(0, 212, 255, 0.2)', width: 1, style: 2 },
                horzLine: { color: 'rgba(0, 212, 255, 0.2)', width: 1, style: 2 },
            },
            rightPriceScale: {
                borderColor: 'rgba(255, 255, 255, 0.06)',
                scaleMargins: { top: 0.1, bottom: 0.2 },
            },
            timeScale: {
                borderColor: 'rgba(255, 255, 255, 0.06)',
                timeVisible: true,
                secondsVisible: false,
            },
            handleScroll: { vertTouchDrag: false },
        });

        // Candlestick series
        this.candleSeries = this.chart.addCandlestickSeries({
            upColor: '#00ff88',
            downColor: '#ff4466',
            borderUpColor: '#00ff88',
            borderDownColor: '#ff4466',
            wickUpColor: 'rgba(0, 255, 136, 0.5)',
            wickDownColor: 'rgba(255, 68, 102, 0.5)',
        });

        // EMA lines
        this.ema11Line = this.chart.addLineSeries({
            color: 'rgba(0, 212, 255, 0.6)',
            lineWidth: 1,
            title: 'EMA 11',
            priceLineVisible: false,
            lastValueVisible: false,
        });
        this.ema21Line = this.chart.addLineSeries({
            color: 'rgba(168, 85, 247, 0.5)',
            lineWidth: 1,
            title: 'EMA 21',
            priceLineVisible: false,
            lastValueVisible: false,
        });
        this.ema50Line = this.chart.addLineSeries({
            color: 'rgba(255, 170, 0, 0.4)',
            lineWidth: 1.5,
            title: 'EMA 50',
            priceLineVisible: false,
            lastValueVisible: false,
        });

        // Volume
        this.volumeSeries = this.chart.addHistogramSeries({
            color: 'rgba(0, 212, 255, 0.15)',
            priceFormat: { type: 'volume' },
            priceScaleId: '',
        });
        this.volumeSeries.priceScale().applyOptions({
            scaleMargins: { top: 0.85, bottom: 0 },
        });

        // Resize handler
        const resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const { width, height } = entry.contentRect;
                this.chart.applyOptions({ width, height });
            }
        });
        resizeObserver.observe(container);
    },

    /**
     * Update chart with candle and feature data.
     */
    update(candles, features) {
        if (!this.chart || !candles || candles.length === 0) return;

        // Parse candle data
        const candleData = candles.map(c => ({
            time: Math.floor(new Date(c.timestamp).getTime() / 1000),
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
        }));

        // Volume data
        const volData = candles.map(c => ({
            time: Math.floor(new Date(c.timestamp).getTime() / 1000),
            value: c.volume,
            color: c.close >= c.open ? 'rgba(0, 255, 136, 0.12)' : 'rgba(255, 68, 102, 0.12)',
        }));

        this.candleSeries.setData(candleData);
        this.volumeSeries.setData(volData);

        // Seed the live tick feed with the latest candle so subsequent
        // ticks can mutate it in place without a full reload.
        if (window.LiveFeed && typeof window.LiveFeed.seedFromCandles === 'function') {
            window.LiveFeed.seedFromCandles(candles);
        }

        // EMA lines
        if (features && features.length > 0) {
            const ema11Data = features
                .filter(f => f.ema_11 !== null)
                .map(f => ({ time: Math.floor(new Date(f.timestamp).getTime() / 1000), value: f.ema_11 }));
            const ema21Data = features
                .filter(f => f.ema_21 !== null)
                .map(f => ({ time: Math.floor(new Date(f.timestamp).getTime() / 1000), value: f.ema_21 }));
            const ema50Data = features
                .filter(f => f.ema_50 !== null)
                .map(f => ({ time: Math.floor(new Date(f.timestamp).getTime() / 1000), value: f.ema_50 }));

            if (ema11Data.length) this.ema11Line.setData(ema11Data);
            if (ema21Data.length) this.ema21Line.setData(ema21Data);
            if (ema50Data.length) this.ema50Line.setData(ema50Data);
        }

        // Fit content
        this.chart.timeScale().fitContent();
    },

    /**
     * Add buy/sell markers on the chart.
     */
    addMarkers(decision) {
        if (!this.candleSeries || !decision) return;
        if (decision.direction === 'NO_TRADE') return;

        const markers = [];
        const now = Math.floor(Date.now() / 1000);

        if (decision.direction === 'BUY') {
            markers.push({
                time: now,
                position: 'belowBar',
                color: '#00ff88',
                shape: 'arrowUp',
                text: `BUY @ ${decision.entry_price}`,
            });
        } else if (decision.direction === 'SELL') {
            markers.push({
                time: now,
                position: 'aboveBar',
                color: '#ff4466',
                shape: 'arrowDown',
                text: `SELL @ ${decision.entry_price}`,
            });
        }

        if (markers.length > 0) {
            this.candleSeries.setMarkers(markers);
        }
    },

    /**
     * Add horizontal price lines for SL/TP levels.
     */
    addLevels(decision) {
        if (!this.candleSeries || !decision) return;

        // Remove previous lines (re-set)
        // Entry
        if (decision.entry_price > 0) {
            this.candleSeries.createPriceLine({
                price: decision.entry_price,
                color: 'rgba(0, 212, 255, 0.5)',
                lineWidth: 1,
                lineStyle: 2,
                title: 'Entry',
            });
        }
        // Stop Loss
        if (decision.stop_loss > 0) {
            this.candleSeries.createPriceLine({
                price: decision.stop_loss,
                color: 'rgba(255, 68, 102, 0.5)',
                lineWidth: 1,
                lineStyle: 2,
                title: 'SL',
            });
        }
        // Take Profit
        if (decision.take_profit > 0) {
            this.candleSeries.createPriceLine({
                price: decision.take_profit,
                color: 'rgba(0, 255, 136, 0.5)',
                lineWidth: 1,
                lineStyle: 2,
                title: 'TP',
            });
        }
    },
};
