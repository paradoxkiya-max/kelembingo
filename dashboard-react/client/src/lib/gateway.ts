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
export type Round = { id?: string; round_id?: string; status?: string; stake?: number; player_count?: number; derash?: number; called_numbers?: number[]; winners?: string[]; winner_name?: string; winning_cartela?: number; prize_per_winner?: number; created_at?: string | number; completed_at?: string | number; game_started_at?: string | number; next_number_at?: string | number; selection_deadline?: string | number; taken_cartelas?: number[]; pending_selections?: Record<string, number[]>; pending_revision?: number; players?: Record<string, { cartelas?: number[]; name?: string }> };
export type Cartela = { id?: string; number: number; cartela?: number[]; data?: number[][]; grid?: number[][]; taken?: boolean; status?: string };
export type CartelaSelection = { ok: boolean; play_wallet?: number; selected_cartelas?: number[]; reserved_cartelas?: number[]; pending_revision?: number; taken_cartelas?: number[]; player_count?: number; derash_pool?: number; pending_selections?: Record<string, number[]> };
export type DepositConfig = { ok?: boolean; error?: string; message?: string; phone?: string; pending_count?: number; pending_limit?: number; minimum_amount?: number; texts?: Record<string, string> };
export type WithdrawalValidation = { ok?: boolean; error?: string; message?: string; min?: number; max?: number; balance?: number; min_deposit?: number; current_deposit?: number; limit?: number; minutes?: number; hours?: number };
export type Transaction = { id?: string; type?: string; amount?: number; status?: string; created_at?: string | number; description?: string; reference?: string; telebirr_name?: string; phone?: string };
type TransactionDocument = { id?: string; data?: Record<string, unknown>; amount?: unknown; status?: unknown; createdAt?: unknown; created_at?: unknown; transactionId?: unknown; transaction_id?: unknown; telebirrName?: unknown; telebirr_name?: unknown; phone?: unknown };
const cartelaCache = new Map<number, Cartela>();

function normalizeTransaction(document: TransactionDocument): Transaction {
  const data: Record<string, unknown> = document.data && typeof document.data === "object" ? document.data : document as Record<string, unknown>;
  const value = (key: string) => data[key] ?? (document as Record<string, unknown>)[key];
  const amount = Number(value("amount"));
  const createdAt = value("createdAt") ?? value("created_at");
  return {
    id: document.id || String(value("id") || ""),
    amount: Number.isFinite(amount) ? amount : 0,
    status: String(value("status") || "pending"),
    created_at: typeof createdAt === "string" || typeof createdAt === "number" ? createdAt : undefined,
    reference: typeof (value("transactionId") ?? value("transaction_id")) === "string" ? String(value("transactionId") ?? value("transaction_id")) : undefined,
    telebirr_name: typeof (value("telebirrName") ?? value("telebirr_name")) === "string" ? String(value("telebirrName") ?? value("telebirr_name")) : undefined,
    phone: typeof value("phone") === "string" ? String(value("phone")) : undefined,
  };
}

