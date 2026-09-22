# jev-trading · Strategy Iteration Log

Append-only. Newest entries go at the **bottom**.
Each entry: timestamp (America/Los_Angeles), what we observed, lessons, strategy decision (change vs keep), and next action.

Format:

```
## YYYY-MM-DD HH:MM PT · iteration N · [CHANGE|KEEP|OBSERVE]
### Observed
### Lessons learned
### Strategy decision
### Code / config changes (if any)
### Next observe window
```

---

## 2026-09-22 10:04 PT · iteration 1 · CHANGE

### Observed
- Finished first ~8h paper campaign (~01:03–09:03 PT). Starting cash $10k per market.
- **Crypto (trusted-ish):** primary `v_best` final PnL ≈ **−$98.84** / equity ≈ $9901; 67 fills; buy-heavy (~55 buy / 12 sell); cash nearly exhausted into many small alts. Mid-run equity peaked ~+$350. End winners included ALCX long (~+$213 unrealized); many small losers (THQ, AURORA, CHECK, FAI, …).
- Shadow ranking (crypto): `v_loose` (−$89.65) ≳ `v_best`/`v_large_only` (−$98.84) > `v_strict` (−$136.61) > `v_edge_size` (−$146.89).
- **Stock (NOT trustworthy as headline PnL):** reported primary ≈ **−$4999** / equity ≈ $5000, but **28/35** end positions had **missing Yahoo mid**. Mark-to-market treated missing mid as **0**, which write-offs longs as if price went to zero. Cash + cost basis ≈ **$9997** → near flat at cost. Intrabar PnL swung hundreds–thousands between ticks (quote gaps), including mid-campaign reports that once showed ~+$1244 then later large losses.
- Stock shadows (contaminated by same MTM): `v_edge_size` / `v_strict` “least bad” on paper; `v_loose` worst.

### Lessons learned
1. **Missing quotes must never mark as price=0** — that alone can invent multi-thousand “losses.”
2. What actually hurt crypto was **portfolio structure**, not only gate height: too many concurrent names, almost always max $250 size, buy bias with almost no profit-taking sells.
3. Same Jev signal + different execution mattered: looser crypto gates slightly better this run; stock “strict / edge size” looked better but numbers are polluted until MTM is fixed.
4. Hourly A/B without freezing accounting bugs wastes learning — fix measurement first.
5. Keeping current strategy and only observing is a valid iteration when no clear improvement is proven yet — but **this** iteration has a clear must-fix (MTM) plus structural caps.

### Strategy decision · CHANGE (v2)
Implement and observe:
1. **MTM fix:** carry last-good mid per symbol; never mark with 0/missing.
2. **Max open symbols** (e.g. 8 primary): refuse new names when at cap (allows reduce/reverse on existing).
3. **Same-symbol trim preference:** if already in symbol, prefer reducing / flipping over stacking more risk blindly (still Jev-sized, but capped).
4. **Stock RTH-only** paper entries (America/Los_Angeles approximating US cash session); outside session → hold / no new fills.
5. **Next compare set (3 books):** `v2_best` (new rules), `v2_loose` (slightly looser gates), `v2_strict` (tighter) — drop the old five-way clutter for this observe window.
6. Crypto still allows small+large move buckets; flat still skips.

### Code / config changes (if any)
- Planned in same session: `paper.py` last-good mid; `smoke.py` caps + RTH; `docs/strategy-iteration-log.md` (this file); hourly reflect routine; `experiment.json` → v2 variants.

### Next observe window
- Restart paper observe after code lands; hourly routine appends here with CHANGE or KEEP/OBSERVE.
- Success check for next hour: stock PnL path no longer jumps by $1k+ without fills; crypto open-name count ≤ cap.



## 2026-09-22 10:06 PT · iteration 1b · CHANGE (implemented)

### Observed
- Implemented v2 code on box; preparing observe restart.

### Lessons learned
- (carry-forward) Measurement fix before more A/B noise.

