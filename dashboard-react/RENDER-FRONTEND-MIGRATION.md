# React frontend service migration

This directory is the isolated React/Tailwind replacement for the existing static KelemBingo frontend. The Python gateway, cron bot, Supabase database, Socket.IO protocol, and three-service Render topology remain unchanged.

For the existing Render frontend service, use the same service type and connect it to the `react-rebuild` branch for verification. Set the service root directory to `dashboard-react`, use `pnpm install --frozen-lockfile && pnpm build` as the build command, and publish `dist/public` as the static directory. The service must continue to use the existing gateway URL through `VITE_GATEWAY_URL`, or fall back to the current browser origin when that variable is absent.

Do not change the gateway service, the bot cron service, `GAME_ENGINE_ENABLED`, `DATABASE_URL`, or any credentials while testing this branch. The branch is safe to preview independently; merge only after player and admin flows are verified against the existing live gateway.

The frontend build is static and does not introduce a new backend. Its `server/` directory is only the template compatibility placeholder and is not required by the Render static service.
