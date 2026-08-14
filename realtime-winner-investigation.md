# Realtime and multiple-winner investigation

## Confirmed live evidence

The live gateway at https://kelembingo-sqnv.onrender.com returned HTTP 200 for `/api/rounds?limit=100`. The most recent completed round with a player winner had one winner ID, one scalar winning cartela, `completion_reason=smart_single_winner`, `player_count=2`, `called_count=23`, and `payout_processed=true`. A read-only Supabase query across durable round documents found no record whose `winners` array or `winning_cartela` array contains more than one item.

This means the reported two-cartela winner was not reproduced as a persisted double-winner payout in the current database. It is most likely a client-side perception caused by local bingo detection, stale/duplicate snapshots, or a prior/manual end path rather than the normal game loop’s current stored result. The normal game loop evaluates all players but chooses one deterministic winner; the client’s `checkMyBingo()` only performs local detection and displays `BINGO! Waiting for confirmation...` without submitting an authoritative claim.

## Confirmed lag sources in code

The server sends direct `snapshot` and `query_snapshot` broadcasts after many writes, while every document write also inserts a `system_events` row and the 250ms `_event_broadcast_loop` re-broadcasts those events. This creates duplicate realtime delivery and an extra database read per event. The event loop filters `SystemEvent.id > last_id`, but IDs are random UUID strings, not monotonic cursors, so events can be skipped or delayed unpredictably.

The client performs an initial REST fetch plus Socket.IO subscription for every `onSnapshot`. Collection-level listeners subscribe to the entire collection and do not apply their original filters to incoming `query_snapshot` payloads. The authenticated app permanently subscribes to active rounds for homepage statistics, while the game board subscribes to the current round and also retains a 3-second REST fallback timer. These paths amplify work during frequent round writes.

The client uses a single shared `roundUnsubscribe` slot between card selection and the game board. The game teardown is mostly present, but navigation cleanup is asymmetric and the collection-level statistics listener remains active during play. The card-select screen also has both a document listener and a dedicated `cartela_pool` listener.

## Winner-integrity risks

`RoundEngine.evaluate_winners()` breaks after the first winning cartela for each user, and `_game_loop()` deterministically selects exactly one winner. However, `check_bingo()` returns every winning cartela for a player, and the client locally scans all owned cartelas. The manual/admin `/api/rounds/{round_id}/end` endpoint accepts a list of winner IDs, and `RoundEngine._end_sync()` pays every valid winner in that list. The payout layer filters membership and duplicates but does not independently validate a winner against the called numbers or enforce a single winner. This is a defense-in-depth gap even though the normal game loop currently stores a single winner.

## Implemented on feature branch

The gateway now deduplicates identical snapshot fanout from direct route broadcasts and the durable event bridge. The event bridge consumes `(created_at, id)` with a PostgreSQL index and a startup watermark rather than comparing random UUIDs. The unsafe stale-snapshot fallback number writer was removed; failed serialized calls retry without mutating the round.

The round engine now validates a Bingo claim against current called numbers inside a durable round lock, canonicalizes a player with two winning cartelas to one selected cartela, rejects manual multi-winner end requests, and uses the same authority before payout. The browser sends local Bingo detections to the new authenticated claim endpoint, and loser result screens no longer present themselves as Bingo winners or play the win sound.

The browser bridge now reference-counts rooms, filters collection updates client-side, ignores irrelevant/identical changes, and prevents a slow initial REST fetch from overwriting a newer live snapshot. Homepage-wide active-round statistics are paused during gameplay. Changed scripts and dynamic components are cache-busted for Telegram WebViews. New regression coverage passed for concurrent valid claims, two winning cards on one player, multi-winner rejection, JavaScript syntax, timer schedule, startup readiness, and the SQLite query adapter. The additive live Supabase index migration completed successfully.

## Latency baseline and follow-up optimization

A read-only baseline against the current live deployment returned HTTP 200 but measured approximately 1.36–3.84 seconds for health, 2.04–2.69 seconds for `/api/rounds?limit=2`, and 1.77–4.02 seconds for a small round collection read from the sandbox network. This is a pre-fix baseline, not a post-deployment result. The feature branch additionally reduces active-round discovery from two sequential status queries to one `status in` query and caches the 500-card master catalog for the browser session, avoiding repeated full catalog downloads when a player starts another round.
