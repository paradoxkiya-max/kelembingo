// Style reminder: context controls state only; screens remain faithful to the compact dark-glass player shell.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { playerApi, type Player, type PublicStats } from "@/lib/gateway";
import { observePlayer } from "@/lib/realtime";

export type TelegramAuthState = "detecting" | "browser" | "telegram-no-init-data" | "authenticating" | "authenticated" | "auth-failed";
type PlayerContextValue = { player: Player | null; stats: PublicStats | null; loading: boolean; telegramAvailable: boolean; telegramState: TelegramAuthState; authError: string; refresh: () => Promise<void>; applyPlayWallet: (balance: number) => void; logout: () => void };
const PlayerContext = createContext<PlayerContextValue | null>(null);

const PLAYER_TOKEN_KEY = "kelembingo.playerToken";
const PLAYER_SESSION_KEY = "kelembingo.playerSession";

type GatewayError = Error & { status?: number };

function normalizePlayer(value: unknown): Player | null {
  if (!value || typeof value !== "object") return null;
  const source = value as Player;
  const numericId = Number(source.user_id ?? source.id);
  if (!Number.isInteger(numericId) || numericId <= 0) return null;
  return {
    ...source,
    id: source.id ?? numericId,
    user_id: source.user_id ?? source.id ?? numericId,
  };
}

function readCachedPlayer(): Player | null {
  if (typeof window === "undefined") return null;
  try {
    return normalizePlayer(JSON.parse(window.localStorage.getItem(PLAYER_SESSION_KEY) || "null"));
  } catch {
    return null;
  }
}

function cachePlayer(player: Player | null | undefined) {
  const normalized = normalizePlayer(player);
  if (!normalized || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(PLAYER_SESSION_KEY, JSON.stringify(normalized));
  } catch {
    // Local storage can be unavailable in privacy-restricted WebViews; the
    // signed X-Player-Token remains the real source of authorization.
  }
}

function clearPlayerSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(PLAYER_TOKEN_KEY);
  window.localStorage.removeItem(PLAYER_SESSION_KEY);
}

function webApp() { return (window as Window & { Telegram?: { WebApp?: { initData?: string; ready?: () => void; expand?: () => void } } }).Telegram?.WebApp; }

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const cachedAtStartup = readCachedPlayer();
  const [player, setPlayer] = useState<Player | null>(cachedAtStartup);
  const [stats, setStats] = useState<PublicStats | null>(null);
  const [loading, setLoading] = useState(!cachedAtStartup);
  const [telegramState, setTelegramState] = useState<TelegramAuthState>(cachedAtStartup ? "authenticating" : "detecting");
  const [authError, setAuthError] = useState("");
  const refreshSequence = useRef(0);

  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    const app = webApp();
    const initData = app?.initData || "";
    const cachedToken = window.localStorage.getItem(PLAYER_TOKEN_KEY) || "";
    const cachedPlayer = readCachedPlayer();
    const hasCachedSession = Boolean(cachedToken && cachedPlayer);

    app?.ready?.();
    app?.expand?.();
    setAuthError("");
    if (hasCachedSession) {
      // Paint the previously verified identity immediately. All protected
      // requests still carry the signed token; this cache is display state,
      // never an authority source.
      setPlayer((current) => current || cachedPlayer);
      setTelegramState("authenticating");
      setLoading(false);
    }

    void playerApi.stats().then(setStats).catch(() => undefined);

    const restoreFromToken = async () => {
      const token = window.localStorage.getItem(PLAYER_TOKEN_KEY) || "";
      if (!token) return false;
      try {
        const result = await playerApi.reconcile();
        if (sequence !== refreshSequence.current) return false;
        const next = normalizePlayer(result.user);
        if (!next) throw new Error("Player session is no longer available");
        cachePlayer(next);
        setPlayer(next);
        setTelegramState("authenticated");
        setLoading(false);
        return true;
      } catch (error) {
        if (sequence !== refreshSequence.current) return false;
        const status = (error as GatewayError)?.status;
        if (status === 401 || status === 403) {
          clearPlayerSession();
          setPlayer(null);
          setTelegramState("auth-failed");
          setAuthError("Your Telegram session expired. Please reopen KelemBingo from the bot.");
          setLoading(false);
          return false;
        }
        // A temporary network failure must not erase a valid cached identity.
        // The next authenticated request or refresh will retry verification.
        return hasCachedSession;
      }
    };

    if (!app) {
      if (hasCachedSession) {
        void restoreFromToken();
      } else {
        setTelegramState("browser");
        setLoading(false);
      }
      return;
    }

    if (!initData) {
      if (hasCachedSession) {
        void restoreFromToken();
      } else {
        setTelegramState("telegram-no-init-data");
        setLoading(false);
      }
      return;
    }

    setTelegramState("authenticating");
    try {
      const auth = await playerApi.authenticate(initData);
      if (sequence !== refreshSequence.current) return;
      const token = auth.player_token || auth.token;
      if (!token) throw new Error("Telegram authentication returned no player token");
      window.localStorage.setItem(PLAYER_TOKEN_KEY, token);
      const next = normalizePlayer(auth.user);
      if (!next) throw new Error("Telegram authentication returned no player identity");
      cachePlayer(next);
      setPlayer(next);
      setTelegramState("authenticated");
      setLoading(false);
      // Preserve the existing active-round reconciliation, but keep it off the
      // first paint and out of the Telegram initData critical path.
      void restoreFromToken();
    } catch (error) {
      if (sequence !== refreshSequence.current) return;
      const restored = hasCachedSession ? await restoreFromToken() : false;
      if (!restored && !hasCachedSession) {
        setPlayer(null);
        setTelegramState("auth-failed");
        setAuthError(error instanceof Error ? error.message : "Telegram authentication failed");
      }
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void playerApi.stats().then(setStats).catch(() => undefined), 30000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  useEffect(() => {
    const userId = String(player?.user_id ?? player?.id ?? "");
    if (!userId) return;
    const applyPlayer = (next: Player | null | undefined) => {
      const normalized = normalizePlayer(next);
      if (!normalized) return;
      cachePlayer(normalized);
      setPlayer((current) => current ? {
        ...current,
        ...normalized,
        id: normalized.id ?? current.id,
        user_id: normalized.user_id ?? normalized.id ?? current.user_id,
      } : normalized);
      void playerApi.stats().then(setStats).catch(() => undefined);
    };
    const unsubscribe = observePlayer(userId, applyPlayer);
    return unsubscribe;
  }, [player?.id, player?.user_id]);

  const applyPlayWallet = useCallback((balance: number) => {
    if (!Number.isFinite(balance)) return;
    setPlayer((current) => {
      if (!current) return current;
      const next = { ...current, play_wallet: balance };
      cachePlayer(next);
      return next;
    });
  }, []);

  const value = useMemo(() => ({
    player,
    stats,
    loading,
    telegramAvailable: telegramState !== "browser" && telegramState !== "detecting",
    telegramState,
    authError,
    refresh,
    applyPlayWallet,
    logout: () => {
      clearPlayerSession();
      setPlayer(null);
      setTelegramState("telegram-no-init-data");
      setAuthError("");
    },
  }), [player, stats, loading, telegramState, authError, refresh, applyPlayWallet]);

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
}

export function usePlayer() { const value = useContext(PlayerContext); if (!value) throw new Error("usePlayer must be used inside PlayerProvider"); return value; }
