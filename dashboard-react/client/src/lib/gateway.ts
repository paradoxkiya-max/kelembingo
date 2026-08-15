// Style reminder: keep the gateway layer invisible to the UI; preserve the legacy player-token and API contract.

export const GATEWAY_URL = (import.meta.env.VITE_GATEWAY_URL || "https://kelembingo-sqnv.onrender.com").replace(/\/$/, "");

export type GatewayError = Error & { status?: number; code?: string };

export function formatGatewayError(value: unknown, fallback = "Request failed", depth = 0): string {
  if (depth > 4 || value === null || value === undefined) return fallback;
  if (value instanceof Error) return value.message || fallback;
  if (typeof value === "string") return value.trim() || fallback;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const messages = value.map((item) => formatGatewayError(item, "", depth + 1)).filter(Boolean);
    return messages.join("; ") || fallback;
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const key of ["message", "detail", "error", "reason", "msg", "description"]) {
      if (record[key] !== undefined && record[key] !== value) {
        const message = formatGatewayError(record[key], "", depth + 1);
        if (message) return message;
      }
    }
    try {
      const compact = JSON.stringify(value);
      if (compact && compact !== "{}") return compact;
    } catch { /* fall through to the safe fallback */ }
  }
  return fallback;
}

function playerToken() {
  return window.localStorage.getItem("kelembingo.playerToken") || "";
}

export async function gatewayFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = playerToken();
  if (token) headers.set("X-Player-Token", token);
  const response = await fetch(`${GATEWAY_URL}${path}`, { ...init, headers });
  const raw = await response.text();
  let payload: unknown = null;
  try { payload = raw ? JSON.parse(raw) : null; } catch { payload = raw; }
  if (!response.ok) {
    const message = formatGatewayError(payload, `Gateway request failed (${response.status})`);
    const error = new Error(message) as GatewayError;
    error.status = response.status;
    if (typeof payload === "object" && payload && "code" in payload) error.code = String((payload as { code?: unknown }).code);
    throw error;
  }
  return payload as T;
}

export type Player = { id?: string | number; user_id?: string | number; first_name?: string; username?: string; phone?: string; telebirr_name?: string; play_wallet?: number | { value?: number }; bonus_wallet?: number | { value?: number }; wins?: number; total_games?: number; games_played?: number; is_playing?: boolean; status?: string };
export type PublicStats = { active_cartelas: number; games_played: number; winners_today: number };
export type Round = { id?: string; round_id?: string; status?: string; stake?: number; player_count?: number; derash?: number; called_numbers?: number[]; winners?: string[]; winner_name?: string; winning_cartela?: number; prize_per_winner?: number; created_at?: string | number; completed_at?: string | number; game_started_at?: string | number; next_number_at?: string | number; selection_deadline?: string | number; taken_cartelas?: number[]; pending_selections?: Record<string, number[]>; players?: Record<string, { cartelas?: number[]; name?: string }> };
export type Cartela = { id?: string; number: number; cartela?: number[]; data?: number[][]; grid?: number[][]; taken?: boolean; status?: string };
export type DepositConfig = { ok?: boolean; error?: string; phone?: string; pending_count?: number; pending_limit?: number; minimum_amount?: number };
export type Transaction = { id?: string; type?: string; amount?: number; status?: string; created_at?: string | number; description?: string; reference?: string };

export const playerApi = {
  authenticate: (initData: string) => gatewayFetch<{ user: Player; player_token?: string; token?: string }>("/api/player/auth", { method: "POST", body: JSON.stringify({ initData }) }),
  reconcile: () => gatewayFetch<Player>("/api/player/reconcile-state", { method: "POST" }),
  stats: () => gatewayFetch<PublicStats>("/api/public/stats"),
  time: () => gatewayFetch<{ iso: string }>("/api/time"),
  history: () => gatewayFetch<{ rounds?: Round[]; count?: number }>("/api/rounds?status=completed&winners_only=true&limit=3"),
  activeRounds: (stake: number = 10) => gatewayFetch<{ round: Round | null }>(`/api/rounds/active?stake=${stake}`),
  round: (roundId: string) => gatewayFetch<{ round: Round }>(`/api/rounds/${encodeURIComponent(roundId)}`),
  cartela: (number: number) => gatewayFetch<{ cartela: Cartela }>(`/api/cartelas/${number}`),
  cartelas: () => gatewayFetch<{ cartelas: Cartela[]; count: number }>("/api/cartelas"),
  createRound: (stake: number) => gatewayFetch<{ round: Round }>(`/api/rounds/create?stake=${stake}`, { method: "POST" }),
  joinRound: (roundId: string, userId: string | number, cartelaNumbers: number[], userName?: string) => gatewayFetch<{ round?: Round; ok?: boolean }>(`/api/rounds/${encodeURIComponent(roundId)}/join`, { method: "POST", body: JSON.stringify({ user_id: Number(userId), cartela_numbers: cartelaNumbers, user_name: userName || "Player" }) }),
  selectCartela: (roundId: string, userId: string | number, cartelaNumber: number) => gatewayFetch<{ ok: boolean }>(`/api/rounds/${encodeURIComponent(roundId)}/select`, { method: "POST", body: JSON.stringify({ user_id: Number(userId), cartela_number: cartelaNumber }) }),
  unselectCartela: (roundId: string, userId: string | number, cartelaNumber: number) => gatewayFetch<{ ok: boolean }>(`/api/rounds/${encodeURIComponent(roundId)}/unselect`, { method: "POST", body: JSON.stringify({ user_id: Number(userId), cartela_number: cartelaNumber }) }),
  claimBingo: (roundId: string, userId: string | number, winningCartela: number) => gatewayFetch<{ ok?: boolean; winner?: boolean; winner_name?: string; winning_cartela?: number; prize_per_winner?: number; already_completed?: boolean }>(`/api/rounds/${encodeURIComponent(roundId)}/claim-bingo`, { method: "POST", body: JSON.stringify({ user_id: Number(userId), winning_cartela: winningCartela }) }),
  depositConfig: (userId: string | number) => gatewayFetch<DepositConfig>(`/api/deposits/config/${encodeURIComponent(String(userId))}`),
  submitDeposit: (body: { telebirr_name: string; amount: number; transaction_id: string }) => gatewayFetch<{ ok?: boolean; deposit_id?: string; status?: string; message?: string }>("/api/deposits/submit", { method: "POST", body: JSON.stringify(body) }),
  createWithdrawal: (body: { amount: number; phone: string; telebirr_name: string }, key: string) => gatewayFetch<{ ok?: boolean; error?: unknown; message?: unknown; min?: number }>("/api/withdrawals/create", { method: "POST", headers: { "X-Idempotency-Key": key }, body: JSON.stringify(body) }),
  deposits: (userId: string | number) => gatewayFetch<Transaction[]>(`/api/db/deposits?filters=${encodeURIComponent(JSON.stringify([["userId", "==", String(userId)]]))}&order_by=createdAt&order_dir=DESCENDING&limit_n=20`),
  withdrawals: (userId: string | number) => gatewayFetch<Transaction[]>(`/api/db/withdrawals?filters=${encodeURIComponent(JSON.stringify([["userId", "==", String(userId)]]))}&order_by=createdAt&order_dir=DESCENDING&limit_n=20`),
};