### Strategy decision · CHANGE shipped
- `paper.py`: last-good mid / cost-basis hold when quote missing.
- `smoke.py`: max 8 open symbols; stock `rth_only`; remember mids each tick.
- `experiment.json`: `v2_best` / `v2_loose` / `v2_strict` only.
- Hourly routine will append to this file (CHANGE or KEEP/OBSERVE).

### Code / config changes (if any)
- See git commit after push.

### Next observe window
- Fresh paper books; hourly reflect loop on.



## 2026-09-22 10:09 PT · iteration 1c · CHANGE (raw decision logging)

### Observed
- User requested durable raw logs of every investment decision (strategy + model outputs).

### Lessons learned
- Tick summaries in results.json are not enough for later audit; need append-only JSONL with `jev_raw_answers`.

### Strategy decision · CHANGE
- Append each tick to `out/{market}/decisions.jsonl` and `logs/raw_decisions/{market}.jsonl`.

### Code / config changes (if any)
- `jev_trading/smoke.py` `append_decision_log`; README under `logs/raw_decisions/`.

### Next observe window
- Continue v2 observe; hourly iterate routine can cite these raw logs.



## 2026-09-22 10:12 PT · iteration 1d · CHANGE (git-backed accumulation)

### Observed
- User wants frequent GitHub pushes of intermediate data; history must accumulate, never overwrite.

### Lessons learned
- `out/` is gitignored scratch; durable truth must live under `logs/` (JSONL + timestamped snapshots).

### Strategy decision · CHANGE
- `scripts/push_accum_data.sh` mirrors decisions and writes new `logs/snapshots/.../live_TIMESTAMP.json` each push; refuses JSONL deletes.
- Push every ~15 minutes + after each hourly iterate.

### Code / config changes (if any)
- scripts/push_accum_data.sh, logs/README.md; routines updated.

### Next observe window
- Continue v2; verify GitHub `logs/raw_decisions` grows over time.




## 2026-09-22 10:28 PT · iteration 2 · CHANGE (multi-horizon A/B/C)

### Observed
- Prior v2 observe showed chase risk: short-horizon move alone can fire while 5m/10m/1h disagree.
- Need same-tick A/B/C comparison with identical Jev answers, different agree gates.

### Lessons learned
- Measurement (MTM/caps) fixed; next risk is **horizon disagreement / chase**.
- Logging must capture all horizons + which variant would have passed each tick.

### Strategy decision · CHANGE
1. Experiment `jev_paper_horizons_ABC_2026_09_22`: primary **exp_A_short**, shadows **exp_B_short_med** / **exp_C_multi**.
2. Jev now answers `move` / `move_5m` / `move_10m` / `move_1h` / `trend_1d` each tick.
3. `require_agree` + optional `block_1d_opposite` gate fills per book.
4. Decision JSONL gains `horizons`, `variant_pass`, and gate fields; dashboard shows multi-horizon signal + A/B/C compare.
5. Restart campaign `horizons_ABC_observe` for remaining wall time (~old ends_ts).

### Code / config changes (if any)
- `jev_trading/data/experiment.json`, `jev_client.py`, `markets.py`, `smoke.py`, `dashboard/server.py`
- `out/EXPERIMENT.md`, `docs/EXPERIMENT.md`, this log

### Next observe window
- Fresh primary/shadow books; append-only decisions continue on same JSONL paths.
- Success: live shadows include B/C; decisions have horizons + variant_pass; dashboard compare shows A/B/C.



## 2026-09-22 10:40 PT · iteration 3 · KEEP/OBSERVE (horizons A/B/C early)

