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


## 2026-09-22 11:31 PT · iteration 5 · KEEP/OBSERVE (A–H early window)

### Observed
- Campaign `A_to_H_observe` active; ends_ts `2026-09-22T21:06:00Z` (~14:06 PT); ~2.6h remaining. Restarted ~11:27 PT. PIDs crypto/stock/dashboard all alive; dashboard http://127.0.0.1:8787 returns 200. No restarts this hour.
- **Crypto primary `exp_A_short` (~17 ticks / ~3m since A–H restart):** equity ≈ **$9986–$9999** / PnL ≈ **−$1 to −$14** (mark noise); **~7–11 fills** in window; **3 open** (XRP short, NEAR short, SXT long). All mids healthy; `mark_stale=false`; no mid=0. Decision mix skewed sell/buy on alts; pick concentration on **SXT-USD** (majority of picks) plus NEAR/AIOZ/XRP. Regime mostly **chop**; trade_imbalance ≈ 0.
- **Crypto shadows (same ticks):** B/C/D still **0 fills / flat $10k** (agree / imbalance gates quiet). E ≈ A with slightly fewer open (exit overlay); F/H ≈ A PnL; G slightly green (~+$0.13) on same names — differences are tiny and not yet meaningful. `variant_pass` true rates ~A/E/F/G ~11/17, H ~9/17, B/C/D **0/17**.
- **Stock:** process alive but **very slow cadence** (~1 logged tick in ~3m; live.json can lag mid-tick while Yahoo quotes). JSONL shows `session_ok=true`, one early **TSLA short** fill (~$100) with A/B/E/F/G/H pass and C/D false; live snapshot may still read flat until next live write. RTH gate appears intact. Sample too small to rank A–H.
- Accounting vs trading: crypto MTM looks real (nonzero mids, no wipeouts). Stock live lag is operational, not an invented PnL bug.

### Lessons learned
1. **Good:** A–H ledgers + `variant_pass` keys are live and differentiating (B/C/D silence vs A/E/F/G/H activity) without truncating JSONL history.
2. **Good:** v2 guards still hold — open count well under max-8; stock `session_ok` / RTH; no stale/zero marks on open crypto names.
3. **Bad / watch:** crypto still **name-clusters on thin alts (SXT)** and flip-flops size on the same symbol within minutes — capacity and adverse selection risk; H markout veto only slightly quieter so far.
4. **Bad / watch:** stock tick rate much slower than crypto (likely Yahoo polling); do not treat a 1-tick sample as strategy evidence; watch that live.json keeps catching up.
5. Evidence too thin (~3 minutes post A–H restart) to change gates, exits, or primary — KEEP/OBSERVE.

### Strategy decision · KEEP/OBSERVE
- No strategy/code change this hour. Continue primary A + shadows B–H until more fills accumulate or a concrete failure appears (stale marks, RTH leak, cap breach, live stuck).
- Watch next windows for: (a) first B/C/D crypto fills, (b) whether E exits help vs A on SXT churn, (c) stock fill rate / live freshness under RTH.

### Code / config changes (if any)
- None.

### Next observe window
- Next hourly reflect ~12:08–12:40 PT; campaign end ~14:06 PT. If ends_ts passes and both smokes exit → final summary + delete routine `jev-trading-hourly-strategy-iterate`.


## 2026-09-22 12:35 PT · iteration 6 · KEEP/OBSERVE (A–H ~1h post-restart)

### Observed
- Campaign `A_to_H_observe` active; ends_ts `2026-09-22T21:06:00Z` (~14:06 PT); ~1.5h remaining. PIDs crypto/stock/dashboard all alive (~1h07m uptime); dashboard http://127.0.0.1:8787 returns 200. No restarts this hour.
- **Crypto primary `exp_A_short` (~390 ticks / ~1h since A–H restart):** equity ≈ **$9940** / PnL ≈ **−$60**; **62 fills**; **8/8 open** (at cap): SUKU/DRIFT longs + SXT/AURORA/LCX/XRP/ALCX/NEAR shorts. All `mark_stale=false`; nonzero mids. Decision mix ~92 buy / 66 sell / 232 hold. Pick concentration: **SXT / DRIFT / ALCX / AURORA / SUKU**. Regime mostly **chop** (~80% of AH ticks); trade_imbalance ≈ 0. Horizons disagree ~43% of ticks.
- **Crypto shadows:** B ≈ **−$10 / 8 fills / 6 open** (first sustained B fills; `variant_pass` only ~2%). C and D still **0 fills / flat $10k**. E ≈ **−$70 / 164 fills / 6 open** (exit overlay churns hard, worse than A). F ≈ A (−$60 / 62 / 8). **G ≈ +$38 / 72 fills / 8 open** (best so far; fade-in-chop opposite side on last DRIFT tick). H ≈ **−$49 / 45 fills / 8 open** (slightly quieter via markout veto). `variant_pass` rates ~A/E/F/G 35%, H 28%, B 2%, C/D 0%.
- **Stock (~40 AH JSONL ticks; live.json can lag ~10m behind JSONL while Yahoo polls):** primary ≈ **−$0.51 / 10 fills / 8 open** (TSLA dust + META/MAR/AAPL/COIN/GOOGL/DELL shorts, INTC long). B ≈ −$0.19 / 6; C ≈ −$0.11 / 4; D flat 0; E ≈ −$0.26 / 14; F/H ≈ A; G ≈ **+$0.45 / 10**. All near-flat; `session_ok=true` on AH ticks; no stale/zero marks. Sample still small vs crypto.
- Accounting vs trading: crypto drawdown looks like real alt mark + adverse selection on thin names (not mid=0 wipeouts). E’s extra fills are real exit churn. Stock live lag is operational freshness, not invented PnL.

### Lessons learned
1. **Good:** A–H ledgers keep differentiating without truncating JSONL — B finally has crypto fills; C/D remain correctly quiet; G’s chop-fade is the only green crypto book so far.
2. **Good:** v2 guards hold — crypto open capped at 8; stock RTH/`session_ok`; zero `mark_stale` / zero mid on open crypto detail rows.
3. **Bad / watch:** primary still **clusters thin alts** (SXT/DRIFT/SUKU/AURORA) and sits at the open-name ceiling — capacity spent before majors; large unit qtys on sub-cent names amplify mark noise.
4. **Bad / concrete but early:** **E exit overlay overtrades** (164 fills vs A’s 62) and is **worst PnL** this window — time/TP/trail may be cutting winners or recycling the same alts; do not promote E yet.
5. **Watch:** G lead (~+$38 vs A −$60) is the first meaningful A–H spread, but only ~1h in chop-heavy regime — not enough to flip primary. Prefer KEEP until trend regime hours or stock sample grows.
6. Stock tick cadence remains much slower than crypto; do not overfit stock A–H ranks on ~40 ticks.

