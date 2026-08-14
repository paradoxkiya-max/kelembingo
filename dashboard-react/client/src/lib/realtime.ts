// Style reminder: realtime state must feel instant but never duplicate listeners, snapshots, timers, or playback.

import { io, type Socket } from "socket.io-client";
import { GATEWAY_URL, gatewayFetch, type Round } from "@/lib/gateway";

type SnapshotMessage = { collection?: string; id?: string; data?: unknown; exists?: boolean };
type Listener = (value: Round | null) => void;
type Subscription = { collection: string; doc_id?: string; player_token?: string };

class RoomManager {
  private socket: Socket | null = null;
  private rooms = new Map<string, { data: Subscription; refs: number; listeners: Set<(message: SnapshotMessage) => void> }>();
  private ready = false;

  private connect() {
    if (this.socket) return this.socket;
    try {
      this.socket = io(GATEWAY_URL, { transports: ["websocket", "polling"], reconnection: true, reconnectionDelay: 1000, reconnectionAttempts: Infinity });
      this.socket.on("connect", () => { this.ready = true; Array.from(this.rooms.values()).forEach((room) => this.socket?.emit("subscribe", room.data)); });
      this.socket.on("disconnect", () => { this.ready = false; });
      this.socket.on("snapshot", (message: SnapshotMessage) => this.dispatch("snapshot", message));
      this.socket.on("cartela_pool", (message: SnapshotMessage) => this.dispatch("cartela_pool", message));
      return this.socket;
    } catch { this.socket = null; return null; }
  }

  private dispatch(event: string, message: SnapshotMessage) {
    if (event === "snapshot" && message.collection !== "rounds") return;
    if (event === "cartela_pool" && message.collection && message.collection !== "rounds") return;
    const id = message.id || String((message.data as { id?: string } | undefined)?.id || "");
    Array.from(this.rooms.entries()).forEach(([key, room]) => { if (key !== JSON.stringify({ collection: "rounds", doc_id: id, player_token: room.data.player_token })) return; Array.from(room.listeners).forEach((listener) => listener(message)); });
  }

  subscribeRound(roundId: string, listener: (message: SnapshotMessage) => void) {
    const data: Subscription = { collection: "rounds", doc_id: roundId };
    const token = window.localStorage.getItem("kelembingo.playerToken"); if (token) data.player_token = token;
    const key = JSON.stringify(data); const existing = this.rooms.get(key);
    if (existing) { existing.refs += 1; existing.listeners.add(listener); } else { this.rooms.set(key, { data, refs: 1, listeners: new Set([listener]) }); this.connect()?.emit("subscribe", data); }
    return () => { const room = this.rooms.get(key); if (!room) return; room.listeners.delete(listener); room.refs -= 1; if (room.refs <= 0) { this.rooms.delete(key); this.socket?.emit("unsubscribe", data); } };
  }
}

export const roomManager = new RoomManager();

export function observeRound(roundId: string, listener: Listener) {
  let loaded = false; let queued: SnapshotMessage | null = null; let last = "";
  const deliver = (data: Round | null) => { const fingerprint = JSON.stringify(data); if (fingerprint === last) return; last = fingerprint; listener(data); };
  const handle = (message: SnapshotMessage) => { const payload = message.data && typeof message.data === "object" ? message.data as Round : null; if (!loaded) queued = message; else deliver(message.exists === false ? null : payload); };
  const unsubscribe = roomManager.subscribeRound(roundId, handle);
  gatewayFetch<{ id?: string; data?: Round }>(`/api/db/rounds/${encodeURIComponent(roundId)}`).then((response) => { loaded = true; deliver(response.data || response as unknown as Round); if (queued) { const latest = queued; queued = null; deliver(latest.exists === false ? null : latest.data as Round); } }).catch(() => { loaded = true; });
  return unsubscribe;
}
