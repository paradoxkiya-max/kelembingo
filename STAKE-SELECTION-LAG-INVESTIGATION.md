# Stake-Selection Lag Investigation

The screenshot shows the home/stake screen rendered, but the 10 ETB and 20 ETB actions can feel unresponsive because the first-load path and stake-tap path compete for the same gateway and database resources.

The first-load path previously awaited all shared components before setting `appReady`, including hidden win, rules, transfer, deposit, withdrawal, registration, and card-selection components. The stake tap then awaited player reconciliation before looking up the active round. At the same time, the homepage statistics listener downloaded every completed round document and repeated that full collection query every 10 seconds. The migrated database currently contains thousands of rounds, so this was unnecessary network transfer, JSON parsing, and database work during the latency-sensitive interaction.

The fix makes only the visible shell components blocking, fetches hidden components in the background with shared in-flight deduplication, and loads registration/card-selection/rules markup on demand when needed. It replaces the completed-round download with a cached `/api/public/stats` aggregate endpoint that returns only three integers and refreshes every 30 seconds. Stake taps now show the loading overlay before reconciliation, so the user receives immediate feedback while the secure wallet/active-round checks continue. Changed Telegram assets use the `stake-1` cache key.

The local regression suite passes JavaScript syntax, public-stats helper shape, stake-selection path invariants, realtime/winner hardening, startup readiness, timer schedule, and mobile timer checks. A production authenticated player-session measurement is still required after deployment; no real-money mutation was used in this audit.