### Strategy decision · KEEP/OBSERVE
- No strategy/code change this hour. Keep primary A + shadows B–H through remaining wall time.
- Next windows: (a) whether G stays ahead when regime≠chop, (b) whether E’s exit churn stays net-negative, (c) first C/D crypto fills, (d) stock live.json freshness vs JSONL.

### Code / config changes (if any)
- None.

### Next observe window
- Next hourly reflect ~13:08–13:40 PT; campaign end ~14:06 PT. If ends_ts passes and both smokes exit → final summary + delete routine `jev-trading-hourly-strategy-iterate`.


## 2026-09-22 13:33 PT · iteration 7 · KEEP/OBSERVE (A–H ~2h; G still ahead)

### Observed
- Campaign `A_to_H_observe` active; ends_ts `2026-09-22T21:06:00Z` (~14:06 PT); ~0.5h remaining. PIDs crypto/stock/dashboard all alive (~2h05m uptime); dashboard http://127.0.0.1:8787 returns 200. No restarts this hour.
- **Crypto primary `exp_A_short` (~726 ticks / ~2h05m since A–H restart):** equity ≈ **$9933** / PnL ≈ **−$67**; **107 fills**; **8/8 open** (at cap): SUKU/DRIFT/ALCX longs + SXT/AURORA/LCX/XRP/NEAR shorts. All `mark_stale=false`; nonzero mids (incl. sub-cent alts). Decision mix ~184 buy / 148 sell / 394 hold. Pick concentration: **DRIFT / AURORA / ALCX / SXT / SUKU**. Regime mix **chop ~66% / trend ~34%** (483 vs 246 AH JSONL ticks); trade_imbalance ≈ 0. Horizons disagree ~47% of ticks.
- **Crypto shadows:** **G ≈ +$63 / 112 fills / 8 open** (still best; held lead into trend hours). **B ≈ +$31 / 22 fills / 8 open** (recovered from earlier red; `variant_pass` ~6%). **C ≈ +$3 / 13 fills / 8 open** (first sustained C fills; pass ~2%). D still **0 fills / flat $10k**. E ≈ **−$98 / 272 fills** (exit overlay still overtrades; worst PnL). F ≈ A (−$67 / 107). H ≈ **−$92 / 68 fills** (quieter but worse than A). `variant_pass` rates ~A/E/F/G 40%, H 33%, B 6%, C 2%, D 0%.
- **Stock (~72 ticks; live.json last_ts can lag JSONL by several minutes while Yahoo polls):** primary ≈ **+$2.34 / 10 fills / 8 open** (META/MAR/AAPL/COIN/GOOGL/DELL shorts, INTC long, TSLA dust). B ≈ +$2.09 / 9; C ≈ +$1.93 / 6; D flat 0; E ≈ −$0.14 / 23; F/H ≈ A; G ≈ **−$1.75 / 10** (slightly behind A on stock). Nearly all `session_ok` path under RTH; zero stale/zero mids on open detail. Sample still small vs crypto.
- Accounting vs trading: crypto drawdown remains alt mark + adverse selection on thin names (not mid=0 wipeouts). E’s fill explosion is real exit churn. Stock near-flat PnL looks like real small marks. Live lag is operational freshness, not invented PnL.

### Lessons learned
1. **Good:** G’s chop-fade lead persisted across ~2h and into a non-trivial trend share (~1/3 of ticks) — strongest A–H signal so far on crypto (~+$63 vs A −$67).
2. **Good:** B and C finally have meaningful crypto fill samples; agree gates are no longer totally silent. D remains correctly quiet with imbalance ≈ 0.
3. **Good:** v2 guards hold — primary open capped at 8; stock RTH intact; zero `mark_stale` / zero mid on open crypto/stock detail rows.
4. **Bad / reinforced:** **E exit overlay overtrades** (272 vs A’s 107 fills) and stays worst PnL — do not promote E; time/TP/trail likely recycling thin alts.
5. **Bad / watch:** primary still **clusters thin alts** (DRIFT/AURORA/SXT/SUKU) at the open-name ceiling; large unit qtys on sub-cent names amplify mark noise. H’s markout veto cut activity but did not improve PnL vs A this window.
6. **Caveat:** G leads crypto but is slightly behind A on the small stock sample — not enough to flip primary with ~30m wall time left. Prefer KEEP through campaign end; consider G-primary in a fresh post-window campaign if the lead survives the final half-hour.

### Strategy decision · KEEP/OBSERVE
- No strategy/code change this hour. Keep primary A + shadows B–H through remaining wall time (~14:06 PT).
- Final half-hour watch: (a) whether G stays ahead through end, (b) E churn stays net-negative, (c) D ever fires if imbalance moves, (d) stock live.json freshness.

### Code / config changes (if any)
- None.

### Next observe window
- Next hourly reflect ~14:08 PT may land after ends_ts — if ends_ts passed and both smokes exit → final summary + delete routine `jev-trading-hourly-strategy-iterate`.

## 2026-09-22 14:30 PT · iteration 8 · FINAL (A–H observe window complete)

