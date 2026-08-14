// Style reminder: preserve the existing Telegram-style header, narrow mobile geometry, orange active nav, and glass surfaces.

import { BarChart3, Gamepad2, History as HistoryIcon, UserRound, WalletCards } from "lucide-react";
import { Link, useLocation } from "wouter";
import { usePlayer } from "@/contexts/PlayerContext";
import { walletValue } from "@/lib/format";

const navItems = [{ href: "/", label: "Home", icon: Gamepad2 }, { href: "/history", label: "History", icon: HistoryIcon }, { href: "/wallet", label: "Wallet", icon: WalletCards }, { href: "/profile", label: "Profile", icon: UserRound }];

export default function PlayerShell({ children }: { children: React.ReactNode }) {
  const [location] = useLocation(); const { player } = usePlayer(); const wallet = walletValue(player?.play_wallet);
  return <div className="player-app min-h-screen bg-[#0D1117] text-white"><div className="mx-auto flex min-h-screen w-full max-w-[420px] flex-col border-x border-white/[0.03] bg-[#0D1117] shadow-[0_0_80px_rgba(0,0,0,0.35)]">
    <header className="telegram-header sticky top-0 z-40 flex h-14 items-center justify-between border-b border-white/[0.06] bg-[#0D1117]/95 px-4 backdrop-blur-xl"><Link href="/" className="flex items-center gap-2.5" aria-label="Kelem Bingo home"><img src="/images/kelembingo-mark.webp" alt="Kelem Bingo mark" className="h-8 w-8 rounded-full object-contain" /><div className="leading-none"><p className="text-[13px] font-black tracking-tight">Kelem Bingo</p><p className="mt-1 text-[9px] font-semibold uppercase tracking-[0.18em] text-white/35">Play to win</p></div></Link><div className="flex items-center gap-2 rounded-xl border border-white/[0.07] bg-white/[0.045] px-2.5 py-1.5"><BarChart3 className="h-3.5 w-3.5 text-[#34D399]" /><div className="text-right leading-none"><p className="text-[9px] uppercase tracking-wider text-white/35">Wallet</p><p className="mt-1 text-[11px] font-black text-[#34D399]">{wallet.toLocaleString()} ETB</p></div></div></header>
    <main className="screen-transition flex-1 pb-20">{children}</main>
    <nav className="fixed bottom-0 left-1/2 z-40 flex w-full max-w-[420px] -translate-x-1/2 items-center justify-around border-t border-white/[0.06] bg-[#111326]/95 px-3 py-2.5 backdrop-blur-xl" aria-label="Player navigation">{navItems.map(({ href, label, icon: Icon }) => { const active = href === "/" ? location === "/" : location.startsWith(href); return <Link key={href} href={href} className={`nav-item flex min-w-[64px] flex-col items-center gap-1 rounded-xl px-2 py-1 text-[10px] font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FF8C00] ${active ? "text-[#FF8C00]" : "text-white/35 hover:text-white/70"}`} aria-current={active ? "page" : undefined}><Icon className="h-4 w-4" strokeWidth={active ? 2.5 : 1.8} />{label}</Link>; })}</nav>
  </div></div>;
}
