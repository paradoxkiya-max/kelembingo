# Implementation Plan — Kelem Bingo Security & Reliability Fixes

> Generated from a full 5-agent audit + manual verification of the bot, gateway,
> DB layer, game engine, frontend, and deployment configs.

## Priority summary

| Sev | # | Issue | Status |
|-----|---|-------|--------|
| CRITICAL | C1/C6 | No server-side auth on HTTP API; fake dashboard login | ✅ Implemented |
| CRITICAL | C2 | `end_round` re-pays winners (no payout guard) | ✅ Implemented |
| CRITICAL | C3 | Backup pipeline backs up the wrong DB (live data never saved) | ✅ Implemented |
| CRITICAL | C4 | GatewayClient swallows errors → wallet wipes / silent failed writes | ✅ Implemented |
| CRITICAL | C5 | Committed secrets in render.yaml & code defaults | ✅ Implemented |
| CRITICAL | C7 | NaN/Inf bypasses every amount check | ✅ Implemented |
| HIGH | H1 | Restart orphans `playing` rounds → game stuck, money locked | 🔜 Next |
| HIGH | H5 | Join auto-creates users with free 270 ETB | ✅ Implemented |
| HIGH | H3 | `/cancel` does not end conversations → accidental money moves | ✅ Implemented |
| HIGH | H4 | `banned` flag never enforced | 🔜 Next |
| HIGH | H6 | No bot crash supervisor / OOM risk (6 processes) | 🔜 Next |
| HIGH | H2/H7 | Non-atomic wallet updates; withdraw debit without re-check | 🔜 Next |
| MEDIUM | — | Conversation timeouts, missing bot-content keys, Markdown escaping, admin-online gate for withdraw, event-loop watermark, duplicate-round CAS | 🔜 Next |
| LOW | — | Unused OCR deps, CI tests, placeholder tokens, dead code | 🔜 Next |

---

## ✅ C1/C6 — Server-side auth

**Problem:** Every `/api/*` endpoint is open. `/api/db/*` allows raw read/write of any
document (set any wallet balance, dump all PII). Dashboard login is client-side only.

**Fix:**
- New `POST /api/admin/login` — verifies credentials server-side (env
  `ADMIN_USERNAME`/`ADMIN_PASSWORD`, defaults `paradox`/`12345678`), returns a short-lived
  HMAC-signed token.
- New auth dependency `require_auth` applied to every destructive/admin route:
  `/api/db/*`, `/api/admin/*`, `/api/notify`, `/api/rounds/{id}/end`,
  `/api/rounds/{id}/start`, `/api/rounds/{id}/call`.
- Accepts either `X-Internal-Key: <INTERNAL_API_KEY>` (bots) or
  `Authorization: Bearer <token>` (dashboard).
- Player-facing endpoints stay public (game join/select/cartelas/deposits) since the
  web app needs them — documented as remaining risk, to be closed with Telegram
  WebApp initData verification later.
- Frontend `login.html` + `admin/auth.js` now call the real endpoint and store the
  token; `admin/utils.js` `api()` and `firebase.js` `apiFetch()` attach the token.

**Files:** `api/admin_api.py`, `dashboard/login.html`, `dashboard/js/auth.js`,
`dashboard/js/admin/auth.js`, `dashboard/js/admin/utils.js`, `dashboard/js/firebase.js`,
`dashboard/js/admin/games.js`, `dashboard/js/admin/wipe.js`, `dashboard/js/admin/botcontent.js`,
`dashboard/js/admin/cartelas.js`.

---

## ✅ C2 — end_round payout guard

**Problem:** `end_round` (`game/round_engine.py:647`) allows status `completed` and has no
payout guard → calling it repeatedly re-pays winners.

**Fix:**
- Reject `end_round` unless status is `playing`.
- Set `status: 'completed'` AND `payout_processed: True` in the same update.
- Refuse to pay if `payout_processed` is already true.
- `/api/rounds/{id}/end` (admin) now also verifies winner membership in the round.

**Files:** `game/round_engine.py`, `api/admin_api.py`.

---

## ✅ C3 — Backup pipeline on the right DB (manual-only)

**Problem:** bots service backs up its own *local* sqlite (stale copy). The gateway holds
the live DB but ran no scheduler → every redeploy loses all data. Auto-scheduling every
`BACKUP_INTERVAL_MINUTES` also spammed the backup chat with snapshots.

**Fix (manual-only by design):**
- Backups are saved **only when the admin dashboard asks**: `POST /api/admin/backup/create`
  (already wired to the "Create Backup" button in `dashboard/js/admin/backup.js`).
