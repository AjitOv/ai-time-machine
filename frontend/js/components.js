/**
 * UI Components – updates DOM elements from analysis data.
 */

const Components = {

    // ── DECISION PANEL ──
    updateDecision(decision) {
        if (!decision) return;

        const badge = document.getElementById('decision-badge');
        const dirLabel = document.querySelector('.direction-label');
        const gaugeFill = document.getElementById('gauge-fill');
        const gaugeValue = document.getElementById('gauge-value');

        // Direction
        badge.textContent = decision.direction;
        badge.className = 'badge';
        dirLabel.className = 'direction-label';

        if (decision.direction === 'BUY') {
            badge.classList.add('buy');
            dirLabel.classList.add('buy');
            dirLabel.textContent = '▲ BUY';
        } else if (decision.direction === 'SELL') {
            badge.classList.add('sell');
            dirLabel.classList.add('sell');
            dirLabel.textContent = '▼ SELL';
        } else {
            badge.classList.add('no-trade');
            dirLabel.classList.add('no-trade');
            dirLabel.textContent = '— NO TRADE';
        }

        // Confidence gauge (arc length = 157 total)
        const conf = decision.confidence || 0;
        const dashLen = conf * 157;
        gaugeFill.setAttribute('stroke-dasharray', `${dashLen} 157`);
        gaugeValue.textContent = `${(conf * 100).toFixed(1)}%`;

        // Levels
        document.getElementById('level-entry').textContent = decision.entry_price ? `$${decision.entry_price.toFixed(2)}` : '—';
        document.getElementById('level-sl').textContent = decision.stop_loss ? `$${decision.stop_loss.toFixed(2)}` : '—';
        document.getElementById('level-tp').textContent = decision.take_profit ? `$${decision.take_profit.toFixed(2)}` : '—';
        document.getElementById('level-rr').textContent = decision.risk_reward ? `1:${decision.risk_reward.toFixed(1)}` : '—';

        // Reasons
        const reasonsEl = document.getElementById('decision-reasons');
        reasonsEl.innerHTML = '';
        if (decision.reasons) {
            decision.reasons.forEach(r => {
                const div = document.createElement('div');
                div.className = 'reason';
                div.textContent = r;
                reasonsEl.appendChild(div);
            });
        }
        if (decision.rejected_reasons) {
            decision.rejected_reasons.forEach(r => {
                const div = document.createElement('div');
                div.className = 'reason rejected';
                div.textContent = r;
                reasonsEl.appendChild(div);
            });
        }
    },

    // ── CONTEXT PANEL ──
    updateContext(context, behavior) {
        if (!context) return;

        // Context values
        const setCtx = (id, val, colorClass) => {
            const el = document.getElementById(id);
            el.textContent = val;
            el.className = 'ctx-value';
            if (colorClass) el.classList.add(colorClass);
        };

        setCtx('ctx-phase', context.phase);
        setCtx('ctx-regime', context.regime);
        setCtx('ctx-htf', context.htf_bias,
            context.htf_bias === 'BULLISH' ? 'bullish' :
            context.htf_bias === 'BEARISH' ? 'bearish' : 'neutral');
        setCtx('ctx-zone', context.zone,
            context.zone === 'DISCOUNT' ? 'bullish' :
            context.zone === 'PREMIUM' ? 'bearish' : 'neutral');
        setCtx('ctx-eq', `$${context.equilibrium?.toFixed(2) || '—'}`);
        setCtx('ctx-perm', context.trade_permission ? '✓ YES' : '✕ NO',
            context.trade_permission ? 'bullish' : 'bearish');

        // Context score badge
        const scoreBadge = document.getElementById('ctx-score-badge');
        scoreBadge.textContent = context.context_score?.toFixed(3) || '0.000';
        scoreBadge.style.color = context.context_score > 0 ? 'var(--accent-green)' :
                                  context.context_score < 0 ? 'var(--accent-red)' : 'var(--text-secondary)';

        // Behavior patterns
        if (behavior) {
            const patternsList = document.getElementById('patterns-list');
            patternsList.innerHTML = '';
            if (behavior.patterns && behavior.patterns.length > 0) {
                behavior.patterns.forEach(p => {
                    const tag = document.createElement('span');
                    tag.className = `pattern-tag ${p.direction.toLowerCase()}`;
                    tag.textContent = `${p.name} (${(p.strength * 100).toFixed(0)}%)`;
                    patternsList.appendChild(tag);
                });
            } else {
                patternsList.innerHTML = '<span class="no-data">No patterns detected</span>';
            }
        }
    },

    // ── SCENARIOS PANEL ──
    updateScenarios(scenarios, simulation) {
        if (!scenarios) return;

        const findScenario = (label) => scenarios.find(s => s.label === label) || {};

        // Bullish
        const bull = findScenario('BULLISH');
        document.getElementById('prob-bullish').textContent = `${((bull.probability || 0) * 100).toFixed(1)}%`;
        document.getElementById('bar-bullish').style.width = `${(bull.probability || 0) * 100}%`;
        document.getElementById('target-bullish').textContent = `Target: $${bull.expected_price?.toFixed(2) || '—'}`;

        // Bearish
        const bear = findScenario('BEARISH');
        document.getElementById('prob-bearish').textContent = `${((bear.probability || 0) * 100).toFixed(1)}%`;
        document.getElementById('bar-bearish').style.width = `${(bear.probability || 0) * 100}%`;
        document.getElementById('target-bearish').textContent = `Target: $${bear.expected_price?.toFixed(2) || '—'}`;

        // Neutral
        const neut = findScenario('NEUTRAL');
        document.getElementById('prob-neutral').textContent = `${((neut.probability || 0) * 100).toFixed(1)}%`;
        document.getElementById('bar-neutral').style.width = `${(neut.probability || 0) * 100}%`;
        document.getElementById('target-neutral').textContent = `Range: $${neut.expected_price?.toFixed(2) || '—'}`;

        // Dominant badge
        const dominant = scenarios.reduce((a, b) => a.probability > b.probability ? a : b, {label: '—'});
        const domBadge = document.getElementById('dominant-badge');
        domBadge.textContent = dominant.label;
        domBadge.className = 'badge';
        if (dominant.label === 'BULLISH') domBadge.classList.add('buy');
        else if (dominant.label === 'BEARISH') domBadge.classList.add('sell');
        else domBadge.classList.add('no-trade');

        // Simulation stats
        if (simulation) {
            document.getElementById('sim-mean').textContent = `$${simulation.mean_final_price?.toFixed(2) || '—'}`;
            const range = simulation.price_range;
            document.getElementById('sim-range').textContent = range ?
                `$${range[0]?.toFixed(2)} – $${range[1]?.toFixed(2)}` : '—';
            const bias = simulation.simulation_bias || 0;
            const biasEl = document.getElementById('sim-bias');
            biasEl.textContent = `${bias > 0 ? '+' : ''}${bias.toFixed(4)}`;
            biasEl.style.color = bias > 0 ? 'var(--accent-green)' : bias < 0 ? 'var(--accent-red)' : '';
        }
    },

    // ── DNA PANEL ──
    updateDNA(dna, uncertainty, meta) {
        // DNA match
        const dnaMatch = document.getElementById('dna-match');
        if (dna && dna.best_match) {
            const m = dna.best_match;
            dnaMatch.innerHTML = `
                <div class="dna-match-card">
                    <div class="dna-header">
                        <span class="dna-id">${m.dna_id}</span>
                        <span class="dna-dir ${m.direction.toLowerCase()}">${m.direction}</span>
                    </div>
                    <div class="dna-stats">
                        <div class="dna-stat">
                            <span class="dna-stat-label">Similarity</span>
                            <span class="dna-stat-value">${(m.similarity * 100).toFixed(1)}%</span>
                        </div>
                        <div class="dna-stat">
                            <span class="dna-stat-label">Win Rate</span>
                            <span class="dna-stat-value">${(m.win_rate * 100).toFixed(0)}%</span>
                        </div>
                        <div class="dna-stat">
                            <span class="dna-stat-label">Total Trades</span>
                            <span class="dna-stat-value">${m.total_trades}</span>
                        </div>
                        <div class="dna-stat">
                            <span class="dna-stat-label">Confidence</span>
                            <span class="dna-stat-value">${(dna.dna_confidence * 100).toFixed(1)}%</span>
                        </div>
                    </div>
                </div>
            `;
        } else {
            dnaMatch.innerHTML = `
                <div class="dna-empty">
                    <svg width="40" height="40" viewBox="0 0 40 40" fill="none" opacity="0.3">
                        <path d="M20 5 L20 35 M12 10 Q20 15 28 10 M12 20 Q20 25 28 20 M12 30 Q20 35 28 30" stroke="currentColor" stroke-width="2"/>
                    </svg>
                    <span>No DNA matches — system is learning</span>
                </div>
            `;
        }

        // DNA confidence badge
        const confBadge = document.getElementById('dna-conf-badge');
        confBadge.textContent = dna ? (dna.dna_confidence * 100).toFixed(1) + '%' : '0.0%';

        // Uncertainty
        if (uncertainty) {
            const uncFill = document.getElementById('unc-fill');
            const uncValue = document.getElementById('unc-value');
            uncFill.style.width = `${(uncertainty.score || 0) * 100}%`;
            uncValue.textContent = `${((uncertainty.score || 0) * 100).toFixed(0)}%`;
            uncValue.style.color = uncertainty.score > 0.5 ? 'var(--accent-red)' :
                                    uncertainty.score > 0.3 ? 'var(--accent-amber)' : 'var(--accent-green)';

            const uncSignals = document.getElementById('unc-signals');
            uncSignals.innerHTML = '';
            if (uncertainty.reasons) {
                uncertainty.reasons.forEach(r => {
                    const div = document.createElement('div');
                    div.className = 'unc-signal';
                    div.textContent = `⚠ ${r}`;
                    uncSignals.appendChild(div);
                });
            }
        }

        // Meta
        if (meta) {
            const metaStatus = document.getElementById('meta-status');
            const dotClass = meta.health_status === 'HEALTHY' ? 'healthy' :
                             meta.health_status === 'DEGRADED' ? 'degraded' : 'critical';
            metaStatus.innerHTML = `
                <span class="meta-dot ${dotClass}"></span>
                <span>${meta.health_status} | ${meta.performance_trend}</span>
            `;
        }
    },

    // ── PERFORMANCE PANEL ──
    updatePerformance(perf, weights) {
        if (perf) {
            document.getElementById('perf-total').textContent = perf.total_trades || 0;
            document.getElementById('perf-winrate').textContent = `${((perf.win_rate || 0) * 100).toFixed(0)}%`;
            document.getElementById('perf-pnl').textContent = `$${(perf.total_pnl || 0).toFixed(0)}`;
            document.getElementById('perf-rr').textContent = (perf.avg_rr || 0).toFixed(1);
        }

        if (weights) {
            const container = document.getElementById('weights-bars');
            container.innerHTML = '';
            const names = {
                context_weight: 'Context',
                behavior_weight: 'Behavior',
                dna_weight: 'DNA',
                simulation_weight: 'Simulation',
            };
            for (const [key, value] of Object.entries(weights)) {
                const name = names[key] || key;
                const pct = (value * 100).toFixed(0);
                container.innerHTML += `
                    <div class="weight-bar-row">
                        <span class="weight-name">${name}</span>
                        <div class="weight-track">
                            <div class="weight-fill" style="width: ${pct}%"></div>
                        </div>
                        <span class="weight-val">${pct}%</span>
                    </div>
                `;
            }
        }
    },

    // ── TRADE HISTORY ──
    updateTrades(trades) {
        const tbody = document.getElementById('trades-tbody');
        const countEl = document.getElementById('trade-count');

        if (!trades || trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="no-data">No trades recorded yet</td></tr>';
            countEl.textContent = '0 trades';
            return;
        }

        countEl.textContent = `${trades.length} trades`;
        tbody.innerHTML = '';

        trades.slice(0, 30).forEach(t => {
            const time = t.timestamp ? new Date(t.timestamp).toLocaleString('en-US', {
                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
            }) : '—';

            const dirClass = t.direction === 'BUY' ? 'dir-buy' :
                             t.direction === 'SELL' ? 'dir-sell' : 'dir-no';
            const outcomeClass = t.outcome === 'WIN' ? 'outcome-win' :
                                  t.outcome === 'LOSS' ? 'outcome-loss' :
                                  t.outcome === 'PENDING' ? 'outcome-pending' : 'outcome-skipped';

            tbody.innerHTML += `
                <tr>
                    <td>${time}</td>
                    <td class="${dirClass}">${t.direction}</td>
                    <td>${t.entry_price ? '$' + t.entry_price.toFixed(2) : '—'}</td>
                    <td>${t.stop_loss ? '$' + t.stop_loss.toFixed(2) : '—'}</td>
                    <td>${t.take_profit ? '$' + t.take_profit.toFixed(2) : '—'}</td>
                    <td>${t.confidence ? (t.confidence * 100).toFixed(0) + '%' : '—'}</td>
                    <td class="${outcomeClass}">${t.outcome || '—'}</td>
                </tr>
            `;
        });
    },

    // ── PRICE DISPLAY ──
    updatePrice(price, change) {
        const priceEl = document.getElementById('current-price');
        const changeEl = document.getElementById('price-change');

        priceEl.textContent = price ? `$${price.toFixed(2)}` : '—';

        if (change !== undefined && change !== null) {
            const pct = change;
            changeEl.textContent = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
            changeEl.className = `price-change ${pct >= 0 ? 'up' : 'down'}`;
        }
    },
};
