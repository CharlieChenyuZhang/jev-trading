# Paper experiment — multi-horizon A/B/C

Same Jev multi-horizon answers each tick; A/B/C differ only in which horizons must agree before filling.

| Book | Role | Agree gates | Idea |
|------|------|-------------|------|
| **exp_A_short** (primary) | Primary | `move` only | Short-horizon baseline (~30s–1m) — current-style |
| **exp_B_short_med** | Compare | `move` + `move_5m` + `move_10m` | Reduce chase: short and medium windows must agree |
| **exp_C_multi** | Compare | `move` + `move_5m` + `move_10m` + `move_1h`; **block_1d_opposite** | Strictest: also require 1h agree; block new risk if 1d trend opposite |

Shared gates (all variants): noul≥0.42, dir_tail≥0.40, tox≤2.0, cap $200, small+large moves, `jev_capped` size.

Dashboard: http://127.0.0.1:8787
