# Legacy UI cleanup

The legacy `dashboard/` HTML, CSS, JavaScript, component fragments, and static UI assets were removed from the isolated `react-rebuild` branch after the React replacement was added under `dashboard-react/`.

This cleanup does not change the Python gateway, Socket.IO protocol, Supabase/database code, Telegram bots, Render service definitions, or regression tests. The pre-cleanup state remains recoverable from the parent commit `6f299cf` and normal Git history. This branch must not be merged until the `dashboard-react` static service is verified against the existing live gateway.
