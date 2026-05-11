// API base — same auto-detect logic as the main app
const API_BASE = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
  ? 'http://localhost:8001/api/v1'
  : 'https://ai-time-machine-api.onrender.com/api/v1';

// Animated counter helper
function countUp(el, target, { duration = 1400, suffix = '', decimals = 0 } = {}) {
  const start = performance.now();
  const tick = (t) => {
    const p = Math.min(1, (t - start) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    const v = target * eased;
    el.textContent = (decimals ? v.toFixed(decimals) : Math.round(v).toLocaleString()) + suffix;
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// Animate any stat-num with a static data-count attribute
function animateStaticCounters() {
  document.querySelectorAll('.stat-num[data-count]').forEach(el => {
    const target = parseInt(el.dataset.count, 10);
    if (Number.isFinite(target) && target > 0) countUp(el, target);
  });
}

// Pull live performance + weights from the backend
async function loadLiveStats() {
  try {
    const [perfRes, wRes] = await Promise.all([
      fetch(`${API_BASE}/system/performance`).then(r => r.ok ? r.json() : null),
      fetch(`${API_BASE}/system/weights`).then(r => r.ok ? r.json() : null),
    ]);

    if (perfRes && perfRes.performance) {
      const p = perfRes.performance;
      const meta = perfRes.meta || {};

      // trades
      const tradesEl = document.querySelector('[data-stat="trades"] .stat-num');
      if (tradesEl) {
        if (p.total_trades > 0) countUp(tradesEl, p.total_trades);
        else tradesEl.textContent = '0';
        tradesEl.parentElement.classList.add('live-on');
      }

      // win rate (fraction → percent)
      const winEl = document.querySelector('[data-stat="winrate"] .stat-num');
      if (winEl) {
        const pct = (p.win_rate || 0) * 100;
        if (p.total_trades > 0) countUp(winEl, pct, { decimals: 1, suffix: '%' });
        else winEl.textContent = 'awaiting trades';
        winEl.parentElement.classList.add('live-on');
      }

      // health text
      const healthEl = document.querySelector('[data-stat="health"] .stat-num');
      if (healthEl) {
        healthEl.textContent = meta.health_status || '—';
        healthEl.parentElement.classList.add('live-on');
        if (meta.health_status === 'CRITICAL') healthEl.style.background = 'linear-gradient(120deg,#f87171,#fb923c)';
        else if (meta.health_status === 'HEALTHY') healthEl.style.background = 'linear-gradient(120deg,#34d399,#7cf)';
        if (meta.health_status) {
          healthEl.style.webkitBackgroundClip = 'text';
          healthEl.style.backgroundClip = 'text';
          healthEl.style.color = 'transparent';
        }
      }
    }

    if (wRes && wRes.weights) {
      const w = wRes.weights;
      const map = {
        context: w.context_weight,
        behavior: w.behavior_weight,
        dna: w.dna_weight,
        simulation: w.simulation_weight,
      };
      Object.entries(map).forEach(([k, val]) => {
        const row = document.querySelector(`.wbar[data-w="${k}"]`);
        if (!row || val == null) return;
        const fill = row.querySelector('.wbar-fill');
        const num = row.querySelector('b');
        const pct = Math.max(0, Math.min(1, val)) * 100;
        // Scale so the bar uses the full range — equal weights would all show ~25%,
        // so amplify deviations from 25% for visual readability.
        fill.style.width = (pct * 4) + '%'; // 0.25 → 100%
        num.textContent = (pct).toFixed(1) + '%';
      });
    }
  } catch (e) {
    console.warn('live stats unavailable', e);
  }
}

// Reveal-on-scroll for cards and sections
function attachReveal() {
  const targets = document.querySelectorAll(
    '.engine-card, .spec, .compare-col, .pipe-step, .promise-grid > div, .api-block, .section-head'
  );
  targets.forEach(el => el.classList.add('reveal'));
  const io = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('in');
        io.unobserve(e.target);
      }
    });
  }, { threshold: 0.12 });
  targets.forEach(el => io.observe(el));
}

document.addEventListener('DOMContentLoaded', () => {
  animateStaticCounters();
  attachReveal();
  loadLiveStats();
  // Refresh live numbers every 30s without reloading the page
  setInterval(loadLiveStats, 30000);
});
