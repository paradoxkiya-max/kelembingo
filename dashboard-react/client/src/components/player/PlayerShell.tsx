// Style reminder: replicate the legacy Telegram Mini App chrome: compact centered title bar, close/overflow controls, and fixed four-item bottom nav.

import { Clock3, Gamepad2, History as HistoryIcon, MoreVertical, UserRound, WalletCards, X } from "lucide-react";
import { Link, useLocation } from "wouter";

const navItems = [
  { href: "/", label: "Game", icon: Gamepad2 },
  { href: "/history", label: "History", icon: HistoryIcon },
  { href: "/wallet", label: "Wallet", icon: WalletCards },
  { href: "/profile", label: "Profile", icon: UserRound },
];

type TelegramApp = { close?: () => void; showPopup?: (options: { title: string; message: string }) => void };

function telegramApp() {
  return (window as Window & { Telegram?: { WebApp?: TelegramApp } }).Telegram?.WebApp;
}

export default function PlayerShell({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const immersive = location === "/select" || location === "/game";

  return <div className="player-app min-h-screen bg-[#0D1117] text-white"><div className="mx-auto flex min-h-screen w-full max-w-[420px] flex-col bg-[linear-gradient(180deg,#0D1117_0%,#0A1628_42%,#111827_100%)] shadow-[0_0_80px_rgba(0,0,0,0.35)]">
    <header className="telegram-header sticky top-0 z-40 flex h-14 shrink-0 items-center justify-between border-b border-white/10 bg-[#0D1117]/95 px-4 backdrop-blur-sm">
      <button onClick={() => telegramApp()?.close?.()} className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-white/70 transition-colors hover:text-white" aria-label="Close Kelem Bingo"><X className="h-4 w-4" /></button>
      <span className="text-sm font-semibold text-white">Kelem Bingo</span>
      <button onClick={() => telegramApp()?.showPopup?.({ title: "Kelem Bingo", message: "A fun bingo game! Select stake and play." })} className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-white/70 transition-colors hover:text-white" aria-label="About Kelem Bingo"><MoreVertical className="h-4 w-4" /></button>
    </header>
    <main className={`screen-transition flex-1 ${immersive ? "pb-0" : "pb-20"}`}>{children}</main>
    {!immersive && <nav className="fixed bottom-0 left-1/2 z-40 flex w-full max-w-[420px] -translate-x-1/2 items-center justify-around border-t border-white/10 bg-[#0D1117]/95 px-3 py-2 backdrop-blur-sm" aria-label="Player navigation">{navItems.map(({ href, label, icon: Icon }) => { const active = href === "/" ? location === "/" : location.startsWith(href); return <Link key={href} href={href} className={`nav-item flex flex-col items-center gap-1 px-4 py-1 text-[10px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FF8C00] ${active ? "text-[#FF8C00]" : "text-white/90 hover:text-white"}`} aria-current={active ? "page" : undefined}><Icon className="h-6 w-6" strokeWidth={active ? 2.5 : 2} />{label}</Link>; })}</nav>}
  </div></div>;
}
