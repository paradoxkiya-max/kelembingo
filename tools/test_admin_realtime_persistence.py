from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
context = (ROOT / "dashboard-react/client/src/contexts/AdminContext.tsx").read_text()
dashboard = (ROOT / "dashboard-react/client/src/pages/admin/AdminDashboard.tsx").read_text()
realtime = (ROOT / "dashboard-react/client/src/lib/realtime.ts").read_text()

assert 'observeAdminCollections(["users", "rounds", "deposits", "withdrawals", "cartelas_master", "settings", "bot_content", "system"]' in context
assert "realtimeRevision" in context
assert "subscribeCollection" in realtime and "admin_token" in realtime
assert "useCallback" in dashboard and "useRef" in dashboard
assert "const loadVersion = useRef(0)" in dashboard
assert "if (version !== loadVersion.current) return" in dashboard
assert "realtimeRevision === 0 ? 0 : 180" in dashboard
assert "const [isRefreshing, setIsRefreshing] = useState(false)" in dashboard
assert "{loading ? <Loading />" not in dashboard
assert "{error ? <State" not in dashboard
assert "Updating live data" in dashboard and "Retry live sync" in dashboard
assert "}, []);" in dashboard
assert "<CartelasSection refreshToken={realtimeRevision} />" in dashboard
assert "<SettingsSection refreshToken={realtimeRevision} />" in dashboard
assert "<BotContentSection refreshToken={realtimeRevision} />" in dashboard
assert "key={`cartelas-${realtimeRevision}`}" not in dashboard
assert "key={`settings-${realtimeRevision}`}" not in dashboard
assert "key={`botcontent-${realtimeRevision}`}" not in dashboard
assert "const dirty = useRef(false)" in dashboard
assert "if (!dirty.current) void load()" in dashboard

print("admin realtime persistence contract check: PASS")
