// Style reminder: context controls state only; screens remain faithful to the compact dark-glass player shell.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { playerApi, type Player, type PublicStats } from "@/lib/gateway";

type PlayerContextValue = { player: Player | null; stats: PublicStats | null; loading: boolean; telegramAvailable: boolean; refresh: () => Promise<void>; logout: () => void };
const PlayerContext = createContext<PlayerContextValue | null>(null);
function webApp() { return (window as Window & { Telegram?: { WebApp?: { initData?: string; ready?: () => void; expand?: () => void } } }).Telegram?.WebApp; }

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const [player, setPlayer] = useState<Player | null>(null); const [stats, setStats] = useState<PublicStats | null>(null); const [loading, setLoading] = useState(true); const [telegramAvailable, setTelegramAvailable] = useState(false);
  const refresh = useCallback(async () => {
    const app = webApp(); const initData = app?.initData || ""; setTelegramAvailable(Boolean(app)); app?.ready?.(); app?.expand?.();
    const publicStats = await Promise.allSettled([playerApi.stats()]); if (publicStats[0].status === "fulfilled") setStats(publicStats[0].value);
    if (!initData) { setLoading(false); return; }
    try { const auth = await playerApi.authenticate(initData); const token = auth.player_token || auth.token; if (token) window.localStorage.setItem("kelembingo.playerToken", token); setPlayer({ ...auth.user, user_id: auth.user.user_id ?? auth.user.id }); } catch { setPlayer(null); } finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); const interval = window.setInterval(() => void playerApi.stats().then(setStats).catch(() => undefined), 30000); return () => window.clearInterval(interval); }, [refresh]);
  const value = useMemo(() => ({ player, stats, loading, telegramAvailable, refresh, logout: () => { window.localStorage.removeItem("kelembingo.playerToken"); setPlayer(null); } }), [player, stats, loading, telegramAvailable, refresh]);
  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
}
export function usePlayer() { const value = useContext(PlayerContext); if (!value) throw new Error("usePlayer must be used inside PlayerProvider"); return value; }
