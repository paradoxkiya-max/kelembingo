// Style reminder: reproduce legacy game-board.html: six compact stat pills, 45/55 called-number/cartela split, audio controls, called tags, orange cartela headers, and Leave/Auto controls.

import { Check, Eye, Loader2, Music, Volume2, VolumeX, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearch } from "wouter";
import { usePlayer } from "@/contexts/PlayerContext";
import { playerApi, type Cartela, type Round } from "@/lib/gateway";
import { observeRound } from "@/lib/realtime";
import { etb } from "@/lib/format";

const letters = ["B", "I", "N", "G", "O"];
const colors = ["#3B82F6", "#8B5CF6", "#D946EF", "#10B981", "#F97316"];
const numbers = Array.from({ length: 75 }, (_, index) => index + 1);

export default function GameBoard() {
  const [, navigate] = useLocation();
  const search = useSearch();
  const { player } = usePlayer();
  const roundId = new URLSearchParams(search).get("round") || "";
  const [round, setRound] = useState<Round | null>(null);
  const [cartelas, setCartelas] = useState<Cartela[]>([]);
  const [marked, setMarked] = useState<Record<number, Set<number>>>({});
  const [autoMark, setAutoMark] = useState(true);
  const [voice, setVoice] = useState(true);
  const [music, setMusic] = useState(false);
  const [current, setCurrent] = useState<number | null>(null);
  const [countdown, setCountdown] = useState(0);
  const [timer, setTimer] = useState(0);
  const [claiming, setClaiming] = useState(false);
  const [result, setResult] = useState<{ winner: boolean; payout?: number; message?: string } | null>(null);
  const previousCalled = useRef<number[]>([]);
  const claimAttempts = useRef(new Set<string>());

  useEffect(() => {
    if (!roundId) { navigate("/"); return; }
    let active = true;
    playerApi.round(roundId).then((response) => active && setRound(response.round)).catch(() => active && navigate("/"));
    const unsubscribe = observeRound(roundId, (next) => active && next && setRound(next));
    return () => { active = false; unsubscribe(); };
  }, [navigate, roundId]);

  useEffect(() => {
    const numbersCalled = round?.called_numbers || [];
    const latest = numbersCalled[numbersCalled.length - 1] || null;
    setCurrent(latest);
    if (latest && latest !== previousCalled.current[previousCalled.current.length - 1] && voice) {
      try { window.speechSynthesis?.cancel(); window.speechSynthesis?.speak(new SpeechSynthesisUtterance(`${letters[Math.floor((latest - 1) / 15)]} ${latest}`)); } catch { /* speech is best-effort */ }
    }
    previousCalled.current = numbersCalled;
    if (autoMark && latest) setMarked((old) => { const next = { ...old }; for (const card of cartelas) { const existing = new Set(next[card.number] || []); if (flattenCartela(card).includes(latest)) existing.add(latest); next[card.number] = existing; } return next; });
  }, [round?.called_numbers, voice, autoMark, cartelas]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      const nextAt = round?.next_number_at ? new Date(round.next_number_at).getTime() : 0;
      const start = round?.game_started_at ? new Date(round.game_started_at).getTime() : 0;
      const now = Date.now();
      setTimer(nextAt ? Math.max(0, Math.ceil((nextAt - now) / 1000)) : start ? Math.max(0, Math.ceil((start + 60000 - now) / 1000)) : 0);
      if (round?.status === "selecting" && round.selection_deadline) setCountdown(Math.max(0, Math.ceil((new Date(round.selection_deadline).getTime() - now) / 1000)));
    }, 200);
    return () => window.clearInterval(interval);
  }, [round?.next_number_at, round?.game_started_at, round?.selection_deadline, round?.status]);

  useEffect(() => {
    const ids = round?.players?.[String(player?.user_id || "")]?.cartelas || [];
    if (!ids.length) return;
    let active = true;
    Promise.all(ids.slice(0, 2).map((number) => playerApi.cartela(Number(number)).then((response) => response.cartela))).then((items) => active && setCartelas(items)).catch(() => undefined);
    return () => { active = false; };
  }, [player?.user_id, round?.players]);

  const called = useMemo(() => new Set(round?.called_numbers || []), [round?.called_numbers]);

  useEffect(() => {
    if (!round || !player?.user_id || round.status !== "playing" || claiming) return;
    const calledNumbers = round.called_numbers || [];
    for (const card of cartelas) {
      if (!checkBingoLocal(flattenCartela(card), calledNumbers)) continue;
      const attemptKey = `${roundId}:${card.number}:${calledNumbers.length}`;
      if (claimAttempts.current.has(attemptKey)) continue;
      claimAttempts.current.add(attemptKey);
      void claim(card.number, attemptKey);
      break;
    }
  }, [round, roundId, player?.user_id, cartelas, claiming]);

  async function claim(number: number, attemptKey?: string) {
    if (claiming || !roundId || !player?.user_id) return;
    setClaiming(true);
    try {
      const response = await playerApi.claimBingo(roundId, player.user_id, number);
      if (!response.winner && !response.already_completed && attemptKey) claimAttempts.current.delete(attemptKey);
      setResult(response.winner ? { winner: true, payout: response.prize_per_winner } : { winner: false, message: "The server did not validate this cartela." });
    } catch (e) {
      if (attemptKey) claimAttempts.current.delete(attemptKey);
      setResult({ winner: false, message: e instanceof Error ? e.message : "Claim failed" });
    } finally { setClaiming(false); }
  }

  function mark(cardNumber: number, number: number) { if (called.has(number)) setMarked((old) => ({ ...old, [cardNumber]: new Set([...Array.from(old[cardNumber] || []), number]) })); }

  if (!round) return <div className="flex min-h-[calc(100vh-56px)] items-center justify-center text-white/40"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading round</div>;

  return <div className="flex min-h-[calc(100vh-56px)] flex-col bg-[linear-gradient(180deg,#0D1117_0%,#0A0F18_50%,#111827_100%)] px-2 py-1"><div className="grid grid-cols-3 gap-1.5">{[["GAME", `#${String(round.id || roundId).slice(0, 8)}`, "orange"], ["CARTELAS", round.player_count || 0, "green"], ["BET", etb(round.stake), "blue"], ["DERASH POOL", etb(round.derash || Math.round((round.player_count || 0) * (round.stake || 0) * 0.75 * 10) / 10), "purple"], ["CALLED", called.size, "teal"], ["TIMER", `${timer}s`, "red"]].map(([label, value, tone]) => <div key={String(label)} className={`rounded-xl border px-2 py-1.5 ${toneClass(String(tone))}`}><p className="text-[8px] font-bold uppercase tracking-wider opacity-60">{label}</p><p className="mt-1 text-[10px] font-black">{value}</p></div>)}</div>{round.status === "selecting" && <div className="mt-1 rounded-xl border border-purple-400/30 bg-purple-500/20 px-4 py-2 text-center text-xs font-black text-purple-200">Game starting soon · selection {countdown}s</div>}<div className="mt-1 flex min-h-0 flex-1 gap-2 pb-3"><section className="order-1 flex w-[45%] flex-col rounded-2xl border border-white/[0.06] bg-[#1A1A2E]/70 p-2 backdrop-blur-md"><div className="mb-1.5 grid grid-cols-5 gap-0.5">{letters.map((letter, index) => <div key={letter} className="rounded-lg py-1 text-center text-[10px] font-black text-white" style={{ background: colors[index] }}>{letter}</div>)}</div><div className="grid flex-1 grid-cols-5 gap-px overflow-hidden">{numbers.map((number) => <div key={number} className={`flex aspect-square items-center justify-center rounded-[3px] text-[8px] font-black transition-all ${called.has(number) ? "text-white shadow-[0_0_8px_rgba(255,255,255,0.35)]" : "bg-white/[0.02] text-white/25"}`} style={called.has(number) ? { background: colors[Math.floor((number - 1) / 15)] } : undefined}>{number}</div>)}</div></section><section className="order-2 flex w-[55%] flex-col rounded-2xl border border-white/[0.06] bg-[#1A1A2E]/70 p-2 backdrop-blur-md"><div className="flex items-center justify-center gap-2 py-1"><button onClick={() => setVoice((value) => !value)} aria-label="Toggle voice" className="audio-btn flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.08] text-white/70">{voice ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}</button><div className="number-circle-outer flex h-14 w-14 items-center justify-center rounded-full bg-[conic-gradient(from_0deg,#FFD700,#FF8C00,#FFD700,#FF8C00,#FFD700)] p-[3px]">{current ? <div className="flex h-full w-full flex-col items-center justify-center rounded-full border-2 border-yellow-300/30 bg-[radial-gradient(circle,#1A1A2E_60%,#0D1117_100%)]"><span className="text-[10px] font-black" style={{ color: colors[Math.floor((current - 1) / 15)] }}>{letters[Math.floor((current - 1) / 15)]}</span><span className="text-lg font-black">{current}</span></div> : <div className="flex h-full w-full items-center justify-center rounded-full bg-[#1A1A2E] text-[9px] text-white/30">Waiting</div>}</div><button onClick={() => setMusic((value) => !value)} aria-label="Toggle music" className="audio-btn flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.08] text-white/70"><Music className="h-4 w-4" /></button></div><div className="my-1 h-px bg-white/[0.06]" /><div className="flex min-h-[22px] gap-1 overflow-x-auto py-1 [scrollbar-width:none]">{(round.called_numbers || []).slice(-12).map((number) => <span key={number} className={`called-tag flex min-w-[36px] flex-col items-center rounded-lg border px-2 py-[3px] ${tagClass(number)}`}><span className="text-[8px] font-bold leading-none" style={{ color: colors[Math.floor((number - 1) / 15)] }}>{letters[Math.floor((number - 1) / 15)]}</span><span className="text-[11px] font-black leading-tight text-white">{number}</span></span>)}</div><div className="my-1 h-px bg-white/[0.06]" /><div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto">{cartelas.length ? cartelas.map((card) => <CartelaCard key={card.number} card={card} marked={marked[card.number] || new Set()} called={called} onMark={(number) => mark(card.number, number)} />) : <div className="flex flex-1 flex-col items-center justify-center px-2 py-4 text-center"><Eye className="mb-2 h-7 w-7 text-[#FF8C00]" /><p className="mb-1 text-sm font-bold text-[#FF8C00]">Spectating</p><p className="text-xs text-white/40">Join next round to play!</p></div>}</div></section></div><div className="section-separator mx-2 h-px bg-white/[0.08]" /><div className="mt-auto px-2 py-2"><div className="flex items-center justify-between gap-2 rounded-2xl border border-white/[0.08] bg-[#1A1A2E]/80 px-3 py-2 backdrop-blur-xl"><button onClick={() => navigate("/")} className="flex items-center gap-1.5 rounded-xl border border-red-500/25 bg-red-500/15 px-3 py-2 text-[11px] font-semibold text-red-400 transition-transform active:scale-95"><X className="h-3.5 w-3.5" /> Leave</button><div className="flex items-center gap-2"><span className="text-[9px] font-medium uppercase tracking-wider text-white/40">Auto</span><button onClick={() => setAutoMark((value) => !value)} className={`relative h-6 w-11 rounded-full border transition-colors ${autoMark ? "border-emerald-400/50 bg-emerald-500" : "border-white/15 bg-white/10"}`} aria-pressed={autoMark} aria-label="Toggle auto mark"><span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${autoMark ? "translate-x-[22px]" : "translate-x-0.5"}`} /></button></div><button onClick={() => setAutoMark((value) => !value)} className="rounded-xl border border-orange-400/30 bg-gradient-to-br from-orange-400/20 to-orange-500/20 px-3 py-2 text-[11px] font-bold text-[#FF8C00] transition-transform active:scale-95">AUTO</button></div></div>{result && <ResultModal result={result} onClose={() => setResult(null)} />}</div>;
}

