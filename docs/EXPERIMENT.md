# Paper experiment — A–H compare ledgers

Same Jev multi-horizon answers each tick; A–H differ in entry/exit overlays.

| Book | Role | Rule (one line) |
|------|------|-----------------|
| **exp_A_short** (primary) | Primary | Short-horizon `move` only — baseline |
| **exp_B_short_med** | Compare | `move`+`move_5m`+`move_10m` must agree |
| **exp_C_multi** | Compare | A horizons + `move_1h` agree; block if 1d opposite |
| **exp_D_imbalance** | Compare | Same as A; `trade_imbalance` must agree (buy>+0.15 / sell<-0.15; missing/0 fails) |
| **exp_E_exit_overlay** | Compare | Same as A entry; auto-exit on TP 12bps / max hold / trailing |
| **exp_F_inv_skew** | Compare | Same as A + inventory skew (long/short/cash gates; soft noul bump) |
| **exp_G_regime_mr** | Compare | Trend→A momentum; chop→fade large moves only, size cap $100 |
| **exp_H_markout_veto** | Compare | Same as A; veto symbol if recent avg adverse markout < −8 bps |

Shared gates (all variants): noul≥0.42, dir_tail≥0.40, tox≤2.0, cap $200, small+large moves, `jev_capped` size.

**Note:** stock quotes set `trade_imbalance=0` today → D will typically fail the imbalance gate on stock (conservative).

Dashboard: http://127.0.0.1:8787