### Observed
- Campaign `A_to_H_observe` **ended** at `ends_ts` `2026-09-22T21:06:00Z` (~14:06 PT). Wall clock now ~14:30 PT. Crypto PID 1137920 and stock PID 1137921 **exited**; dashboard PID 1137915 still alive; http://127.0.0.1:8787 returns 200. No restart (window over).
- Final JSONL: `logs/raw_decisions/crypto.jsonl` **1373** lines; `stock.jsonl` **144** lines (append-only preserved). Live last_ts crypto `21:05:50Z` / stock `21:05:31Z` (both just before ends_ts). Errors: 0 / 0.
- **Crypto primary `exp_A_short` (920 ticks / ~2.64h):** equity ≈ **$9923** / PnL ≈ **−$77** / **128 fills** / **8 open** (XRP/NEAR/SXT/ALCX/LCX/AURORA shorts-or-mixed + DRIFT/SUKU). Decision mix 229 buy / 187 sell / 504 hold. Top picks: **DRIFT / AURORA / ALCX / SXT / BNKR**. Regime on AH JSONL: **chop ~631 / trend ~289** (~69% chop); trade_imbalance ≈ 0. Zero stale/zero-mid hits in JSONL book snapshots.
- **Crypto shadows (final):** **G ≈ +$187 / 120 fills / 8 open** (clear best). **B ≈ +$78 / 23 fills / 8**. **C ≈ +$13 / 13 fills / 8**. D still **0 fills / flat $10k**. F ≈ A (−$75 / 123). **E ≈ −$111 / 316 fills** (heaviest churn). **H ≈ −$172 / 86 fills** (worst PnL). Rank by PnL: G ≫ B > C > D=0 > F≈A > E > H.
- **Stock (97 ticks):** primary ≈ **+$2.72 / 10 fills / 8 open** (TSLA dust + META/MAR/AAPL/COIN/GOOGL/DELL shorts, INTC long). B ≈ −$0.24 / 9; C ≈ −$0.40 / 6; D flat 0; E ≈ −$0.14 / 23; F/H ≈ A (+$2.72); **G ≈ −$2.12 / 10** (slightly behind A). Nearly all ticks chop; sample still small vs crypto. No invented wipeouts.

### Lessons learned
1. **Good / concrete:** On crypto over the full A–H window, **regime fade (G) was the only large green book** (~+$187 vs A −$77) while sharing the same open names — strongest promote candidate for a *fresh* post-window campaign, not a mid-run flip.
2. **Good:** Horizon-agree gates **B** and **C** finished green with thinner activity (fewer fills, less alt churn) — useful as selective overlays, not silent failures.
3. **Good:** v2 guards held through exit — primary open capped at 8; stock stayed near-flat with sane marks; JSONL never truncated; no mid=0 accounting wipeouts this campaign.
4. **Bad / reinforced:** **E exit overlay overtrades** (316 vs A’s 128 fills) and stays net-negative — do not promote time/TP/trail as-is on thin alts.
5. **Bad / reinforced:** **H markout veto** cut fills but finished **worst PnL** (~−$172) — soft veto alone did not fix adverse selection this window.
6. **Bad / watch:** Primary still **clusters thin alts** (DRIFT/AURORA/SXT/ALCX) at the open-name ceiling; imbalance D never fired (imbalance≈0) so that ledger stayed uninformative.
7. **Caveat:** G leads crypto but is slightly red on the small stock sample — next campaign should keep dual-market A/B with G as crypto candidate primary, not a blind global flip. Stock evidence remains underpowered (97 ticks).

### Strategy decision · FINAL / KEEP code (window closed)
- Observe window finished. **No mid-exit code change** this hour (processes already stopped).
- Recommended next campaign (when user starts one): trial **G as crypto primary** with A/B/C as shadows; keep E/H as research-only or retune; consider a thin-name / min-price filter so capacity is not spent on sub-cent alts; leave D until imbalance signal exists.
- Leave dashboard up for post-mortem viewing; do not restart smokes past ends_ts.

### Code / config changes (if any)
- None this hour.

### Next observe window
- **None for this campaign.** Hourly iterate routine should be **deleted** after this final push. Data remains under `logs/raw_decisions/` and this log; resume only if a new campaign is launched.

## 2026-09-22 15:20 PT · iteration 9 · CHANGE (G primary crypto · 24h RSI)

### Observed
- Prior campaign `A_to_H_observe` ended at ends_ts ~14:06 PT (iter 8 FINAL). Crypto/stock smokes were dead; dashboard PID 1137915 stayed up (:8787 → 200).
- Final A–H crypto rank: **G ≫ B > C > D=0 > F≈A > E > H** (G ~+$187 vs A −$77). Stock sample small: A slightly ahead of G.
- `logs/raw_decisions/crypto.jsonl` and `stock.jsonl` preserved append-only (pre-restart ~1373 / 144 lines; still growing).

### Lessons learned
1. **Promote G on crypto only** — clearest A–H signal; do **not** blind-flip stock primary (G was slightly red vs A on stock).
2. Hardcoded PRIMARY in `smoke.py` ignored `experiment.json` → fixed with `primary` + `primary_by_market` and full variant dict (incl. fade_in_chop / chop_size_cap).
3. CHANGE framing = **new campaign wave**: archive prior books, fresh $10k ledgers, new ends_ts (~24h), keep JSONL history.

### Strategy decision · CHANGE
- Launch campaign **G_primary_24h**: crypto primary **exp_G_regime_mr**, stock primary **exp_A_short** (G remains stock shadow). Shadows = remaining A–H compare ledgers.
- Hourly RSI reflect: model reviews right vs wrong decisions; on clear lessons → CHANGE (restart new wave); else KEEP / OBSERVE. (Parent owns hourly routine creation.)

### Code / config changes
- `jev_trading/smoke.py`: resolve primary per market from experiment; full variant dict for tick loop; live/meta report actual primary id.
- `jev_trading/data/experiment.json`: jev_paper_G_primary_24h_2026_09_22, iteration 9, primary_by_market.
- `docs/EXPERIMENT.md`, this log; archive `out/archive_pre_G_primary_24h/`; fresh `out/campaign.json` + PIDs.

### Next observe window
- ~24h until ends_ts 2026-09-23 ~15:19 PT / 22:19 UTC. First hourly reflect should confirm G primary on crypto live ticks and A on stock; watch chop-fade vs trend hours and stock RTH sample size.



## 2026-09-22 16:32 PT · iteration 10 · CHANGE (G primary fade fix · fresh 24h)

