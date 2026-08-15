// Style reminder: admin auth is a quiet session guard around the persistent dark operations console.

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { adminApi, type AdminUser } from "@/lib/admin";
import { observeAdminCollections } from "@/lib/realtime";

type AdminContextValue = { admin: AdminUser | null; loading: boolean; realtimeRevision: number; login: (username: string, password: string) => Promise<void>; logout: () => Promise<void> };
const AdminContext = createContext<AdminContextValue | null>(null);

export function AdminProvider({ children }: { children: React.ReactNode }) {
  const [admin, setAdmin] = useState<AdminUser | null>(null); const [loading, setLoading] = useState(true); const [realtimeRevision, setRealtimeRevision] = useState(0);
  useEffect(() => { if (!window.localStorage.getItem("kelembingo.adminToken")) { setLoading(false); return; } adminApi.me().then(setAdmin).catch(() => { window.localStorage.removeItem("kelembingo.adminToken"); setAdmin(null); }).finally(() => setLoading(false)); }, []);
  useEffect(() => {
    if (!admin || !window.localStorage.getItem("kelembingo.adminToken")) return;
    return observeAdminCollections(["users", "rounds", "deposits", "withdrawals", "cartelas_master", "settings", "bot_content", "system"], () => setRealtimeRevision((value) => value + 1));
  }, [admin]);
  const value = useMemo(() => ({ admin, loading, realtimeRevision, login: async (username: string, password: string) => { const response = await adminApi.login(username, password); window.localStorage.setItem("kelembingo.adminToken", response.token); setAdmin({ username: response.username, role: response.role, display_name: response.display_name }); }, logout: async () => { try { await adminApi.logout(); } catch { /* local session still clears */ } window.localStorage.removeItem("kelembingo.adminToken"); setAdmin(null); setRealtimeRevision(0); } }), [admin, loading, realtimeRevision]);
  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>;
}
export function useAdmin() { const value = useContext(AdminContext); if (!value) throw new Error("useAdmin must be used inside AdminProvider"); return value; }
