// Style reminder: admin data access stays separate from player state and preserves the bearer-token contract.

import { GATEWAY_URL } from "@/lib/gateway";

export type AdminUser = { username?: string; display_name?: string; role?: string };
export type AdminRound = { id?: string; status?: string; player_count?: number; stake?: number; derash?: number; winners?: string[]; prize_per_winner?: number; called_numbers?: number[]; created_at?: string | number; completed_at?: string | number };
export type AdminRecord = { id?: string; user_id?: string | number; first_name?: string; username?: string; status?: string; play_wallet?: number | { value?: number }; wins?: number; total_games?: number; amount?: number; created_at?: string | number; createdAt?: string | number; [key: string]: unknown };

export async function adminFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers); headers.set("Accept", "application/json"); if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json"); const token = window.localStorage.getItem("kelembingo.adminToken"); if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${GATEWAY_URL}${path}`, { ...init, headers }); const raw = await response.text(); let payload: unknown = null; try { payload = raw ? JSON.parse(raw) : null; } catch { payload = raw; }
  if (!response.ok) { const detail = typeof payload === "object" && payload && "detail" in payload ? String((payload as { detail?: unknown }).detail) : "Admin request failed"; const error = new Error(detail) as Error & { status?: number }; error.status = response.status; throw error; }
  return payload as T;
}

export const adminApi = {
  login: (username: string, password: string) => adminFetch<{ token: string; username: string; role?: string; display_name?: string }>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  me: () => adminFetch<AdminUser>("/api/auth/me"),
  logout: () => adminFetch<{ ok?: boolean }>("/api/auth/logout", { method: "POST" }),
  dashboard: () => adminFetch<Record<string, unknown>>("/api/dashboard"),
  users: () => adminFetch<AdminRecord[]>("/api/users"),
  rounds: () => adminFetch<{ rounds?: AdminRound[]; count?: number }>("/api/rounds?limit=50"),
  deposits: () => adminFetch<AdminRecord[]>("/api/admin/deposits"),
  withdrawals: () => adminFetch<AdminRecord[]>("/api/admin/withdrawals"),
  status: () => adminFetch<{ online?: boolean }>("/api/admin/status"),
  setStatus: (online: boolean) => adminFetch<{ ok?: boolean }>("/api/admin/status", { method: "POST", body: JSON.stringify({ online }) }),
  approveDeposit: (id: string, note = "") => adminFetch<{ ok?: boolean }>(`/api/admin/deposits/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ note }) }),
  rejectDeposit: (id: string, note: string) => adminFetch<{ ok?: boolean }>(`/api/admin/deposits/${encodeURIComponent(id)}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
  approveWithdrawal: (id: string) => adminFetch<{ ok?: boolean }>(`/api/admin/withdrawals/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ note: "" }) }),
  rejectWithdrawal: (id: string, note: string) => adminFetch<{ ok?: boolean }>(`/api/admin/withdrawals/${encodeURIComponent(id)}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
  cartelaStatus: () => adminFetch<Record<string, unknown>>("/api/cartelas/status"),
  cartelas: () => adminFetch<{ cartelas?: unknown[]; count?: number }>("/api/cartelas"),
  generateCartelas: () => adminFetch<Record<string, unknown>>("/api/cartelas/generate", { method: "POST" }),
  resetCartelas: () => adminFetch<Record<string, unknown>>("/api/cartelas/reset", { method: "POST" }),
  settings: () => adminFetch<Record<string, unknown>>("/api/admin/settings"),
  saveSettings: (settings: Record<string, unknown>) => adminFetch<Record<string, unknown>>("/api/admin/settings", { method: "POST", body: JSON.stringify(settings) }),
  seedBotContent: () => adminFetch<Record<string, unknown>>("/api/admin/bot-content/seed", { method: "POST" }),
  saveBotContent: (key: string, value: string) => adminFetch<Record<string, unknown>>(`/api/admin/bot-content/${encodeURIComponent(key)}`, { method: "POST", body: JSON.stringify({ value }) }),
  backupStatus: () => adminFetch<Record<string, unknown>>("/api/admin/backup/status"),
  createBackup: () => adminFetch<Record<string, unknown>>("/api/admin/backup/create", { method: "POST" }),
  restoreBackup: (overwrite: boolean) => adminFetch<Record<string, unknown>>("/api/admin/backup/restore", { method: "POST", body: JSON.stringify({ overwrite, confirm: overwrite }) }),
  wipeAll: () => adminFetch<Record<string, unknown>>("/api/admin/wipe-all", { method: "POST", body: JSON.stringify({ confirm: true }) }),
  botContent: () => adminFetch<Record<string, unknown>>("/api/admin/bot-content"),
};
