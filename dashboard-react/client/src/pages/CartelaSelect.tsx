// Style reminder: replicate legacy card-select.html: compact Back/title row, three summary chips, eight-column touch grid, directly removable selected previews, and timer bar.

import { ArrowLeft, Check, Loader2 } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearch } from "wouter";
import { usePlayer } from "@/contexts/PlayerContext";
import { playerApi, type Cartela, type Round } from "@/lib/gateway";
import { walletValue } from "@/lib/format";
import { observeCartelaPool, observeRound, primeRoundSnapshot } from "@/lib/realtime";

const STAKES = [10, 20];
const MAX_SELECTIONS = 2;
const SELECTION_SECONDS = 35;
const CARTELA_POOL: Cartela[] = Array.from({ length: 500 }, (_, index) => ({ number: index + 1 }));

type PoolSnapshot = { taken_cartelas?: number[]; player_count?: number; derash_pool?: number; pending_revision?: number; pending_selections?: Record<string, number[]> };
type SelectionIntent = { id: string; cartelaNumber: number; selecting: boolean };

function replayIntents(authoritative: number[], intents: SelectionIntent[]) {
  const next = new Set(normalizeCartelas(authoritative));
  for (const intent of intents) intent.selecting ? next.add(intent.cartelaNumber) : next.delete(intent.cartelaNumber);
  return normalizeCartelas(Array.from(next));
}

function selectionRequestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `selection-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export default function CartelaSelect() {
  const [, navigate] = useLocation();
  const search = useSearch();
  const { player, applyPlayWallet } = usePlayer();
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
  const [walletPreview, setWalletPreview] = useState<number | null>(null);
  const [committedWallet, setCommittedWallet] = useState<number | null>(null);
  const [liveDerashPool, setLiveDerashPool] = useState<number | null>(null);
  const confirmStarted = useRef(false);
  const previewFetches = useRef(new Set<number>());
  const pendingRevision = useRef(0);
  const selectedRef = useRef<number[]>([]);
  const authoritativeSelectedRef = useRef<number[]>([]);
  const selectionIntents = useRef<SelectionIntent[]>([]);
  const previewSlotByCartela = useRef(new Map<number, number>());
  const selectionQueue = useRef<Promise<void>>(Promise.resolve());
  const selectionEpoch = useRef(0);
  const currentRoundId = useRef("");

  const wallet = walletValue(player?.play_wallet);
  const displayedWallet = walletPreview ?? committedWallet ?? wallet;
  const sharedCartelaCount = useMemo(() => {
    const allRoundCartelas = new Set<number>(Array.from(taken));
    Object.values(pending).forEach((numbers) => (numbers || []).forEach((number) => allRoundCartelas.add(Number(number))));
    selected.forEach((number) => allRoundCartelas.add(Number(number)));
    return Math.max(Number(round?.player_count || 0), allRoundCartelas.size);
  }, [pending, round?.player_count, selected, taken]);
  const sharedDerashPool = liveDerashPool ?? (round?.status === "playing" && Number.isFinite(Number(round.derash))
    ? Number(round.derash)
    : Math.round(sharedCartelaCount * stake * 0.80 * 100) / 100);

  const publishSelected = useCallback((next: number[]) => {
    const normalized = normalizeCartelas(next);
    const occupied = new Set<number>();
    normalized.forEach((number, index) => {
      const existingSlot = previewSlotByCartela.current.get(number);
      if (existingSlot !== undefined && !occupied.has(existingSlot)) occupied.add(existingSlot);
      else {
        const slot = [0, 1].find((candidate) => !occupied.has(candidate)) ?? Math.min(index, 1);
        previewSlotByCartela.current.set(number, slot);
        occupied.add(slot);
      }
    });
    for (const number of Array.from(previewSlotByCartela.current.keys())) if (!normalized.includes(number)) previewSlotByCartela.current.delete(number);
    selectedRef.current = normalized;
    setSelected((previous) => previous.length === normalized.length && previous.every((number, index) => number === normalized[index]) ? previous : normalized);
    return normalized;
  }, []);

  const applyPoolSnapshot = useCallback((snapshot: PoolSnapshot) => {
    const revision = Math.max(0, Number(snapshot.pending_revision) || 0);
    if ((!revision && pendingRevision.current > 0) || (revision && revision < pendingRevision.current)) return null;
    if (revision) pendingRevision.current = revision;
    const nextPending = snapshot.pending_selections || {};
    const authoritative = normalizeCartelas(nextPending[String(player?.user_id || "")] || []);
    authoritativeSelectedRef.current = authoritative;
    setTaken(new Set((snapshot.taken_cartelas || []).map(Number)));
    setPending(nextPending);
    if (Number.isFinite(Number(snapshot.derash_pool))) setLiveDerashPool(Number(snapshot.derash_pool));
    return { authoritative, visible: publishSelected(replayIntents(authoritative, selectionIntents.current)) };
  }, [player?.user_id, publishSelected]);

  useEffect(() => {
    if (committedWallet !== null && wallet === committedWallet) setCommittedWallet(null);
  }, [committedWallet, wallet]);

  useEffect(() => {
    if (!selected.length) confirmStarted.current = false;
  }, [selected.length]);

  useEffect(() => {
    let active = true;
    const epoch = ++selectionEpoch.current;
    let unsubscribePool: (() => void) | null = null;
    let unsubscribeRound: (() => void) | null = null;
    setLoadError("");
    setError("");
    selectionQueue.current = Promise.resolve();
    selectionIntents.current = [];
    currentRoundId.current = "";
    playerApi.activeRounds(stake).then((activeResponse) => {
      if (!active || selectionEpoch.current !== epoch) return;
      const nextRound = activeResponse.round || null;
      setCartelas([]);
      previewFetches.current.clear();
      confirmStarted.current = false;
      setRound(nextRound);
      setLiveDerashPool(null);
      setCommittedWallet(null);
      pendingRevision.current = Math.max(0, Number(nextRound?.pending_revision) || 0);
      authoritativeSelectedRef.current = normalizeCartelas(nextRound?.pending_selections?.[String(player?.user_id || "")] || []);
      if (nextRound?.id) primeRoundSnapshot(String(nextRound.id), nextRound);
      setTaken(new Set((nextRound?.taken_cartelas || []).map(Number)));
      setPending(nextRound?.pending_selections || {});
      publishSelected(authoritativeSelectedRef.current);
      setExpired(false);
      const deadline = nextRound?.selection_deadline ? new Date(nextRound.selection_deadline).getTime() : 0;
      if (deadline) setSeconds(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
      if (nextRound?.id) {
        currentRoundId.current = String(nextRound.id);
        unsubscribePool = observeCartelaPool(nextRound.id, (message) => {
          if (active && selectionEpoch.current === epoch) applyPoolSnapshot(message);
        });
        unsubscribeRound = observeRound(nextRound.id, (latest) => {
          if (!active || selectionEpoch.current !== epoch || !latest) return;
          setRound(latest);
          const playerCartelas = latest.players?.[String(player?.user_id || "")]?.cartelas || [];
          if (latest.status === "playing" && playerCartelas.length) { const targetId = String(latest.id || nextRound.id); primeRoundSnapshot(targetId, latest); navigate(`/game?round=${encodeURIComponent(targetId)}`, { replace: true }); }
          else if (latest.status === "playing") { publishSelected([]); setWalletPreview(null); setExpired(true); setError("This round started without your cartelas. The next selection opens after this game."); }
          else if (latest.status === "completed") navigate("/", { replace: true });
        }, { fetchInitial: false });
        const initialPlayerCartelas = nextRound.players?.[String(player?.user_id || "")]?.cartelas || [];
        if (nextRound.status === "playing" && initialPlayerCartelas.length) navigate(`/game?round=${encodeURIComponent(String(nextRound.id))}`, { replace: true });
        else if (nextRound.status === "playing") { setExpired(true); setError("This round is already live. The next selection opens after this game."); }
        else if (nextRound.status === "completed") navigate("/", { replace: true });
      }
    }).catch((e) => active && selectionEpoch.current === epoch && setLoadError(e instanceof Error ? e.message : "Unable to load this round")).finally(() => active && selectionEpoch.current === epoch && setLoading(false));
    return () => { active = false; selectionEpoch.current += 1; currentRoundId.current = ""; unsubscribePool?.(); unsubscribeRound?.(); };
  }, [applyPoolSnapshot, navigate, publishSelected, stake, player?.user_id]);

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

  const toggleCard = useCallback((number: number) => {
    const current = selectedRef.current;
    const userId = String(player?.user_id || "");
    if (busy || (!current.includes(number) && taken.has(number)) || !userId || expired || !round?.id) return;
    const isSelected = current.includes(number);
    if (!isSelected && current.length >= MAX_SELECTIONS) return;
    const intent: SelectionIntent = { id: selectionRequestId(), cartelaNumber: number, selecting: !isSelected };
    const roundId = String(round.id);
    const epoch = selectionEpoch.current;
    selectionIntents.current.push(intent);
    publishSelected(isSelected ? current.filter((item) => item !== number) : [...current, number]);
    setError("");
    setLiveDerashPool(Math.round(Math.max(0, sharedCartelaCount + (isSelected ? -1 : 1)) * stake * 0.80 * 100) / 100);
    setWalletPreview((preview) => Math.max(0, (preview ?? committedWallet ?? wallet) + (isSelected ? stake : -stake)));
    const execute = async () => {
      try {
        const result = await (intent.selecting
          ? playerApi.selectCartela(roundId, userId, number, intent.id)
          : playerApi.unselectCartela(roundId, userId, number, intent.id));
        if (selectionEpoch.current !== epoch || currentRoundId.current !== roundId) return;
        selectionIntents.current = selectionIntents.current.filter((item) => item.id !== intent.id);
        const applied = applyPoolSnapshot(result);
        const authoritative = applied?.authoritative ?? authoritativeSelectedRef.current;
        const visible = applied?.visible ?? publishSelected(replayIntents(authoritative, selectionIntents.current));
        if (Number.isFinite(Number(result.play_wallet))) {
          const balance = Number(result.play_wallet);
          setCommittedWallet(balance);
          applyPlayWallet(balance);
          setWalletPreview(visible.length === authoritative.length ? null : Math.max(0, balance - ((visible.length - authoritative.length) * stake)));
        }
      } catch (e) {
        if (selectionEpoch.current !== epoch || currentRoundId.current !== roundId) return;
        selectionIntents.current = selectionIntents.current.filter((item) => item.id !== intent.id);
        const authoritative = authoritativeSelectedRef.current;
        publishSelected(replayIntents(authoritative, selectionIntents.current));
        setWalletPreview(null);
        setLiveDerashPool(null);
        setError(e instanceof Error ? e.message : "Selection failed");
      }
    };
    selectionQueue.current = selectionQueue.current.then(execute, execute);
  }, [applyPoolSnapshot, applyPlayWallet, busy, committedWallet, expired, player?.user_id, publishSelected, round?.id, sharedCartelaCount, stake, taken, wallet]);

  async function confirmSelection() {
    if (!selectedRef.current.length || busy || !player?.user_id) return;
    setBusy(true);
    try {
      await selectionQueue.current;
      const committedSelection = selectedRef.current;
      if (!committedSelection.length) { setBusy(false); return; }
      const activeRound = round || (await playerApi.createRound(stake)).round;
      if (!activeRound?.id) throw new Error("Round unavailable");
      const displayName = player.username ? `@${player.username.replace(/^@/, "")}` : player.first_name || "Player";
      try { await playerApi.joinRound(activeRound.id, player.user_id, committedSelection, displayName); }
      catch (joinError) { if (!/already joined/i.test(joinError instanceof Error ? joinError.message : "")) throw joinError; }
      primeRoundSnapshot(String(activeRound.id), { ...activeRound, players: { ...(activeRound.players || {}), [String(player.user_id)]: { cartelas: committedSelection, name: displayName } } });
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
    <div className="flex items-center justify-between gap-1 border-b border-white/5 bg-[#111326]/60 px-4 py-3 text-[11px] font-semibold text-gray-300"><div className="flex gap-2"><Summary label="PLAY WALLET" value={`${displayedWallet.toLocaleString()} ETB`} tone="text-[#34D399]" /><Summary label="STAKE" value={`${stake} ETB`} tone="text-[#FF8C00]" /><Summary label="DERASH POOL" value={`${sharedDerashPool} ETB`} tone="text-[#8B5CF6]" /></div><div className={`relative flex min-w-[68px] items-center justify-center overflow-hidden rounded-lg border px-3.5 py-1.5 ${expired ? "border-amber-400/30 bg-amber-500/15 text-amber-200" : "border-emerald-500/30 bg-emerald-600/20 text-emerald-400"}`}><div className="absolute inset-y-0 left-0 bg-gradient-to-r from-[#10B981] to-[#34D399] opacity-30 transition-[width] duration-300" style={{ width: `${Math.min(100, Math.max(0, (seconds / SELECTION_SECONDS) * 100))}%` }} /><span className="relative z-10 text-[10px] font-black">{expired ? "CLOSED" : seconds > 0 ? `${seconds}s` : "GO"}</span></div></div>
    <div className="card-select-grid-enhanced flex-1 overflow-y-auto px-2 py-2 [contain:layout_style]" aria-label="Available cartelas">{loading ? <div className="flex items-center justify-center py-16 text-sm text-white/35"><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading cartelas</div> : loadError ? <div className="px-4 py-12 text-center text-xs text-red-300">{loadError}</div> : <CartelaGrid selected={selected} pending={pending} taken={taken} playerId={String(player?.user_id || "")} onToggle={toggleCard} />}</div>
    {selected.length > 0 && <div className="sticky bottom-0 z-20 border-t border-orange-400/30 bg-[#0e1026]/95 px-3 py-2 shadow-[0_-10px_25px_rgba(0,0,0,0.35)] backdrop-blur-md"><div className="mb-1 text-center text-[10px] font-black uppercase tracking-[0.2em] text-orange-300">Selected cartelas</div><p className="mb-2 text-center text-[10px] font-semibold text-white/50">Tap a selected cartela to remove it</p><div className="grid grid-cols-2 justify-items-center gap-2">{[0, 1].map((slot) => { const number = selected.find((candidate) => previewSlotByCartela.current.get(candidate) === slot); const card = number === undefined ? undefined : cartelas.find((item) => item.number === number); return number === undefined ? <div key={`empty-slot-${slot}`} className="w-[46%] max-w-[170px]" aria-hidden="true" /> : <button key={number} type="button" onClick={() => void toggleCard(number)} disabled={busy || expired} aria-label={`Remove selected Cartela ${number}`} className="w-[46%] max-w-[170px] rounded-lg text-left transition-transform active:scale-[0.97] disabled:opacity-50"><MiniPreview card={card} /><span className="mt-1 block text-center text-[10px] font-bold text-red-300">Tap to remove</span></button>; })}</div></div>}
    {error && <div className="mx-3 mb-1 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-300" role="alert">{error}</div>}
  </div>;
}

function Summary({ label, value, tone }: { label: string; value: string; tone: string }) { return <div className="flex flex-col justify-center rounded-lg border border-white/5 bg-[#1E2340] px-2 py-1"><span className="text-[9px] leading-none text-gray-500">{label}</span><span className={`mt-0.5 font-bold leading-normal ${tone}`}>{value}</span></div>; }
const CartelaGrid = memo(function CartelaGrid({ selected, pending, taken, playerId, onToggle }: { selected: number[]; pending: Record<string, number[]>; taken: Set<number>; playerId: string; onToggle: (number: number) => void }) {
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const pendingTaken = useMemo(() => {
    const next = new Set<number>();
    Object.entries(pending).forEach(([userId, numbers]) => { if (userId !== playerId) (numbers || []).forEach((number) => next.add(Number(number))); });
    return next;
  }, [pending, playerId]);
  return <div className="grid grid-cols-8 content-start gap-1.5 max-[360px]:grid-cols-7 max-[360px]:gap-1">{CARTELA_POOL.map((card) => {
    const isSelected = selectedSet.has(card.number);
    const isTaken = !isSelected && (taken.has(card.number) || pendingTaken.has(card.number));
    return <button key={card.number} disabled={isTaken} onClick={() => onToggle(card.number)} aria-label={`Cartela ${card.number}${isTaken ? ", taken" : isSelected ? ", selected" : ""}`} className={`relative aspect-square rounded-lg border text-[13px] font-extrabold transition-transform active:scale-[0.92] ${isTaken ? "pointer-events-none border-[#FF8C00] bg-[#FF8C00]/25 text-[#FFB45C] shadow-[0_0_12px_rgba(255,140,0,0.35)]" : isSelected ? "z-[1] scale-[1.04] border-emerald-400/60 bg-gradient-to-br from-[#10B981] to-[#059669] text-white shadow-[0_0_16px_rgba(16,185,129,0.45)]" : "border-white/10 bg-gradient-to-br from-[#1E2340] to-[#151833] text-white shadow-[0_2px_8px_rgba(0,0,0,0.3)]"}`}>{isSelected ? <Check className="mx-auto h-4 w-4" /> : isTaken ? <span className="text-[10px]">TAKEN</span> : card.number}</button>;
  })}</div>;
});
function MiniPreview({ card }: { card?: Cartela }) { const values = flattenCartela(card); return <div className="w-full overflow-hidden rounded-lg border-2 border-orange-400 bg-[#1A1A2E] shadow-[0_0_14px_rgba(255,140,0,0.25)]"><div className="bg-gradient-to-r from-[#FF8C00] to-[#FF6B00] py-0.5 text-center text-[7px] font-black tracking-wider text-white">CARTELA NO: {card?.number || "—"}</div><div className="grid grid-cols-5 gap-px">{["B", "I", "N", "G", "O"].map((letter, index) => <div key={letter} className="py-0.5 text-center text-[6px] font-black text-white" style={{ background: ["#3B82F6", "#8B5CF6", "#D946EF", "#10B981", "#F97316"][index] }}>{letter}</div>)}{values.map((number, index) => <div key={`${number}-${index}`} className={`aspect-square text-center text-[6px] font-bold leading-3 ${index === 12 ? "bg-emerald-500 text-white" : "bg-[#151833] text-white/70"}`}>{index === 12 ? "★" : number}</div>)}</div></div>; }
function normalizeCartelas(values: unknown) { return Array.isArray(values) ? Array.from(new Set(values.map(Number).filter((value) => Number.isInteger(value) && value >= 1 && value <= 500))).slice(0, MAX_SELECTIONS) : []; }
function flattenCartela(card?: Cartela) { const source: unknown = card?.cartela || card?.data || card?.grid || []; const values = Array.isArray(source) && Array.isArray(source[0]) ? (source as number[][]).reduce<number[]>((all, row) => all.concat(row), []) : Array.isArray(source) ? source as number[] : []; return values.length === 25 ? values : Array.from({ length: 25 }, (_, index) => index + 1); }