### Observed
- Campaign `G_primary_24h` (~1.1h in; ends_ts was 2026-09-23T22:19Z). Crypto/stock/dashboard PIDs alive before change. Stock `session_ok=false` (after RTH) → **0 fills / flat $10k** across A–H (expected overnight).
- **Crypto primary `exp_G_regime_mr` pre-fix (~400 ticks):** equity ≈ **$9914** / PnL ≈ **−$86** / **69 fills** / **8 open**. Rank by PnL: **D 0 > C ≈−$3 / 3f > H ≈−$5 / 36f > B ≈−$37 / 25f > E ≈−$50 / 172f > G=A=F ≈−$86 / 69f**.
- **Critical:** G vs A PnL diverged on **0 / ~400** ticks. Chop primary fills were momentum (buy large_up / sell large_down), not fade. Root cause: `apply_regime_fade` ran only in the **shadow** loop; with G promoted to primary, the primary entry path used raw Jev direction — so **G ≡ A**.
- AURORA concentration still hurt the shared G/A book (~−$66 unrealized on AURORA short). E still overtrades (172 fills). D silent (imbalance≈0). Horizon disagree ~72%.
- Prior A–H observe FINAL (iter 8) had still favored G when G was a **shadow** — consistent with the bug only biting G-as-primary.

### Lessons learned
1. **Clear bug / actionable:** Promoting a fade overlay to primary requires the **primary** trade path to call `apply_regime_fade` (and honor `primary_fade_ok` / chop size cap). Shadow-only application silently nullifies the experiment.
2. Early ~1h of `G_primary_24h` is **not** evidence against regime fade — it was an A-clone run. Do not KEEP that wave.
3. Stock overnight flat is RTH guard working, not a signal. E churn + thin-alt clustering remain watch items after the fix.
4. Post-restart smoke log already shows chop fade fills (`large_up→sell`, `large_down→buy`, `fade_applied=true`) and **G≠A** PnL within first ticks — fix verified live.

### Strategy decision · CHANGE
- Fix `jev_trading/smoke.py` primary entry to apply regime fade when `fade_in_chop`.
- Archive prior books under `out/archive_pre_G_fade_fix_20260922_163053/`. Fresh **$10k** books. New campaign **`G_primary_fade_fix_24h`** (iteration 10), ends_ts `2026-09-23T23:30:55.713766+00:00` (~24h). Crypto primary G, stock primary A. JSONL history preserved append-only under `logs/raw_decisions/`.

### Code / config changes
- `jev_trading/smoke.py`: primary path uses `apply_regime_fade` → `primary_dir` / `primary_move` / `primary_fade_ok`; skip entry when fade says hold; meta `fade_applied` + `regime` on primary fills.
- `jev_trading/data/experiment.json`: `jev_paper_G_primary_fade_fix_24h_2026_09_22`, iteration 10.
- `out/campaign.json` + new smoke PIDs; prior wave archived.

### Next observe window
- Hourly reflect through ends_ts ~2026-09-23T23:30:55.713766+00:00. Confirm G continues to diverge from A in chop, and whether G leads shadows over a full day (incl. next RTH for stock).

## 2026-09-22 17:38 PT · iteration 11 · KEEP (G fade ok · timeout crash ops fix)

### Observed
- Campaign `G_primary_fade_fix_24h` still active; ends_ts `2026-09-23T23:30:55.713766+00:00` (~22.9h left). Stock PID stayed up overnight; **crypto PID 1284584 died ~17:19 PT** on uncaught `TimeoutError` in `call_jev` (OpenRouter SSL read). Dashboard 1137915 alive.
- **Pre-crash crypto window (~270 ticks / ~47m from ~16:31 PT, archived `out/archive_crypto_ssl_timeout_20260922_173446/`):** primary **`exp_G_regime_mr` ≈ +$43.71 / 40 fills / 8 open**. Shadows by PnL: **G ≫ C=0 / D=0 > B ≈−$14 / 20f > E ≈−$21 / 104f > A=F ≈−$54 / 40f > H ≈−$64 / 27f**. **G≠A** gap ≈ **+$98** (G +44 vs A −54). All 40 primary fills had `fade_applied=true`; recent chop samples correct (e.g. BLUECHIP/AURORA `large_up→sell`). Open names: FARTCOIN long (+$29 uPnL), AURORA short (+$12), BLUECHIP short (−$6), plus DOGE/NEAR/TROLL/ZEC/BCH — thin-alt concentration persists but marks non-stale.
- **Stock overnight (pre-restart ~86 ticks):** primary A flat **$0 / 0 fills** — `session_ok=false` correctly blocked sells (META/GM/CSCO signals). All A–H flat. Expected post-RTH.
- **Ops:** Restarted crypto once (~17:34) → died again on same TimeoutError at tick≈2–3. Root cause: `call_jev` only caught `HTTPError`, so SSL read timeouts crashed the process. Patched + restarted both markets with remaining wall time to same ends_ts; books re-init **$10k** (pre-crash crypto books preserved in archive). Post-fix smoke: crypto fading again (`large_down→buy`, `fade_applied=true` on XRP/ZEC/VVV/ZEN); stock tick=1 RTH-closed flat.

### Lessons learned
1. **Good / confirmed:** Iteration-10 fade-on-primary fix holds — G diverges hard from A in chop and led the A–H board pre-crash (~+$44 vs A −$54).
2. **Good:** Stock RTH guard still blocks overnight fills; zero invented wipeouts.
3. **Bad / actionable (ops, not strategy):** Uncaught Jev `TimeoutError` hard-kills the paper loop. Must treat network timeouts like HTTP errors (log + continue), not process death.
4. **Watch:** E still overtrades (104 vs G’s 40 fills) and stays red; H quiet but worst PnL; thin-alt picks (AURORA/BLUECHIP/FARTCOIN) still dominate capacity — observe through next RTH before any promote/demote.
5. Early campaign (~1h) + clean G lead → **no strategy CHANGE / no new campaign wave**.

### Strategy decision · KEEP
- Keep crypto primary **exp_G_regime_mr**, stock primary **exp_A_short**, shadows A–H, same campaign id + ends_ts.
- Ops-only: catch timeouts in `call_jev`, bump Jev HTTP timeout 30→45s, restart smokes to ends_ts (fresh $10k books after crash; JSONL append-only preserved under `logs/raw_decisions/`).

### Code / config changes (if any)
- `jev_trading/jev_client.py`: `call_jev` catches `TimeoutError` / `URLError` / `OSError` → `{error:true,status:"timeout"}`; timeout 45s.
- `out/campaign_pids.json` updated; crypto pre-crash out archived; campaign.json annotated with ops restart notes. No experiment overlay / primary changes.

