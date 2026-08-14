# KelemBingo UI and Payment-Flow Audit

## Scope and conclusion

The audit covered the home/stake screen, card selection, game board, history, wallet, deposit flow, withdrawal flow, page loading, realtime subscriptions, and payment notifications. The dominant lag pattern was not one isolated button bug: several screens were sharing a single event loop and database connection pool while background listeners performed large reads. The supplied withdrawal screenshot also exposed missing submit-state protection and a two-request withdrawal path.

## Findings and fixes

| Area | Finding | Fix status |
|---|---|---|
| Home and stake selection | Hidden components blocked startup; completed-round statistics downloaded the entire completed-round collection every 10 seconds. | Merged in PR #11. The current branch adds the follow-up payment release cache key and keeps the aggregate stats path. |
| Card selection | The picker and master cartela catalog were loaded during the stake-to-selection transition. | Existing realtime branch caches the master catalog and loads the picker on demand. |
| Game board | The board has the existing realtime deduplication, stale REST protection, timer guards, and atomic Bingo claim path. | Previously merged and retained. |
| History | The screen requests up to 50 completed round documents and scans them client-side. This is a secondary hotspot and remains a candidate for a dedicated user-history endpoint. | Identified; not changed in this payment-focused patch. |
| Wallet transactions | Deposits and withdrawals were read without a limit and rendered after every payment. | Limited to the latest 20 per type and cached for 15 seconds; cache is invalidated after a successful payment. |
| Deposit | Config reads could feel slow, and Submit had no duplicate-submit guard or explicit button state. | Config reads are offloaded; modal is load-on-demand; submit is disabled while in flight. The existing transaction-ID duplicate rule remains authoritative. |
| Withdrawal | The client performed validation and creation as two sequential requests, had no in-flight guard, sent no idempotency key, and the API validation route failed open with `ok: true` on unexpected exceptions. | The client now performs one authoritative create request with a stable idempotency key, disables Submit while in flight, and shows progress. Validation now fails closed with `system_error`. |
| Payment notifications | User responses waited for Telegram admin notification delivery after the money operation committed. | Deposit and withdrawal notifications are scheduled in the background after the authoritative transaction returns. |
| UI caching | Telegram WebViews could retain older payment and modal JavaScript. | Payment assets and dynamic components use the `pay-1` cache key. |

## Safety boundaries

No deposit submission, withdrawal creation, payout, wallet debit, or other real-money mutation was executed during this audit. Local syntax, payment hardening, stake-selection performance, realtime/winner, startup, timer, and mobile-timer regressions pass. A live authenticated player-session smoke test remains required after deployment to observe actual Telegram interaction latency and to verify that payment UI success/error states match the production backend.
