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