### Next observe window
- Next hourly reflect ~18:08–18:40 PT. Confirm smokes stay alive through timeouts (error ticks, not crashes), G still ≠ A, and stock remains flat until next RTH.

## 2026-09-22 18:30 PT · iteration 12 · KEEP (post-timeout-fix wave · early G vs A)

### Observed
- Campaign `G_primary_fade_fix_24h` still active; ends_ts `2026-09-23T23:30:55.713766+00:00` (~29h left). Crypto PID 1317447 + stock PID 1317448 + dashboard 1137915 **alive**. `errors=0` on both live books since ops restart (~17:37 PT) — TimeoutError path no longer kills the loop.
- **Crypto post-restart (~306 ticks / ~53m from $10k re-init):** primary **`exp_G_regime_mr` ≈ −$6.5 / 14 fills / 8 open**. Shadows by PnL: **A = F = H ≈ +$5 / 15f** > **C = D = 0 fills / flat** > **G ≈ −$6.5** > **B ≈ −$27 / 12f** > **E ≈ −$40–−$66 / 112f** (still heaviest churn). Regime mix ~70% chop / 30% trend; trade_imbalance still ≈ 0.
- **G≠A verified:** all 8 open names opposite sign vs A; every shared fill tick is opposite side in chop (`large_down→G buy / A sell`, `large_up→G sell / A buy`). All 14 primary fills have `fade_applied=true` + `regime=chop`.
- **Fill sample (right mechanics, mixed early markouts):** XRP/ZEC/VVV/ZEN buys on `large_down` fade; FARTCOIN/BONK/API3/PYTH sells on `large_up` fade. Worst open uPnL: ZEN long ≈ −$4.7 (4× $100 adds), BONK short ≈ −$4.6 (sub-cent), FARTCOIN short ≈ −$3.2; best: API3 short ≈ +$5.8, PYTH short ≈ +$2.2. No stale/zero-mid marks.
- **Stock overnight (~32 ticks):** primary A flat **$0 / 0 fills**; all shadows flat. `session_ok=false` correctly blocked sized signals (AMZN/BDX/BUD etc.). Expected pre-RTH.
- JSONL append-only: `logs/raw_decisions/crypto.jsonl` ~2365 lines; `stock.jsonl` ~377. Out run books are the post-17:37 re-init wave only.

### Lessons learned
1. **Good / ops:** Iteration-11 timeout catch is holding — 0 error ticks, continuous crypto loop through OpenRouter latency spikes (max ~2.5s, avg ~0.3s).
2. **Good / mechanics:** Fade-on-primary still correct post-restart; G remains a true invert of A in chop, not an A-clone.
3. **Watch / not actionable yet:** This ~1h book has **A slightly ahead of G** (~+$5 vs −$6.5), opposite the pre-crash ~1h archive where G led (~+$44 vs A −$54). Gap is small ($11) and books were re-seeded after crash — **do not CHANGE** on one short opposing sample; need multi-hour + next RTH.
4. **Bad / reinforced:** E exit overlay still overtrades (~8× G fills) and stays red — research-only. H ≡ A this window (same fills/PnL) so markout veto is not differentiating yet. C/D silent (horizon disagree / imbalance≈0).
5. **Watch:** Capacity still clusters thin/meme names (ZEN repeats, BONK/FARTCOIN/API3/PYTH); ZEN 4-fill stack drove early G drag. Observe whether a min-price / max-per-name rule becomes a clear CHANGE later — not mid-wave without a longer edge.

### Strategy decision · KEEP
- No strategy/code CHANGE. Keep crypto primary **exp_G_regime_mr**, stock primary **exp_A_short**, shadows A–H, same campaign id + ends_ts.
- Continue hourly RSI through the 24h window; revisit promote/demote only if G systematically trails A for several hours *or* a concrete gate bug reappears.

### Code / config changes (if any)
- None.

### Next observe window
- Next hourly reflect ~19:08–19:40 PT. Confirm smokes stay up, whether G reclaim vs A as marks mean-revert, E churn stays junk, and stock remains flat until next RTH open.


## 2026-09-22 19:24 PT · iteration 13 · KEEP (G reclaim vs A · post-restart ~2h)

### Observed
- Campaign `G_primary_fade_fix_24h` still active; ends_ts `2026-09-23T23:30:55.713766+00:00` (~21h left). Crypto PID 1317447 + stock PID 1317448 + dashboard 1137915 **alive**. `errors=0` both markets since ops restart (~17:37 PT).
- **Crypto post-restart (~620 ticks / ~1h47m from $10k re-init):** primary **`exp_G_regime_mr` ≈ +$7.7 / 15 fills / 8 open**. Shadows by PnL: **G ≈ +$7.7** > **E ≈ +$4.2 / 221f** (equity still ~$9973; heaviest churn) > **D = 0 fills / flat** > **A = F = H ≈ −$10.3 / 16f** > **C ≈ −$15 / 9f** > **B ≈ −$20 / 16f**. Regime mix ~63% chop / 37% trend; trade_imbalance still ≈ 0.
- **G≠A verified:** all 8 open names opposite sign vs A; latest shared fill (VVV tick 373) `large_down→G buy / A sell` with `fade_applied=true` + `regime=chop`. All 15 primary fills are fade-shaped (`large_down→buy` or `large_up→sell`).
- **Open markouts (G):** best API3 short ≈ +$6.1, PYTH short ≈ +$5.0, FARTCOIN short ≈ +$1.0; worst ZEN long ≈ −$2.8 (4× $100 stack), VVV long ≈ −$1.2, BONK short ≈ −$0.8. No stale/zero-mid marks.
- **Stock overnight (~126 ticks):** primary A flat **$0 / 0 fills**; all shadows flat. `session_ok` blocking sized sells (e.g. NOW/ORCL signals with move=flat). Expected pre-RTH.
- JSONL append-only: `logs/raw_decisions/crypto.jsonl` ~2680 lines; `stock.jsonl` ~476.

