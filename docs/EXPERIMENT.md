# Paper experiment — G primary crypto · A primary stock (24h)

Campaign `G_primary_24h` / experiment `jev_paper_G_primary_24h_2026_09_22` (iteration 9).

Same Jev multi-horizon answers each tick; A–H differ in entry/exit overlays. **Per-market primary** via `primary_by_market`:

| Book | Crypto role | Stock role | Rule (one line) |
|------|-------------|------------|-----------------|
| **exp_G_regime_mr** | **Primary** | Compare (shadow) | Trend→A momentum; chop→fade large moves only, size cap $100 |
| **exp_A_short** | Compare (shadow) | **Primary** | Short-horizon `move` only — baseline |
| **exp_B_short_med** | Compare | Compare | `move`+`move_5m`+`move_10m` must agree |
| **exp_C_multi** | Compare | Compare | A horizons + `move_1h` agree; block if 1d opposite |
| **exp_D_imbalance** | Compare | Compare | Same as A; `trade_imbalance` must agree (buy>+0.15 / sell<-0.15; missing/0 fails) |
| **exp_E_exit_overlay** | Compare | Compare | Same as A entry; auto-exit on TP 12bps / max hold / trailing |
| **exp_F_inv_skew** | Compare | Compare | Same as A + inventory skew (long/short/cash gates; soft noul bump) |
| **exp_H_markout_veto** | Compare | Compare | Same as A; veto symbol if recent avg adverse markout < −8 bps |

Shared gates (all variants): noul≥0.42, dir_tail≥0.40, tox≤2.0, cap $200, small+large moves, `jev_capped` size.

**Why G on crypto only:** A–H observe window (iter 8) showed G ~+$187 vs A −$77 on crypto, but G slightly behind A on the small stock sample — do **not** blind-flip stock to G.

**RSI / hourly:** model reflects right vs wrong decisions; may CHANGE code on clear lessons (restart new campaign wave), else KEEP.

**Note:** stock quotes set `trade_imbalance=0` today → D will typically fail the imbalance gate on stock (conservative).

Dashboard: http://127.0.0.1:8787