- `run_gateway.py`: no scheduler thread — removed `start_backup_scheduler()` entirely;
  keeps `auto_restore_on_startup()` (re-seeds only when the DB comes up empty on a fresh deploy).
- `run_bots.py`: removed `run_backup_scheduler()` and the `BackupScheduler` subprocess.
- `render.yaml`: dropped `BACKUP_INTERVAL_MINUTES`.

**Files:** `run_gateway.py`, `run_bots.py`, `render.yaml`, `dashboard/js/admin/backup.js` (existing).

---

## ✅ C4 — GatewayClient error handling + retry

**Problem:** any timeout/5xx returned `exists=False`/empty → `get_or_create_user` then did
`set(merge=False)` wiping real wallets. Writes silently failed.

**Fix:**
- `GatewayDocRef.get`: only treat **HTTP 404** as "not exists". Timeouts/5xx/connection
  errors raise `GatewayUnavailableError` after bounded retries (3 attempts, backoff 0.5/1/2s).
- `set`/`update`/`delete`: retry on retryable errors, re-raise on final failure so the bot
  handler's error path runs instead of silently skipping.
- Add a cache-bypass flag when a get raises so callers can distinguish outage vs missing.

**Files:** `gateway_client.py`, `handlers/user_manager.py` (call sites that must not
`set(merge=False)` on outage).

---

## ✅ C5 — Remove committed secrets

**Problem:** live tokens in `render.yaml`, hardcoded token fallbacks in
`backup_common.py`/`support_common.py`, Firebase private key in `.env`.

**Fix:**
- `render.yaml`: replace token values with `${BOT_TOKEN}`-style dashboard references or
  `your_..._here` placeholders.
- Remove hardcoded backup/support token fallbacks (require env).
- Document rotation steps.

**Files:** `render.yaml`, `backup_common.py`, `support_common.py`.

---

## ✅ C7 — Reject non-finite amounts

**Problem:** `float("nan")`/`float("inf")` pass every `<` comparison, corrupting wallets or
minting infinite balance.

**Fix:** central `finite_amount()` helper; enforce in deposit/withdraw/transfer/bonus in
`bot.py`, `handlers/user_manager.py`, `api/admin_api.py`, and admin credit paths.

**Files:** `handlers/user_manager.py` (helper), `bot.py`, `api/admin_api.py`.

---

## 🔜 H1 — Resume `playing` rounds after restart (NOT implemented yet)

**Problem:** startup monitor only starts loops for `selecting` rounds.

**Fix (planned):** also `_start_game_loop()` for `playing` rounds with no active task; the loop
already reconciles `next_number_at`/`called_numbers` from stored state.

**Files:** `api/admin_api.py`.

---

## ✅ H5 — No free 270 ETB

**Problem:** `join_round_sync` auto-creates users with `play_wallet: 270`.

**Fix:** auto-created users get `play_wallet: 0`, `registered: False` — a new user must
deposit before joining. Existing registered users unaffected.

**Files:** `game/round_engine.py`.

---

## ✅ H3 — Cancel actually cancels

**Problem:** `/cancel` outside a conversation returns `END` that's ignored → stray messages
execute money flows.

**Fix:** add `/cancel` (and `/start`) to every conversation's fallbacks so they return
`ConversationHandler.END`; guard money flows to refuse if the flow was cancelled.

**Files:** `bot.py`.

---

## 🔜 Next (not yet implemented)

- **H4** banned-flag enforcement in every user flow.
- **H6** bot crash supervisor (restart dead children) + reduce process count.
- **H2/H7** atomic wallet mutations (`Increment`/CAS), re-check balance at withdraw debit.
- **M1** conversation timeouts.
- **M2** missing `bot_content` keys → user-facing placeholders.
- **M3** escape user text in support admin notifications.
- **M5** admin-online gate in withdraw flow.
- **M7** event-broadcast watermark (auto-increment) + purge.
- **M8** unique active-round-per-stake constraint.

---

## Deployment notes

New env vars (add on the relevant Render service):
- `ADMIN_USERNAME` (default `paradox`), `ADMIN_PASSWORD` (default `12345678` — **change it**)
- `ADMIN_AUTH_SECRET` (token signing; defaults to `INTERNAL_API_KEY` if unset)
- `BACKUP_CHAT_ID` (recommended: a group where @kelembackupbot is admin, for pinning)
- All bot tokens should move to Render secret env vars; remove literals.

After deploy:
1. Rotate every Telegram bot token listed in the audit (they were committed).
2. Change `ADMIN_PASSWORD`.
3. Click **Create Backup** in the admin dashboard (or run `POST /api/admin/backup/create`) to
   seed a fresh snapshot from the gateway — backups are manual-only.
4. Verify cache hit-rate logs on the bots service.