### Lessons learned
1. **Good / reclaim:** The early post-restart hour where A edged G (~+$5 vs −$6.5 at iter 12) **mean-reverted** — G now leads A by ~$18 on the same book wave. Matches the “do not CHANGE on one short opposing sample” call.
2. **Good / mechanics:** Fade-on-primary still correct; G remains a true invert of A in chop; TimeoutError catch still holding (`errors=0`, max latency ~2.5s).
3. **Bad / reinforced:** E exit overlay still ~15× G fills and is not a clean PnL winner (equity lag vs headline pnl). H ≡ A (same −$10.3 / 16f) — markout veto still not differentiating. C/D mostly silent (horizon / imbalance≈0).
4. **Watch:** Capacity still clusters thin/meme names (ZEN 4-fill stack, BONK/FARTCOIN/API3/PYTH/AURORA-heavy picks). ZEN drag shrunk vs prior hour but stacking remains the main concentration risk — still **not** a mid-wave CHANGE without multi-hour + RTH evidence.
5. Stock still uninformative overnight; wait for next RTH before any stock primary judgment.

### Strategy decision · KEEP
- No strategy/code CHANGE. Keep crypto primary **exp_G_regime_mr**, stock primary **exp_A_short**, shadows A–H, same campaign id + ends_ts.
- Continue hourly RSI through the 24h window; revisit thin-name / max-per-name only if G systematically trails *and* concentration is the clear driver across several hours.

### Code / config changes (if any)
- None.

### Next observe window
- Next hourly reflect ~20:08–20:40 PT. Confirm G lead holds vs A/F/H, E churn stays junk, and whether stock remains flat until RTH open.

## 2026-09-22 20:21 PT · iteration 14 · KEEP (G still leads A · lead compressed)

### Observed
- Campaign `G_primary_fade_fix_24h` still active; ends_ts `2026-09-23T23:30:55.713766+00:00` (~20.1h left). Crypto PID 1317447 + stock PID 1317448 + dashboard 1137915 **alive**. `errors=0` both markets since ops restart (~17:37 PT).
- **Crypto post-restart (~948 ticks / ~2h45m from $10k re-init):** primary **`exp_G_regime_mr` ≈ −$0.50 / 17 fills / 8 open**. Shadows by PnL: **D = 0 fills / flat** > **G ≈ −$0.5** > **A = F = H ≈ −$4.65 / 18f** > **C ≈ −$19.7 / 12f** > **B ≈ −$23.4 / 16f** > **E ≈ −$79.7 / 307f** (still heaviest churn). Regime mix ~67% chop / 33% trend; trade_imbalance still ≈ 0.
- **G≠A verified:** 16/17 shared primary fills opposite side vs A. All but one primary fill are correct chop fades (`large_down→buy` / `large_up→sell`, `fade_applied=true`). Lead vs A compressed from iter-13 ~+$18 gap to ~+$4.2 — G no longer green but still best among active books.
- **One anomaly (watch, not CHANGE):** tick 753 `BONK-USD` sell on `large_down` with `fade_applied=true` while `regime=trend` — side matches A (momentum-correct for trend) but fade flag should not claim a flip. Immediately followed by tick 756 chop fade buy BONK (opposite A). Net: metadata/edge-case, not a G≡A regression.
- **Open markouts (G):** best API3 short ≈ +$3.9, PYTH short ≈ +$2.5, XRP long ≈ +$1.0; worst ZEN long ≈ −$2.6 (4× $100 stack), BONK short ≈ −$1.6, VVV long ≈ −$1.4, FARTCOIN short ≈ −$1.1. No stale/zero-mid marks.
- **Stock overnight (~234 ticks):** primary A flat **$0 / 0 fills**; all shadows flat. `session_ok=false` blocked all 234 ticks; ~18 sized signals (AMZN/BA/DLTR/XLE etc.) correctly suppressed. Expected pre-RTH.
- JSONL append-only: `logs/raw_decisions/crypto.jsonl` ~3008 lines; `stock.jsonl` ~579.

### Lessons learned
1. **Good / persistence:** G still leads A/F/H after ~2.7h post-restart despite lead mean-reverting from iter-13’s ~+$7.7. Matches “do not CHANGE on short opposing samples” — compressed lead ≠ failed fade.
2. **Good / mechanics:** Fade-on-primary holds on 16/17 fills; TimeoutError catch still holding (`errors=0`, max latency ~2.5s).
3. **Watch / single tick:** trend-regime fill with `fade_applied=true` + same side as A (BONK tick 753) — likely flag/path edge when regime flips mid-symbol; observe whether it repeats before touching `apply_regime_fade`.
4. **Bad / reinforced:** E exit overlay ~18× G fills and deepest red (~−$80). H ≡ A (markout veto idle). C/D mostly silent (horizon / imbalance≈0). D “wins” only by not trading.
5. **Watch:** ZEN 4-fill stack + thin/meme concentration (BONK/FARTCOIN/API3/PYTH/AURORA picks) still the main capacity risk — still **not** mid-wave CHANGE without multi-hour + next RTH evidence.
6. Stock still uninformative overnight; wait for next RTH before any stock primary judgment.

### Strategy decision · KEEP
- No strategy/code CHANGE. Keep crypto primary **exp_G_regime_mr**, stock primary **exp_A_short**, shadows A–H, same campaign id + ends_ts.
- Continue hourly RSI through the 24h window; only escalate on repeated trend/fade flag bugs or sustained G≪A across several hours.

### Code / config changes (if any)
- None.

### Next observe window
- Next hourly reflect ~21:08–21:40 PT. Confirm G lead vs A holds, whether BONK-style trend/fade flag anomaly repeats, E churn stays junk, and stock remains flat until RTH open.

## 2026-09-22 21:22 PT · iteration 15 · KEEP (G≈A noise · C spike watch)

