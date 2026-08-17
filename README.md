# Kelem Bingo

Real-time multiplayer Telegram Bingo platform. Players open a Telegram Mini App
to join rounds, pick cartelas, and watch numbers called live. Admins manage
deposits, withdrawals, players, and bot content from a web dashboard.

The platform is split across two deployments: the **backend** (Render — bots,
API, game loop, Socket.IO) and the **frontend** (Vercel — dashboard/game static
site).

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Repository Layout](#repository-layout)
- [The "Firebase" Emulator](#the-firebase-emulator)
- [Bots](#bots)
- [Game Rules](#game-rules)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Running the App](#running-the-app)
- [Admin Dashboard](#admin-dashboard)
- [Data Backup & Restore](#data-backup--restore)
- [Deployment (Render)](#deployment-render)
- [REST API Reference](#rest-api-reference)
- [Troubleshooting](#troubleshooting)

---

## Features

- 🎮 **Live multiplayer Bingo** — automatic rounds per stake, 35s selection
  window, a number called every 5s, single-winner resolution.
- 💸 **Wallets & payments** — TeleBirr-based deposits and withdrawals with
  admin approval, per-day limits, cooldowns, and minimum thresholds.
- 👥 **Invitations** — personal referral links to invite friends (invitation
  tracking only; no monetary bonus).
- 🆘 **Support system** — a user support bot (3 messages/day) that forwards to
  an admin support bot; admins reply without exposing their real account.
- 🛠️ **Admin dashboard** — users, games, cartelas, reports, payments, editable
  bot messages, and editable money/limits that apply instantly.
- 💾 **JSON backup/restore** — snapshots the whole database to a Telegram bot so
  data survives Render's ephemeral-disk redeploys.

---

## Architecture

```
┌──────────────────────────────────────────┐   ┌─────────────────────────┐
│      Render Cloud — Docker container       │   │   Render (static site) │
│                                             │   │                         │
│  run_bots.py  (multiprocessing launcher)     │   │  dashboard-react/       │
│  ├─ Process: Game Bot          bot.py        │   │  ├─ React + Tailwind    │
│  ├─ Process: Admin Bot         admin_bot.py  │   │  ├─ Socket.IO client    │
│  ├─ Process: Support Bot       support_bot.py│   │  └─ static build        │
│  ├─ Process: Admin Support Bot ...           │   │                         │
│  └─ Main:    FastAPI + Socket.IO             │   │                         │
│                 ├─ REST API                  │   │   env.js →             │
│                 ├─ Socket.IO events          │   │   window.BACKEND_URL   │
│                 └─ game loop (numbers, pay)  │   └─────────┬───────────────┘
│                                   │                       │
│                              ┌────▼─────┐                 │
│                              │ Database │  SQLite / PG    │
│                              │ SQLAlchemy│  (Persistent)  │
│                              └──────────┘                 │
└─────────────────────────────────────┬──────────────────────┘
        │                             │
   Telegram users              Web browsers
   (bots + Mini App)           (dashboard + game via Socket.IO)
```

- **Backend** (one Render Docker service): `run_all.py` starts the gateway,
  Supabase/PostgreSQL-backed game engine, Socket.IO API, and configured Telegram
  workers in one container. The gateway is the single database owner.
- **Frontend** (separate Render static service, `dashboard-react/` as root):
  Vite-built React/Tailwind app using `VITE_GATEWAY_URL` or the browser origin.
- The gateway and bots share the same Supabase/PostgreSQL database through the
  local gateway HTTP bridge; no second Render polling service is required.
- The gateway never serves frontend files; it remains API + Socket.IO + game engine.

---

## Tech Stack

| Layer      | Technology |
|------------|-----------|
| Backend    | Python 3.12, FastAPI, Uvicorn |
| Real-time  | python-socketio v5, Socket.IO JS v4 |
| Database   | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy |
| Telegram   | python-telegram-bot v21+ |
| Frontend   | React 19 + TypeScript + TailwindCSS 4 + Socket.IO client |
| Deployment | One combined Docker service on Render + Render static service (frontend) |

---

## Repository Layout

```
kelembingo/
├── run_bots.py            # Production entry point (launches everything)
├── bot.py                 # Main game bot (registration, wallet, invites, webapp link)
├── admin_bot.py           # Admin game bot (approve deposits/withdrawals)
├── support_bot.py         # User support bot (@kelemsupportbot)
├── admin_support_bot.py   # Admin support bot (@kelemadminsupportbot)
├── support_common.py      # Shared support helpers + hard-coded support tokens
├── backup_common.py       # JSON backup/restore via @kelembackupbot
├── config.py              # Env vars + Firebase mocking + db init
├── firestore_db.py        # SQLAlchemy-backed Firestore emulator + export/import
├── requirements.txt
├── Dockerfile
├── render.yaml            # Render deployment config
├── migrate_fix_playwallet.py  # One-time migration for corrupted wallet data
├── simulate_round_scenarios.py  # Monte Carlo testing for predetermined winner
│
├── api/
│   └── admin_api.py       # FastAPI app: REST + Socket.IO + game loop
│
├── game/
│   ├── round_engine.py    # Round lifecycle, join, number calling, payouts
│   ├── engine.py
│   └── prediction.py      # Smart number predictor (bounded game length)
│
├── handlers/
│   ├── user_manager.py    # User CRUD, withdrawals, transfers, referrals
│   ├── admin_handlers.py
│   ├── withdraw_handler.py
│   └── bot_content.py     # Editable bot messages + config defaults
│
├── dashboard-react/       # React player Mini App + admin console
│   ├── client/src/        # Pages, contexts, gateway, realtime, and UI
│   ├── package.json       # Vite/Tailwind build contract
│   └── RENDER-FRONTEND-MIGRATION.md
│
└── tests/                 # 48 tests + Monte Carlo (900 rounds)
```

---

## The "Firebase" Emulator

The code is written against a Firestore-style API (`db.collection(...).document(...)`),
but **no real Firebase is used**. Instead:

- `firestore_db.py` implements `MockFirestoreClient`, backed by a single
  SQLAlchemy table (`firestore_documents`) storing `(collection, doc_id, json)`.
- `config.py` injects mock `firebase_admin` modules so existing imports work.
- The React gateway/realtime client mirrors the same API in the browser,
  translating calls into REST (`/api/db/...`) and Socket.IO subscriptions.

This means every database read/write flows through the FastAPI backend into SQL.

---

## Bots

| Bot | Username | Token source | Purpose |
|-----|----------|--------------|---------|
| Game        | *(your bot)*            | `BOT_TOKEN` (env)        | Registration, wallet, invites, opens the Mini App |
| Admin        | *(your bot)*            | `ADMIN_BOT_TOKEN` (env)  | Approve/reject deposits & withdrawals |
| Support      | `@kelemsupportbot`      | hard-coded (`support_common.py`) | Users send support messages (3/day), forwarded to admin |
| Admin support| `@kelemadminsupportbot` | hard-coded (`support_common.py`) | Admin replies to players without exposing their account |
| Backup       | `@kelembackupbot`       | hard-coded (`backup_common.py`)  | Stores JSON DB snapshots (see [Backup](#data-backup--restore)) |

The admin's Telegram user id (`ADMIN_CHAT_ID`) is used to authorize the admin
support bot and to route support replies and backups. It is **never exposed to
users**.

---

## Game Rules

- Stakes: **10** or **20 ETB** (`VALID_STAKES`).
- Selection window: **35 seconds** to pick cartelas.
- Up to **2 cartelas** per player per round.
- A new number is called every **5 seconds**.
- Rounds resolve within **15–30 calls** (smart predictor keeps games snappy).
- Winner takes the **Derash = 75%** of the total stake pool.

---

## Getting Started

### Prerequisites

- Python **3.12**
- `gcc` and `tesseract-ocr` (for `pytesseract`; also handled by the Dockerfile)
- Telegram bot tokens from [@BotFather](https://t.me/BotFather)

### Install

```bash
git clone https://github.com/ethcocoder/kelembingo.git
cd kelembingo

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

Create a `.env` file in the project root (see [Environment Variables](#environment-variables)):

```env
BOT_TOKEN=123456:your-game-bot-token
ADMIN_BOT_TOKEN=123456:your-admin-bot-token
ADMIN_CHAT_ID=123456789
WEBAPP_URL=https://your-app.onrender.com
# DATABASE_URL=postgresql://user:pass@host/db   # optional; defaults to local SQLite
```

> The support and backup bot tokens are hard-coded in `support_common.py` and
> `backup_common.py`. Replace them there if you use your own bots.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `BOT_TOKEN` | ✅ | — | Game bot token |
| `ADMIN_BOT_TOKEN` | ✅ | — | Admin bot token (must differ from `BOT_TOKEN`) |
| `ADMIN_CHAT_ID` | ✅ | — | Admin's Telegram user id (auth + support routing + backups) |
| `DATABASE_URL` | ➖ | `sqlite:///kelembingo.db` | SQLAlchemy URL; use Postgres in production |
| `WEBAPP_URL` | ➖ | `https://kelembingo.vercel.app/game` | Public URL of the Mini App |
| `BACKEND_URL` | ➖ | — | Backend API URL (auto-detected by `env.js`) |
| `RENDER_API_ONLY` | ➖ | — | Set `true` on Render to skip static file serving (saves RAM) |
| `SUPPORT_USERNAME` | ➖ | `kelemsupportbot` | Support handle shown in the game bot |
| `TELEBIRR_NUMBER` | ➖ | `+251911000000` | Deposit destination number |
| `DEFAULT_STAKE_10` / `DEFAULT_STAKE_20` | ➖ | `10` / `20` | Stake presets |
| `GAME_TIMER_SECONDS` | ➖ | `35` | Selection window |
| `MIN_WITHDRAW` / `MAX_WITHDRAW` | ➖ | `50` / `50000` | Withdrawal bounds (ETB) |
| `MIN_INITIAL_DEPOSIT` | ➖ | `50` | Minimum first deposit (ETB) |
| `MAX_WITHDRAW_PER_DAY` | ➖ | `3` | Daily withdrawal count limit |
| `WITHDRAW_COOLDOWN_HOURS` | ➖ | `4` | Cooldown between withdrawals |
| `BONUS_TO_ETB_RATE` | ➖ | `10` | Bonus-coin → ETB conversion rate |
| `BACKUP_INTERVAL_MINUTES` | ➖ | `1` | Auto-backup interval (default 1 min; set higher to save Telegram API calls) |

> Most money/limit values are also editable at runtime from the dashboard's
> **Amounts & Limits** tab (stored in the `bot_content` collection) and take
> effect instantly.

---

## Running the App

### Everything (production layout)

```bash
python run_bots.py
```

Launches all bots, the backup scheduler, and the FastAPI + Socket.IO server on
`PORT` (default `8000`). Dashboard is served at `http://localhost:8000` when
`RENDER_API_ONLY` is unset.

### API only (no bots)

```bash
python run_api.py         # API + dashboard at http://localhost:8000
```

### Frontend (Vercel)

The `dashboard/` folder is deployed as a Vercel static site. `env.js`
auto-detects the backend URL — set `window.BACKEND_URL` manually if needed.

### With Docker

```bash
docker compose up --build
# → http://localhost:8000
```

---

## Admin Dashboard

Served by the Render static frontend service under `/admin`. Sections:

- **Dashboard** — live stats.
- **Users** — search, view, adjust balance, ban/unban.
- **Games** — round history and outcomes.
- **Cartelas** — generate / inspect the 500-card pool.
- **Reports** — revenue and activity.
- **Payments** — approve/reject deposits and withdrawals.
- **Settings** — bot config and admin password.
- **Bot Content** — edit every bot message; the first tab **Amounts & Limits**
  edits money/limits live.
- **Data Backup** — status, "Back Up Now", and "Restore" (only works when
  `ADMIN_CHAT_ID` is set and the backup bot is configured).

---

## Data Backup & Restore

Render's free plan wipes the container disk on every deploy, so a local SQLite
database would be lost. The backup bot (`@kelembackupbot`) stores JSON snapshots
to recover data after a restart.

**How it works**

1. `create_backup()` exports the document store to JSON, uploads it to the
   admin's chat with the backup bot, and pins the message.
2. On startup, `restore_if_empty()` downloads the pinned backup and re-seeds an
   empty database.
3. A background scheduler backs up every `BACKUP_INTERVAL_MINUTES` (default 1);
   manual controls live in the dashboard's Data Backup section.

**One-time setup:** press Start on `@kelembackupbot` and set `ADMIN_CHAT_ID`.

> This is a safety net, not a live replica. For zero-data-loss, use a managed
> PostgreSQL database (`DATABASE_URL`).

---

## Deployment

### Backend (Render)

The repo ships a `render.yaml` and a `Dockerfile`. On Render:

1. Create a **Web Service** from this repo (Docker runtime).
2. Set env vars: `BOT_TOKEN`, `ADMIN_BOT_TOKEN`, `ADMIN_CHAT_ID`,
   `RENDER_API_ONLY=true`.
3. Deploy. The container runs `python run_bots.py`.
4. Health check: `GET /api/health`.

### Frontend (Render static service)

1. Connect this repository and use branch `react-rebuild` for verification.
2. Set the root directory to `dashboard-react`.
3. Build with `pnpm install --frozen-lockfile && pnpm build`.
4. Publish `dist/public` as the static directory.
5. Set `VITE_GATEWAY_URL` to the existing gateway URL, or rely on the browser-origin fallback.

### Data persistence

On Render's free plan, the container disk is **ephemeral** — SQLite data is lost
on every deploy. Use a managed PostgreSQL (`DATABASE_URL`) for durable storage,
or rely on the backup bot for snapshot-based recovery.

---

## REST API Reference

Selected endpoints (see `api/admin_api.py` for the full list):

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/health` | Health check |
| `GET`  | `/api/time` | Server time (client clock sync) |
| `GET`  | `/api/dashboard` | Aggregate dashboard stats |
| `GET`  | `/api/users` · `/api/users/{id}` | List / fetch users |
| `GET`/`POST` | `/api/rounds*` | Round lifecycle (create, join, select, call, end) |
| `GET`/`POST` | `/api/admin/deposits*` | Deposit review |
| `GET`/`POST` | `/api/admin/withdrawals*` | Withdrawal review |
| `GET`/`POST` | `/api/admin/bot-content*` | Read / edit bot messages |
| `GET`  | `/api/admin/backup/status` | Latest backup metadata |
| `POST` | `/api/admin/backup/create` | Create a backup now |
| `POST` | `/api/admin/backup/restore` | Restore from the latest backup |
| `*`    | `/api/db/{collection}[/{doc}]` | Generic Firestore-emulator CRUD |

Real-time updates are delivered over **Socket.IO** (`subscribe` → `snapshot`
events), mirroring Firestore's `onSnapshot`.

---

## Troubleshooting

- **409 Conflict from Telegram** — `BOT_TOKEN` and `ADMIN_BOT_TOKEN` must be
  two different bots; `config.py` logs a critical error if they match.
- **Data disappears after deploy** — expected on ephemeral disks; enable the
  backup bot or use a managed `DATABASE_URL`. See [Backup](#data-backup--restore).
- **Backup not pinned** — check Render logs for `pin failed` or `verification failed` messages; ensure `ADMIN_CHAT_ID` matches the admin user who pressed Start on `@kelembackupbot`.
- **Backups disabled** — press Start on `@kelembackupbot` and set `ADMIN_CHAT_ID`.
- **Support replies not routing** — ensure `ADMIN_CHAT_ID` is set and the admin
  has started the admin support bot.
- **Frontend can't reach backend** — check that `env.js` resolves the correct
  `BACKEND_URL` (or set it manually in Vercel env vars).

---
## License

ISC

> Data is backed up to @kelembackupbot and auto-restored on deploy.
