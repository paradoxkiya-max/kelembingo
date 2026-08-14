// Style reminder: admin data access stays separate from player state and preserves the bearer-token contract.

import { GATEWAY_URL } from "@/lib/gateway";

export type AdminUser = { username?: string; display_name?: string; role?: string };
export type AdminRound = { id?: string; status?: string; player_count?: number; stake?: number; derash?: number; winners?: string[]; prize_per_winner?: number; called_numbers?: number[]; created_at?: string | number; createdAt?: string | number; completed_at?: string | number; completedAt?: string | number };
export type AdminRecord = { id?: string; user_id?: string | number; userId?: string | number; first_name?: string; firstName?: string; username?: string; status?: string; play_wallet?: number | { value?: number }; playWallet?: number | { value?: number }; wins?: number; total_games?: number; totalGames?: number; amount?: number; created_at?: string | number; createdAt?: string | number; [key: string]: unknown };
export type AdminDashboardData = { total_users?: number; total_balance?: number; total_play_wallets?: number; total_wins?: number; active_players?: number; completed_rounds?: number; total_admin_profit?: number; cartela_count?: number };
export type AdminBotContentItem = { id?: string; key?: string; content?: string; category?: string; updatedAt?: string | number };
export type AdminBackupStatus = { exists?: boolean; enabled?: boolean; chat_id?: string | number; created_at?: string | number; documents?: number; live_documents?: number; file_size?: number; file_name?: string };

export async function adminFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = window.localStorage.getItem("kelembingo.adminToken");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${GATEWAY_URL}${path}`, { ...init, headers });
  const raw = await response.text();
  let payload: unknown = null;
  try { payload = raw ? JSON.parse(raw) : null; } catch { payload = raw; }
  if (!response.ok) {
    const detail = typeof payload === "object" && payload && "detail" in payload ? String((payload as { detail?: unknown }).detail) : "Admin request failed";
    const error = new Error(detail) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return payload as T;
}

export const adminApi = {
  login: (username: string, password: string) => adminFetch<{ token: string; username: string; role?: string; display_name?: string }>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  me: () => adminFetch<AdminUser>("/api/auth/me"),
  logout: () => adminFetch<{ ok?: boolean }>("/api/auth/logout", { method: "POST" }),
  dashboard: () => adminFetch<AdminDashboardData>("/api/dashboard"),
  users: () => adminFetch<{ users?: AdminRecord[]; count?: number }>("/api/users"),
  updateUserBalance: (userId: string | number, newBalance: number) => adminFetch<{ ok?: boolean }>(`/api/admin/users/${encodeURIComponent(String(userId))}/balance`, { method: "PATCH", body: JSON.stringify({ new_balance: newBalance }) }),
  banUser: (userId: string | number, banned: boolean) => adminFetch<{ ok?: boolean }>(`/api/admin/users/${encodeURIComponent(String(userId))}/ban`, { method: "PATCH", body: JSON.stringify({ banned }) }),
  notifyUser: (userId: string | number, text: string) => adminFetch<{ status?: string }>("/api/notify", { method: "POST", body: JSON.stringify({ user_id: Number(userId), text }) }),
  rounds: () => adminFetch<{ rounds?: AdminRound[]; count?: number }>("/api/rounds?limit=50"),
  deposits: () => adminFetch<AdminRecord[]>("/api/admin/deposits"),
  withdrawals: () => adminFetch<AdminRecord[]>("/api/admin/withdrawals"),
  status: () => adminFetch<{ online?: boolean; updatedAt?: string }>("/api/admin/status"),
  setStatus: (online: boolean) => adminFetch<{ ok?: boolean; online?: boolean }>("/api/admin/status", { method: "POST", body: JSON.stringify({ online }) }),
  approveDeposit: (id: string, note = "") => adminFetch<{ ok?: boolean }>(`/api/admin/deposits/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ note }) }),
  rejectDeposit: (id: string, note: string) => adminFetch<{ ok?: boolean }>(`/api/admin/deposits/${encodeURIComponent(id)}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
  approveWithdrawal: (id: string) => adminFetch<{ ok?: boolean }>(`/api/admin/withdrawals/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ note: "" }) }),
  rejectWithdrawal: (id: string, note: string) => adminFetch<{ ok?: boolean }>(`/api/admin/withdrawals/${encodeURIComponent(id)}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
  cartelaStatus: () => adminFetch<{ status?: string; generated?: number; total?: number; error?: string }>("/api/cartelas/status"),
  cartelas: () => adminFetch<{ cartelas?: unknown[]; count?: number }>("/api/cartelas"),
  generateCartelas: () => adminFetch<{ status?: string; generated?: number; total?: number; count?: number }>("/api/cartelas/generate", { method: "POST" }),
  resetCartelas: () => adminFetch<{ status?: string }>("/api/cartelas/reset", { method: "POST" }),
  settings: () => adminFetch<Record<string, unknown>>("/api/admin/settings"),
  saveSettings: (settings: Record<string, unknown>) => adminFetch<{ ok?: boolean }>("/api/admin/settings", { method: "POST", body: JSON.stringify({ data: settings }) }),
  seedBotContent: () => adminFetch<{ ok?: boolean; seeded?: number }>("/api/admin/bot-content/seed", { method: "POST" }),
  saveBotContent: (key: string, value: string) => adminFetch<{ ok?: boolean }>(`/api/admin/bot-content/${encodeURIComponent(key)}`, { method: "POST", body: JSON.stringify({ data: { key, content: value, category: key.split("_")[0] } }) }),
  backupStatus: () => adminFetch<AdminBackupStatus>("/api/admin/backup/status"),
  createBackup: () => adminFetch<Record<string, unknown>>("/api/admin/backup/create", { method: "POST" }),
  restoreBackup: (overwrite: boolean) => adminFetch<Record<string, unknown>>("/api/admin/backup/restore", { method: "POST", body: JSON.stringify({ overwrite, confirm: overwrite }) }),
  uploadBackup: (snapshot: Record<string, unknown>, overwrite: boolean) => adminFetch<Record<string, unknown>>("/api/admin/backup/upload", { method: "POST", body: JSON.stringify({ snapshot, overwrite, confirm: overwrite }) }),
  wipeAll: () => adminFetch<Record<string, unknown>>("/api/admin/wipe-all", { method: "POST", body: JSON.stringify({ confirm: true }) }),
  botContent: () => adminFetch<AdminBotContentItem[]>("/api/admin/bot-content"),
};
