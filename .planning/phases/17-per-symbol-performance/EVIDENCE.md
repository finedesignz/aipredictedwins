# Phase 17 EVIDENCE — Per-Symbol / Per-Bot Performance (TUNE-02)

## Provenance

- **Source data:** the LIVE production trade log — Coolify `aipw-postgres` (database `aipw`),
  655 position-closed rows, bots A / B / C / E, read on 2026-07-13 (UTC).
- **Access was SELECT-only. No row, table, index or sequence was written, altered or deleted in
  production.** The prod session was opened with `SET default_transaction_read_only = on` and issued
  nothing but `SELECT`.
- **Why the report was not pointed straight at the prod `DATABASE_URL`:** `src/db.py:44` `get_pool()`
  calls `_bootstrap_schema()`, which executes `src/db_schema.sql` — DDL plus an
  `INSERT INTO bots (...) ON CONFLICT DO NOTHING` — on the FIRST pool creation in the process. Those
  statements are idempotent, but they are **not `SELECT`**. To keep "no prod write" literally true, the
  655 `alpaca_trades` rows and the 4 `bots` rows were read out of prod with plain `SELECT`s and mirrored
  into a local scratch Postgres, and `scripts/symbol_report.py` was run against that byte-for-byte
  mirror. The numbers below are prod's numbers. *(The bootstrap-on-read behaviour is itself a
  REPORTED finding for Phase 18/20 — any script that imports `src.db` writes DDL to whatever database
  `DATABASE_URL` names.)*
- **Reproduce:** `python scripts/symbol_report.py` and `python scripts/symbol_report.py --window 90`
  (the script has no write flag and issues no mutating SQL — pinned by `tests/test_symbol_stats.py`
  cases 20/21).

### `sign_suspect_rows` audit SQL (re-runnable by hand)

    SELECT count(*) FROM alpaca_trades
    WHERE fees IS NULL AND side <> 'buy'
      AND status IN ('closed','stopped','target_hit');

## Headline findings

