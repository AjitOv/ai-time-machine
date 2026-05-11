/**
 * Main Application – orchestrates the AI Time Machine dashboard.
 */

const App = {
    symbol: 'NSE:NIFTY50-INDEX',
    timeframe: '1h',
    isLoading: false,
    autoAnalyze: true,
    paperTab: 'all',
    lastAnalysis: null,
    refreshInterval: null,
    activityInterval: null,

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

        // Auto-refresh chart every 60s — catches candle rollovers and any ticks
        // the WebSocket may have missed.
        this.startMarketDataRefresh();

        // Draw the initial forecast cone so users see "the future" right away.
        if (window.Forecast) window.Forecast.runAndDraw();
    },

    /**
     * Bind all event listeners.
     */
    bindEvents() {
        // Analyze button
        document.getElementById('btn-run-analysis').addEventListener('click', () => {
            this.runAnalysis();
        });

        // Auto-analyze toggle
        const autoEl = document.getElementById('auto-analyze');
        if (autoEl) {
            this.autoAnalyze = autoEl.checked;
            autoEl.addEventListener('change', (e) => { this.autoAnalyze = e.target.checked; });
        }

        // Symbol selector — load + (optionally) auto-analyze
        document.getElementById('symbol-select').addEventListener('change', async (e) => {
            this.symbol = e.target.value;
            await this.loadMarketData();
            if (this.autoAnalyze) this.runAnalysis();
        });

        // Timeframe buttons — load + (optionally) auto-analyze
        document.querySelectorAll('.tf-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.timeframe = e.target.dataset.tf;
                await this.loadMarketData();
                if (this.autoAnalyze) this.runAnalysis();
            });
        });

        // Keyboard shortcut: Enter to analyze
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                this.runAnalysis();
            }
        });

        // Scanner panel
        const scanBtn = document.getElementById('scanner-run');
        if (scanBtn) {
            scanBtn.addEventListener('click', () => this.runScanner({ refresh: true }));
            // First load: serve cached results if available
            this.runScanner({ refresh: false });
        }

        // Activity panel
        const actBtn = document.getElementById('activity-refresh');
        const actChk = document.getElementById('activity-actionable');
        if (actBtn) actBtn.addEventListener('click', () => this.loadActivity());
        if (actChk) actChk.addEventListener('change', () => this.loadActivity());
        this.loadActivity();
        // Auto-refresh activity every 20s so new analysis runs surface without a click
        this.activityInterval = setInterval(() => this.loadActivity(), 20000);

        // Backtest panel
        const btBtn = document.getElementById('bt-run');
        if (btBtn) btBtn.addEventListener('click', () => this.runBacktest());
        const btSeed = document.getElementById('bt-seed-dna');
        if (btSeed) btSeed.addEventListener('click', () => this.seedDnaFromBacktest());

        // Import panel
        const impBtn = document.getElementById('import-run');
        if (impBtn) impBtn.addEventListener('click', () => this.runImport());
        const cacheBtn = document.getElementById('import-cache-list');
        if (cacheBtn) cacheBtn.addEventListener('click', () => this.toggleCacheList());

        // Paper loop panel
        const tBtn = document.getElementById('paper-toggle');
        const sNow = document.getElementById('paper-scan-now');
        const rNow = document.getElementById('paper-resolve-now');
        if (tBtn) tBtn.addEventListener('click', () => this.toggleLoop());
        if (sNow) sNow.addEventListener('click', () => this.loopScanNow());
        if (rNow) rNow.addEventListener('click', () => this.loopResolveNow());
        // Token pill (header) — opens modal
        const tokPill = document.getElementById('token-pill');
        const tokModal = document.getElementById('token-modal');
        const tokClose = document.getElementById('token-modal-close');
        const tokCancel = document.getElementById('token-cancel');
        const tokSave = document.getElementById('token-save');
        if (tokPill) tokPill.addEventListener('click', () => this.openTokenModal());
        if (tokClose) tokClose.addEventListener('click', () => this.closeTokenModal());
        if (tokCancel) tokCancel.addEventListener('click', () => this.closeTokenModal());
        if (tokSave) tokSave.addEventListener('click', () => this.saveToken());
        if (tokModal) tokModal.addEventListener('click', (e) => {
            if (e.target === tokModal) this.closeTokenModal();
        });
        // First refresh + every 60s
        this.refreshTokenStatus();
        setInterval(() => this.refreshTokenStatus(), 60000);

        document.querySelectorAll('.paper-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                document.querySelectorAll('.paper-tab').forEach(t => t.classList.remove('active'));
                e.target.classList.add('active');
                this.paperTab = e.target.dataset.tab;
                this.refreshLoop();
            });
        });
        this.refreshLoop();
        this.loopInterval = setInterval(() => this.refreshLoop(), 10000);
    },

    /**
     * Pull current paper-loop status + open positions, render both.
     */
    async refreshLoop() {
        try {
            const [status, paper] = await Promise.all([
                api.loopStatus(),
                api.paperTrades({ status: this.paperTab, limit: 100 }),
            ]);
            this.renderLoopStatus(status);
            this.renderOpenPositions(paper.trades || []);
        } catch (e) {
            // backend likely down; leave UI as-is
        }
    },

    renderLoopStatus(s) {
        const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        const stateEl = document.getElementById('ps-state');
        if (stateEl) {
            stateEl.textContent = s.enabled ? 'RUNNING' : 'STOPPED';
            stateEl.className = 'ps-v ' + (s.enabled ? 'ps-on' : 'ps-off');
        }
        const marketEl = document.getElementById('ps-market');
        if (marketEl) {
            marketEl.textContent = s.market_open ? 'OPEN' : 'CLOSED';
            marketEl.className = 'ps-v ' + (s.market_open ? 'ps-on' : 'ps-off');
        }
        setText('ps-open', String(s.open_positions ?? 0));
        setText('ps-last-scan', s.last_scan_at ? new Date(s.last_scan_at).toLocaleTimeString() : '—');
        setText('ps-last-signals', s.last_scan_total ? `${s.last_scan_signals} / ${s.last_scan_total}` : '—');
        setText('ps-next-scan', s.next_scan_in == null ? '—' : `${s.next_scan_in}s`);

        const btn = document.getElementById('paper-toggle');
        if (btn) {
            btn.textContent = s.enabled ? 'Stop loop' : 'Start loop';
            btn.classList.toggle('paper-stop', !!s.enabled);
        }
    },

    renderOpenPositions(trades) {
        const tbody = document.getElementById('paper-positions-tbody');
        if (!tbody) return;
        if (trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="13" class="no-data">No paper trades in this view.</td></tr>';
            return;
        }
        const fmt = (v, dp = 2) => v == null ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
        const fmtSign = (v) => {
            if (v == null) return '—';
            const n = Number(v);
            const sign = n > 0 ? '+' : '';
            return `${sign}${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        };

        tbody.innerHTML = trades.map(t => {
            const dir = (t.direction || '').toUpperCase();
            const dirClass = dir === 'BUY' ? 'dir-buy' : 'dir-sell';
            const cleanSym = (t.symbol || '').replace(/^NSE:/, '').replace(/^BSE:/, '').replace(/^MCX:/, '').replace(/-EQ$/, '').replace(/-INDEX$/, '');
            const time = t.timestamp ? new Date(t.timestamp).toLocaleString('en-IN', {
                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
            }) : '—';

            const isOpen = !t.is_realized;
            const curOrExit = isOpen ? t.current_price : t.exit_price;
            const pnl = t.pnl_value;
            const pct = t.pnl_pct;
            const rr = t.rr_realized;

            const pnlCls = pnl == null ? '' : (pnl > 0 ? 'pnl-pos' : pnl < 0 ? 'pnl-neg' : 'pnl-flat');

            const outcome = isOpen ? 'OPEN' : (t.outcome || '—').toUpperCase();
            const outClass = outcome === 'WIN' ? 'dir-buy' : outcome === 'LOSS' ? 'dir-sell' : outcome === 'TIMEOUT' ? 'dir-flat' : 'dir-open';

            return `
                <tr class="${isOpen ? 'row-open' : 'row-closed'}">
                  <td class="time-cell">${time}</td>
                  <td class="sym">${cleanSym}</td>
                  <td>${t.timeframe || '—'}</td>
                  <td><span class="dir-pill ${dirClass}">${dir}</span></td>
                  <td class="num">${fmt(t.entry_price)}</td>
                  <td class="num ${isOpen ? 'live-cell' : ''}">${fmt(curOrExit)}</td>
                  <td class="num">${fmt(t.stop_loss)}</td>
                  <td class="num">${fmt(t.take_profit)}</td>
                  <td class="num ${pnlCls}">${fmtSign(pnl)}</td>
                  <td class="num ${pnlCls}">${pct == null ? '—' : (pct > 0 ? '+' : '') + pct.toFixed(2) + '%'}</td>
                  <td class="num">${rr == null ? '—' : '1:' + rr.toFixed(2)}</td>
                  <td><span class="dir-pill ${outClass}">${outcome}</span></td>
                  <td><button class="btn-mini" data-sym="${t.symbol}" data-tf="${t.timeframe || '1h'}">→</button></td>
                </tr>`;
        }).join('');

        tbody.querySelectorAll('button.btn-mini').forEach(b => {
            b.addEventListener('click', () => {
                const sym = b.dataset.sym, tf = b.dataset.tf;
                const sel = document.getElementById('symbol-select');
                if (sel) sel.value = sym;
                this.symbol = sym;
                this.timeframe = tf;
                document.querySelectorAll('.tf-btn').forEach(b2 => b2.classList.toggle('active', b2.dataset.tf === tf));
                this.loadMarketData().then(() => this.runAnalysis());
                window.scrollTo({ top: 0, behavior: 'smooth' });
            });
        });
    },

    async toggleLoop() {
        const btn = document.getElementById('paper-toggle');
        if (!btn) return;
        const wasRunning = btn.classList.contains('paper-stop');
        btn.disabled = true;
        try {
            if (wasRunning) await api.loopStop();
            else await api.loopStart();
            await this.refreshLoop();
        } catch (e) {
            console.warn('toggle failed', e);
        } finally {
            btn.disabled = false;
        }
    },

    async loopScanNow() {
        const btn = document.getElementById('paper-scan-now');
        btn.disabled = true; btn.textContent = 'Scanning…';
        try { await api.loopScanOnce(); await this.refreshLoop(); await this.loadActivity(); }
        catch (e) { console.warn('scan-now failed', e); }
        finally { btn.disabled = false; btn.textContent = 'Scan now'; }
    },

    async loopResolveNow() {
        const btn = document.getElementById('paper-resolve-now');
        btn.disabled = true; btn.textContent = 'Resolving…';
        try { await api.loopResolveOnce(); await this.refreshLoop(); await this.loadActivity(); await this.loadPerformance(); }
        catch (e) { console.warn('resolve-now failed', e); }
        finally { btn.disabled = false; btn.textContent = 'Resolve now'; }
    },

    /**
     * Pull JWT-decoded info about the current Dhan token, colour the header
     * pill: green = healthy, amber = < 2h to expiry, red = expired/missing.
     */
    async refreshTokenStatus() {
        const pill = document.getElementById('token-pill');
        const text = document.getElementById('token-text');
        if (!pill || !text) return;
        try {
            const info = await api.dhanTokenInfo();
            this._lastTokenInfo = info;
            pill.classList.remove('ok', 'warn', 'err');
            if (!info.configured) {
                pill.classList.add('err');
                text.textContent = 'DHAN — NOT SET';
                return;
            }
            if (info.expired) {
                pill.classList.add('err');
                text.textContent = 'DHAN — EXPIRED';
                return;
            }
            if (info.warn) {
                pill.classList.add('warn');
                text.textContent = `DHAN — ${this._fmtDuration(info.seconds_left)}`;
                return;
            }
            pill.classList.add('ok');
            text.textContent = `DHAN — ${this._fmtDuration(info.seconds_left)}`;
        } catch (_) {
            pill.classList.add('err');
            text.textContent = 'DHAN — ?';
        }
    },

    _fmtDuration(sec) {
        if (sec == null) return '—';
        if (sec <= 0) return 'expired';
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m`;
    },

    openTokenModal() {
        const m = document.getElementById('token-modal');
        const info = document.getElementById('token-info');
        if (info) {
            const t = this._lastTokenInfo || {};
            if (!t.configured) info.textContent = 'No token configured.';
            else if (t.expired) info.textContent = 'Token EXPIRED — refresh to restore live data.';
            else if (t.seconds_left != null) info.textContent = `Current token expires in ${this._fmtDuration(t.seconds_left)} (client ${t.client_id || ''}).`;
            else info.textContent = '—';
        }
        document.getElementById('token-input').value = '';
        m.hidden = false;
    },

    closeTokenModal() {
        document.getElementById('token-modal').hidden = true;
    },

    /**
     * Run a backtest against the currently selected symbol.
     */
    async runBacktest() {
        const btn = document.getElementById('bt-run');
        const status = document.getElementById('bt-status');
        const tf = document.getElementById('bt-timeframe').value;
        const maxBars = parseInt(document.getElementById('bt-bars').value, 10);

        btn.disabled = true;
        btn.textContent = 'Running…';
        status.innerHTML = `<span class="bt-running">⏳ Replaying ${maxBars} bars of ${this.symbol} ${tf} through the engine stack…</span>`;

        try {
            const result = await api.runBacktest({
                symbol: this.symbol,
                timeframe: tf,
                warmup: 100,
                max_bars: maxBars,
            });
            this.renderBacktest(result);
            status.innerHTML = '';
        } catch (e) {
            console.error('backtest failed', e);
            status.innerHTML = `<span class="bt-err">Backtest failed: ${e.message}</span>`;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Run backtest';
        }
    },

    renderBacktest(r) {
        // ── Stats grid ──
        const setText = (id, v, cls) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.textContent = v;
            el.className = 'ps-v ' + (cls || '');
        };
        const sign = (v, dec = 2) => {
            const n = Number(v);
            return (n > 0 ? '+' : '') + n.toFixed(dec);
        };
        const wrCls = r.win_rate > 0.55 ? 'ps-on' : r.win_rate < 0.45 ? 'pnl-neg' : '';
        const totalCls = r.total_pnl_pct > 0 ? 'ps-on' : r.total_pnl_pct < 0 ? 'pnl-neg' : '';
        const pfCls = r.profit_factor > 1.5 ? 'ps-on' : r.profit_factor < 1.0 ? 'pnl-neg' : '';

        setText('bt-total', sign(r.total_pnl_pct) + '%', totalCls);
        setText('bt-count', `${r.total_trades} (${r.wins}W / ${r.losses}L)`);
        setText('bt-wr',  (r.win_rate * 100).toFixed(1) + '%', wrCls);
        setText('bt-pf',  r.profit_factor.toFixed(2), pfCls);
        setText('bt-rr',  '1:' + r.avg_rr.toFixed(2));
        setText('bt-dd',  r.max_drawdown_pct.toFixed(2) + '%', 'pnl-neg');
        setText('bt-sharpe', r.sharpe_ratio.toFixed(2), r.sharpe_ratio > 1 ? 'ps-on' : '');
        setText('bt-runtime', `${r.bars_processed} bars · ${r.runtime_ms}ms`);

        document.getElementById('bt-stats').hidden = false;

        // ── Equity curve SVG ──
        this.renderEquityCurve(r);
        document.getElementById('bt-equity-wrap').hidden = false;
        document.getElementById('bt-equity-meta').textContent =
            `${new Date(r.start_ts).toLocaleDateString()} → ${new Date(r.end_ts).toLocaleDateString()} · ${r.symbol} ${r.timeframe}`;

        // ── Breakdowns ──
        const dirHtml = Object.entries(r.by_direction).map(([k, v]) => `
            <div class="bt-bd-row">
                <span class="dir-pill ${k === 'BUY' ? 'dir-buy' : 'dir-sell'}">${k}</span>
                <span class="bt-bd-num">${v.count} trades</span>
                <span class="bt-bd-num">${(v.win_rate * 100).toFixed(0)}% WR</span>
                <span class="bt-bd-num ${v.avg_pnl_pct > 0 ? 'pnl-pos' : 'pnl-neg'}">${sign(v.avg_pnl_pct, 2)}%</span>
            </div>`).join('') || '<div class="no-data">—</div>';
        document.getElementById('bt-by-dir').innerHTML = dirHtml;

        const regHtml = Object.entries(r.by_regime).filter(([k]) => !k.startsWith('_')).map(([k, v]) => `
            <div class="bt-bd-row">
                <span class="bt-bd-tag">${k}</span>
                <span class="bt-bd-num">${v.count} trades</span>
                <span class="bt-bd-num">${(v.win_rate * 100).toFixed(0)}% WR</span>
                <span class="bt-bd-num ${v.avg_pnl_pct > 0 ? 'pnl-pos' : 'pnl-neg'}">${sign(v.avg_pnl_pct, 2)}%</span>
            </div>`).join('') || '<div class="no-data">No trades classified by regime</div>';
        document.getElementById('bt-by-regime').innerHTML = regHtml;
        document.getElementById('bt-breakdowns').hidden = false;

        // ── Trade ledger ──
        const tradesHtml = (r.trades || []).slice(-50).reverse().map(t => {
            const pnlCls = t.pnl_pct > 0 ? 'pnl-pos' : t.pnl_pct < 0 ? 'pnl-neg' : '';
            const dirCls = t.direction === 'BUY' ? 'dir-buy' : 'dir-sell';
            const outCls = t.outcome === 'WIN' ? 'dir-buy' : t.outcome === 'LOSS' ? 'dir-sell' : 'dir-flat';
            const time = t.timestamp ? new Date(t.timestamp).toLocaleString('en-IN', {
                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
            }) : '—';
            return `
                <tr>
                  <td class="time-cell">${time}</td>
                  <td><span class="dir-pill ${dirCls}">${t.direction}</span></td>
                  <td class="num">${Number(t.entry_price).toFixed(2)}</td>
                  <td class="num">${t.exit_price != null ? Number(t.exit_price).toFixed(2) : '—'}</td>
                  <td class="num ${pnlCls}">${sign(t.pnl_pct, 2)}%</td>
                  <td class="num">1:${Number(t.rr_realized).toFixed(2)}</td>
                  <td class="num">${t.bars_held}</td>
                  <td class="num">${(t.confidence * 100).toFixed(0)}%</td>
                  <td>${t.regime}</td>
                  <td>${t.phase}</td>
                  <td><span class="dir-pill ${outCls}">${t.outcome}</span></td>
                </tr>`;
        }).join('') || '<tr><td colspan="11" class="no-data">No trades produced — try a longer max_bars.</td></tr>';
        document.getElementById('bt-trades-tbody').innerHTML = tradesHtml;
        document.getElementById('bt-trades-wrap').hidden = false;

        // Enable the "Seed DNA" button — there are now patterns to seed
        const seedBtn = document.getElementById('bt-seed-dna');
        if (seedBtn) {
            seedBtn.disabled = (r.total_trades === 0);
            const winners = r.wins;
            const losers = r.losses;
            seedBtn.title = `Seed the live DNA library with ${winners} winners + ${losers} losers from this backtest`;
        }
    },

    async runImport() {
        const path = document.getElementById('import-path').value.trim();
        const symbol = document.getElementById('import-symbol').value.trim();
        const tf = document.getElementById('import-timeframe').value;
        const pin = document.getElementById('import-pin').checked;
        const status = document.getElementById('import-status');
        const btn = document.getElementById('import-run');

        if (!path || !symbol) {
            status.innerHTML = '<span class="bt-err">File path and symbol are required.</span>';
            return;
        }

        btn.disabled = true; btn.textContent = 'Importing…';
        status.innerHTML = '<span class="bt-running">⏳ Loading + parsing the file…</span>';
        try {
            const r = await api.importData({ path, symbol, timeframe: tf, pin });
            if (!r.ok) {
                status.innerHTML = `<span class="bt-err">${r.error}</span>`;
                return;
            }
            const span = (new Date(r.end) - new Date(r.start)) / (365.25 * 24 * 3600 * 1000);
            status.innerHTML = `
              <span class="bt-success">
                ✓ Loaded <b>${r.rows.toLocaleString()}</b> ${r.timeframe} candles for <b>${r.symbol}</b>
                — ${r.start.slice(0,10)} → ${r.end.slice(0,10)}
                (${span.toFixed(2)} years, ₹${r.first_close.toLocaleString()} → ₹${r.last_close.toLocaleString()})
                ${r.pinned ? '· pinned' : ''}
              </span>
              <div class="import-hint">Now switch the chart to <b>${r.symbol}</b> · <b>${r.timeframe}</b> and run a Backtest — it'll replay the imported history.</div>`;
        } catch (e) {
            status.innerHTML = `<span class="bt-err">Import failed: ${e.message}</span>`;
        } finally {
            btn.disabled = false; btn.textContent = 'Import';
        }
    },

    async toggleCacheList() {
        const wrap = document.getElementById('cache-list-wrap');
        const tbody = document.getElementById('cache-list-tbody');
        if (!wrap || !tbody) return;
        if (!wrap.hidden) { wrap.hidden = true; return; }
        try {
            const data = await api.listCache();
            tbody.innerHTML = (data.entries || []).map(e => `
                <tr>
                  <td class="sym">${e.key}</td>
                  <td class="num">${e.rows.toLocaleString()}</td>
                  <td class="time-cell">${e.start.slice(0,16).replace('T',' ')}</td>
                  <td class="time-cell">${e.end.slice(0,16).replace('T',' ')}</td>
                  <td>${e.pinned ? '<span class="dir-pill dir-buy">PIN</span>' : '—'}</td>
                </tr>`).join('') || '<tr><td colspan="5" class="no-data">Cache empty.</td></tr>';
            wrap.hidden = false;
        } catch (e) {
            console.warn('cache list failed', e);
        }
    },

    async seedDnaFromBacktest() {
        const seedBtn = document.getElementById('bt-seed-dna');
        const status = document.getElementById('bt-status');
        const tf = document.getElementById('bt-timeframe').value;
        const maxBars = parseInt(document.getElementById('bt-bars').value, 10);

        const ok = confirm(
            `Seed the live DNA library from a fresh ${maxBars}-bar backtest of ${this.symbol} ${tf}?\n\n` +
            `This will create or update SetupDNA records for every WIN and LOSS pattern. ` +
            `The live system will start matching against these patterns immediately.`
        );
        if (!ok) return;

        seedBtn.disabled = true;
        const orig = seedBtn.textContent;
        seedBtn.textContent = '🧬 Seeding…';
        status.innerHTML = `<span class="bt-running">⏳ Replaying ${maxBars} bars and writing pattern memory…</span>`;

        try {
            const r = await api.seedDnaFromBacktest({
                symbol: this.symbol,
                timeframe: tf,
                warmup: 100,
                max_bars: maxBars,
                include_losses: true,
            });
            if (!r.ok) throw new Error(r.reason || 'seed failed');
            status.innerHTML =
                `<span class="bt-success">✓ Seeded ${r.seeded_wins} winning + ${r.seeded_losses} losing patterns into the live DNA library` +
                ` from ${r.total_trades} trades over ${r.bars_processed} bars (WR ${(r.win_rate_seed*100).toFixed(1)}%, PF ${r.profit_factor.toFixed(2)}).</span>`;
        } catch (e) {
            console.error('seed-dna failed', e);
            status.innerHTML = `<span class="bt-err">Seed failed: ${e.message}</span>`;
        } finally {
            seedBtn.disabled = false;
            seedBtn.textContent = orig;
        }
    },

    renderEquityCurve(r) {
        const svg = document.getElementById('bt-equity');
        if (!svg) return;
        const W = 900, H = 200, PAD = 24;
        svg.innerHTML = '';
        const pts = r.equity_curve || [];
        if (pts.length < 2) return;

        const eqs = pts.map(p => p.equity);
        const minE = Math.min(...eqs);
        const maxE = Math.max(...eqs);
        const range = maxE - minE || 1;

        const x = (i) => PAD + (i / (pts.length - 1)) * (W - 2 * PAD);
        const y = (e) => H - PAD - ((e - minE) / range) * (H - 2 * PAD);

        // Baseline (starting equity) line
        const start = pts[0].equity;
        const yStart = y(start);
        const baseline = `<line x1="${PAD}" x2="${W - PAD}" y1="${yStart}" y2="${yStart}" stroke="rgba(255,255,255,0.12)" stroke-dasharray="3,3"/>`;

        // Equity polyline
        const pathD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(p.equity).toFixed(1)}`).join(' ');
        const finalEq = pts[pts.length - 1].equity;
        const stroke = finalEq >= start ? '#00ff88' : '#ff5656';
        const fill = finalEq >= start ? 'rgba(0,255,136,0.10)' : 'rgba(255,86,86,0.10)';

        // Filled area below the curve (down to baseline)
        const areaD = pathD + ` L ${x(pts.length - 1).toFixed(1)} ${yStart} L ${x(0).toFixed(1)} ${yStart} Z`;

        // Drawdown shading on the worst point
        let worstIdx = 0;
        for (let i = 0; i < pts.length; i++) {
            if (pts[i].drawdown < pts[worstIdx].drawdown) worstIdx = i;
        }

        svg.innerHTML = `
            ${baseline}
            <path d="${areaD}" fill="${fill}" stroke="none"/>
            <path d="${pathD}" fill="none" stroke="${stroke}" stroke-width="1.6" stroke-linejoin="round"/>
            <line x1="${x(worstIdx)}" x2="${x(worstIdx)}" y1="${PAD}" y2="${H - PAD}" stroke="rgba(255,86,86,0.4)" stroke-dasharray="2,3"/>
            <text x="${x(worstIdx) + 4}" y="${PAD + 12}" fill="#ff5656" font-size="10" font-family="JetBrains Mono">max DD ${pts[worstIdx].drawdown.toFixed(2)}%</text>
            <text x="${PAD}" y="${PAD - 8}" fill="#888" font-size="10" font-family="JetBrains Mono">₹${minE.toFixed(0)} – ₹${maxE.toFixed(0)}</text>
            <text x="${W - PAD}" y="${PAD - 8}" text-anchor="end" fill="${stroke}" font-size="10" font-family="JetBrains Mono">final ₹${finalEq.toFixed(0)}</text>
        `;
    },

    async saveToken() {
        const btn = document.getElementById('token-save');
        const ta = document.getElementById('token-input');
        const tok = ta.value.trim();
        if (!tok || tok.split('.').length !== 3) {
            ta.focus();
            return alert('That doesn\'t look like a JWT — should be 3 parts separated by dots.');
        }
        btn.disabled = true; btn.textContent = 'Saving…';
        try {
            const r = await api.dhanTokenUpdate({ access_token: tok });
            if (!r.ok) throw new Error(r.error || 'token update failed');
            await this.refreshTokenStatus();
            this.closeTokenModal();
            // Force-reload market data with the fresh token
            await this.loadMarketData();
            await this.refreshLoop();
        } catch (e) {
            alert('Token update failed: ' + e.message);
        } finally {
            btn.disabled = false; btn.textContent = 'Save & hot-swap';
        }
    },

    /**
     * Render the cross-symbol Recent Activity table.
     */
    async loadActivity() {
        const tbody = document.getElementById('activity-tbody');
        const meta = document.getElementById('activity-meta');
        if (!tbody) return;

        const onlyActionable = !!document.getElementById('activity-actionable')?.checked;
        try {
            const data = await api.getActivity({ limit: 50, only_actionable: onlyActionable });
            const trades = data.trades || [];
            if (trades.length === 0) {
                tbody.innerHTML = `<tr><td colspan="10" class="no-data">No ${onlyActionable ? 'actionable ' : ''}activity yet — run an analysis to populate.</td></tr>`;
            } else {
                tbody.innerHTML = trades.map(t => {
                    const dir = (t.direction || 'NO_TRADE').toUpperCase();
                    const dirClass = dir === 'BUY' ? 'dir-buy' : (dir === 'SELL' ? 'dir-sell' : 'dir-flat');
                    const cleanSym = (t.symbol || '').replace(/^NSE:/, '').replace(/^BSE:/, '').replace(/^MCX:/, '').replace(/-EQ$/, '').replace(/-INDEX$/, '');
                    const time = t.timestamp ? new Date(t.timestamp).toLocaleString('en-IN', {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                    }) : '—';
                    const conf = t.confidence != null ? (t.confidence * 100).toFixed(0) + '%' : '—';
                    const fmt = (v) => (v == null ? '—' : Number(v).toLocaleString());
                    const outcome = t.outcome || (dir === 'NO_TRADE' ? '—' : 'pending');
                    const outcomeClass = outcome === 'WIN' ? 'dir-buy' : outcome === 'LOSS' ? 'dir-sell' : 'dir-flat';
                    const outcomeHtml = outcome === '—' ? '—' : `<span class="dir-pill ${outcomeClass}">${outcome}</span>`;
                    return `
                        <tr>
                          <td class="time-cell">${time}</td>
                          <td class="sym">${cleanSym}</td>
                          <td>${t.timeframe || '—'}</td>
                          <td><span class="dir-pill ${dirClass}">${dir}</span></td>
                          <td class="num">${fmt(t.entry_price)}</td>
                          <td class="num">${fmt(t.stop_loss)}</td>
                          <td class="num">${fmt(t.take_profit)}</td>
                          <td class="num">${conf}</td>
                          <td>${outcomeHtml}</td>
                          <td><button class="btn-mini" data-sym="${t.symbol}" data-tf="${t.timeframe || '1h'}">→</button></td>
                        </tr>`;
                }).join('');

                tbody.querySelectorAll('button.btn-mini').forEach(b => {
                    b.addEventListener('click', () => {
                        const sym = b.dataset.sym;
                        const tf = b.dataset.tf;
                        const sel = document.getElementById('symbol-select');
                        if (sel && [...sel.options].some(o => o.value === sym)) sel.value = sym;
                        this.symbol = sym;
                        this.timeframe = tf;
                        document.querySelectorAll('.tf-btn').forEach(b2 => b2.classList.toggle('active', b2.dataset.tf === tf));
                        this.loadMarketData().then(() => this.runAnalysis());
                        window.scrollTo({ top: 0, behavior: 'smooth' });
                    });
                });
            }
            if (meta) meta.textContent = `${trades.length} decisions · refreshes every 20s${onlyActionable ? ' · BUY/SELL only' : ''}`;
        } catch (e) {
            console.warn('Activity load failed', e);
            if (meta) meta.textContent = 'activity feed unavailable';
        }
    },

    /**
     * Run the top-opportunities scanner.
     */
    async runScanner({ refresh = false } = {}) {
        const tbody = document.getElementById('scanner-tbody');
        const meta = document.getElementById('scanner-meta');
        const btn = document.getElementById('scanner-run');
        if (!tbody || !btn) return;

        const universe = document.getElementById('scanner-universe').value;
        const timeframe = document.getElementById('scanner-timeframe').value;
        const onlyActionable = document.getElementById('scanner-actionable').checked;

        btn.disabled = true;
        btn.textContent = 'Scanning…';
        tbody.innerHTML = '<tr><td colspan="12" class="no-data">Running pipeline across universe…</td></tr>';
        meta.textContent = '';

        try {
            const data = await api.scanOpportunities({ universe, timeframe, limit: 12, only_actionable: onlyActionable, refresh });
            const rows = data.results || [];
            if (rows.length === 0) {
                tbody.innerHTML = '<tr><td colspan="12" class="no-data">No setups found.</td></tr>';
            } else {
                tbody.innerHTML = rows.map(r => {
                    const dirClass = r.direction === 'BUY' ? 'dir-buy' : (r.direction === 'SELL' ? 'dir-sell' : 'dir-flat');
                    const cleanSym = r.symbol.replace(/^NSE:/, '').replace(/-EQ$/, '').replace(/-INDEX$/, '');
                    return `
                        <tr>
                          <td class="sym">${cleanSym}</td>
                          <td><span class="dir-pill ${dirClass}">${r.direction}</span></td>
                          <td class="num">${r.rank_score >= 0 ? '+' : ''}${r.rank_score.toFixed(3)}</td>
                          <td class="num">${r.current_price.toLocaleString()}</td>
                          <td>${r.phase}</td>
                          <td>${r.regime}</td>
                          <td>${r.zone}</td>
                          <td class="num">${(r.dna_confidence * 100).toFixed(0)}%</td>
                          <td class="num">${(r.sim_bullish_prob * 100).toFixed(0)}%</td>
                          <td class="num">${(r.uncertainty * 100).toFixed(0)}%</td>
                          <td class="num">${r.dominant_scenario.expected_price.toLocaleString()}</td>
                          <td><button class="btn-mini" data-sym="${r.symbol}" data-tf="${r.timeframe}">→</button></td>
                        </tr>`;
                }).join('');

                tbody.querySelectorAll('button.btn-mini').forEach(b => {
                    b.addEventListener('click', () => {
                        const sym = b.dataset.sym;
                        const tf = b.dataset.tf;
                        const sel = document.getElementById('symbol-select');
                        if ([...sel.options].some(o => o.value === sym)) sel.value = sym;
                        this.symbol = sym;
                        this.timeframe = tf;
                        document.querySelectorAll('.tf-btn').forEach(b2 => b2.classList.toggle('active', b2.dataset.tf === tf));
                        this.loadMarketData().then(() => this.runAnalysis());
                        window.scrollTo({ top: 0, behavior: 'smooth' });
                    });
                });
            }
            const cachedAt = data.cached_at ? new Date(data.cached_at * 1000) : null;
            const ago = cachedAt ? Math.max(0, Math.round((Date.now() - cachedAt.getTime()) / 1000)) : 0;
            meta.textContent = `Showing ${rows.length} of ${data.scanned} symbols · ${ago}s ago · cache TTL ${data.ttl_seconds}s`;
        } catch (e) {
            console.error('Scanner failed:', e);
            tbody.innerHTML = `<tr><td colspan="12" class="no-data">Scan failed: ${e.message}</td></tr>`;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Scan';
        }
    },

    /**
     * Start a periodic chart refresh — every 60s during market hours, every
     * 5 min otherwise. Cheap because of backend cache TTL; mainly catches
     * candle rollover and fixes any cases where the WebSocket missed ticks.
     */
    startMarketDataRefresh() {
        if (this.marketRefreshInterval) clearInterval(this.marketRefreshInterval);
        const tick = async () => {
            try { await this.loadMarketData(); } catch (_) {}
        };
        // Every 60s — cheap; backend will skip upstream if cache is fresh
        this.marketRefreshInterval = setInterval(tick, 60000);
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

                // Subscribe live tick feed to current symbol/timeframe
                if (window.LiveFeed) {
                    window.LiveFeed.subscribe(this.symbol, this.timeframe);
                }
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

            // Render the forecast cone right after analysis
            if (window.Forecast) {
                window.Forecast.runAndDraw();
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
