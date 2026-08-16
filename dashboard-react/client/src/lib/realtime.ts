// Style reminder: realtime state must feel instant but never duplicate listeners, snapshots, timers, or playback.

import { io, type Socket } from "socket.io-client";
import { GATEWAY_URL, gatewayFetch, type Player, type Round } from "@/lib/gateway";

type SnapshotMessage = { collection?: string; id?: string; user_id?: string; round_id?: string; type?: string; data?: unknown; docs?: Array<{ id?: string; data?: unknown }>; exists?: boolean; taken_cartelas?: number[]; player_count?: number; derash_pool?: number; pending_revision?: number; pending_selections?: Record<string, number[]> };
type Listener = (value: Round | null) => void;
type Subscription = { collection: string; doc_id?: string; player_token?: string; admin_token?: string };
const roundSnapshotCache = new Map<string, Round>();

export function primeRoundSnapshot(roundId: string, round: Round | null | undefined) {
  if (roundId && round) roundSnapshotCache.set(roundId, round);
}

class RoomManager {
  private socket: Socket | null = null;
  private rooms = new Map<string, { data: Subscription; refs: number; listeners: Set<(message: SnapshotMessage) => void> }>();
  private ready = false;
  private connectedOnce = false;
  private reconnectListeners = new Set<() => void>();

  private connect() {
    if (this.socket) return this.socket;
    try {
      this.socket = io(GATEWAY_URL, { transports: ["websocket", "polling"], reconnection: true, reconnectionDelay: 1000, reconnectionAttempts: Infinity });
      this.socket.on("connect", () => {
        const reconnecting = this.connectedOnce;
        this.connectedOnce = true;
        this.ready = true;
        Array.from(this.rooms.values()).forEach((room) => this.socket?.emit("subscribe", room.data));
        if (reconnecting) Array.from(this.reconnectListeners).forEach((listener) => listener());
      });
      this.socket.on("disconnect", () => { this.ready = false; });
      this.socket.on("snapshot", (message: SnapshotMessage) => this.dispatch("snapshot", message));
      this.socket.on("query_snapshot", (message: SnapshotMessage) => this.dispatch("query_snapshot", message));
      this.socket.on("cartela_pool", (message: SnapshotMessage) => this.dispatch("cartela_pool", message));
      this.socket.on("payment_update", (message: SnapshotMessage) => this.dispatch("payment_update", message));
      return this.socket;
    } catch { this.socket = null; return null; }
  }

  private dispatch(event: string, message: SnapshotMessage) {
    if (event === "snapshot" && !message.collection) return;
    if (event === "query_snapshot" && !message.collection) return;
    if (event === "cartela_pool" && message.collection && message.collection !== "rounds") return;
    if (event === "query_snapshot") {
      Array.from(this.rooms.values()).forEach((room) => {
        if (room.data.collection !== message.collection || room.data.doc_id) return;
        Array.from(room.listeners).forEach((listener) => listener(message));
      });
      return;
    }
    const collection = event === "cartela_pool" ? "rounds" : event === "payment_update" ? "payments" : message.collection || "";
    const id = event === "payment_update" ? String(message.user_id || "") : message.id || message.round_id || String((message.data as { id?: string } | undefined)?.id || "");
    Array.from(this.rooms.values()).forEach((room) => {
      if (room.data.collection !== collection || String(room.data.doc_id || "") !== String(id)) return;
      Array.from(room.listeners).forEach((listener) => listener(message));
    });
  }

  subscribeDocument(collection: string, docId: string, listener: (message: SnapshotMessage) => void) {
    const data: Subscription = { collection, doc_id: docId };
    const playerToken = window.localStorage.getItem("kelembingo.playerToken"); if (playerToken) data.player_token = playerToken;
    const adminToken = window.localStorage.getItem("kelembingo.adminToken"); if (adminToken) data.admin_token = adminToken;
    const key = JSON.stringify(data); const existing = this.rooms.get(key);
    if (existing) { existing.refs += 1; existing.listeners.add(listener); } else { this.rooms.set(key, { data, refs: 1, listeners: new Set([listener]) }); this.connect()?.emit("subscribe", data); }
    return () => { const room = this.rooms.get(key); if (!room) return; room.listeners.delete(listener); room.refs -= 1; if (room.refs <= 0) { this.rooms.delete(key); this.socket?.emit("unsubscribe", data); } };
  }