| Finding | Value | Meaning |
|---|---|---|
| `zero_pnl_total` | **395 / 655 rows (60%)** | `closed` rows with `pnl = 0.0` — the external-exit sentinel (`src/alpaca_orchestrator.py:167-176`). NOT losses, NOT trades. `get_alpaca_accuracy` books every one of them as a **LOSS**. |
| `gross_pnl_rows_total` | **248** | COUNTED rows with NULL `fees` — their `pnl` is GROSS (`src/bot_c/strategy.py:393-395`, `src/trend_strategy.py:172-173`). |
| `null_fees_total` | **643** | Nearly the whole log carries no fee data at all. |
| `null_pnl_total` | **0** | No resolution defects left (Phase 14's backfill held). |
| `sign_suspect_rows` | **0** | No NULL-fee short rows — the sign-inversion class of defect is not present today. |
| Win-rate divergence | **Bot A 33.0% (ours) vs 12.4% (dashboard)** · Bot B 34.1% vs 13.5% | The dashboard number is the naive one. The defect is in the **denominator**, not the sum. |

**This report ranks and annotates; Phase 18 decides.** No quarantine verdict appears anywhere in it.

---

# Run 1 — full history (`python scripts/symbol_report.py`)

# Phase 17 — Per-Symbol Performance (TUNE-02)

- Database: prod-readonly (**SELECT-only** — no rows written)
- Generated: 2026-07-13T01:38:50.837727+00:00
- Window: full history
- min-sample: 5 (cells below it are marked `insufficient` and asterisked — shown, never hidden)
- Rows: 655 position-closed | Cells: 61

This report ranks and annotates; Phase 18 decides.

`sign_suspect_rows` audit SQL (re-runnable by hand):

    SELECT count(*) FROM alpaca_trades WHERE fees IS NULL AND side <> 'buy' AND status IN ('closed','stopped','target_hit')

## Per-(bot, symbol)

| bot | symbol | trades | wins | losses | win_rate | realized_pnl | total_fees | avg_win | avg_loss | expectancy | best | worst | zero_pnl | null_pnl | gross_pnl_rows | sample | quarantined | off_universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C | COIN * | 2 | 0 | 2 | 0.0% | -1,026.17 | 0.00 | 0.00 | -513.09 | -513.09 | -364.05 | -662.13 | 0 | 0 | 2 | insufficient | False | False |
| A | GRT/USD * | 3 | 2 | 1 | 66.7% | -1,038.68 | 0.00 | 58.70 | -1,156.09 | -346.23 | 92.05 | -1,156.09 | 1 | 0 | 3 | insufficient | False | True |
| A | TRUMP/USD | 5 | 0 | 5 | 0.0% | -1,507.19 | 0.00 | 0.00 | -301.44 | -301.44 | -0.84 | -1,225.57 | 0 | 0 | 5 | sufficient | False | True |
| A | SKY/USD | 5 | 2 | 3 | 40.0% | -1,454.98 | 0.00 | 42.62 | -513.41 | -291.00 | 42.66 | -1,538.23 | 0 | 0 | 5 | sufficient | False | True |
| C | META * | 1 | 0 | 1 | 0.0% | -271.04 | 0.00 | 0.00 | -271.04 | -271.04 | -271.04 | -271.04 | 0 | 0 | 1 | insufficient | False | False |
| A | XTZ/USD * | 4 | 2 | 2 | 50.0% | -791.14 | 0.00 | 11.44 | -407.01 | -197.78 | 21.25 | -743.92 | 2 | 0 | 4 | insufficient | False | True |
| C | MSFT * | 1 | 0 | 1 | 0.0% | -189.79 | 0.00 | 0.00 | -189.79 | -189.79 | -189.79 | -189.79 | 0 | 0 | 1 | insufficient | False | False |
| A | BTC/USD | 10 | 0 | 10 | 0.0% | -970.58 | 110.01 | 0.00 | -97.06 | -97.06 | -1.44 | -210.51 | 2 | 0 | 8 | sufficient | False | False |
| A | FIL/USD | 6 | 1 | 5 | 16.7% | -575.46 | 0.00 | 405.96 | -196.28 | -95.91 | 405.96 | -808.05 | 1 | 0 | 6 | sufficient | False | True |
| B | GRT/USD * | 4 | 2 | 2 | 50.0% | -349.87 | 0.00 | 79.78 | -254.72 | -87.47 | 119.95 | -295.50 | 0 | 0 | 4 | insufficient | False | True |
| B | SKY/USD | 6 | 2 | 4 | 33.3% | -484.78 | 0.00 | 27.52 | -134.95 | -80.80 | 41.89 | -524.47 | 0 | 0 | 6 | sufficient | False | True |
| A | AVAX/USD | 13 | 4 | 9 | 30.8% | -983.16 | 43.55 | 204.00 | -199.91 | -75.63 | 593.93 | -951.24 | 1 | 0 | 12 | sufficient | False | False |
| A | SOL/USD | 15 | 5 | 10 | 33.3% | -1,117.39 | 70.20 | 182.67 | -203.07 | -74.49 | 628.09 | -1,102.75 | 0 | 0 | 14 | sufficient | False | False |
| C | TSLA * | 2 | 1 | 1 | 50.0% | -147.42 | 0.00 | 177.28 | -324.70 | -73.71 | 177.28 | -324.70 | 0 | 0 | 2 | insufficient | False | False |
| B | SUSHI/USD * | 4 | 1 | 3 | 25.0% | -286.42 | 0.00 | 4.13 | -96.85 | -71.61 | 4.13 | -146.17 | 0 | 0 | 4 | insufficient | False | True |
| B | TRUMP/USD * | 4 | 0 | 4 | 0.0% | -269.70 | 0.00 | 0.00 | -67.43 | -67.43 | -8.82 | -190.37 | 0 | 0 | 4 | insufficient | False | True |
| A | AAVE/USD * | 2 | 1 | 1 | 50.0% | -117.66 | 0.00 | 2.00 | -119.66 | -58.83 | 2.00 | -119.66 | 0 | 0 | 2 | insufficient | False | True |
| A | ADA/USD | 10 | 5 | 5 | 50.0% | -545.62 | 46.08 | 126.23 | -235.35 | -54.56 | 339.44 | -515.64 | 0 | 0 | 9 | sufficient | False | False |
| B | FIL/USD | 7 | 1 | 6 | 14.3% | -262.29 | 0.00 | 221.82 | -80.69 | -37.47 | 221.82 | -215.42 | 0 | 0 | 7 | sufficient | False | True |
| B | BAT/USD | 5 | 2 | 3 | 40.0% | -187.06 | 0.00 | 32.41 | -83.96 | -37.41 | 33.32 | -161.41 | 0 | 0 | 5 | sufficient | False | True |
| A | SUSHI/USD * | 3 | 1 | 2 | 33.3% | -112.15 | 0.00 | 0.18 | -56.16 | -37.38 | 0.18 | -105.21 | 0 | 0 | 3 | insufficient | False | True |
| B | SOL/USD | 17 | 6 | 11 | 35.3% | -470.30 | 20.98 | 31.10 | -59.72 | -27.66 | 65.41 | -267.03 | 0 | 0 | 16 | sufficient | False | False |
| B | ADA/USD | 10 | 5 | 5 | 50.0% | -244.49 | 8.77 | 33.61 | -82.51 | -24.45 | 70.42 | -167.19 | 0 | 0 | 9 | sufficient | False | False |
| B | ARB/USD * | 3 | 0 | 3 | 0.0% | -68.06 | 0.00 | 0.00 | -22.69 | -22.69 | -7.38 | -46.60 | 0 | 0 | 3 | insufficient | False | True |
| A | ARB/USD * | 3 | 0 | 3 | 0.0% | -59.05 | 0.00 | 0.00 | -19.68 | -19.68 | -6.28 | -45.61 | 0 | 0 | 3 | insufficient | False | True |
| B | BTC/USD | 13 | 2 | 11 | 15.4% | -236.31 | 28.56 | 14.01 | -24.03 | -18.18 | 27.98 | -68.49 | 2 | 0 | 11 | sufficient | False | False |
| B | XTZ/USD * | 4 | 2 | 2 | 50.0% | -69.23 | 0.00 | 29.17 | -63.78 | -17.31 | 36.46 | -103.14 | 1 | 0 | 4 | insufficient | False | True |
| B | ETH/USD * | 4 | 0 | 4 | 0.0% | -59.27 | 0.00 | 0.00 | -14.82 | -14.82 | -2.38 | -30.30 | 0 | 0 | 4 | insufficient | False | True |
| B | AVAX/USD | 13 | 4 | 9 | 30.8% | -170.95 | 7.85 | 71.13 | -50.61 | -13.15 | 143.21 | -166.30 | 1 | 0 | 12 | sufficient | False | False |
| A | LINK/USD * | 3 | 1 | 2 | 33.3% | -38.65 | 0.00 | 47.21 | -42.93 | -12.88 | 47.21 | -81.41 | 1 | 0 | 3 | insufficient | False | True |
| B | AAVE/USD * | 2 | 1 | 1 | 50.0% | -23.46 | 0.00 | 11.25 | -34.71 | -11.73 | 11.25 | -34.71 | 0 | 0 | 2 | insufficient | False | True |
| A | DOT/USD * | 3 | 0 | 3 | 0.0% | -33.57 | 0.00 | 0.00 | -11.19 | -11.19 | -1.98 | -20.49 | 0 | 0 | 3 | insufficient | False | True |
| A | BAT/USD * | 4 | 2 | 2 | 50.0% | -28.86 | 0.00 | 9.08 | -23.51 | -7.22 | 14.97 | -42.51 | 1 | 0 | 4 | insufficient | False | True |
| B | XRP/USD | 16 | 6 | 10 | 37.5% | -69.02 | 14.52 | 58.73 | -42.14 | -4.31 | 208.87 | -119.48 | 1 | 0 | 15 | sufficient | False | False |
| B | UNI/USD | 7 | 4 | 3 | 57.1% | -3.47 | 0.00 | 120.42 | -161.72 | -0.50 | 253.47 | -411.38 | 1 | 0 | 7 | sufficient | False | True |
| A | ETH/USD * | 1 | 0 | 1 | 0.0% | -0.40 | 0.00 | 0.00 | -0.40 | -0.40 | -0.40 | -0.40 | 0 | 0 | 1 | insufficient | False | True |
| B | LDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 67 | 0 | 0 | insufficient | False | True |
| A | LDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 68 | 0 | 0 | insufficient | False | True |
| C | QQQ * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1 | 0 | 0 | insufficient | False | False |
| B | ONDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 29 | 0 | 0 | insufficient | False | True |
| A | ONDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 27 | 0 | 0 | insufficient | False | True |
| A | POL/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 51 | 0 | 0 | insufficient | False | True |
| B | POL/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 60 | 0 | 0 | insufficient | False | True |
| B | RENDER/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 32 | 0 | 0 | insufficient | False | True |
| A | RENDER/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 28 | 0 | 0 | insufficient | False | True |
| B | HYPE/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 6 | 0 | 0 | insufficient | False | True |
| A | HYPE/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 7 | 0 | 0 | insufficient | False | True |
| B | LINK/USD * | 3 | 1 | 2 | 33.3% | 13.19 | 0.00 | 63.33 | -25.07 | 4.40 | 63.33 | -26.54 | 1 | 0 | 3 | insufficient | False | True |
| A | XRP/USD | 14 | 5 | 9 | 35.7% | 89.02 | 57.26 | 246.52 | -127.06 | 6.36 | 847.36 | -362.84 | 1 | 0 | 13 | sufficient | False | False |
| B | LTC/USD * | 1 | 1 | 0 | 100.0% | 10.66 | 0.00 | 10.66 | 0.00 | 10.66 | 10.66 | 10.66 | 0 | 0 | 1 | insufficient | False | True |
| A | LTC/USD * | 1 | 1 | 0 | 100.0% | 14.54 | 0.00 | 14.54 | 0.00 | 14.54 | 14.54 | 14.54 | 0 | 0 | 1 | insufficient | False | True |
| A | UNI/USD | 6 | 3 | 3 | 50.0% | 106.50 | 0.00 | 507.14 | -471.64 | 17.75 | 1,425.66 | -1,356.77 | 1 | 0 | 6 | sufficient | False | True |
| B | DOT/USD * | 4 | 1 | 3 | 25.0% | 88.53 | 0.00 | 175.82 | -29.10 | 22.13 | 175.82 | -66.42 | 0 | 0 | 4 | insufficient | False | True |
| B | CRV/USD | 5 | 4 | 1 | 80.0% | 172.19 | 0.00 | 48.07 | -20.10 | 34.44 | 76.30 | -20.10 | 0 | 0 | 5 | sufficient | False | True |
| A | CRV/USD * | 4 | 3 | 1 | 75.0% | 169.28 | 0.00 | 63.87 | -22.33 | 42.32 | 189.35 | -22.33 | 0 | 0 | 4 | insufficient | False | True |
| C | AAPL * | 1 | 1 | 0 | 100.0% | 164.65 | 0.00 | 164.65 | 0.00 | 164.65 | 164.65 | 164.65 | 1 | 0 | 1 | insufficient | False | False |
| C | AMZN * | 1 | 1 | 0 | 100.0% | 229.95 | 0.00 | 229.95 | 0.00 | 229.95 | 229.95 | 229.95 | 0 | 0 | 1 | insufficient | False | False |
| C | AMD * | 2 | 1 | 1 | 50.0% | 696.76 | 0.00 | 1,129.43 | -432.66 | 348.38 | 1,129.43 | -432.66 | 0 | 0 | 2 | insufficient | False | False |
| C | NVDA * | 1 | 1 | 0 | 100.0% | 380.19 | 0.00 | 380.19 | 0.00 | 380.19 | 380.19 | 380.19 | 0 | 0 | 1 | insufficient | False | False |
| C | MSTR * | 1 | 1 | 0 | 100.0% | 775.04 | 0.00 | 775.04 | 0.00 | 775.04 | 775.04 | 775.04 | 0 | 0 | 1 | insufficient | False | False |
| C | GOOGL * | 1 | 1 | 0 | 100.0% | 1,427.46 | 0.00 | 1,427.46 | 0.00 | 1,427.46 | 1,427.46 | 1,427.46 | 0 | 0 | 1 | insufficient | False | False |

## Roll-up — all bots, per symbol

| bot | symbol | trades | wins | losses | win_rate | realized_pnl | total_fees | avg_win | avg_loss | expectancy | best | worst | zero_pnl | null_pnl | gross_pnl_rows | sample | quarantined | off_universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ALL | COIN * | 2 | 0 | 2 | 0.0% | -1,026.17 | 0.00 | 0.00 | -513.09 | -513.09 | -364.05 | -662.13 | 0 | 0 | 2 | insufficient | False | False |
| ALL | META * | 1 | 0 | 1 | 0.0% | -271.04 | 0.00 | 0.00 | -271.04 | -271.04 | -271.04 | -271.04 | 0 | 0 | 1 | insufficient | False | False |
| ALL | GRT/USD | 7 | 4 | 3 | 57.1% | -1,388.55 | 0.00 | 69.24 | -555.18 | -198.36 | 119.95 | -1,156.09 | 1 | 0 | 7 | sufficient | False | False |
| ALL | TRUMP/USD | 9 | 0 | 9 | 0.0% | -1,776.90 | 0.00 | 0.00 | -197.43 | -197.43 | -0.84 | -1,225.57 | 0 | 0 | 9 | sufficient | False | False |
| ALL | MSFT * | 1 | 0 | 1 | 0.0% | -189.79 | 0.00 | 0.00 | -189.79 | -189.79 | -189.79 | -189.79 | 0 | 0 | 1 | insufficient | False | False |
| ALL | SKY/USD | 11 | 4 | 7 | 36.4% | -1,939.76 | 0.00 | 35.07 | -297.15 | -176.34 | 42.66 | -1,538.23 | 0 | 0 | 11 | sufficient | False | False |
| ALL | XTZ/USD | 8 | 4 | 4 | 50.0% | -860.36 | 0.00 | 20.31 | -235.40 | -107.55 | 36.46 | -743.92 | 3 | 0 | 8 | sufficient | False | False |
| ALL | TSLA * | 2 | 1 | 1 | 50.0% | -147.42 | 0.00 | 177.28 | -324.70 | -73.71 | 177.28 | -324.70 | 0 | 0 | 2 | insufficient | False | False |
| ALL | FIL/USD | 13 | 2 | 11 | 15.4% | -837.74 | 0.00 | 313.89 | -133.23 | -64.44 | 405.96 | -808.05 | 1 | 0 | 13 | sufficient | False | False |
| ALL | SUSHI/USD | 7 | 2 | 5 | 28.6% | -398.57 | 0.00 | 2.15 | -80.58 | -56.94 | 4.13 | -146.17 | 0 | 0 | 7 | sufficient | False | False |
| ALL | BTC/USD | 23 | 2 | 21 | 8.7% | -1,206.90 | 138.57 | 14.01 | -58.81 | -52.47 | 27.98 | -210.51 | 4 | 0 | 19 | sufficient | False | False |
| ALL | SOL/USD | 32 | 11 | 21 | 34.4% | -1,587.69 | 91.19 | 99.99 | -127.98 | -49.62 | 628.09 | -1,102.75 | 0 | 0 | 30 | sufficient | False | False |
| ALL | AVAX/USD | 26 | 8 | 18 | 30.8% | -1,154.12 | 51.40 | 137.56 | -125.26 | -44.39 | 593.93 | -951.24 | 2 | 0 | 24 | sufficient | False | False |
| ALL | ADA/USD | 20 | 10 | 10 | 50.0% | -790.11 | 54.85 | 79.92 | -158.93 | -39.51 | 339.44 | -515.64 | 0 | 0 | 18 | sufficient | False | False |
| ALL | AAVE/USD * | 4 | 2 | 2 | 50.0% | -141.12 | 0.00 | 6.62 | -77.18 | -35.28 | 11.25 | -119.66 | 0 | 0 | 4 | insufficient | False | False |
| ALL | BAT/USD | 9 | 4 | 5 | 44.4% | -215.92 | 0.00 | 20.74 | -59.78 | -23.99 | 33.32 | -161.41 | 1 | 0 | 9 | sufficient | False | False |
| ALL | ARB/USD | 6 | 0 | 6 | 0.0% | -127.11 | 0.00 | 0.00 | -21.19 | -21.19 | -6.28 | -46.60 | 0 | 0 | 6 | sufficient | False | False |
| ALL | ETH/USD | 5 | 0 | 5 | 0.0% | -59.67 | 0.00 | 0.00 | -11.93 | -11.93 | -0.40 | -30.30 | 0 | 0 | 5 | sufficient | False | False |
| ALL | LINK/USD | 6 | 2 | 4 | 33.3% | -25.46 | 0.00 | 55.27 | -34.00 | -4.24 | 63.33 | -81.41 | 2 | 0 | 6 | sufficient | False | False |
| ALL | LDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 135 | 0 | 0 | insufficient | False | False |
| ALL | QQQ * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1 | 0 | 0 | insufficient | False | False |
| ALL | ONDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 56 | 0 | 0 | insufficient | False | False |
| ALL | POL/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 111 | 0 | 0 | insufficient | False | False |
| ALL | RENDER/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 60 | 0 | 0 | insufficient | False | False |
| ALL | HYPE/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 13 | 0 | 0 | insufficient | False | False |
| ALL | XRP/USD | 30 | 11 | 19 | 36.7% | 19.99 | 71.77 | 144.09 | -82.37 | 0.67 | 847.36 | -362.84 | 2 | 0 | 28 | sufficient | False | False |
| ALL | DOT/USD | 7 | 1 | 6 | 14.3% | 54.96 | 0.00 | 175.82 | -20.14 | 7.85 | 175.82 | -66.42 | 0 | 0 | 7 | sufficient | False | False |
| ALL | UNI/USD | 13 | 7 | 6 | 53.8% | 103.03 | 0.00 | 286.16 | -316.68 | 7.93 | 1,425.66 | -1,356.77 | 2 | 0 | 13 | sufficient | False | False |
| ALL | LTC/USD * | 2 | 2 | 0 | 100.0% | 25.20 | 0.00 | 12.60 | 0.00 | 12.60 | 14.54 | 10.66 | 0 | 0 | 2 | insufficient | False | False |
| ALL | CRV/USD | 9 | 7 | 2 | 77.8% | 341.47 | 0.00 | 54.84 | -21.22 | 37.94 | 189.35 | -22.33 | 0 | 0 | 9 | sufficient | False | False |
| ALL | AAPL * | 1 | 1 | 0 | 100.0% | 164.65 | 0.00 | 164.65 | 0.00 | 164.65 | 164.65 | 164.65 | 1 | 0 | 1 | insufficient | False | False |
| ALL | AMZN * | 1 | 1 | 0 | 100.0% | 229.95 | 0.00 | 229.95 | 0.00 | 229.95 | 229.95 | 229.95 | 0 | 0 | 1 | insufficient | False | False |
| ALL | AMD * | 2 | 1 | 1 | 50.0% | 696.76 | 0.00 | 1,129.43 | -432.66 | 348.38 | 1,129.43 | -432.66 | 0 | 0 | 2 | insufficient | False | False |
| ALL | NVDA * | 1 | 1 | 0 | 100.0% | 380.19 | 0.00 | 380.19 | 0.00 | 380.19 | 380.19 | 380.19 | 0 | 0 | 1 | insufficient | False | False |
| ALL | MSTR * | 1 | 1 | 0 | 100.0% | 775.04 | 0.00 | 775.04 | 0.00 | 775.04 | 775.04 | 775.04 | 0 | 0 | 1 | insufficient | False | False |
| ALL | GOOGL * | 1 | 1 | 0 | 100.0% | 1,427.46 | 0.00 | 1,427.46 | 0.00 | 1,427.46 | 1,427.46 | 1,427.46 | 0 | 0 | 1 | insufficient | False | False |

## Roll-up — per bot

| bot | symbol | trades | wins | losses | win_rate | realized_pnl | total_fees | avg_win | avg_loss | expectancy | best | worst | zero_pnl | null_pnl | gross_pnl_rows | sample | quarantined | off_universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | ALL | 115 | 38 | 77 | 33.0% | -8,995.21 | 327.09 | 158.41 | -195.00 | -78.22 | 1,425.66 | -1,538.23 | 192 | 0 | 109 | sufficient | False | False |
| B | ALL | 132 | 45 | 87 | 34.1% | -2,970.13 | 80.68 | 55.96 | -63.09 | -22.50 | 253.47 | -524.47 | 201 | 0 | 126 | sufficient | False | False |
| C | ALL | 13 | 7 | 6 | 53.8% | 2,039.64 | 0.00 | 612.00 | -374.06 | 156.90 | 1,427.46 | -662.13 | 2 | 0 | 13 | sufficient | False | False |

## Ranking (sufficient cells ONLY)

Best by expectancy:

- B CRV/USD: expectancy 34.44 over 5 trades (realized 172.19)
- A UNI/USD: expectancy 17.75 over 6 trades (realized 106.50)
- A XRP/USD: expectancy 6.36 over 14 trades (realized 89.02)
- B UNI/USD: expectancy -0.50 over 7 trades (realized -3.47)
- B XRP/USD: expectancy -4.31 over 16 trades (realized -69.02)

Worst by expectancy:

- A TRUMP/USD: expectancy -301.44 over 5 trades (realized -1,507.19)
- A SKY/USD: expectancy -291.00 over 5 trades (realized -1,454.98)
- A BTC/USD: expectancy -97.06 over 10 trades (realized -970.58)
- A FIL/USD: expectancy -95.91 over 6 trades (realized -575.46)
- B SKY/USD: expectancy -80.80 over 6 trades (realized -484.78)

## Summary — the five loud counters (printed even at zero)

- `null_pnl_total`: 0 — resolution defects (pnl IS NULL on a position-closed row). Excluded from every statistic, never coerced to zero.
- `zero_pnl_total`: 395 — pnl == 0.0 on a position-closed row: the external-exit sentinel (src/alpaca_orchestrator.py:167-176). NOT losses, NOT trades.
- `gross_pnl_rows_total`: 248 — COUNTED rows with NULL fees; their pnl is probably GROSS (src/bot_c/strategy.py:393-395, src/trend_strategy.py:172-173).
- `null_fees_total`: 643 — ALL rows with NULL fees (the wider set, including zero/null-pnl rows).
- `sign_suspect_rows`: 0 — of the NULL-fee rows, those with `side <> 'buy'`.

A non-zero value in ANY of these is a FINDING for Phase 18/20. Phase 17 does not fix it.

*The realized_pnl of cells with gross_pnl_rows > 0 is NOT fee-adjusted (those rows were written with a gross pnl and no fee data); total_fees under-reports drag for those bots.*

*sign_suspect_rows are NULL-fee rows with side <> 'buy': the gross writers compute (current_price - entry) * q with no side handling, so a short's P&L sign is INVERTED while the row is still counted as a win or a loss. A losing short reads as a winner. Non-zero here is a finding of a WORSE class than "gross" and Phase 18 must not rank on those cells.*

## Known limitations

### (a) The count/rate divergence vs get_alpaca_accuracy — the number the dashboard shows

| bot | trades T (symbol_stats) | resolved R (get_alpaca_accuracy) | R - T | zero_pnl + null_pnl | win_rate (ours) | win_rate (naive) |
|---|---|---|---|---|---|---|
| A | 115 | 307 | 192 | 192 | 33.0% | 12.4% |
| B | 132 | 333 | 201 | 201 | 34.1% | 13.5% |
| C | 13 | 15 | 2 | 2 | 53.8% | 46.7% |

Y books every sentinel zero and every NULL as a LOSS (src/db.py:228-229 `losses = resolved - wins`); avg_pnl divides by `resolved`. realized_pnl AGREES with db.get_realized_pnl BY CONSTRUCTION — the defect is in the DENOMINATOR, not the sum. Phase 17 does not change get_alpaca_accuracy.

### (b) 'stopped' and 'target_hit' are EMPTY populations

No writer emits them — every update_alpaca_trade call site writes 'closed' or 'rejected'. Every row in this report is `'closed'`. Do not read "no stop-outs" as a performance fact.

### (c) get_recent_loss_symbols uses a FOURTH status-set spelling

`src/db.py:201` `get_recent_loss_symbols` filters `status IN ('closed','stopped')` — dropping `'target_hit'` — and it is LIVE in the entry cooldown. Reported as a Phase-18/20 finding; Phase 17 changes no bot behavior.


---

# Run 2 — last 90 days (`python scripts/symbol_report.py --window 90`)

# Phase 17 — Per-Symbol Performance (TUNE-02)

- Database: prod-readonly (**SELECT-only** — no rows written)
- Generated: 2026-07-13T01:39:11.554367+00:00
- Window: last 90 days
- min-sample: 5 (cells below it are marked `insufficient` and asterisked — shown, never hidden)
- Rows: 629 position-closed | Cells: 60

This report ranks and annotates; Phase 18 decides.

`sign_suspect_rows` audit SQL (re-runnable by hand):

    SELECT count(*) FROM alpaca_trades WHERE fees IS NULL AND side <> 'buy' AND status IN ('closed','stopped','target_hit')

## Per-(bot, symbol)

| bot | symbol | trades | wins | losses | win_rate | realized_pnl | total_fees | avg_win | avg_loss | expectancy | best | worst | zero_pnl | null_pnl | gross_pnl_rows | sample | quarantined | off_universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C | COIN * | 2 | 0 | 2 | 0.0% | -1,026.17 | 0.00 | 0.00 | -513.09 | -513.09 | -364.05 | -662.13 | 0 | 0 | 2 | insufficient | False | False |
| A | GRT/USD * | 3 | 2 | 1 | 66.7% | -1,038.68 | 0.00 | 58.70 | -1,156.09 | -346.23 | 92.05 | -1,156.09 | 1 | 0 | 3 | insufficient | False | True |
| A | TRUMP/USD | 5 | 0 | 5 | 0.0% | -1,507.19 | 0.00 | 0.00 | -301.44 | -301.44 | -0.84 | -1,225.57 | 0 | 0 | 5 | sufficient | False | True |
| A | SKY/USD | 5 | 2 | 3 | 40.0% | -1,454.98 | 0.00 | 42.62 | -513.41 | -291.00 | 42.66 | -1,538.23 | 0 | 0 | 5 | sufficient | False | True |
| C | META * | 1 | 0 | 1 | 0.0% | -271.04 | 0.00 | 0.00 | -271.04 | -271.04 | -271.04 | -271.04 | 0 | 0 | 1 | insufficient | False | False |
| A | XTZ/USD * | 4 | 2 | 2 | 50.0% | -791.14 | 0.00 | 11.44 | -407.01 | -197.78 | 21.25 | -743.92 | 2 | 0 | 4 | insufficient | False | True |
| C | MSFT * | 1 | 0 | 1 | 0.0% | -189.79 | 0.00 | 0.00 | -189.79 | -189.79 | -189.79 | -189.79 | 0 | 0 | 1 | insufficient | False | False |
| A | BTC/USD | 8 | 0 | 8 | 0.0% | -963.96 | 110.01 | 0.00 | -120.49 | -120.49 | -46.66 | -210.51 | 2 | 0 | 6 | sufficient | False | False |
| A | FIL/USD | 6 | 1 | 5 | 16.7% | -575.46 | 0.00 | 405.96 | -196.28 | -95.91 | 405.96 | -808.05 | 1 | 0 | 6 | sufficient | False | True |
| B | GRT/USD * | 4 | 2 | 2 | 50.0% | -349.87 | 0.00 | 79.78 | -254.72 | -87.47 | 119.95 | -295.50 | 0 | 0 | 4 | insufficient | False | True |
| A | SOL/USD | 13 | 5 | 8 | 38.5% | -1,110.50 | 70.20 | 182.67 | -252.98 | -85.42 | 628.09 | -1,102.75 | 0 | 0 | 12 | sufficient | False | False |
| A | AVAX/USD | 12 | 4 | 8 | 33.3% | -976.60 | 43.55 | 204.00 | -224.07 | -81.38 | 593.93 | -951.24 | 1 | 0 | 11 | sufficient | False | False |
| B | SKY/USD | 6 | 2 | 4 | 33.3% | -484.78 | 0.00 | 27.52 | -134.95 | -80.80 | 41.89 | -524.47 | 0 | 0 | 6 | sufficient | False | True |
| C | TSLA * | 2 | 1 | 1 | 50.0% | -147.42 | 0.00 | 177.28 | -324.70 | -73.71 | 177.28 | -324.70 | 0 | 0 | 2 | insufficient | False | False |
| B | SUSHI/USD * | 4 | 1 | 3 | 25.0% | -286.42 | 0.00 | 4.13 | -96.85 | -71.61 | 4.13 | -146.17 | 0 | 0 | 4 | insufficient | False | True |
| B | TRUMP/USD * | 4 | 0 | 4 | 0.0% | -269.70 | 0.00 | 0.00 | -67.43 | -67.43 | -8.82 | -190.37 | 0 | 0 | 4 | insufficient | False | True |
| A | ADA/USD | 9 | 5 | 4 | 55.6% | -534.37 | 46.08 | 126.23 | -291.38 | -59.37 | 339.44 | -515.64 | 0 | 0 | 8 | sufficient | False | False |
| A | AAVE/USD * | 2 | 1 | 1 | 50.0% | -117.66 | 0.00 | 2.00 | -119.66 | -58.83 | 2.00 | -119.66 | 0 | 0 | 2 | insufficient | False | True |
| B | FIL/USD | 7 | 1 | 6 | 14.3% | -262.29 | 0.00 | 221.82 | -80.69 | -37.47 | 221.82 | -215.42 | 0 | 0 | 7 | sufficient | False | True |
| B | BAT/USD | 5 | 2 | 3 | 40.0% | -187.06 | 0.00 | 32.41 | -83.96 | -37.41 | 33.32 | -161.41 | 0 | 0 | 5 | sufficient | False | True |
| A | SUSHI/USD * | 3 | 1 | 2 | 33.3% | -112.15 | 0.00 | 0.18 | -56.16 | -37.38 | 0.18 | -105.21 | 0 | 0 | 3 | insufficient | False | True |
| B | SOL/USD | 14 | 5 | 9 | 35.7% | -434.90 | 20.98 | 36.15 | -68.41 | -31.06 | 65.41 | -267.03 | 0 | 0 | 13 | sufficient | False | False |
| B | ETH/USD * | 2 | 0 | 2 | 0.0% | -51.53 | 0.00 | 0.00 | -25.77 | -25.77 | -21.23 | -30.30 | 0 | 0 | 2 | insufficient | False | True |
| B | ARB/USD * | 3 | 0 | 3 | 0.0% | -68.06 | 0.00 | 0.00 | -22.69 | -22.69 | -7.38 | -46.60 | 0 | 0 | 3 | insufficient | False | True |
| B | ADA/USD | 9 | 5 | 4 | 55.6% | -177.24 | 8.77 | 33.61 | -86.32 | -19.69 | 70.42 | -167.19 | 0 | 0 | 8 | sufficient | False | False |
| A | ARB/USD * | 3 | 0 | 3 | 0.0% | -59.05 | 0.00 | 0.00 | -19.68 | -19.68 | -6.28 | -45.61 | 0 | 0 | 3 | insufficient | False | True |
| B | BTC/USD | 10 | 1 | 9 | 10.0% | -195.95 | 28.56 | 27.98 | -24.88 | -19.60 | 27.98 | -68.49 | 2 | 0 | 8 | sufficient | False | False |
| B | XTZ/USD * | 4 | 2 | 2 | 50.0% | -69.23 | 0.00 | 29.17 | -63.78 | -17.31 | 36.46 | -103.14 | 1 | 0 | 4 | insufficient | False | True |
| A | LINK/USD * | 2 | 1 | 1 | 50.0% | -34.21 | 0.00 | 47.21 | -81.41 | -17.10 | 47.21 | -81.41 | 1 | 0 | 2 | insufficient | False | True |
| B | AAVE/USD * | 2 | 1 | 1 | 50.0% | -23.46 | 0.00 | 11.25 | -34.71 | -11.73 | 11.25 | -34.71 | 0 | 0 | 2 | insufficient | False | True |
| A | DOT/USD * | 2 | 0 | 2 | 0.0% | -22.46 | 0.00 | 0.00 | -11.23 | -11.23 | -1.98 | -20.49 | 0 | 0 | 2 | insufficient | False | True |
| B | AVAX/USD | 12 | 4 | 8 | 33.3% | -131.71 | 7.85 | 71.13 | -52.03 | -10.98 | 143.21 | -166.30 | 1 | 0 | 11 | sufficient | False | False |
| A | BAT/USD * | 4 | 2 | 2 | 50.0% | -28.86 | 0.00 | 9.08 | -23.51 | -7.22 | 14.97 | -42.51 | 1 | 0 | 4 | insufficient | False | True |
| B | XRP/USD | 13 | 5 | 8 | 38.5% | -51.12 | 14.52 | 69.63 | -49.91 | -3.93 | 208.87 | -119.48 | 1 | 0 | 12 | sufficient | False | False |
| B | UNI/USD | 7 | 4 | 3 | 57.1% | -3.47 | 0.00 | 120.42 | -161.72 | -0.50 | 253.47 | -411.38 | 1 | 0 | 7 | sufficient | False | True |
| B | LDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 67 | 0 | 0 | insufficient | False | True |
| A | LDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 68 | 0 | 0 | insufficient | False | True |
| C | QQQ * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1 | 0 | 0 | insufficient | False | False |
| B | ONDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 29 | 0 | 0 | insufficient | False | True |
| A | ONDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 27 | 0 | 0 | insufficient | False | True |
| A | POL/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 51 | 0 | 0 | insufficient | False | True |
| B | POL/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 60 | 0 | 0 | insufficient | False | True |
| B | RENDER/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 32 | 0 | 0 | insufficient | False | True |
| A | RENDER/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 28 | 0 | 0 | insufficient | False | True |
| B | HYPE/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 6 | 0 | 0 | insufficient | False | True |
| A | HYPE/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 7 | 0 | 0 | insufficient | False | True |
| A | XRP/USD | 12 | 5 | 7 | 41.7% | 92.73 | 57.26 | 246.52 | -162.84 | 7.73 | 847.36 | -362.84 | 1 | 0 | 11 | sufficient | False | False |
| B | LTC/USD * | 1 | 1 | 0 | 100.0% | 10.66 | 0.00 | 10.66 | 0.00 | 10.66 | 10.66 | 10.66 | 0 | 0 | 1 | insufficient | False | True |
| A | LTC/USD * | 1 | 1 | 0 | 100.0% | 14.54 | 0.00 | 14.54 | 0.00 | 14.54 | 14.54 | 14.54 | 0 | 0 | 1 | insufficient | False | True |
| A | UNI/USD | 6 | 3 | 3 | 50.0% | 106.50 | 0.00 | 507.14 | -471.64 | 17.75 | 1,425.66 | -1,356.77 | 1 | 0 | 6 | sufficient | False | True |
| B | LINK/USD * | 2 | 1 | 1 | 50.0% | 39.73 | 0.00 | 63.33 | -23.60 | 19.86 | 63.33 | -23.60 | 1 | 0 | 2 | insufficient | False | True |
| B | CRV/USD | 5 | 4 | 1 | 80.0% | 172.19 | 0.00 | 48.07 | -20.10 | 34.44 | 76.30 | -20.10 | 0 | 0 | 5 | sufficient | False | True |
| A | CRV/USD * | 4 | 3 | 1 | 75.0% | 169.28 | 0.00 | 63.87 | -22.33 | 42.32 | 189.35 | -22.33 | 0 | 0 | 4 | insufficient | False | True |
| B | DOT/USD * | 3 | 1 | 2 | 33.3% | 154.96 | 0.00 | 175.82 | -10.43 | 51.65 | 175.82 | -18.03 | 0 | 0 | 3 | insufficient | False | True |
| C | AAPL * | 1 | 1 | 0 | 100.0% | 164.65 | 0.00 | 164.65 | 0.00 | 164.65 | 164.65 | 164.65 | 1 | 0 | 1 | insufficient | False | False |
| C | AMZN * | 1 | 1 | 0 | 100.0% | 229.95 | 0.00 | 229.95 | 0.00 | 229.95 | 229.95 | 229.95 | 0 | 0 | 1 | insufficient | False | False |
| C | AMD * | 2 | 1 | 1 | 50.0% | 696.76 | 0.00 | 1,129.43 | -432.66 | 348.38 | 1,129.43 | -432.66 | 0 | 0 | 2 | insufficient | False | False |
| C | NVDA * | 1 | 1 | 0 | 100.0% | 380.19 | 0.00 | 380.19 | 0.00 | 380.19 | 380.19 | 380.19 | 0 | 0 | 1 | insufficient | False | False |
| C | MSTR * | 1 | 1 | 0 | 100.0% | 775.04 | 0.00 | 775.04 | 0.00 | 775.04 | 775.04 | 775.04 | 0 | 0 | 1 | insufficient | False | False |
| C | GOOGL * | 1 | 1 | 0 | 100.0% | 1,427.46 | 0.00 | 1,427.46 | 0.00 | 1,427.46 | 1,427.46 | 1,427.46 | 0 | 0 | 1 | insufficient | False | False |

## Roll-up — all bots, per symbol

| bot | symbol | trades | wins | losses | win_rate | realized_pnl | total_fees | avg_win | avg_loss | expectancy | best | worst | zero_pnl | null_pnl | gross_pnl_rows | sample | quarantined | off_universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ALL | COIN * | 2 | 0 | 2 | 0.0% | -1,026.17 | 0.00 | 0.00 | -513.09 | -513.09 | -364.05 | -662.13 | 0 | 0 | 2 | insufficient | False | False |
| ALL | META * | 1 | 0 | 1 | 0.0% | -271.04 | 0.00 | 0.00 | -271.04 | -271.04 | -271.04 | -271.04 | 0 | 0 | 1 | insufficient | False | False |
| ALL | GRT/USD | 7 | 4 | 3 | 57.1% | -1,388.55 | 0.00 | 69.24 | -555.18 | -198.36 | 119.95 | -1,156.09 | 1 | 0 | 7 | sufficient | False | False |
| ALL | TRUMP/USD | 9 | 0 | 9 | 0.0% | -1,776.90 | 0.00 | 0.00 | -197.43 | -197.43 | -0.84 | -1,225.57 | 0 | 0 | 9 | sufficient | False | False |
| ALL | MSFT * | 1 | 0 | 1 | 0.0% | -189.79 | 0.00 | 0.00 | -189.79 | -189.79 | -189.79 | -189.79 | 0 | 0 | 1 | insufficient | False | False |
| ALL | SKY/USD | 11 | 4 | 7 | 36.4% | -1,939.76 | 0.00 | 35.07 | -297.15 | -176.34 | 42.66 | -1,538.23 | 0 | 0 | 11 | sufficient | False | False |
| ALL | XTZ/USD | 8 | 4 | 4 | 50.0% | -860.36 | 0.00 | 20.31 | -235.40 | -107.55 | 36.46 | -743.92 | 3 | 0 | 8 | sufficient | False | False |
| ALL | TSLA * | 2 | 1 | 1 | 50.0% | -147.42 | 0.00 | 177.28 | -324.70 | -73.71 | 177.28 | -324.70 | 0 | 0 | 2 | insufficient | False | False |
| ALL | FIL/USD | 13 | 2 | 11 | 15.4% | -837.74 | 0.00 | 313.89 | -133.23 | -64.44 | 405.96 | -808.05 | 1 | 0 | 13 | sufficient | False | False |
| ALL | BTC/USD | 18 | 1 | 17 | 5.6% | -1,159.91 | 138.57 | 27.98 | -69.88 | -64.44 | 27.98 | -210.51 | 4 | 0 | 14 | sufficient | False | False |
| ALL | SOL/USD | 27 | 10 | 17 | 37.0% | -1,545.40 | 91.19 | 109.41 | -155.27 | -57.24 | 628.09 | -1,102.75 | 0 | 0 | 25 | sufficient | False | False |
| ALL | SUSHI/USD | 7 | 2 | 5 | 28.6% | -398.57 | 0.00 | 2.15 | -80.58 | -56.94 | 4.13 | -146.17 | 0 | 0 | 7 | sufficient | False | False |
| ALL | AVAX/USD | 24 | 8 | 16 | 33.3% | -1,108.32 | 51.40 | 137.56 | -138.05 | -46.18 | 593.93 | -951.24 | 2 | 0 | 22 | sufficient | False | False |
| ALL | ADA/USD | 18 | 10 | 8 | 55.6% | -711.61 | 54.85 | 79.92 | -188.85 | -39.53 | 339.44 | -515.64 | 0 | 0 | 16 | sufficient | False | False |
| ALL | AAVE/USD * | 4 | 2 | 2 | 50.0% | -141.12 | 0.00 | 6.62 | -77.18 | -35.28 | 11.25 | -119.66 | 0 | 0 | 4 | insufficient | False | False |
| ALL | ETH/USD * | 2 | 0 | 2 | 0.0% | -51.53 | 0.00 | 0.00 | -25.77 | -25.77 | -21.23 | -30.30 | 0 | 0 | 2 | insufficient | False | False |
| ALL | BAT/USD | 9 | 4 | 5 | 44.4% | -215.92 | 0.00 | 20.74 | -59.78 | -23.99 | 33.32 | -161.41 | 1 | 0 | 9 | sufficient | False | False |
| ALL | ARB/USD | 6 | 0 | 6 | 0.0% | -127.11 | 0.00 | 0.00 | -21.19 | -21.19 | -6.28 | -46.60 | 0 | 0 | 6 | sufficient | False | False |
| ALL | LDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 135 | 0 | 0 | insufficient | False | False |
| ALL | QQQ * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1 | 0 | 0 | insufficient | False | False |
| ALL | ONDO/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 56 | 0 | 0 | insufficient | False | False |
| ALL | POL/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 111 | 0 | 0 | insufficient | False | False |
| ALL | RENDER/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 60 | 0 | 0 | insufficient | False | False |
| ALL | HYPE/USD * | 0 | 0 | 0 | 0.0% | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 13 | 0 | 0 | insufficient | False | False |
| ALL | LINK/USD * | 4 | 2 | 2 | 50.0% | 5.52 | 0.00 | 55.27 | -52.51 | 1.38 | 63.33 | -81.41 | 2 | 0 | 4 | insufficient | False | False |
| ALL | XRP/USD | 25 | 10 | 15 | 40.0% | 41.61 | 71.77 | 158.08 | -102.61 | 1.66 | 847.36 | -362.84 | 2 | 0 | 23 | sufficient | False | False |
| ALL | UNI/USD | 13 | 7 | 6 | 53.8% | 103.03 | 0.00 | 286.16 | -316.68 | 7.93 | 1,425.66 | -1,356.77 | 2 | 0 | 13 | sufficient | False | False |
| ALL | LTC/USD * | 2 | 2 | 0 | 100.0% | 25.20 | 0.00 | 12.60 | 0.00 | 12.60 | 14.54 | 10.66 | 0 | 0 | 2 | insufficient | False | False |
| ALL | DOT/USD | 5 | 1 | 4 | 20.0% | 132.49 | 0.00 | 175.82 | -10.83 | 26.50 | 175.82 | -20.49 | 0 | 0 | 5 | sufficient | False | False |
| ALL | CRV/USD | 9 | 7 | 2 | 77.8% | 341.47 | 0.00 | 54.84 | -21.22 | 37.94 | 189.35 | -22.33 | 0 | 0 | 9 | sufficient | False | False |
| ALL | AAPL * | 1 | 1 | 0 | 100.0% | 164.65 | 0.00 | 164.65 | 0.00 | 164.65 | 164.65 | 164.65 | 1 | 0 | 1 | insufficient | False | False |
| ALL | AMZN * | 1 | 1 | 0 | 100.0% | 229.95 | 0.00 | 229.95 | 0.00 | 229.95 | 229.95 | 229.95 | 0 | 0 | 1 | insufficient | False | False |
| ALL | AMD * | 2 | 1 | 1 | 50.0% | 696.76 | 0.00 | 1,129.43 | -432.66 | 348.38 | 1,129.43 | -432.66 | 0 | 0 | 2 | insufficient | False | False |
| ALL | NVDA * | 1 | 1 | 0 | 100.0% | 380.19 | 0.00 | 380.19 | 0.00 | 380.19 | 380.19 | 380.19 | 0 | 0 | 1 | insufficient | False | False |
| ALL | MSTR * | 1 | 1 | 0 | 100.0% | 775.04 | 0.00 | 775.04 | 0.00 | 775.04 | 775.04 | 775.04 | 0 | 0 | 1 | insufficient | False | False |
| ALL | GOOGL * | 1 | 1 | 0 | 100.0% | 1,427.46 | 0.00 | 1,427.46 | 0.00 | 1,427.46 | 1,427.46 | 1,427.46 | 0 | 0 | 1 | insufficient | False | False |

## Roll-up — per bot

| bot | symbol | trades | wins | losses | win_rate | realized_pnl | total_fees | avg_win | avg_loss | expectancy | best | worst | zero_pnl | null_pnl | gross_pnl_rows | sample | quarantined | off_universe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | ALL | 104 | 38 | 66 | 36.5% | -8,944.22 | 327.09 | 158.41 | -226.73 | -86.00 | 1,425.66 | -1,538.23 | 192 | 0 | 98 | sufficient | False | False |
| B | ALL | 117 | 42 | 75 | 35.9% | -2,669.26 | 80.68 | 59.72 | -69.03 | -22.81 | 253.47 | -524.47 | 201 | 0 | 111 | sufficient | False | False |
| C | ALL | 13 | 7 | 6 | 53.8% | 2,039.64 | 0.00 | 612.00 | -374.06 | 156.90 | 1,427.46 | -662.13 | 2 | 0 | 13 | sufficient | False | False |

## Ranking (sufficient cells ONLY)

Best by expectancy:

- B CRV/USD: expectancy 34.44 over 5 trades (realized 172.19)
- A UNI/USD: expectancy 17.75 over 6 trades (realized 106.50)
- A XRP/USD: expectancy 7.73 over 12 trades (realized 92.73)
- B UNI/USD: expectancy -0.50 over 7 trades (realized -3.47)
- B XRP/USD: expectancy -3.93 over 13 trades (realized -51.12)

Worst by expectancy:

- A TRUMP/USD: expectancy -301.44 over 5 trades (realized -1,507.19)
- A SKY/USD: expectancy -291.00 over 5 trades (realized -1,454.98)
- A BTC/USD: expectancy -120.49 over 8 trades (realized -963.96)
- A FIL/USD: expectancy -95.91 over 6 trades (realized -575.46)
- A SOL/USD: expectancy -85.42 over 13 trades (realized -1,110.50)

## Summary — the five loud counters (printed even at zero)

- `null_pnl_total`: 0 — resolution defects (pnl IS NULL on a position-closed row). Excluded from every statistic, never coerced to zero.
- `zero_pnl_total`: 395 — pnl == 0.0 on a position-closed row: the external-exit sentinel (src/alpaca_orchestrator.py:167-176). NOT losses, NOT trades.
- `gross_pnl_rows_total`: 222 — COUNTED rows with NULL fees; their pnl is probably GROSS (src/bot_c/strategy.py:393-395, src/trend_strategy.py:172-173).
- `null_fees_total`: 617 — ALL rows with NULL fees (the wider set, including zero/null-pnl rows).
- `sign_suspect_rows`: 0 — of the NULL-fee rows, those with `side <> 'buy'`.

A non-zero value in ANY of these is a FINDING for Phase 18/20. Phase 17 does not fix it.

*The realized_pnl of cells with gross_pnl_rows > 0 is NOT fee-adjusted (those rows were written with a gross pnl and no fee data); total_fees under-reports drag for those bots.*

*sign_suspect_rows are NULL-fee rows with side <> 'buy': the gross writers compute (current_price - entry) * q with no side handling, so a short's P&L sign is INVERTED while the row is still counted as a win or a loss. A losing short reads as a winner. Non-zero here is a finding of a WORSE class than "gross" and Phase 18 must not rank on those cells.*

## Known limitations

### (a) The count/rate divergence vs get_alpaca_accuracy — the number the dashboard shows

| bot | trades T (symbol_stats) | resolved R (get_alpaca_accuracy) | R - T | zero_pnl + null_pnl | win_rate (ours) | win_rate (naive) |
|---|---|---|---|---|---|---|
| A | 104 | 307 | 203 | 192 | 36.5% | 12.4% |
| B | 117 | 333 | 216 | 201 | 35.9% | 13.5% |
| C | 13 | 15 | 2 | 2 | 53.8% | 46.7% |

Y books every sentinel zero and every NULL as a LOSS (src/db.py:228-229 `losses = resolved - wins`); avg_pnl divides by `resolved`. realized_pnl AGREES with db.get_realized_pnl BY CONSTRUCTION — the defect is in the DENOMINATOR, not the sum. Phase 17 does not change get_alpaca_accuracy.

### (b) 'stopped' and 'target_hit' are EMPTY populations

No writer emits them — every update_alpaca_trade call site writes 'closed' or 'rejected'. Every row in this report is `'closed'`. Do not read "no stop-outs" as a performance fact.

### (c) get_recent_loss_symbols uses a FOURTH status-set spelling

`src/db.py:201` `get_recent_loss_symbols` filters `status IN ('closed','stopped')` — dropping `'target_hit'` — and it is LIVE in the entry cooldown. Reported as a Phase-18/20 finding; Phase 17 changes no bot behavior.
