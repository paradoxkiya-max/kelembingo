// Style reminder: replicate legacy card-select.html: compact Back/title row, three summary chips, eight-column touch grid, selected previews, timer bar, and Cancel footer.

import { ArrowLeft, Check, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearch } from "wouter";
import { usePlayer } from "@/contexts/PlayerContext";
import { playerApi, type Cartela, type Round } from "@/lib/gateway";
import { walletValue } from "@/lib/format";
import { observeCartelaPool, observeRound } from "@/lib/realtime";

const STAKES = [10, 20];
const MAX_SELECTIONS = 2;
const SELECTION_SECONDS = 35;
const CARTELA_POOL: Cartela[] = Array.from({ length: 500 }, (_, index) => ({ number: index + 1 }));

export default function CartelaSelect() {
  const [, navigate] = useLocation();
  const search = useSearch();
  const { player } = usePlayer();
  const requestedStake = Number(new URLSearchParams(search).get("stake"));
  const stake = STAKES.includes(requestedStake) ? requestedStake : 10;
  const [round, setRound] = useState<Round | null>(null);
  const [cartelas, setCartelas] = useState<Cartela[]>([]);
  const [taken, setTaken] = useState<Set<number>>(new Set());
  const [pending, setPending] = useState<Record<string, number[]>>({});
  const [selected, setSelected] = useState<number[]>([]);
  const [seconds, setSeconds] = useState(SELECTION_SECONDS);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [expired, setExpired] = useState(false);
  const confirmStarted = useRef(false);
  const previewFetches = useRef(new Set<number>());

  const wallet = walletValue(player?.play_wallet);
  const poolEstimate = Math.round(((round?.player_count || 0) + selected.length) * stake * 0.80 * 10) / 10;

  useEffect(() => {
    let active = true;
    let unsubscribePool: (() => void) | null = null;
    let unsubscribeRound: (() => void) | null = null;
    setLoadError("");
    playerApi.activeRounds(stake).then((activeResponse) => {
      if (!active) return;
      const nextRound = activeResponse.round || null;
      setCartelas([]);
      previewFetches.current.clear();
      confirmStarted.current = false;
      setRound(nextRound);
      setTaken(new Set((nextRound?.taken_cartelas || []).map(Number)));
      setPending(nextRound?.pending_selections || {});
      setExpired(false);
      const deadline = nextRound?.selection_deadline ? new Date(nextRound.selection_deadline).getTime() : 0;
      if (deadline) setSeconds(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
      if (nextRound?.id) {
        unsubscribePool = observeCartelaPool(nextRound.id, (message) => {
          setTaken(new Set((message.taken_cartelas || []).map(Number)));
          setPending(message.pending_selections || {});
        });
        unsubscribeRound = observeRound(nextRound.id, (latest) => {
          if (!active || !latest) return;
          setRound(latest);
          if (latest.status === "playing") navigate(`/game?round=${encodeURIComponent(String(latest.id || nextRound.id))}`, { replace: true });
          else if (latest.status === "completed") navigate("/", { replace: true });
        }, { fetchInitial: false });
        if (nextRound.status === "playing") navigate(`/game?round=${encodeURIComponent(String(nextRound.id))}`, { replace: true });
        else if (nextRound.status === "completed") navigate("/", { replace: true });
      }
    }).catch((e) => active && setLoadError(e instanceof Error ? e.message : "Unable to load this round")).finally(() => active && setLoading(false));
    return () => { active = false; unsubscribePool?.(); unsubscribeRound?.(); };
  }, [navigate, stake, player?.user_id]);

  useEffect(() => {
    if (seconds <= 0) {
      if (selected.length && !confirmStarted.current) { confirmStarted.current = true; void confirmSelection(); }
      else if (!selected.length) navigate("/", { replace: true });
      return;
    }
    const timer = window.setInterval(() => setSeconds((value) => value - 1), 1000);
    return () => window.clearInterval(timer);
  }, [seconds, selected.length]);

  useEffect(() => {
    const missing = selected.filter((number) => !cartelas.some((card) => card.number === number) && !previewFetches.current.has(number));
    if (!missing.length) return;
    let active = true;
    missing.forEach((number) => previewFetches.current.add(number));
    Promise.all(missing.map((number) => playerApi.cartela(number).then((response) => response.cartela)))
      .then((items) => { if (active) setCartelas((old) => [...old.filter((card) => !items.some((item) => item.number === card.number)), ...items]); })
      .catch(() => { if (active) setError("A selected cartela preview could not be loaded. You can still continue safely."); });
    return () => { active = false; };
  }, [cartelas, selected]);

  const visibleCartelas = useMemo(() => CARTELA_POOL, []);

  async function toggleCard(number: number) {
    if (busy || (!selected.includes(number) && taken.has(number)) || !player?.user_id || expired) return;
    const isSelected = selected.includes(number);
    if (!isSelected && selected.length >= MAX_SELECTIONS) return;
    setSelected((items) => isSelected ? items.filter((item) => item !== number) : [...items, number]);
    if (!round?.id) return;
    try {
      await (isSelected ? playerApi.unselectCartela(round.id, player.user_id, number) : playerApi.selectCartela(round.id, player.user_id, number));
    } catch (e) {
      setSelected((items) => isSelected ? [...items, number] : items.filter((item) => item !== number));
      setError(e instanceof Error ? e.message : "Selection failed");
    }
  }

  async function confirmSelection() {
    if (!selected.length || busy || !player?.user_id) return;
    setBusy(true);
    try {
      const activeRound = round || (await playerApi.createRound(stake)).round;
      if (!activeRound?.id) throw new Error("Round unavailable");
      const serverRound = await playerApi.round(activeRound.id).then((response) => response.round).catch(() => null);
      const alreadyJoined = Boolean(serverRound?.players?.[String(player.user_id)]?.cartelas?.length);
      const displayName = player.username ? `@${player.username.replace(/^@/, "")}` : player.first_name || "Player";
      if (!alreadyJoined) await playerApi.joinRound(activeRound.id, player.user_id, selected, displayName);
      navigate(`/game?round=${encodeURIComponent(activeRound.id)}`, { replace: true });
    } catch (e) {
      const activeRoundId = round?.id;
      const latest = activeRoundId ? await playerApi.round(activeRoundId).then((response) => response.round).catch(() => null) : null;
      const recovered = Boolean(latest?.players?.[String(player.user_id)]?.cartelas?.length);
      if (recovered) {
        navigate(`/game?round=${encodeURIComponent(String(latest?.id || activeRoundId))}`, { replace: true });
        return;
      }
      if (latest?.status === "completed") {
        navigate("/", { replace: true });
        return;
      }
      setError(e instanceof Error ? e.message : "Could not join the round");
      setBusy(false);
    }
  }

  return <div className="flex min-h-[calc(100vh-56px)] flex-col bg-[linear-gradient(180deg,#0d0f22_0%,#151833_40%,#0d0f22_100%)]">
    <div className="flex items-center justify-between border-b border-white/5 px-4 pb-2 pt-4"><button onClick={() => navigate("/")} className="flex items-center gap-1 rounded-lg bg-indigo-600/90 px-3.5 py-1.5 text-xs font-bold text-white shadow-md transition-transform active:scale-[0.97]"><ArrowLeft className="h-3.5 w-3.5" /> Back</button><h3 className="text-sm font-bold tracking-wide text-white">Select Cartela</h3><span className="w-[62px]" /></div>
    <div className="flex items-center justify-between gap-1 border-b border-white/5 bg-[#111326]/60 px-4 py-3 text-[11px] font-semibold text-gray-300"><div className="flex gap-2"><Summary label="PLAY WALLET" value={`${wallet.toLocaleString()} ETB`} tone="text-[#34D399]" /><Summary label="STAKE" value={`${stake} ETB`} tone="text-[#FF8C00]" /><Summary label="EST. DERASH" value={`${poolEstimate} ETB`} tone="text-[#8B5CF6]" /></div><div className={`relative flex min-w-[68px] items-center justify-center overflow-hidden rounded-lg border px-3.5 py-1.5 ${expired ? "border-amber-400/30 bg-amber-500/15 text-amber-200" : "border-emerald-500/30 bg-emerald-600/20 text-emerald-400"}`}><div className="absolute inset-y-0 left-0 bg-gradient-to-r from-[#10B981] to-[#34D399] opacity-30 transition-[width] duration-300" style={{ width: `${Math.min(100, Math.max(0, (seconds / SELECTION_SECONDS) * 100))}%` }} /><span className="relative z-10 text-[10px] font-black">{expired ? "CLOSED" : seconds > 0 ? `${seconds}s` : "SYNCING…"}</span></div></div>
    <div className="card-select-grid-enhanced flex-1 overflow-y-auto px-2 py-2 [contain:layout_style]" aria-label="Available cartelas">{loading ? <div className="flex items-center justify-center py-16 text-sm text-white/35"><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading cartelas</div> : loadError ? <div className="px-4 py-12 text-center text-xs text-red-300">{loadError}</div> : <div className="grid grid-cols-8 content-start gap-1.5 max-[360px]:grid-cols-7 max-[360px]:gap-1">{visibleCartelas.map((card) => { const isSelected = selected.includes(card.number); const isPendingTaken = Object.entries(pending).some(([uid, numbers]) => uid !== String(player?.user_id || "") && numbers.includes(card.number)); const isTaken = !isSelected && (taken.has(card.number) || isPendingTaken || Boolean(card.taken) || card.status === "taken"); return <button key={card.number} disabled={isTaken} onClick={() => void toggleCard(card.number)} aria-label={`Cartela ${card.number}${isTaken ? ", taken" : isSelected ? ", selected" : ""}`} className={`relative aspect-square rounded-lg border text-[13px] font-extrabold transition-transform active:scale-[0.92] ${isTaken ? "pointer-events-none border-[#FF8C00] bg-[#FF8C00]/25 text-[#FFB45C] shadow-[0_0_12px_rgba(255,140,0,0.35)]" : isSelected ? "z-[1] scale-[1.04] border-emerald-400/60 bg-gradient-to-br from-[#10B981] to-[#059669] text-white shadow-[0_0_16px_rgba(16,185,129,0.45)]" : "border-white/10 bg-gradient-to-br from-[#1E2340] to-[#151833] text-white shadow-[0_2px_8px_rgba(0,0,0,0.3)]"}`}>{isSelected ? <Check className="mx-auto h-4 w-4" /> : isTaken ? <span className="text-[10px]">TAKEN</span> : card.number}</button>; })}</div>}</div>
    {selected.length > 0 && <div className="sticky bottom-0 z-20 border-t border-orange-400/30 bg-[#0e1026]/95 px-3 py-2 shadow-[0_-10px_25px_rgba(0,0,0,0.35)] backdrop-blur-md"><div className="mb-1 text-center text-[10px] font-black uppercase tracking-[0.2em] text-orange-300">Selected cartelas</div><div className="flex justify-center gap-2">{selected.map((number) => { const card = cartelas.find((item) => item.number === number); return <MiniPreview key={number} card={card} />; })}</div></div>}
    {error && <div className="mx-3 mb-1 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-300" role="alert">{error}</div>}
    <div className="border-t border-white/5 bg-[#0a0f1d] pb-4"><div className={`items-center justify-between px-4 py-2 text-xs ${selected.length ? "flex" : "hidden"}`}><span className="font-semibold text-gray-400">Selected: <span className="font-bold text-emerald-400">{selected.length}/{MAX_SELECTIONS}</span> cards</span><span className="font-semibold text-gray-400">Total Cost: <span className="font-bold text-orange-400">{selected.length * stake} ETB</span></span></div><div className="grid grid-cols-2 gap-2 px-4 py-2"><button onClick={() => navigate("/", { replace: true })} disabled={busy} className="rounded-xl bg-white/10 py-3 text-sm font-bold text-white transition-colors hover:bg-white/20 disabled:opacity-50">Cancel</button><button onClick={() => void confirmSelection()} disabled={busy || !selected.length || expired} className="rounded-xl bg-gradient-to-r from-[#FF9800] to-[#FF6D00] py-3 text-sm font-black text-white shadow-[0_8px_20px_rgba(255,140,0,0.2)] transition-transform active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45">{busy ? "Joining…" : "Play now"}</button></div></div>
  </div>;
}

function Summary({ label, value, tone }: { label: string; value: string; tone: string }) { return <div className="flex flex-col justify-center rounded-lg border border-white/5 bg-[#1E2340] px-2 py-1"><span className="text-[9px] leading-none text-gray-500">{label}</span><span className={`mt-0.5 font-bold leading-normal ${tone}`}>{value}</span></div>; }
function MiniPreview({ card }: { card?: Cartela }) { const values = flattenCartela(card); return <div className="w-[46%] max-w-[170px] overflow-hidden rounded-lg border-2 border-orange-400 bg-[#1A1A2E] shadow-[0_0_14px_rgba(255,140,0,0.25)]"><div className="bg-gradient-to-r from-[#FF8C00] to-[#FF6B00] py-0.5 text-center text-[7px] font-black tracking-wider text-white">CARTELA NO: {card?.number || "—"}</div><div className="grid grid-cols-5 gap-px">{["B", "I", "N", "G", "O"].map((letter, index) => <div key={letter} className="py-0.5 text-center text-[6px] font-black text-white" style={{ background: ["#3B82F6", "#8B5CF6", "#D946EF", "#10B981", "#F97316"][index] }}>{letter}</div>)}{values.map((number, index) => <div key={`${number}-${index}`} className={`aspect-square text-center text-[6px] font-bold leading-3 ${index === 12 ? "bg-emerald-500 text-white" : "bg-[#151833] text-white/70"}`}>{index === 12 ? "★" : number}</div>)}</div></div>; }
function flattenCartela(card?: Cartela) { const source: unknown = card?.cartela || card?.data || card?.grid || []; const values = Array.isArray(source) && Array.isArray(source[0]) ? (source as number[][]).reduce<number[]>((all, row) => all.concat(row), []) : Array.isArray(source) ? source as number[] : []; return values.length === 25 ? values : Array.from({ length: 25 }, (_, index) => index + 1); }