function CartelaCard({ card, marked, called, onMark }: { card: Cartela; marked: Set<number>; called: Set<number>; onMark: (number: number) => void }) { const values = flattenCartela(card); return <div className="cartela-container overflow-hidden rounded-xl border border-orange-400/30"><div className="cartela-header bg-gradient-to-br from-[#FF8C00] to-[#FF6B00] py-1 text-center text-[10px] font-black tracking-wider text-white">CARTELA NO: {card.number}</div><div className="grid grid-cols-5 gap-px" style={{ background: "rgba(26,26,46,0.5)" }}>{letters.map((letter, index) => <div key={letter} className="py-0.5 text-center text-[8px] font-black text-white" style={{ background: colors[index] }}>{letter}</div>)}{values.map((number, index) => { const isMarked = marked.has(number) || (index === 12 && true); return <button key={`${card.number}-${index}`} onClick={() => onMark(number)} className={`cartela-cell aspect-square text-[9px] font-black transition-transform active:scale-90 ${isMarked ? "marked bg-gradient-to-br from-[#10B981] to-[#059669] text-white shadow-[0_0_8px_rgba(16,185,129,0.3)]" : "bg-[rgba(30,35,64,0.8)] text-white/75"}`} disabled={!called.has(number) && index !== 12}>{index === 12 ? "★" : number}</button>; })}</div></div>; }
function flattenCartela(card?: Cartela) { const source: unknown = card?.data || card?.grid || []; const values = Array.isArray(source) && Array.isArray(source[0]) ? (source as number[][]).reduce<number[]>((all, row) => all.concat(row), []) : Array.isArray(source) ? source as number[] : []; return values.length === 25 ? values : Array.from({ length: 25 }, (_, index) => index + 1); }
function checkBingoLocal(flat: number[], called: number[]) { const calledSet = new Set(called); const grid = Array.from({ length: 5 }, (_, row) => flat.slice(row * 5, row * 5 + 5)); const marked = (number: number) => number === 0 || calledSet.has(number); for (let row = 0; row < 5; row += 1) if (grid[row].every(marked)) return true; for (let column = 0; column < 5; column += 1) if (grid.every((row) => marked(row[column]))) return true; if ([0, 1, 2, 3, 4].every((index) => marked(grid[index][index]))) return true; if ([0, 1, 2, 3, 4].every((index) => marked(grid[index][4 - index]))) return true; return [[0, 0], [0, 4], [4, 0], [4, 4]].every(([row, column]) => { const number = grid[row][column]; return number !== 0 && calledSet.has(number); }); }
function toneClass(tone: string) { return tone === "orange" ? "border-[#FF8C00]/30 bg-[#FF8C00]/10 text-[#FF8C00]" : tone === "green" ? "border-[#10B981]/30 bg-[#10B981]/10 text-[#34D399]" : tone === "blue" ? "border-[#3B82F6]/30 bg-[#3B82F6]/10 text-[#60A5FA]" : tone === "purple" ? "border-[#A855F7]/30 bg-[#A855F7]/10 text-[#C084FC]" : tone === "teal" ? "border-[#14B8A6]/30 bg-[#14B8A6]/10 text-[#2DD4BF]" : "border-red-400/30 bg-red-500/10 text-red-300"; }
function tagClass(number: number) { return ["border-blue-400/40 bg-blue-500/20", "border-violet-400/40 bg-violet-500/20", "border-fuchsia-400/40 bg-fuchsia-500/20", "border-emerald-400/40 bg-emerald-500/20", "border-orange-400/40 bg-orange-500/20"][Math.floor((number - 1) / 15)] || "border-white/10 bg-white/5"; }
function ResultModal({ result, onClose }: { result: { winner: boolean; payout?: number; message?: string }; onClose: () => void }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"><div className="w-full max-w-[360px] rounded-3xl border border-white/10 bg-[#1A1A2E] p-6 text-center shadow-2xl"><div className={`mx-auto flex h-16 w-16 items-center justify-center rounded-full ${result.winner ? "bg-[#10B981]/20 text-[#34D399]" : "bg-red-500/15 text-red-300"}`}>{result.winner ? <Check className="h-8 w-8" /> : <X className="h-8 w-8" />}</div><h2 className="mt-4 text-xl font-black">{result.winner ? "Bingo verified" : "Claim not verified"}</h2>{result.winner ? <p className="mt-2 text-sm text-white/45">PRIZE PER WINNER</p> : null}<p className={`mt-1 text-2xl font-black ${result.winner ? "text-[#FFB45C]" : "text-red-300"}`}>{result.winner ? etb(result.payout) : result.message}</p><button onClick={onClose} className="mt-5 w-full rounded-xl bg-[#FF8C00] py-3 text-xs font-black text-white">Close</button></div></div>; }
