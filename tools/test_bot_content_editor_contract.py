from pathlib import Path


source = (Path(__file__).resolve().parents[1] / "dashboard-react/client/src/pages/admin/AdminDashboard.tsx").read_text(encoding="utf-8")

assert "drafts[config.key] ?? items.find" in source
assert "drafts[item.key || item.id || \"\"] ?? item.content" in source
assert "setDrafts((current) => ({ ...current, [config.key]: value }))" in source
assert "setDrafts((current) => ({ ...current, [item.key || item.id || \"\"]: value }))" in source
assert 'value={drafts[config.key] || items.find' not in source
assert 'value={drafts[item.key || item.id || ""] || item.content' not in source

print("PASS: Bot Content editor preserves empty local drafts while typing")
