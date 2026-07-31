# Fix: "No Player" Toaster, Remove 5s Grace Killer, Change 35s → 45s Timer

## Problem Summary

Three issues reported on stake 20 with ~10 cards:

1. **"No players" toaster then redirect to card selection** — When a round transitions to `playing` state, the frontend checks `player_count` and if it reads `0` (due to the `Increment` dict bug or race condition), it cancels the round, shows "No players in this round", and restarts card selection. This creates a loop.

2. **5-second grace period "killer"** — After the selection timer expires, the backend (`_game_loop` in `admin_api.py` line 224) adds an extra `+ timedelta(seconds=5)` delay before starting the game. If `player_count` is still `0` after that grace, it sleeps **another** 5 seconds (line 243), totalling 10 seconds of dead time. The user wants this removed.

3. **Selection timer 35s → 45s** — `SELECTION_DURATION` is defined as `35` in both backend (`round_engine.py` line 24) and frontend (`state.js` line 22). The user wants it changed to `45`.

## Root Cause Analysis

### "No Players" Bug
The `player_count` field uses `Increment(len(cartela_numbers))` in `join_round_sync` (line 275). When the round is read back, `player_count` could appear as `{'__type': 'increment', 'value': N}` or `{'_type': 'Increment', 'value': N}` instead of a plain integer — especially after the REST bridge processes it. The frontend sees this dict as falsy/0 and triggers the "no players" path.

> [!IMPORTANT]
> The `normalize_doc` fix from the previous commit should fix this for `to_dict()` calls, but the frontend also reads `player_count` directly from Firestore snapshots. We need to ensure the backend always stores `player_count` as a resolved integer, not an Increment dict.

### 5-Second Grace Period
The `_game_loop` has two 5-second delays:
- Line 224: `dl_dt + timedelta(seconds=5)` — waits 5s past the deadline before even checking
- Line 243: `await asyncio.sleep(5)` — waits another 5s if no players found

This means after the 35s selection timer, users wait up to 10 extra seconds before the game starts. The user wants this removed entirely.

## Proposed Changes

### Backend: Round Engine & Game Loop

#### [MODIFY] [round_engine.py](file:///e:/paradox/bingo/game/round_engine.py)

1. **Line 24**: Change `SELECTION_DURATION = 35` → `SELECTION_DURATION = 45`
2. **Line 275**: After `Increment(len(cartela_numbers))`, also store a resolved `player_count_resolved` int, or better: re-read the round and store the actual resolved count.

Actually, the cleaner fix: In `join_round_sync`, after the atomic `Increment` update, ensure the round document `player_count` is always an integer. The `Increment` class handle in `firestore_db.py` already resolves to `curr_val + inc.value`, so `player_count` in the DB should already be an integer. The bug is likely in the REST bridge path (Gateway → `_type: Increment` serialization).

#### [MODIFY] [admin_api.py](file:///e:/paradox/bingo/api/admin_api.py)

1. **Line 224**: Remove the `+ timedelta(seconds=5)` grace period — change to just `dl_dt`
2. **Lines 242-278**: Remove the second 5-second sleep and the recheck. If no players at deadline, cancel immediately.

---

### Frontend: State & Game Board

#### [MODIFY] [state.js](file:///e:/paradox/bingo/dashboard/js/state.js)

1. **Line 22**: Change `SELECTION_DURATION = 35` → `SELECTION_DURATION = 45`

#### [MODIFY] [game-board.js](file:///e:/paradox/bingo/dashboard/js/game-board.js)

1. **Line 95 comment**: Update `35s` → `45s` in comment

#### [MODIFY] [card-select.js](file:///e:/paradox/bingo/dashboard/js/card-select.js)

1. **Lines 73-86 & 327-345**: Add defensive `player_count` parsing — if it's a dict (Increment artifact), extract `.value`

---

### Database Layer: Ensure Clean Integers

#### [MODIFY] [firestore_db.py](file:///e:/paradox/bingo/firestore_db.py)

1. In `DocumentRef.update`, after resolving an `Increment`, ensure the stored value is always `float()` or `int()`, never a dict.

#### [MODIFY] [gateway_client.py](file:///e:/paradox/bingo/gateway_client.py)

1. In `GatewayDocSnapshot.__init__`, the `normalize_doc` call should already handle this. Verify the PATCH endpoint in `admin_api.py` correctly resolves `_type: Increment` dicts to actual `Increment()` objects.

## Verification Plan

### Automated Tests
- Run `python test_bingo.py` — all 49 tests should pass
- Verify `SELECTION_DURATION` is `45` in both backend and frontend

### Manual Verification
- Deploy to Render, start a stake-20 game, join with multiple cards
- Verify selection timer shows 45s
- Verify game starts immediately after timer expires (no 5s delay)
- Verify `player_count` displays correctly (not as dict)
