// Style reminder: keep the legacy compact dark-glass game board, but make live state authoritative, stable, and immediately legible on Telegram WebView.

import { Check, Eye, Loader2, Music, Volume2, VolumeX, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearch } from "wouter";
import { usePlayer } from "@/contexts/PlayerContext";
import { playerApi, type Cartela, type Round } from "@/lib/gateway";
import { observeRound } from "@/lib/realtime";
import { etb } from "@/lib/format";
import { Switch } from "@/components/ui/switch";
import { WinnerAnnouncement, type WinnerAnnouncementData } from "@/components/player/WinnerAnnouncement";

const letters = ["B", "I", "N", "G", "O"];
const colors = ["#3B82F6", "#8B5CF6", "#D946EF", "#10B981", "#F97316"];
const numbers = Array.from({ length: 75 }, (_, index) => index + 1);
const EMPTY_MARKED = new Set<number>();

function statusRank(status?: string) { return status === "completed" ? 3 : status === "playing" ? 2 : status === "selecting" ? 1 : 0; }

export default function GameBoard() {
  const [, navigate] = useLocation();
  const search = useSearch();
  const roundId = new URLSearchParams(search).get("round") || "";
  const { player } = usePlayer();
  const playerId = String(player?.user_id || "");
  const [round, setRound] = useState<Round | null>(null);
  const selectionPath = `/select?stake=${encodeURIComponent(String(Number(round?.stake) || 10))}`;
  const [loadError, setLoadError] = useState("");
  const [cartelas, setCartelas] = useState<Cartela[]>([]);
  const [cardsLoading, setCardsLoading] = useState(false);
  const [cardError, setCardError] = useState("");
  const [marked, setMarked] = useState<Record<number, Set<number>>>({});
  const [autoMark, setAutoMark] = useState(true);
  const [voice, setVoice] = useState(true);
  const [music, setMusic] = useState(false);
  const [current, setCurrent] = useState<number | null>(null);
  const [countdown, setCountdown] = useState(0);
  const [timer, setTimer] = useState(0);
  const [claiming, setClaiming] = useState(false);
  const [claimError, setClaimError] = useState("");
  const [winnerAnnouncement, setWinnerAnnouncement] = useState<(WinnerAnnouncementData & { key: string }) | null>(null);
  const [winnerCartela, setWinnerCartela] = useState<Cartela | null>(null);
  const [returnCountdown, setReturnCountdown] = useState(10);
  const previousCalled = useRef<number[] | null>(null);
  const claimAttempts = useRef(new Set<string>());
  const callAudio = useRef<HTMLAudioElement | null>(null);
  const cartelaAudio = useRef<HTMLAudioElement | null>(null);
  const audioWarmupDone = useRef(false);
  const announcedWinner = useRef("");

  const applyRound = useCallback((next: Round | null) => {
    if (!next) { setRound(null); return; }
    setRound((previous) => {
      if (!previous) return next;
      const previousCalls = previous.called_numbers?.length || 0;
      const nextCalls = next.called_numbers?.length || 0;
      if (nextCalls < previousCalls || statusRank(next.status) < statusRank(previous.status)) return previous;
      return next;
    });
  }, []);

  useEffect(() => {
    if (!roundId) { navigate("/", { replace: true }); return; }
    setRound(null);
    setLoadError("");
    const unsubscribe = observeRound(roundId, applyRound, { onError: () => setLoadError("This round is no longer available. Please choose a new stake.") });
    return unsubscribe;
  }, [applyRound, navigate, roundId]);

  const playerCartelaKey = (round?.players?.[playerId]?.cartelas || []).slice(0, 2).map(Number).join(",");
  const hasPlayerEntry = Boolean(playerId && round?.players && Object.prototype.hasOwnProperty.call(round.players, playerId));

  useEffect(() => {
    if (!hasPlayerEntry || !playerCartelaKey) { setCartelas([]); setCardsLoading(false); return; }
    const ids = playerCartelaKey.split(",").map(Number).filter((number) => Number.isInteger(number) && number > 0);
    if (!ids.length) { setCartelas([]); setCardsLoading(false); return; }
    let active = true;
    setCardsLoading(true);
    setCardError("");
    Promise.all(ids.map((number) => playerApi.cartela(number).then((response) => response.cartela)))
      .then((items) => { if (active) setCartelas(items.filter(Boolean)); })
      .catch(() => { if (active) { setCartelas([]); setCardError("Your cartela could not be loaded. The round is still being watched safely."); } })
      .finally(() => { if (active) setCardsLoading(false); });
    return () => { active = false; };
  }, [hasPlayerEntry, playerCartelaKey]);

  const calledNumbers = round?.called_numbers || [];
  const called = useMemo(() => new Set(calledNumbers), [calledNumbers]);

  useEffect(() => {
    const latest = calledNumbers[calledNumbers.length - 1] || null;
    const previous = previousCalled.current;
    setCurrent(latest);
    if (voice && previous !== null && latest && calledNumbers.length > previous.length) playNumberAudio(latest, callAudio);
    previousCalled.current = calledNumbers;
  }, [calledNumbers, voice]);

  useEffect(() => {
    if (!autoMark || !cartelas.length || !calledNumbers.length) return;
    const calledSet = new Set(calledNumbers);
    setMarked((old) => {
      const next = { ...old };
      let changed = false;
      for (const card of cartelas) {
        const existing = new Set(next[card.number] || []);
        for (const value of flattenCartela(card)) if (calledSet.has(value)) existing.add(value);
        if (existing.size !== (next[card.number]?.size || 0)) { next[card.number] = existing; changed = true; }
      }
      return changed ? next : old;
    });
  }, [autoMark, calledNumbers, cartelas]);

  useEffect(() => {
    const syncClock = () => {
      const now = Date.now();
      const nextAt = round?.next_number_at ? new Date(round.next_number_at).getTime() : 0;
      const selectionAt = round?.selection_deadline ? new Date(round.selection_deadline).getTime() : 0;
      const nextTimer = nextAt ? Math.max(0, Math.ceil((nextAt - now) / 1000)) : 0;
      const nextCountdown = round?.status === "selecting" && selectionAt ? Math.max(0, Math.ceil((selectionAt - now) / 1000)) : 0;
      setTimer((old) => old === nextTimer ? old : nextTimer);
      setCountdown((old) => old === nextCountdown ? old : nextCountdown);
    };
    syncClock();
    const interval = window.setInterval(syncClock, 1000);
    return () => window.clearInterval(interval);
  }, [round?.next_number_at, round?.selection_deadline, round?.status]);

  useEffect(() => {
    if (audioWarmupDone.current || round?.status !== "playing" || timer > 4 || timer < 1) return;
    audioWarmupDone.current = true;
    warmNumberAudio();
  }, [round?.status, timer]);

  useEffect(() => {
    if (!round || round.status !== "completed") return;
    const winnerId = String(round.winners?.[0] || "");
    const cartelaNumber = Number(round.winning_cartela || 0);
    if (!winnerId || !Number.isInteger(cartelaNumber) || cartelaNumber < 1) {
      navigate("/", { replace: true });
      return;
    }
    const key = `${round.id || roundId}:${winnerId}:${cartelaNumber}`;
    const name = round.winner_name || round.players?.[winnerId]?.name || "Player";
    setWinnerAnnouncement({ key, name, cartelaNumber, payout: Number(round.prize_per_winner || 0), isSelf: winnerId === playerId });
    if (announcedWinner.current !== key) {
      announcedWinner.current = key;
      if (voice) playCartelaAudio(cartelaNumber, cartelaAudio);
    }
  }, [navigate, playerId, round, roundId, selectionPath, voice]);

  useEffect(() => {
    if (!winnerAnnouncement) { setWinnerCartela(null); return; }
    let active = true;
    playerApi.cartela(winnerAnnouncement.cartelaNumber).then((response) => {
      if (active) setWinnerCartela(response.cartela);
    }).catch(() => { if (active) setWinnerCartela(null); });
    return () => { active = false; };
  }, [winnerAnnouncement?.key]);

  useEffect(() => {
    if (!winnerAnnouncement) return;
    setReturnCountdown(10);
    const timerId = window.setInterval(() => setReturnCountdown((seconds) => seconds > 0 ? seconds - 1 : 0), 1000);
    return () => window.clearInterval(timerId);
  }, [winnerAnnouncement?.key]);

  useEffect(() => {
    if (winnerAnnouncement && returnCountdown === 0) navigate(selectionPath, { replace: true });
  }, [navigate, returnCountdown, selectionPath, winnerAnnouncement]);

  useEffect(() => {
    if (!round || round.status !== "playing" || !playerId || claiming) return;
    for (const card of cartelas) {
      if (!checkBingoLocal(flattenCartela(card), calledNumbers)) continue;
      const attemptKey = `${roundId}:${card.number}:${calledNumbers.length}`;
      if (claimAttempts.current.has(attemptKey)) continue;
      claimAttempts.current.add(attemptKey);
      void claim(card.number, attemptKey);
      break;
    }
  }, [calledNumbers, cartelas, claiming, playerId, round?.status, roundId]);

  async function claim(number: number, attemptKey?: string) {
    if (claiming || !roundId || !player?.user_id) return;
    setClaiming(true);
    try {
      const response = await playerApi.claimBingo(roundId, player.user_id, number);
      if (!response.winner && !response.already_completed && attemptKey) claimAttempts.current.delete(attemptKey);
      if (!response.winner && !response.already_completed) setClaimError("The server did not validate this cartela.");
    } catch (error) {
      if (attemptKey) claimAttempts.current.delete(attemptKey);
      setClaimError(error instanceof Error ? error.message : "Claim failed");
    } finally { setClaiming(false); }
  }

  function mark(cardNumber: number, number: number) {
    if (!called.has(number)) return;
    setMarked((old) => ({ ...old, [cardNumber]: new Set([...Array.from(old[cardNumber] || []), number]) }));
  }

  if (!round) return <div className="flex min-h-[calc(100vh-56px)] flex-col items-center justify-center gap-3 px-6 text-center text-white/45">{loadError ? <><p className="text-sm text-red-300">{loadError}</p><button onClick={() => navigate("/", { replace: true })} className="rounded-xl bg-[#FF8C00] px-5 py-2.5 text-xs font-black text-white">Choose a stake</button></> : <><Loader2 className="h-5 w-5 animate-spin" /><p className="text-xs">Connecting to the live round…</p></>}</div>;

  const isSpectator = !cardsLoading && cartelas.length === 0;
  const roundStatusLabel = round.status === "completed" ? "Round complete" : round.status === "selecting" ? `Selection ${countdown > 0 ? `${countdown}s` : "Go"}` : isSpectator ? "Spectating live" : "Live game";
  const displayTimer = round.status === "selecting" ? (countdown > 0 ? `${countdown}s` : "Go") : timer > 0 ? `${timer}s` : "Go";
  const sharedDerashPool = roundDerashPool(round);

  return <div className="flex min-h-[calc(100vh-56px)] flex-col bg-[linear-gradient(180deg,#0D1117_0%,#0A0F18_50%,#111827_100%)] px-2 py-1">
    <div className="mb-1 flex items-center justify-between rounded-xl border border-white/[0.06] bg-[#1A1A2E]/60 px-3 py-1.5"><span className="text-[10px] font-black uppercase tracking-wider text-white/65">{roundStatusLabel}</span><span className="text-[10px] font-bold text-white/35">#{String(round.id || roundId).slice(0, 8)}</span></div>
    <div className="grid grid-cols-3 gap-1.5">{[["GAME", `#${String(round.id || roundId).slice(0, 8)}`, "orange"], ["CARTELAS", round.player_count || 0, "green"], ["BET", etb(round.stake), "blue"], ["DERASH POOL", etb(sharedDerashPool), "purple"], ["CALLED", called.size, "teal"], ["TIMER", displayTimer, "red"]].map(([label, value, tone]) => <div key={String(label)} className={`rounded-xl border px-2 py-1.5 ${toneClass(String(tone))}`}><p className="text-[8px] font-bold uppercase tracking-wider opacity-60">{label}</p><p className="mt-1 text-[10px] font-black">{value}</p></div>)}</div>
    {round.status === "selecting" && <div className="mt-1 rounded-xl border border-purple-400/30 bg-purple-500/20 px-4 py-2 text-center text-xs font-black text-purple-200">Game starting soon · selection {countdown > 0 ? `${countdown}s` : "Go"}</div>}
    <div className="mt-1 flex min-h-0 flex-1 gap-2 pb-3">
      <section className="order-1 flex w-[45%] flex-col rounded-2xl border border-white/[0.06] bg-[#1A1A2E]/70 p-2 backdrop-blur-md"><div className="mb-1.5 grid grid-cols-5 gap-0.5">{letters.map((letter, index) => <div key={letter} className="rounded-lg py-1 text-center text-[10px] font-black text-white" style={{ background: colors[index] }}>{letter}</div>)}</div><div className="grid flex-1 grid-cols-5 gap-px overflow-hidden">{numbers.map((number) => <div key={number} className={`flex aspect-square items-center justify-center rounded-[3px] text-[8px] font-black ${called.has(number) ? "text-white shadow-[0_0_8px_rgba(255,255,255,0.35)]" : "bg-white/[0.02] text-white/25"}`} style={called.has(number) ? { background: colors[Math.floor((number - 1) / 15)] } : undefined}>{number}</div>)}</div></section>
      <section className="order-2 flex w-[55%] flex-col rounded-2xl border border-white/[0.06] bg-[#1A1A2E]/70 p-2 backdrop-blur-md"><div className="flex items-center justify-center gap-2 py-1"><button onClick={() => setVoice((value) => !value)} aria-label="Toggle voice" className={`audio-btn flex h-8 w-8 shrink-0 items-center justify-center rounded-full border ${voice ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-300" : "border-white/10 bg-white/[0.08] text-white/45"}`}>{voice ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}</button><div className="number-circle-outer flex h-14 w-14 items-center justify-center rounded-full bg-[conic-gradient(from_0deg,#FFD700,#FF8C00,#FFD700,#FF8C00,#FFD700)] p-[3px]">{current ? <div className="flex h-full w-full flex-col items-center justify-center rounded-full border-2 border-yellow-300/30 bg-[radial-gradient(circle,#1A1A2E_60%,#0D1117_100%)]"><span className="text-[10px] font-black" style={{ color: colors[Math.floor((current - 1) / 15)] }}>{letters[Math.floor((current - 1) / 15)]}</span><span className="text-lg font-black">{current}</span></div> : <div className="flex h-full w-full items-center justify-center rounded-full bg-[#1A1A2E] text-[9px] text-white/30">Waiting</div>}</div><button onClick={() => setMusic((value) => !value)} aria-label="Toggle music" className={`audio-btn flex h-8 w-8 shrink-0 items-center justify-center rounded-full border ${music ? "border-orange-400/30 bg-orange-500/10 text-orange-300" : "border-white/10 bg-white/[0.08] text-white/45"}`}><Music className="h-4 w-4" /></button></div><div className="my-1 h-px bg-white/[0.06]" /><div className="flex min-h-[22px] gap-1 overflow-x-auto py-1 [scrollbar-width:none]">{calledNumbers.slice(-12).map((number) => <span key={number} className={`called-tag flex min-w-[36px] flex-col items-center rounded-lg border px-2 py-[3px] ${tagClass(number)}`}><span className="text-[8px] font-bold leading-none" style={{ color: colors[Math.floor((number - 1) / 15)] }}>{letters[Math.floor((number - 1) / 15)]}</span><span className="text-[11px] font-black leading-tight text-white">{number}</span></span>)}</div><div className="my-1 h-px bg-white/[0.06]" /><div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto">{cardsLoading ? <div className="flex flex-1 flex-col items-center justify-center text-center text-white/40"><Loader2 className="mb-2 h-5 w-5 animate-spin text-[#FF8C00]" /><p className="text-xs">Loading your cartelas…</p></div> : cartelas.length ? cartelas.map((card) => <CartelaCard key={card.number} card={card} marked={marked[card.number] || EMPTY_MARKED} called={called} onMark={(number) => mark(card.number, number)} />) : <div className="flex flex-1 flex-col items-center justify-center px-2 py-4 text-center"><Eye className="mb-2 h-7 w-7 text-[#FF8C00]" /><p className="mb-1 text-sm font-bold text-[#FFB45C]">Spectating mode</p><p className="text-xs leading-5 text-white/45">You are watching this round. Join the next selecting round to play with a cartela.</p>{cardError && <p className="mt-2 text-[10px] text-red-300">{cardError}</p>}</div>}</div></section>
    </div>
    <div className="section-separator mx-2 h-px bg-white/[0.08]" /><div className="mt-auto px-2 py-2"><div className="flex items-center justify-between gap-2 rounded-2xl border border-white/[0.08] bg-[#1A1A2E]/80 px-3 py-2 backdrop-blur-xl"><button onClick={() => navigate("/", { replace: true })} className="flex items-center gap-1.5 rounded-xl border border-red-500/25 bg-red-500/15 px-3 py-2 text-[11px] font-semibold text-red-400 transition-transform active:scale-95"><X className="h-3.5 w-3.5" /> Leave</button><label className={`flex items-center gap-2 rounded-xl border px-3 py-2 ${autoMark ? "border-emerald-400/30 bg-emerald-500/10" : "border-white/10 bg-white/[0.04]"}`}><span className={`text-[10px] font-black uppercase tracking-wider ${autoMark ? "text-emerald-300" : "text-white/45"}`}>Auto mark</span><Switch checked={autoMark} onCheckedChange={setAutoMark} aria-label="Toggle automatic number marking" className="h-5 w-9 border-white/10 data-[state=checked]:bg-emerald-500 data-[state=unchecked]:bg-white/15 [&_[data-slot=switch-thumb]]:size-4" /></label></div></div>
    {claimError && <ResultModal result={{ winner: false, message: claimError }} onClose={() => setClaimError("")} />}
    {winnerAnnouncement && <WinnerAnnouncement winner={winnerAnnouncement} cartela={winnerCartela} called={called} countdown={returnCountdown} onReturn={() => navigate(selectionPath, { replace: true })} />}
  </div>;
}

function CartelaCard({ card, marked, called, onMark }: { card: Cartela; marked: Set<number>; called: Set<number>; onMark: (number: number) => void }) { const values = flattenCartela(card); return <div className="cartela-container overflow-hidden rounded-xl border border-orange-400/30"><div className="cartela-header bg-gradient-to-br from-[#FF8C00] to-[#FF6B00] py-1 text-center text-[10px] font-black tracking-wider text-white">CARTELA NO: {card.number}</div><div className="grid grid-cols-5 gap-px" style={{ background: "rgba(26,26,46,0.5)" }}>{letters.map((letter, index) => <div key={letter} className="py-0.5 text-center text-[8px] font-black text-white" style={{ background: colors[index] }}>{letter}</div>)}{values.map((number, index) => { const isMarked = marked.has(number) || index === 12; return <button key={`${card.number}-${index}`} onClick={() => onMark(number)} className={`cartela-cell aspect-square text-[9px] font-black transition-transform active:scale-90 ${isMarked ? "marked bg-gradient-to-br from-[#10B981] to-[#059669] text-white shadow-[0_0_8px_rgba(16,185,129,0.3)]" : "bg-[rgba(30,35,64,0.8)] text-white/75"}`} disabled={!called.has(number) && index !== 12}>{index === 12 ? "★" : number}</button>; })}</div></div>; }
function roundDerashPool(round: Round) { const authoritative = Number(round.derash); if (Number.isFinite(authoritative) && authoritative >= 0) return authoritative; const cartelas = Math.max(0, Number(round.player_count) || 0); const stake = Math.max(0, Number(round.stake) || 0); return Math.round(cartelas * stake * 0.80 * 100) / 100; }
function flattenCartela(card?: Cartela) { const source: unknown = card?.cartela || card?.data || card?.grid || []; const values = Array.isArray(source) && Array.isArray(source[0]) ? (source as number[][]).reduce<number[]>((all, row) => all.concat(row), []) : Array.isArray(source) ? source as number[] : []; return values.length === 25 ? values : Array.from({ length: 25 }, (_, index) => index + 1); }
function playNumberAudio(number: number, audioRef: { current: HTMLAudioElement | null }) { const letter = letters[Math.floor((number - 1) / 15)]; const audio = new Audio(`/audio/${letter}${number}.mp3`); audio.preload = "auto"; audioRef.current?.pause(); audioRef.current = audio; void audio.play().catch(() => undefined); }
function warmNumberAudio() { ["B1", "I16", "N31", "G46", "O61"].forEach((call) => { const audio = new Audio(`/audio/${call}.mp3`); audio.preload = "auto"; audio.load(); }); }
function playCartelaAudio(number: number, audioRef: { current: HTMLAudioElement | null }) { const audio = new Audio(`/audio/cartela_bingo/cartela_${number}.mp3`); audio.preload = "auto"; audioRef.current?.pause(); audioRef.current = audio; void audio.play().catch(() => undefined); }
function checkBingoLocal(flat: number[], called: number[]) { const calledSet = new Set(called); const grid = Array.from({ length: 5 }, (_, row) => flat.slice(row * 5, row * 5 + 5)); const marked = (number: number) => number === 0 || calledSet.has(number); for (let row = 0; row < 5; row += 1) if (grid[row].every(marked)) return true; for (let column = 0; column < 5; column += 1) if (grid.every((row) => marked(row[column]))) return true; if ([0, 1, 2, 3, 4].every((index) => marked(grid[index][index]))) return true; if ([0, 1, 2, 3, 4].every((index) => marked(grid[index][4 - index]))) return true; return [[0, 0], [0, 4], [4, 0], [4, 4]].every(([row, column]) => { const number = grid[row][column]; return number !== 0 && calledSet.has(number); }); }
function toneClass(tone: string) { return tone === "orange" ? "border-[#FF8C00]/30 bg-[#FF8C00]/10 text-[#FF8C00]" : tone === "green" ? "border-[#10B981]/30 bg-[#10B981]/10 text-[#34D399]" : tone === "blue" ? "border-[#3B82F6]/30 bg-[#3B82F6]/10 text-[#60A5FA]" : tone === "purple" ? "border-[#A855F7]/30 bg-[#A855F7]/10 text-[#C084FC]" : tone === "teal" ? "border-[#14B8A6]/30 bg-[#14B8A6]/10 text-[#2DD4BF]" : "border-red-400/30 bg-red-500/10 text-red-300"; }
function tagClass(number: number) { return ["border-blue-400/40 bg-blue-500/20", "border-violet-400/40 bg-violet-500/20", "border-fuchsia-400/40 bg-fuchsia-500/20", "border-emerald-400/40 bg-emerald-500/20", "border-orange-400/40 bg-orange-500/20"][Math.floor((number - 1) / 15)] || "border-white/10 bg-white/5"; }
function ResultModal({ result, onClose }: { result: { winner: boolean; payout?: number; message?: string }; onClose: () => void }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={result.winner ? "Bingo verified" : "Claim result"}><div className="w-full max-w-[360px] rounded-3xl border border-white/10 bg-[#1A1A2E] p-6 text-center shadow-2xl"><div className={`mx-auto flex h-16 w-16 items-center justify-center rounded-full ${result.winner ? "bg-[#10B981]/20 text-[#34D399]" : "bg-red-500/15 text-red-300"}`}>{result.winner ? <Check className="h-8 w-8" /> : <X className="h-8 w-8" />}</div><h2 className="mt-4 text-xl font-black">{result.winner ? "Bingo verified" : "Claim not verified"}</h2>{result.winner ? <p className="mt-2 text-sm text-white/45">PRIZE PER WINNER</p> : null}<p className={`mt-1 text-2xl font-black ${result.winner ? "text-[#FFB45C]" : "text-red-300"}`}>{result.winner ? etb(result.payout) : result.message}</p><button onClick={onClose} className="mt-5 w-full rounded-xl bg-[#FF8C00] py-3 text-xs font-black text-white">Close</button></div></div>; }
