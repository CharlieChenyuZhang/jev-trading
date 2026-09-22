# Experiment

- **name:** `jev_paper_G_primary_fade_fix_24h_2026_09_22`
- **iteration:** 10
- **primary (crypto):** `exp_G_regime_mr`
- **primary_by_market:** `{'crypto': 'exp_G_regime_mr', 'stock': 'exp_A_short'}`
- **goal:** G_primary_fade_fix_24h: crypto primary = exp_G_regime_mr WITH fade applied on primary path (bugfix: prior G_primary_24h never called apply_regime_fade on primary so G≡A). Stock primary stays exp_A_short. A–H shadows unchanged. Fresh $10k books.
- **lessons_ref:** docs/strategy-iteration-log.md — iteration 10 G primary fade fix

Paper only. See `docs/strategy-iteration-log.md`.