export const playerApi = {
  authenticate: (initData: string) => gatewayFetch<{ user: Player; player_token?: string; token?: string }>("/api/player/auth", { method: "POST", body: JSON.stringify({ initData }) }),
  reconcile: () => gatewayFetch<{ ok?: boolean; active?: boolean; user?: Player }>("/api/player/reconcile-state", { method: "POST" }),
  stats: () => gatewayFetch<PublicStats>("/api/public/stats"),
  time: () => gatewayFetch<{ iso: string }>("/api/time"),
  history: () => gatewayFetch<{ rounds?: Round[]; count?: number }>("/api/rounds?status=completed&winners_only=true&limit=3"),
  activeRounds: (stake: number = 10) => gatewayFetch<{ round: Round | null }>(`/api/rounds/active?stake=${stake}`),
  round: (roundId: string) => gatewayFetch<{ round: Round }>(`/api/rounds/${encodeURIComponent(roundId)}`),
  cartela: async (number: number) => {
    const cached = cartelaCache.get(number);
    if (cached) return { cartela: cached };
    const response = await gatewayFetch<{ cartela: Cartela }>(`/api/cartelas/${number}`);
    if (response.cartela) cartelaCache.set(number, response.cartela);
    return response;
  },
  cartelas: () => gatewayFetch<{ cartelas: Cartela[]; count: number }>("/api/cartelas"),
  createRound: (stake: number) => gatewayFetch<{ round: Round }>(`/api/rounds/create?stake=${stake}`, { method: "POST" }),
  joinRound: (roundId: string, userId: string | number, cartelaNumbers: number[], userName?: string, options?: { requirePending?: boolean; pendingRevision?: number }) => gatewayFetch<{ round?: Round; ok?: boolean }>(`/api/rounds/${encodeURIComponent(roundId)}/join`, { method: "POST", body: JSON.stringify({ user_id: Number(userId), cartela_numbers: cartelaNumbers, user_name: userName || "Player", require_pending: Boolean(options?.requirePending), pending_revision: Number(options?.pendingRevision || 0) }) }),
  selectCartela: (roundId: string, userId: string | number, cartelaNumber: number, requestId?: string) => gatewayFetch<CartelaSelection>(`/api/rounds/${encodeURIComponent(roundId)}/select`, { method: "POST", body: JSON.stringify({ user_id: Number(userId), cartela_number: cartelaNumber, request_id: requestId }) }),
  unselectCartela: (roundId: string, userId: string | number, cartelaNumber: number, requestId?: string) => gatewayFetch<CartelaSelection>(`/api/rounds/${encodeURIComponent(roundId)}/unselect`, { method: "POST", body: JSON.stringify({ user_id: Number(userId), cartela_number: cartelaNumber, request_id: requestId }) }),
  claimBingo: (roundId: string, userId: string | number, winningCartela: number) => gatewayFetch<{ ok?: boolean; winner?: boolean; winner_name?: string; winning_cartela?: number; prize_per_winner?: number; already_completed?: boolean }>(`/api/rounds/${encodeURIComponent(roundId)}/claim-bingo`, { method: "POST", body: JSON.stringify({ user_id: Number(userId), winning_cartela: winningCartela }) }),
  depositConfig: (userId: string | number) => gatewayFetch<DepositConfig>(`/api/deposits/config/${encodeURIComponent(String(userId))}`),
  validateWithdrawal: (userId: string | number, amount: number) => gatewayFetch<WithdrawalValidation>(`/api/validate-withdrawal/${encodeURIComponent(String(userId))}?amount=${encodeURIComponent(String(amount))}`),
  submitDeposit: (body: { telebirr_name: string; amount: number; transaction_id: string }) => gatewayFetch<{ ok?: boolean; deposit_id?: string; status?: string; message?: string }>("/api/deposits/submit", { method: "POST", body: JSON.stringify(body) }),
  createWithdrawal: (body: { amount: number; phone: string; telebirr_name: string }, key: string) => gatewayFetch<{ ok?: boolean; error?: unknown; message?: unknown; min?: number; max?: number; min_deposit?: number; limit?: number; minutes?: number }>("/api/withdrawals/create", { method: "POST", headers: { "X-Idempotency-Key": key }, body: JSON.stringify(body) }),
  deposits: async (userId: string | number) => (await gatewayFetch<TransactionDocument[]>(`/api/db/deposits?filters=${encodeURIComponent(JSON.stringify([["userId", "==", String(userId)]]))}&order_by=createdAt&order_dir=DESCENDING&limit_n=20`)).map(normalizeTransaction),
  withdrawals: async (userId: string | number) => (await gatewayFetch<TransactionDocument[]>(`/api/db/withdrawals?filters=${encodeURIComponent(JSON.stringify([["userId", "==", String(userId)]]))}&order_by=createdAt&order_dir=DESCENDING&limit_n=20`)).map(normalizeTransaction),
};