### Observed
- Campaign `G_primary_fade_fix_24h` still active; ends_ts `2026-09-23T23:30:55.713766+00:00` (~19.1h left). Crypto PID 1317447 + stock PID 1317448 + dashboard 1137915 **alive**. `errors=0` both markets since ops restart (~17:37 PT).
- **Crypto post-restart (~1314 ticks / ~3h45m from $10k re-init):** primary **`exp_G_regime_mr` ≈ $-4.8 / 18 fills / 8 open**. Shadows by PnL: **C_multi≈+31.2/13f > D_imbalance≈+0.0/0f > G_regime_mr≈-4.8/18f > A_short≈-5.1/19f > F_inv_skew≈-5.1/19f > H_markout_veto≈-5.1/19f > B_short_med≈-22.6/17f > E_exit_overlay≈-113.5/411f**. Regime mix ~67% chop / ~33% trend (live top-of-book regime currently `trend`); trade_imbalance still ≈ 0.
- **G≠A verified:** 17/18 primary fills opposite side vs A. All but the known BONK tick-753 case are correct chop fades (`large_down→buy` / `large_up→sell`, `fade_applied=true`). G vs A gap flipped again: iter-14 G lead ~+$4 → now G ≈ $-4.8 vs A ≈ $-5.1 (noise band, not a regime break).
- **C spike (watch, not promote):** `exp_C_multi` ≈ $+31.2 / 13f now tops the board, but equity path was deep red mid-window (≈−$25 around t1050) before a thin-alt bounce (BLAST/ETC/CELR/ALCX/KARRAT). Multi-horizon agree is not yet a stable edge — observe only.
- **Open markouts (G):** ZEN long u≈-6.10, XRP long u≈+4.46, BONK short u≈-4.38, PYTH short u≈+2.08, FARTCOIN short u≈-1.04, VVV long u≈+0.81, ZEC long u≈-0.60, API3 short u≈-0.04. No stale/zero-mid marks. ZEN 4×$100 stack still the worst open (−$7.0); XRP/PYTH best.
- **Last ~1h:** only **1** new G fill (VVV buy fade t982); capacity full at 8 names so primary is mostly mark-to-market. BONK trend/fade anomaly **did not repeat** (still 1/18).
- **Stock overnight (~330 ticks):** primary A flat **$0 / 0 fills**; all shadows flat. `session_ok=false` on all post-restart ticks; 28 sized signals correctly suppressed. Expected pre-RTH.
- JSONL append-only: `logs/raw_decisions/crypto.jsonl` growing; `stock.jsonl` growing. Out run books remain the post-17:37 re-init wave.

### Lessons learned
1. **Good / mean-reversion of ranks:** G↔A leadership keeps oscillating inside a ~$10 band across hours (iter12 A>G → iter13 G≫A → iter14 G>A → iter15 A≳G). Reinforces **do not CHANGE on hourly rank flips**.
2. **Good / mechanics:** Fade-on-primary still correct on 17/18 fills; TimeoutError catch holding (`errors=0`, max latency ~2.5s).
3. **Watch / C:** First time C leads the A–H board post-restart, but path was non-monotonic and name set is thin/meme-heavy — **not** a mid-wave primary swap without multi-hour + RTH confirmation.
4. **Bad / reinforced:** E exit overlay ~23× G fills and deepest red (~−$113). H≡A≡F (markout veto / inv-skew idle this window). D still 0 fills (imbalance≈0).
5. **Watch:** ZEN stack + BONK/FARTCOIN/API3/PYTH/VVV concentration + capacity-full stall (only 1 fill last hour) — still **not** mid-wave CHANGE; revisit if G systematically trails *and* concentration is the clear driver across several more hours / next RTH.
6. Stock still uninformative overnight; wait for next RTH before any stock primary judgment.

### Strategy decision · KEEP
- No strategy/code CHANGE. Keep crypto primary **exp_G_regime_mr**, stock primary **exp_A_short**, shadows A–H, same campaign id + ends_ts.
- Continue hourly RSI through the 24h window; escalate only on repeated trend/fade bugs, sustained G≪A across several hours, or a clean multi-hour C edge that survives RTH.

### Code / config changes (if any)
- None.

### Next observe window
- Next hourly reflect ~22:08–22:40 PT. Confirm whether C lead holds or mean-reverts, G stays within noise of A/F/H, E churn stays junk, and stock remains flat until RTH open.

## 2026-09-22 22:20 PT · iteration 16 · KEEP (G trails A in noise · C mean-reverted)

### Observed
- Campaign `G_primary_fade_fix_24h` still active; ends_ts `2026-09-23T23:30:55.713766+00:00` (~18.2h left). Crypto PID 1317447 + stock PID 1317448 + dashboard 1137915 **alive**. Crypto `errors=1` (was 0; no crash / no TimeoutError traceback in run log; max latency ~6.8s once); stock `errors=0`.
- **Crypto post-restart (~1650 ticks / ~4.7h from $10k re-init):** primary **`exp_G_regime_mr` ≈ −$11.4 / 18 fills / 8 open**. Shadows by PnL: **C_multi≈+$4.5–7.7/13f > D_imbalance≈+$0.0/0f > A_short≈F≈H≈−$3.3–4.3/19f > G≈−$11.4/18f > B_short_med≈−$30–34/17f > E_exit_overlay≈−$150/504f**. Regime mix ~67% chop / ~33% trend (live regime `chop`); trade_imbalance still ≈ 0.
- **G≠A verified:** 17/18 shared fill ticks opposite side vs A. Sole same-side remains BONK tick 753 (trend/fade flag anomaly from iter 14) — **did not repeat**. Open books: 7/8 names opposite sign; BONK both short (G residual after 753 sell + 756 buy vs A’s short stack).
- **C mean-reverted:** iter-15 spike ≈+$31 → now ≈+$5–8; still tops active books but path/name set (BLAST/B3/BLUECHIP/KARRAT/ALCX/CELR/ETC/L3) remains thin-alt — watch only, not promote.
- **Capacity stall:** still **18** primary fills (last = VVV buy fade t982); 8/8 open names so primary is mark-to-market only this hour. Worst open: ZEN long u≈−$6.5 (4×$100 stack), BONK short u≈−$9.9; best PYTH short u≈+$3.5, XRP long u≈+$2.3. No stale/zero-mid marks.
- **Stock overnight (~400 ticks):** primary A flat **$0 / 0 fills**; all shadows flat. `session_ok=false` + `rth_only` correctly zeroed size (e.g. NOW/SNAP/SCHW picks). Expected pre-RTH.
- JSONL append-only: `logs/raw_decisions/crypto.jsonl` ~3710 lines; `stock.jsonl` ~752. Out run books remain the post-17:37 re-init wave.