  subscribeRound(roundId: string, listener: (message: SnapshotMessage) => void) {
    return this.subscribeDocument("rounds", roundId, listener);
  }

  subscribeReconnect(listener: () => void) {
    this.reconnectListeners.add(listener);
    return () => this.reconnectListeners.delete(listener);
  }

  subscribeCollection(collection: string, listener: (message: SnapshotMessage) => void) {
    const data: Subscription = { collection };
    const adminToken = window.localStorage.getItem("kelembingo.adminToken"); if (adminToken) data.admin_token = adminToken;
    const key = JSON.stringify(data); const existing = this.rooms.get(key);
    if (existing) { existing.refs += 1; existing.listeners.add(listener); } else { this.rooms.set(key, { data, refs: 1, listeners: new Set([listener]) }); this.connect()?.emit("subscribe", data); }
    return () => { const room = this.rooms.get(key); if (!room) return; room.listeners.delete(listener); room.refs -= 1; if (room.refs <= 0) { this.rooms.delete(key); this.socket?.emit("unsubscribe", data); } };
  }
}

export const roomManager = new RoomManager();

export function observeRound(roundId: string, listener: Listener, options: { fetchInitial?: boolean; onError?: () => void } = {}) {
  const fetchInitial = options.fetchInitial !== false;
  const cached = roundSnapshotCache.get(roundId);
  let loaded = !fetchInitial || Boolean(cached); let queued: SnapshotMessage | null = null; let last = "";
  const deliver = (data: Round | null) => { const fingerprint = JSON.stringify(data); if (fingerprint === last) return; last = fingerprint; listener(data); };
  const handle = (message: SnapshotMessage) => {
    if (message.type === "cartela_pool") return;
    const raw = message.data && typeof message.data === "object" ? message.data as Record<string, unknown> : null;
    const payload = raw && raw.round && typeof raw.round === "object" ? raw.round as Round : raw as Round | null;
    if (!loaded) queued = message;
    else if (message.exists === false) deliver(null);
    else if (payload) { roundSnapshotCache.set(roundId, payload); deliver(payload); }
  };
  const unsubscribe = roomManager.subscribeRound(roundId, handle);
  if (cached) listener(cached);
  if (fetchInitial) {
    gatewayFetch<{ round?: Round }>(`/api/rounds/${encodeURIComponent(roundId)}`)
      .then((response) => { loaded = true; if (response.round) roundSnapshotCache.set(roundId, response.round); deliver(response.round || null); if (queued) { const latest = queued; queued = null; if (latest.exists === false) deliver(null); else if (latest.data) deliver(latest.data as Round); } })
      .catch(() => { loaded = true; options.onError?.(); });
  }
  return unsubscribe;
}

export function observeCartelaPool(roundId: string, listener: (message: SnapshotMessage) => void) {
  return roomManager.subscribeRound(roundId, (message) => {
    if (message.type === "cartela_pool" || message.round_id === roundId) listener(message);
  });
}

export function observeRealtimeReconnect(listener: () => void) {
  return roomManager.subscribeReconnect(listener);
}

export function observePlayer(userId: string, listener: (player: Player | null) => void) {
  return roomManager.subscribeDocument("users", userId, (message) => {
    if (message.exists === false) { listener(null); return; }
    const data = message.data && typeof message.data === "object" ? message.data as Player : null;
    if (data) listener(data);
  });
}

export function observePlayerPayments(userId: string, listener: () => void) {
  return roomManager.subscribeDocument("payments", userId, () => listener());
}

export function observeAdminCollections(collections: string[], listener: () => void) {
  const unsubscribes = collections.map((collection) => roomManager.subscribeCollection(collection, listener));
  return () => unsubscribes.forEach((unsubscribe) => unsubscribe());
}
