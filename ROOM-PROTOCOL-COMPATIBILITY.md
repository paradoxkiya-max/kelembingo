# KelemBingo Reference-Inspired Room Protocol Contract

This is an additive rebuild. The public `bingo-ethiopia` repository remains untouched in `/home/ubuntu/bingo-ethiopia-reference`, and KelemBingo’s pre-change baseline is preserved by the local branch `backup/pre-room-protocol-c907b94` and tag `pre-room-protocol-c907b94`.

## Preserved invariants

The protocol must preserve existing users, wallets, transactions, rounds, cartela documents, Telegram bot processes, admin APIs, database tables/documents, payout/refund logic, two-cartela simultaneous limit, 45-second selection duration, five-second number cadence, and the current REST endpoints. The old REST select/unselect path remains available as a rollback and non-WebSocket fallback until the new path passes production validation.

## Additive realtime events

A client joins a round room with an authenticated player token and receives one authoritative `room_state` snapshot. During selection it sends `room_intent` messages containing `round_id`, `user_id`, `intent_id`, `action` (`select` or `unselect`), and `cartela_number`. The server serializes intents per round, applies the existing durable wallet/pending transaction, and returns `room_ack` with the same `intent_id`, a monotonic `pending_revision`, the authoritative player selection, wallet balance, pool state, round status, and absolute deadlines.

The server broadcasts `room_state` after committed state changes and broadcasts `round_started`, `number_called`, and `round_ended` from the existing authoritative game loop. A late or post-join intent returns an explicit acknowledgement error and the authoritative state; it does not remain in the client queue.

## Client rules

The client updates the visible selection optimistically for responsiveness, but authoritative acknowledgements reconcile it. Each intent is idempotent by `intent_id`. The client may issue unlimited select/deselect intents while the server reports `status: selecting` and the absolute deadline has not passed. The only simultaneous-card limit is the existing business rule of two cards. When the server reports a joined player or `status: playing`, the client aborts all unsent intents, clears the old room session, primes GameBoard with the authoritative snapshot, and navigates exactly once.

The client never creates or advances the timer. It renders `selection_deadline`, `game_started_at`, and `next_number_at` using server-clock compensation. The gateway continues the round lifecycle when no client is connected.

## Rollback rule

Until the new protocol is validated, Cartela Selection can fall back to the existing REST mutation path. No database migration is required for the first implementation. If the room protocol fails, disabling the feature flag returns traffic to the existing REST/Socket.IO snapshot flow without restoring or altering production data.
