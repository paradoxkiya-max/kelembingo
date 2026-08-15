// Style reminder: keep the winner moment celebratory and compact for Telegram WebView, with authoritative winner data and immediate return clarity.

import { Trophy } from "lucide-react";
import type { Cartela } from "@/lib/gateway";
import { etb } from "@/lib/format";

const letters = ["B", "I", "N", "G", "O"];
const colors = ["#3B82F6", "#8B5CF6", "#D946EF", "#10B981", "#F97316"];

export type WinnerAnnouncementData = {
  name: string;
  cartelaNumber: number;
  payout: number;
  isSelf: boolean;
};

export function WinnerAnnouncement({ winner, cartela, called, countdown, onReturn }: { winner: WinnerAnnouncementData; cartela: Cartela | null; called: Set<number>; countdown: number; onReturn: () => void }) {
  const values = flattenCartela(cartela);
  const winnerLabel = winner.isSelf ? "You" : winner.name;
  return <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#070914]/80 p-4 backdrop-blur-md" role="dialog" aria-modal="true" aria-label="Bingo winner announcement">
    <div className="w-full max-w-[350px] overflow-hidden rounded-[28px] border border-white/20 bg-[linear-gradient(145deg,#A63DFF_0%,#E04BDE_44%,#13C89B_120%)] p-px shadow-[0_20px_60px_rgba(168,62,255,0.45)]">
      <div className="rounded-[27px] bg-[linear-gradient(160deg,rgba(32,18,54,0.95),rgba(28,40,78,0.94))] px-5 py-5 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full border border-yellow-300/35 bg-yellow-400/15 text-yellow-300 shadow-[0_0_28px_rgba(250,204,21,0.28)]"><Trophy className="h-8 w-8" /></div>
        <h2 className="mt-2 text-3xl font-black tracking-tight text-[#FFC21A]">BINGO!</h2>
        <div className="mt-3 rounded-2xl border border-white/10 bg-[#201437]/85 px-4 py-3"><p className="text-base font-black text-white">{winnerLabel} won!</p><p className="mt-1 text-[11px] font-semibold text-white/50">Won with Cartela #{winner.cartelaNumber}</p><p className="mt-3 text-[9px] font-black uppercase tracking-[0.16em] text-white/40">Derash</p><p className="mt-1 text-2xl font-black text-emerald-300">{etb(winner.payout)}</p></div>
        <div className="mt-3 overflow-hidden rounded-xl border border-white/10 bg-[#131B35] p-1.5"><div className="grid grid-cols-5 gap-px overflow-hidden rounded-lg">{letters.map((letter, index) => <span key={letter} className="py-1 text-[8px] font-black text-white" style={{ background: colors[index] }}>{letter}</span>)}{values.map((number, index) => { const marked = index === 12 || called.has(number); return <span key={`${winner.cartelaNumber}-${index}`} className={`aspect-square content-center text-[9px] font-black ${marked ? "bg-emerald-500 text-white" : "bg-[#2A2947] text-white/65"}`}>{index === 12 ? "★" : number}</span>; })}</div></div>
        <p className="mt-4 text-xs font-semibold text-white/55">Returning to cartela selection in <span className="font-black text-[#FFC21A]">{countdown}s</span></p>
        <button onClick={onReturn} className="mt-3 w-full rounded-xl bg-white/10 py-2.5 text-xs font-black text-white transition-transform active:scale-[0.98]">Select cartelas now</button>
      </div>
    </div>
  </div>;
}

function flattenCartela(card?: Cartela | null) {
  const source: unknown = card?.cartela || card?.data || card?.grid || [];
  const values = Array.isArray(source) && Array.isArray(source[0]) ? (source as number[][]).reduce<number[]>((all, row) => all.concat(row), []) : Array.isArray(source) ? source as number[] : [];
  return values.length === 25 ? values : Array.from({ length: 25 }, (_, index) => index + 1);
}
