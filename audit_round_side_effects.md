# Round Side-Effect Audit Findings

## Verified high-risk interactions

1. The React GameBoard contains an auto-claim effect. When any locally loaded cartela completes according to `called_numbers`, it POSTs `/api/rounds/{round_id}/claim-bingo`. In the restored targeted engine, this is a competing winner writer: a client cartela can claim before the gateway evaluates the persisted `target_winner`.

2. The gateway winner loop evaluates every valid winner after each call and chooses through `choose_single_winner`. In the restored targeted model, a target cartela can complete on the target call while another cartela also completes; generic tie selection can choose a different cartela unless the persisted target winner is preferred when valid.

3. The gateway has a process-local `_active_game_tasks` guard only. A second Render gateway instance can resume the same `playing` round because the monitor sees the database status but has no durable distributed lease. The database idempotency lock prevents duplicate array appends for the same expected count, but duplicate workers still perform reads, target selection, broadcasts, and terminal checks.

4. Direct `broadcast_event('rounds', round_id)` calls occur immediately after round writes, while `_event_broadcast_loop()` also polls `system_events` and broadcasts the same committed writes. `_last_broadcast_fingerprints` suppresses some duplicates within one process, but the duplicate database reads and cross-instance fanout remain unnecessary load.

5. The playing loop can write `next_number_at = now + 5s` through a plain update whenever a stale or expired deadline is observed. Competing workers can re-anchor this field repeatedly, extending the visible timer and moving the call schedule outside the intended plan.

6. The GameBoard winner effect navigates home when a completed snapshot has no winner ID or winning cartela yet. A partial terminal snapshot can therefore cause a premature navigation instead of waiting for the authoritative terminal fields.

7. The winner announcement effect creates a new announcement object on every qualifying round snapshot even when the winner key is unchanged. This causes avoidable rerenders, although the card fetch and countdown effects are keyed by the stable winner key.

## Current safeguards that already work

The database `round-call:{round_id}:{expected_count}` idempotency key and `round:{round_id}` lock serialize number appends. `observeRound` fingerprints snapshots, and `complete_round`/`end_round` use durable authority for one winner and one payout. These should be preserved.
