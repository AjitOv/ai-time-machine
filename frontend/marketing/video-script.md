# AI Time Machine — 90-second Video Script

A timed narration + screen-action storyboard for recording a demo video over Loom, OBS, or any screen-recorder.

**Total runtime:** ~90 seconds.
**Pace:** ~150 words/minute (slow enough for non-native English ears).
**Voice:** Calm, confident, low-pitch. Think product launch, not infomercial.

---

## Setup before you record

Open these tabs in advance:

1. `frontend/marketing/index.html` — landing page
2. `frontend/marketing/explainer.html` — animated explainer
3. `frontend/index.html` — the running app (chart loaded for `NSE:NIFTY50-INDEX`)

Mirror the explainer's 8-scene order so on-screen visuals match the voice-over.

---

## Scene 1 — Hook (0:00 – 0:07)

**Screen:** explainer.html scene 1 (hero with gradient title)

> "What if you didn't have to predict the market —
> you just had to **reveal its probable futures**?"

*(Pause 0.5s on the gradient title.)*

---

## Scene 2 — Problem / Promise (0:07 – 0:18)

**Screen:** explainer.html scene 2 (vs comparison)

> "Most AI trading tools are a single black box.
> One model. One signal. No idea why it fired,
> no memory of what worked,
> and no clue when the regime shifts under it."

*(Camera lingers on the left "them" column.)*

> "Time Machine takes a different approach.
> Eleven specialised engines. One decision."

*(Switch focus to the right "us" column.)*

---

## Scene 3 — The Eleven Engines (0:18 – 0:32)

**Screen:** explainer.html scene 3 (engine wheel animating in)

> "Data, Context, Behavior, DNA, Simulation,
> Scenario, Decision, Uncertainty, Risk, Learning, Meta.
> Each engine has one job. None is allowed to act alone."

*(Match each name to the pill popping into the wheel.)*

> "Context gatekeeps. Behavior reads order flow.
> DNA recalls similar setups by cosine similarity.
> Simulation rolls one hundred Monte Carlo paths."

---

## Scene 4 — Pipeline (0:32 – 0:42)

**Screen:** explainer.html scene 4 (pipeline flow animating)

> "From candle to decision in one pass.
> Ingest. Gatekeep. Read. Recall. Simulate. Decide. Adapt.
> Every trade outcome rewards engines that voted correctly,
> and penalises those that didn't."

*(Slow zoom on the "Adapt" step.)*

---

## Scene 5 — Monte Carlo (0:42 – 0:54)

**Screen:** explainer.html scene 5 (Monte Carlo paths drawing)

> "One hundred simulated paths.
> Fifty steps each.
> A probability cloud — not a forecast."

*(Pause as the mean line draws across the cloud.)*

> "Geometric Brownian Motion biased by DNA direction
> and scaled by regime volatility.
> The 95th percentile becomes your target.
> The 5th percentile becomes your stop."

---

## Scene 6 — Decision (0:54 – 1:06)

**Screen:** explainer.html scene 6 (decision card with five gates)

> "The decision engine is the final arbiter.
> Five gates must pass: context permission,
> DNA confidence above 0.6,
> simulation probability above 60%,
> uncertainty below 0.4,
> and a meaningful score."

*(Highlight the green BUY pill, then sweep across the five gates.)*

> "If any gate fails — no trade.
> Risk-to-reward never below 1 to 2."

---

## Scene 7 — Numbers (1:06 – 1:18)

**Screen:** explainer.html scene 7 (eight number cells fading in)

> "One hundred paths. Fifty steps.
> Seven-dimensional pattern memory.
> Five timeframes fused into every call.
> A two percent daily-risk ceiling.
> And a kill-switch that halts the day after three losses in a row."

*(Each number gets a half-second beat.)*

---

## Scene 8 — Closer / CTA (1:18 – 1:30)

**Screen:** explainer.html scene 8 — *or* cut to the live app showing a real chart

> "The market is a probability cloud.
> Time Machine maps it.
> Self-evolving. Auditable. Yours to run."

*(End on the "Launch the system →" button. Hold for 1.5s.)*

---

## Optional intro / outro lines (5 seconds each)

- **Intro card:** "AI Time Machine. Eleven minds. One decision."
- **Outro card:** "Built on FastAPI, SQLAlchemy, TradingView Lightweight Charts. Live on NSE, BSE, MCX."

---

## Recording tips

- **Cursor off** in OBS / Loom — the explainer auto-plays, so you don't need to click.
- **Keyboard nav:** `Space` pause/play, `→ ←` step scenes — useful for tighter sync with narration.
- **Capture region:** 1920×1080 fullscreen, hide browser chrome (Cmd-Shift-F in Chrome).
- **Audio:** record narration in one take to a separate file, then time-align scenes in DaVinci / Premiere / CapCut.
- **Music:** a subtle ambient bed at -22 LUFS works well; nothing percussive — it fights the slow narration.

---

## Want a 30-second cut?

Use scenes 1, 3, 5, and 8 only. Drop the comparison, pipeline, decision card, and numbers. Result: hook → wheel → Monte Carlo → CTA.
