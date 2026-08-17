// Style reminder: admin auth is a quiet session guard around the persistent dark operations console.

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { adminApi, type AdminUser } from "@/lib/admin";
import { observeAdminCollections } from "@/lib/realtime";

type AdminContextValue = { admin: AdminUser | null; loading: boolean; realtimeRevision: number; realtimeCollections: string[]; login: (username: string, password: string) => Promise<void>; logout: () => Promise<void> };
const AdminContext = createContext<AdminContextValue | null>(null);

export function AdminProvider({ children }: { children: React.ReactNode }) {
  const [admin, setAdmin] = useState<AdminUser | null>(null); const [loading, setLoading] = useState(true); const [realtimeRevision, setRealtimeRevision] = useState(0); const [realtimeCollections, setRealtimeCollections] = useState<string[]>([]); const pendingCollections = useRef(new Set<string>()); const batchTimer = useRef<number | null>(null);
  useEffect(() => { if (!window.localStorage.getItem("kelembingo.adminToken")) { setLoading(false); return; } adminApi.me().then(setAdmin).catch(() => { window.localStorage.removeItem("kelembingo.adminToken"); setAdmin(null); }).finally(() => setLoading(false)); }, []);
  useEffect(() => {
    if (!admin || !window.localStorage.getItem("kelembingo.adminToken")) return;
    const unsubscribe = observeAdminCollections(["users", "rounds", "deposits", "withdrawals", "cartelas_master", "settings", "bot_content", "system"], (message) => {
      if (message.collection) pendingCollections.current.add(message.collection);
      if (batchTimer.current !== null) window.clearTimeout(batchTimer.current);
      batchTimer.current = window.setTimeout(() => {
        batchTimer.current = null;
        setRealtimeCollections(Array.from(pendingCollections.current));
        pendingCollections.current.clear();
        setRealtimeRevision((value) => value + 1);
      }, 180);
    });
    return () => { unsubscribe(); if (batchTimer.current !== null) window.clearTimeout(batchTimer.current); batchTimer.current = null; pendingCollections.current.clear(); };
  }, [admin]);
  const value = useMemo(() => ({ admin, loading, realtimeRevision, realtimeCollections, login: async (username: string, password: string) => { const response = await adminApi.login(username, password); window.localStorage.setItem("kelembingo.adminToken", response.token); setAdmin({ username: response.username, role: response.role, display_name: response.display_name }); }, logout: async () => { try { await adminApi.logout(); } catch { /* local session still clears */ } window.localStorage.removeItem("kelembingo.adminToken"); setAdmin(null); setRealtimeRevision(0); setRealtimeCollections([]); } }), [admin, loading, realtimeRevision, realtimeCollections]);
  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>;
}
export function useAdmin() { const value = useContext(AdminContext); if (!value) throw new Error("useAdmin must be used inside AdminProvider"); return value; }