### Lessons learned
1. **Good / C check:** The iter-15 C lead mean-reverted hard (−$23+ in ~1h) — confirms **do not promote on single-hour shadow spikes**, especially on thin-alt baskets.
2. **Watch / G vs A:** G now trails A/F/H by ~$7–8 after oscillating inside a ~$10–20 band all evening (iter12 A>G → 13 G≫A → 14 G>A → 15≈tie → 16 A>G). Still **noise, not a multi-hour systematic fail** — KEEP primary G.
3. **Good / mechanics:** Fade-on-primary still correct on 17/18 fills; capacity gate (max 8 names) working as designed (no new risk while full). Ops: one error tick without process death — timeout catch still holding.
4. **Bad / reinforced:** E exit overlay ~28× G fills and deepest red (~−$150). H≡A≡F (markout veto / inv-skew idle). D still 0 fills (imbalance≈0). B stays red on multi-horizon disagree thrash.
5. **Watch:** ZEN 4-fill stack + BONK/FARTCOIN/API3/PYTH/VVV concentration + capacity-full stall remain the main drag narrative — still **not** mid-wave CHANGE without sustained G≪A across several more hours and/or next RTH evidence.
6. Stock still uninformative overnight; wait for next RTH before any stock primary judgment.

### Strategy decision · KEEP
- No strategy/code CHANGE. Keep crypto primary **exp_G_regime_mr**, stock primary **exp_A_short**, shadows A–H, same campaign id + ends_ts.
- Continue hourly RSI through the 24h window; escalate only on repeated trend/fade bugs, sustained G≪A across several hours, or a clean multi-hour C edge that survives mean-reversion + RTH.

### Code / config changes (if any)
- None.

### Next observe window
- Next hourly reflect ~23:08–23:40 PT. Confirm whether G–A gap stays noise or widens, C stays compressed, E churn stays junk, and stock remains flat until RTH open.

## 2026-09-22 23:26 PT · iteration 17 · KEEP (A lead widens · fade-flag repeats in trend)

### Observed
- Campaign `G_primary_fade_fix_24h` still active; ends_ts `2026-09-23T23:30:55.713766+00:00` (~17.1h left). Crypto PID 1317447 + stock PID 1317448 + dashboard 1137915 **alive**. Crypto `errors=2` (was 1; no crash; max latency ~21s once); stock `errors=0`.
- **Crypto post-restart (~2028 ticks / ~5.8h from $10k re-init):** primary **`exp_G_regime_mr` ≈ −$17.0 / 23 fills / 8 open**. Shadows by PnL: **A≈F≈H≈+$3.0/24f > D=0f/flat > C≈−$9.4/13f > G≈−$17.0/23f > B≈−$40/17f > E≈−$161/607f**. Regime mix all-run ~66% chop / ~34% trend (last-200 ticks flipped heavier trend ~57%); trade_imbalance still ≈ 0.
- **G≠A:** 18/23 primary fills opposite side vs A. **5 same-side** fills, all in `regime=trend` (momentum-correct vs A): BONK t753, FARTCOIN t1823/1825/1826, BONK t1974. Open books: 7/8 names opposite sign; **FARTCOIN both short** (G residual after trend sells).
- **Fade-flag anomaly escalated (metadata, not wrong side):** all 5 trend same-side fills still carry `fade_applied=true` — was 1/18 at iter 14–16, now 5/23. Side selection in trend matches A (correct); flag path still mislabels. No new chop fade-direction bugs.
- **C further mean-reverted:** iter-15 ≈+$31 → iter-16 ≈+$5–8 → now ≈−$9. Confirms single-hour shadow spikes are not promote signals.
- **Capacity / concentration:** 5 new primary fills since iter 16 (FARTCOIN chop buy t1659 + 3× trend sells t1823–26 + BONK trend buy t1974). Worst open: BONK short u≈−$10.8, ZEN long u≈−$6.3 (4×$100 stack), VVV long u≈−$4.4; best XRP/PYTH. No stale/zero-mid marks.
- **G–A gap:** iter-16 A lead ~$7–8 → now A lead ~$20 (A≈+$3 vs G≈−$17). Second consecutive hour of A>G with widening MTM — still inside evening noise band relative to earlier oscillates (iter12–15 flips), **not** yet a multi-hour systematic fail warranting mid-wave CHANGE.
- **Stock overnight (~464 ticks):** primary A flat **$0 / 0 fills**; all shadows flat. `session_ok=false` on recent window; sized signals (NOW/SNAP/SYF/COF etc.) correctly size-zeroed. Expected pre-RTH.
- JSONL append-only: `logs/raw_decisions/crypto.jsonl` ~4088 lines; `stock.jsonl` ~809. Out run books remain the post-17:37 re-init wave.

### Lessons learned
1. **Watch / G vs A:** A lead widened to ~$20 after two hours of A>G. Still treat as MTM noise on a capacity-full thin-alt book — **KEEP** unless the gap stays wide *and* G systematically trails across several more hours / into next RTH.
2. **Watch / fade flag:** `fade_applied=true` on trend-momentum fills is now a **repeating** metadata bug (5 cases: BONK + FARTCOIN stacks). Side logic in trend still matches A; do **not** mid-wave CHANGE for a flag-only defect — queue a post-campaign or low-risk code fix if it keeps firing.
3. **Good / C check:** C’s iter-15 spike fully mean-reverted through zero into red — reinforces no promote on one-hour shadow leaders.
4. **Bad / reinforced:** E exit overlay ~26× G fills and deepest red (~−$161). H≡A≡F. D still 0 fills (imbalance≈0). B stays red on multi-horizon thrash.
5. **Watch:** BONK/ZEN/VVV/FARTCOIN concentration + max-8 stall remain the main drag narrative — still **not** mid-wave CHANGE without sustained G≪A evidence.
6. Stock still uninformative overnight; wait for next RTH before any stock primary judgment.

### Strategy decision · KEEP
- No strategy/code CHANGE. Keep crypto primary **exp_G_regime_mr**, stock primary **exp_A_short**, shadows A–H, same campaign id + ends_ts.
- Continue hourly RSI through the 24h window; escalate only on (a) sustained G≪A across several more hours, (b) fade flag causing *wrong-side* trades, or (c) a clean multi-hour shadow edge that survives mean-reversion + RTH.

### Code / config changes (if any)
- None this hour. (Optional later: fix `fade_applied` labeling on trend path so flag is false when regime=trend / no invert.)

### Next observe window
- Next hourly reflect ~00:08–00:40 PT. Confirm whether G–A gap mean-reverts or keeps widening, whether more trend fills mislabel `fade_applied`, E churn stays junk, and stock remains flat until RTH open.
