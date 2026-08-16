from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app = (ROOT / 'dashboard-react/client/src/App.tsx').read_text()
home = (ROOT / 'dashboard-react/client/src/pages/Home.tsx').read_text()
player_context = (ROOT / 'dashboard-react/client/src/contexts/PlayerContext.tsx').read_text()
gateway = (ROOT / 'dashboard-react/client/src/lib/gateway.ts').read_text()
card_select = (ROOT / 'dashboard-react/client/src/pages/CartelaSelect.tsx').read_text()
admin_api = (ROOT / 'api/admin_api.py').read_text()
assert 'lazy(() => import("@/pages/CartelaSelect"))' in app
assert 'CARTELA_POOL' in card_select
assert 'playerApi.cartelas' not in card_select
assert 'playerApi.cartela(number)' in card_select
assert 'playerApi.createRound(stake)' in card_select
assert 'playerApi.activeRounds' not in card_select
assert 'playerApi.stats()' in player_context
assert 'setInterval(() => void playerApi.stats().then(setStats).catch(() => undefined), 30000)' in player_context
assert '"/api/public/stats"' in gateway
assert 'Promise.all' in card_select
assert '@app.get("/api/public/stats")' in admin_api
assert "jsonb_extract_path_text(CAST(data AS JSONB), 'status')" in admin_api

print('stake-selection performance regression check: PASS')
