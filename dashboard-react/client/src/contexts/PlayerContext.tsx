// Style reminder: context controls state only; screens remain faithful to the compact dark-glass player shell.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { playerApi, type Player, type PublicStats } from "@/lib/gateway";

export type TelegramAuthState = "detecting" | "browser" | "telegram-no-init-data" | "authenticating" | "authenticated" | "auth-failed";
type PlayerContextValue = { player: Player | null; stats: PublicStats | null; loading: boolean; telegramAvailable: boolean; telegramState: TelegramAuthState; authError: string; refresh: () => Promise<void>; logout: () => void };
const PlayerContext = createContext<PlayerContextValue | null>(null);
function webApp() { return (window as Window & { Telegram?: { WebApp?: { initData?: string; ready?: () => void; expand?: () => void } } }).Telegram?.WebApp; }

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const [player, setPlayer] = useState<Player | null>(null); const [stats, setStats] = useState<PublicStats | null>(null); const [loading, setLoading] = useState(true); const [telegramState, setTelegramState] = useState<TelegramAuthState>("detecting"); const [authError, setAuthError] = useState("");
  const refresh = useCallback(async () => {
    const app = webApp(); const initData = app?.initData || ""; app?.ready?.(); app?.expand?.(); setAuthError(""); setPlayer(null);
    const publicStats = await Promise.allSettled([playerApi.stats()]); if (publicStats[0].status === "fulfilled") setStats(publicStats[0].value);
    if (!app) { setTelegramState("browser"); setLoading(false); return; }
    if (!initData) { setTelegramState("telegram-no-init-data"); setLoading(false); return; }
    setTelegramState("authenticating");
    try { const auth = await playerApi.authenticate(initData); const token = auth.player_token || auth.token; if (!token) throw new Error("Telegram authentication returned no player token"); window.localStorage.setItem("kelembingo.playerToken", token); setPlayer({ ...auth.user, user_id: auth.user.user_id ?? auth.user.id }); setTelegramState("authenticated"); } catch (error) { setPlayer(null); setTelegramState("auth-failed"); setAuthError(error instanceof Error ? error.message : "Telegram authentication failed"); } finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); const interval = window.setInterval(() => void playerApi.stats().then(setStats).catch(() => undefined), 30000); return () => window.clearInterval(interval); }, [refresh]);
  const value = useMemo(() => ({ player, stats, loading, telegramAvailable: telegramState !== "browser" && telegramState !== "detecting", telegramState, authError, refresh, logout: () => { window.localStorage.removeItem("kelembingo.playerToken"); setPlayer(null); setTelegramState("telegram-no-init-data"); } }), [player, stats, loading, telegramState, authError, refresh]);
  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
}
export function usePlayer() { const value = useContext(PlayerContext); if (!value) throw new Error("usePlayer must be used inside PlayerProvider"); return value; }
