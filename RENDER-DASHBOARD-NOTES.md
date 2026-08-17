# Render frontend deployment notes

Source: https://dashboard.render.com/ (authenticated browser session, 2026-08-14)

The Render workspace shows an existing `kelembingo-frontend` service with Static runtime, Global region, and a recent deployment. The same workspace also shows `kelembingo-bot` as a deployed Docker service; the gateway service is not visible in the current Active tab but remains a separate production service from the existing deployment topology.

The React migration should update only the existing `kelembingo-frontend` static service: root directory `dashboard-react`, build command `pnpm install --frozen-lockfile && pnpm build`, and publish directory `dist/public`. The gateway must retain `RENDER_API_ONLY=true`; no Vercel service or gateway static-serving change is required.

After merge commit `4bb0938`, Render auto-deploy failed before the build because the service still had the legacy root directory `dashboard` and publish directory `dashboard`. The service settings page exposes editable Root Directory, Build Command, and Publish Directory fields; these must be updated to `dashboard-react`, `pnpm install --frozen-lockfile && pnpm build`, and `dist/public` respectively.

The settings were updated through the authenticated browser. Render accepted `dashboard-react`, `pnpm install --frozen-lockfile && pnpm build`, and `dist/public`, then started a new deployment for main commit `4bb0938`. The deployment was in `Building` state and had reached dependency installation when last observed.

The corrected deployment completed its Vite build and Render reported `Your site is live`. The public URL `https://kelembingo-frontend-i8yy-9m27.onrender.com/` now serves the React KelemBingo shell with home, History, Wallet, and Profile navigation, live public statistics, and Telegram-authentication messaging.

Initial route probing showed `/history`, `/wallet`, `/profile`, and `/admin` returned 404 because the Render static service had no SPA fallback. The Redirects/Rewrites editor is prepared with source `/*`, destination `/index.html`, and action `Rewrite`; this must be saved before direct-route verification can pass.

The rewrite was saved successfully. HTTP verification now returns `200` for `/`, `/history`, `/wallet`, `/profile`, and `/admin`, and the connected browser loaded `/history` directly with the React History screen and shared navigation shell.
