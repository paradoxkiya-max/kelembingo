// Style reminder: reproduce legacy home.html in order—brand row, welcome card, 10/20 ETB stake cards, Derash note, live stats, wallet band, and How to Play.

import { Gamepad2, Info, Loader2 } from "lucide-react";
import { useLocation } from "wouter";
import { usePlayer } from "@/contexts/PlayerContext";
import { walletValue } from "@/lib/format";

const statTones = {
  green: { card: "border-emerald-400/30 bg-[linear-gradient(135deg,rgba(16,185,129,0.15),rgba(16,185,129,0.05))]", value: "text-emerald-400", label: "text-emerald-400/60" },
  blue: { card: "border-blue-400/30 bg-[linear-gradient(135deg,rgba(59,130,246,0.15),rgba(59,130,246,0.05))]", value: "text-blue-400", label: "text-blue-400/60" },
  orange: { card: "border-orange-400/30 bg-[linear-gradient(135deg,rgba(255,140,0,0.15),rgba(255,140,0,0.05))]", value: "text-orange-400", label: "text-orange-400/60" },
} as const;

export default function Home() {
  const [, navigate] = useLocation();
  const { player, stats, loading, telegramAvailable } = usePlayer();
  const wallet = walletValue(player?.play_wallet);

  function play(stake: number) {
    if (!player) {
      window.alert(telegramAvailable ? "Telegram authentication is still loading. Please try again in a moment." : "Open KelemBingo inside Telegram to authenticate and play with your real wallet.");
      return;
    }
    navigate(`/select?stake=${stake}`);
  }

  return <div className="min-h-[calc(100vh-56px)] bg-[linear-gradient(180deg,#0D1117_0%,#0A1628_40%,#111827_100%)] pb-4">
    <div className="flex items-center justify-between px-4 py-4"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#FF8C00] to-[#FF6B00] text-xl font-black text-white">B</div><div><h1 className="text-xl font-bold text-white">Kelem Bingo</h1><p className="text-xs text-white/50">Play &amp; Win Big!</p></div></div><button onClick={() => window.alert("Choose a stake, select up to two cartelas, then follow the live calls to complete a row, column, or diagonal.")} className="flex h-9 w-9 items-center justify-center rounded-full border border-white/10 bg-white/[0.06] text-white/70 hover:text-white" aria-label="Show game rules"><Info className="h-5 w-5" /></button></div>
    <section className="mb-6 px-4"><div className="glass rounded-2xl border border-white/10 bg-[#1A1A2E]/75 p-5 text-center"><div className="mb-2 text-3xl">🎯</div><h2 className="mb-1 text-lg font-bold text-white">Welcome to <span className="text-[#FF8C00]">Kelem Bingo</span></h2><p className="text-sm text-white/60">Pick your stake and start playing!</p><div className="mt-2 text-xs font-medium text-[#14B8A6]">{player ? `Hello, ${player.first_name || "player"}!` : telegramAvailable ? "Hello, player!" : "Open inside Telegram to play"}</div></div></section>
    <section className="mb-6 px-4"><div className="grid grid-cols-2 gap-3"><button onClick={() => play(10)} disabled={loading} className="rounded-2xl bg-gradient-to-br from-[#10B981] to-[#059669] p-4 text-center shadow-[0_8px_25px_rgba(16,185,129,0.3)] transition-transform active:scale-[0.97] disabled:cursor-wait disabled:opacity-55"><div className="mb-1 text-2xl">🎮</div><div className="text-lg font-black text-white">10 ETB</div><div className="mt-1 text-[10px] text-white/80">Standard</div></button><button onClick={() => play(20)} disabled={loading} className="rounded-2xl bg-gradient-to-br from-[#8B5CF6] to-[#6D28D9] p-4 text-center shadow-[0_8px_25px_rgba(139,92,246,0.3)] transition-transform active:scale-[0.97] disabled:cursor-wait disabled:opacity-55"><div className="mb-1 text-2xl">🎯</div><div className="text-lg font-black text-white">20 ETB</div><div className="mt-1 text-[10px] text-white/80">High Stakes</div></button></div><p className="mt-2 text-center text-[10px] text-white/40">Max 2 cartelas · Derash = (Cartelas × Stake × 0.75) / Winners</p></section>
    {!telegramAvailable && !loading && <div className="mx-4 mb-6 rounded-xl border border-[#F59E0B]/25 bg-[#F59E0B]/10 px-3 py-2 text-center text-[11px] text-[#FCD34D]">Open KelemBingo inside Telegram to authenticate and play with your real wallet.</div>}
    <section className="mb-6 px-4"><h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/70">Live Stats</h3><div className="grid grid-cols-3 gap-3"><StatCard value={stats?.active_cartelas ?? 0} label="Active Cartelas" tone="green" loading={loading} /><StatCard value={stats?.games_played ?? 0} label="Games Played" tone="blue" loading={loading} /><StatCard value={stats?.winners_today ?? 0} label="Winners Today" tone="orange" loading={loading} /></div></section>
    <section className="mb-6 px-4"><div className="rounded-2xl border border-white/10 bg-[linear-gradient(135deg,rgba(16,185,129,0.12),rgba(255,140,0,0.08))] p-4"><div className="flex items-center justify-between"><span className="text-sm text-emerald-400/70">Wallet Balance</span><span className="text-lg font-black text-emerald-400">{wallet.toLocaleString()} ETB</span></div></div></section>
    <section className="px-4"><div className="glass rounded-2xl border border-white/10 bg-[#1A1A2E]/75 p-4"><h3 className="mb-3 text-sm font-semibold text-white/70">How to Play</h3><div className="space-y-2 text-xs text-white/60"><Step number="1" tone="text-[#10B981]">Choose 10 or 20 ETB stake</Step><Step number="2" tone="text-[#3B82F6]">Pick up to 2 cartelas</Step><Step number="3" tone="text-[#8B5CF6]">Numbers are called — mark your card</Step><Step number="4" tone="text-[#FF8C00]">Complete a row, column, or diagonal to win!</Step><Step number="5" tone="text-[#14B8A6]">Derash is <strong className="font-bold text-white">(Cartelas × Stake × 0.75) / Winners</strong></Step></div></div></section>
  </div>;
}

function StatCard({ value, label, tone, loading }: { value: number; label: string; tone: keyof typeof statTones; loading: boolean }) { const colors = statTones[tone]; return <div className={`rounded-xl border p-3 text-center ${colors.card}`}><div className={`text-xl font-black ${colors.value}`}>{loading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : value.toLocaleString()}</div><div className={`mt-1 text-[10px] ${colors.label}`}>{label}</div></div>; }
function Step({ number, tone, children }: { number: string; tone: string; children: React.ReactNode }) { return <div className="flex items-start gap-2"><span className={`font-bold ${tone}`}>{number}.</span><span>{children}</span></div>; }