### Observed
- Campaign `horizons_ABC_observe` still active; ends_ts `2026-09-22T21:06:00Z` (~14:06 PT); ~3.4h remaining. PIDs crypto/stock/dashboard all alive; dashboard :8787 up. No restarts this hour.
- **Crypto primary `exp_A_short` (~54 ticks / ~10m since restart):** equity ≈ **$10013** / PnL ≈ **+$13**; **16 fills**; cash ≈ $10k; **8/8 open names** (at max-symbol cap). mark_stale=0; no mid=0 marks. Decision mix ~15 buy / 8 sell / 31 hold. Pick concentration: APE / SUKU / AURORA heavy. Sizes mostly $100–$200 (not stuck on $250). Net book mix of small alts longs/shorts (e.g. SUKU long, ZEC/XRP/USELESS/SXT shorts).
- **Crypto shadows:** `exp_B_short_med` and `exp_C_multi` still **0 fills / flat $10k**. `variant_pass` true only for A (~20/57 ABC ticks); B/C never true this window. Horizons disagree on ~54% of ticks — agree gates doing their job (quiet by design so far).
- **Stock primary (~6 ticks, RTH, session_ok=true):** equity ≈ **$10000.04** / PnL ≈ **+$0.04**; **3 fills** (all sells: AMZN + SNAP shorts); **2 open**. mark_stale=0. Shadows: B ≈ same as A (+$0.04 / 3 fills); C ≈ −$0.01 / 2 fills.
- Accounting vs trading: MTM path looks healthy (no inventing wipeouts). Early PnL noise is real microstructure / mark, not quote-zero bugs.

### Lessons learned
1. **Good:** last-good MTM + max-8 open + stock RTH appear to be holding — stock PnL is near-flat with real quotes; crypto open count capped at 8.
2. **Good:** multi-horizon logging + `variant_pass` is working; B/C silence on crypto confirms short-only chase vs multi-horizon disagreement is common (~half of ticks).
3. **Bad / watch:** crypto primary still name-clusters (APE/SUKU/AURORA) and sits at the open-name ceiling quickly — capacity may be spent on low-liquidity alts before majors get room.
4. **Bad / early:** cannot yet rank A vs B vs C on PnL — B/C have almost no crypto fills; stock sample too small (6 ticks). Changing gates now would be noise.
5. Prefer KEEP/OBSERVE until shadows accumulate fills or a concrete failure (stale marks, RTH leak, cap breach) appears.

### Strategy decision · KEEP/OBSERVE
- No strategy/code change this hour. Continue A primary + B/C shadows for remaining wall time.
- Watch next windows for: (a) first sustained B/C crypto fills, (b) whether open-name cap blocks better names, (c) stock fill rate under RTH.

### Code / config changes (if any)
- None.

### Next observe window
- Next hourly reflect ~11:08–11:40 PT; campaign end ~14:06 PT. If ends_ts passes and both smokes exit → final summary + request routine delete (`jev-trading-hourly-strategy-iterate`).


## 2026-09-22 11:27 PT · iteration 4 · CHANGE (A–H compare ledgers)

### Observed
- A/B/C multi-horizon observe running; need fuller execution A/B (imbalance, exits, inv skew, regime MR, markout veto) while keeping A primary.

### Lessons learned
- Horizon agree alone does not test microstructure / inventory / exit / adverse-selection overlays.
- Same-tick multi-ledger compare remains the right design; extend shadows to D–H without truncating decisions JSONL.

### Strategy decision · CHANGE
1. Experiment `jev_paper_A_to_H_2026_09_22` (iteration 4): primary **exp_A_short**; shadows B–H.
2. D imbalance agree; E TP/time/trail exits; F inv skew; G regime fade-in-chop; H markout veto.
3. Append-only decisions; enrich `variant_pass` for all A–H; log exit fills under shadow_fills.
4. Restart campaign `A_to_H_observe` for remaining wall time until prior ends_ts.

### Code / config changes (if any)
- `jev_trading/data/experiment.json`, `paper.py` (`close_position`), `smoke.py` helpers + tick loop, `dashboard/server.py`
- `docs/EXPERIMENT.md`, this log; archive `out/archive_pre_A_to_H/`

### Next observe window
- Fresh primary/shadow books; decisions JSONL continues append-only.
- Success: live shadows include D–H; decisions have variant_pass keys A–H; dashboard compare shows A–H.
