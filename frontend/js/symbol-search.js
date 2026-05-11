/**
 * Symbol search component — typeahead over the Dhan instrument master.
 *
 * Markup contract (see index.html):
 *   #symbol-search          .symbol-search       wrapper
 *   #symbol-display         .symbol-search-display   pill that opens the popover
 *   #ssd-ticker, #ssd-meta  current selection text
 *   #symbol-select          hidden input holding the canonical symbol value
 *   #symbol-search-pop      .symbol-search-pop   popover container
 *   #symbol-search-input    text input
 *   #symbol-quick-chips     row of pre-built chips
 *   #symbol-search-results  results list
 *   #symbol-search-foot     hint footer
 */

const SymbolSearch = {
    debounceMs: 160,
    debounceTimer: null,
    activeIdx: -1,
    items: [],          // currently-rendered list of {symbol,name,type,exchange}
    recentKey: 'tm.recent_symbols',

    init() {
        this.wrap = document.getElementById('symbol-search');
        if (!this.wrap) return;
        this.display = document.getElementById('symbol-display');
        this.pop = document.getElementById('symbol-search-pop');
        this.input = document.getElementById('symbol-search-input');
        this.results = document.getElementById('symbol-search-results');
        this.chips = document.getElementById('symbol-quick-chips');
        this.foot = document.getElementById('symbol-search-foot');
        this.hidden = document.getElementById('symbol-select');
        this.tickerEl = document.getElementById('ssd-ticker');
        this.metaEl = document.getElementById('ssd-meta');

        this.display.addEventListener('click', () => this.open());
        document.addEventListener('click', (e) => {
            if (!this.wrap.contains(e.target)) this.close();
        });
        this.input.addEventListener('input', () => this.scheduleSearch());
        this.input.addEventListener('keydown', (e) => this.onKeydown(e));

        // Quick chips
        this.chips.querySelectorAll('.qchip').forEach(chip => {
            chip.addEventListener('click', () => {
                this.select({
                    symbol: chip.dataset.sym,
                    name: chip.dataset.name || chip.textContent.trim(),
                    type: 'INDEX',
                    exchange: chip.dataset.sym.split(':')[0],
                });
            });
        });

        // Render any recent picks alongside chips
        this.renderRecent();
    },

    open() {
        this.pop.hidden = false;
        this.input.value = '';
        this.activeIdx = -1;
        this.results.innerHTML = '';
        this.input.focus();
        this.foot.textContent = 'Type at least 2 chars · ↑↓ to navigate · Enter to select · Esc to close';
        this.renderRecent();
    },

    close() {
        this.pop.hidden = true;
    },

    scheduleSearch() {
        clearTimeout(this.debounceTimer);
        const q = this.input.value.trim();
        if (q.length === 0) {
            this.results.innerHTML = '';
            this.activeIdx = -1;
            this.renderRecent();
            return;
        }
        if (q.length === 1) {
            this.foot.textContent = 'Keep typing — at least 2 characters';
            return;
        }
        this.debounceTimer = setTimeout(() => this.runSearch(q), this.debounceMs);
    },

    async runSearch(q) {
        try {
            const data = await api.searchSymbols({ q, limit: 30 });
            this.items = data.results || [];
            this.activeIdx = this.items.length > 0 ? 0 : -1;
            this.renderResults();
            this.foot.textContent = `${this.items.length} of ${data.total_indexed || '?'} symbols matched`;
        } catch (e) {
            this.foot.textContent = 'Search failed — backend unreachable?';
        }
    },

    renderResults() {
        if (this.items.length === 0) {
            this.results.innerHTML = '<div class="ssr-empty">No matches.</div>';
            return;
        }
        this.results.innerHTML = this.items.map((row, i) => this.itemHtml(row, i === this.activeIdx)).join('');
        this.results.querySelectorAll('.ssr-row').forEach((el, i) => {
            el.addEventListener('mouseenter', () => { this.activeIdx = i; this.refreshActive(); });
            el.addEventListener('click', () => this.select(this.items[i]));
        });
    },

    itemHtml(row, active) {
        const ticker = row.symbol.split(':')[1].replace(/-EQ$/, '').replace(/-INDEX$/, '');
        const tagClass = row.type === 'INDEX' ? 'tag-index' : (row.type === 'EQUITY' ? 'tag-equity' : 'tag-other');
        return `
          <div class="ssr-row ${active ? 'active' : ''}">
            <div class="ssr-ticker">${ticker}</div>
            <div class="ssr-name">${this.escape(row.name || '')}</div>
            <div class="ssr-tags">
                <span class="ssr-tag ${tagClass}">${row.type}</span>
                <span class="ssr-tag tag-exch">${row.exchange}</span>
            </div>
          </div>`;
    },

    refreshActive() {
        const rows = this.results.querySelectorAll('.ssr-row');
        rows.forEach((el, i) => el.classList.toggle('active', i === this.activeIdx));
        const active = rows[this.activeIdx];
        if (active) active.scrollIntoView({ block: 'nearest' });
    },

    onKeydown(e) {
        if (e.key === 'Escape') { this.close(); return; }
        if (this.items.length === 0) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.activeIdx = (this.activeIdx + 1) % this.items.length;
            this.refreshActive();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.activeIdx = (this.activeIdx - 1 + this.items.length) % this.items.length;
            this.refreshActive();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (this.activeIdx >= 0) this.select(this.items[this.activeIdx]);
        }
    },

    select(row) {
        if (!row || !row.symbol) return;
        this.hidden.value = row.symbol;
        const ticker = row.symbol.split(':')[1].replace(/-EQ$/, '').replace(/-INDEX$/, '');
        this.tickerEl.textContent = ticker;
        this.metaEl.textContent = `${row.exchange} · ${row.type}${row.name ? ' · ' + row.name : ''}`;
        this.close();
        this.rememberRecent(row);

        // Notify the rest of the app — same shape the old <select>'s 'change' event had
        this.hidden.dispatchEvent(new Event('change', { bubbles: true }));
    },

    rememberRecent(row) {
        try {
            const arr = JSON.parse(localStorage.getItem(this.recentKey) || '[]');
            const without = arr.filter(r => r.symbol !== row.symbol);
            const next = [{ symbol: row.symbol, name: row.name, type: row.type, exchange: row.exchange }, ...without].slice(0, 6);
            localStorage.setItem(this.recentKey, JSON.stringify(next));
        } catch (_) {}
    },

    renderRecent() {
        if (this.input.value.trim()) return;
        const arr = (() => { try { return JSON.parse(localStorage.getItem(this.recentKey) || '[]'); } catch (_) { return []; } })();
        if (arr.length === 0) {
            this.results.innerHTML = '<div class="ssr-hint">Recent picks will appear here.</div>';
            return;
        }
        this.items = arr;
        this.activeIdx = 0;
        this.results.innerHTML =
            '<div class="ssr-section">Recent</div>' +
            arr.map((r, i) => this.itemHtml(r, i === 0)).join('');
        this.results.querySelectorAll('.ssr-row').forEach((el, i) => {
            el.addEventListener('mouseenter', () => { this.activeIdx = i; this.refreshActive(); });
            el.addEventListener('click', () => this.select(arr[i]));
        });
    },

    escape(s) {
        return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
    },
};

document.addEventListener('DOMContentLoaded', () => SymbolSearch.init());
