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

