from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
admin_dashboard = (ROOT / "dashboard-react/client/src/pages/admin/AdminDashboard.tsx").read_text(encoding="utf-8")
admin_context = (ROOT / "dashboard-react/client/src/contexts/AdminContext.tsx").read_text(encoding="utf-8")
realtime = (ROOT / "dashboard-react/client/src/lib/realtime.ts").read_text(encoding="utf-8")

assert 'if (activeLoadScope !== "none") void load(activeLoadScope)' in admin_dashboard
assert "const [loadedScopes, setLoadedScopes]" in admin_dashboard
assert "setLoadedScopes((current) => ({ ...current, [scope]: true }))" in admin_dashboard
assert "loading={Boolean(isRefreshing && !loadedScopes.users)}" in admin_dashboard
assert "loading ? <Loading />" in admin_dashboard
assert "observeAdminCollections([\"users\", \"rounds\", \"deposits\", \"withdrawals\"" in admin_context
assert "roomManager.subscribeCollection" in realtime
assert 'this.connect()?.emit("subscribe", data)' in realtime

print("PASS: admin initial loading and realtime subscription contract")
