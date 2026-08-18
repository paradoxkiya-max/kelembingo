import { ArrowLeft, Check, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearch } from "wouter";
import { usePlayer } from "@/contexts/PlayerContext";
import { playerApi, type Cartela, type Round } from "@/lib/gateway";
import { walletValue } from "@/lib/format";
import { cardValues, fallbackCartela } from "@/lib/cartelaFallback";
import { observeCartelaPool, observeRound } from "@/lib/realtime";

const VALID_STAKES = [10, 20];
const MAX_CARTELAS = 2;
const SELECTION_DURATION = 45;
const CARTELA_NUMBERS = Array.from({ length: 500 }, (_, index) => index + 1);

type PendingMap = Record<string, number[]>;
type PoolMessage = {
  pending_revision?: number;
  taken_cartelas?: number[];
  pending_selections?: PendingMap;
  player_count?: number;
  derash_pool?: number;
  play_wallet?: number;
};

type Cleanup = () => void;

function roundIdOf(round: Round | null | undefined) {
  return String(round?.id || round?.round_id || "");
}

function normalizeNumbers(value: unknown) {
  if (!Array.isArray(value)) return [];
  return Array.from(new Set(value.map(Number).filter((number) => Number.isInteger(number) && number >= 1 && number <= 500)));
}

function normalizePending(value: unknown): PendingMap {
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([uid, numbers]) => [uid, normalizeNumbers(numbers)]));
}

function roundSelections(round: Round | null | undefined, userId: string) {
  const pending = normalizePending(round?.pending_selections);
  const mine = pending[userId] || [];
  if (mine.length) return mine;
  return normalizeNumbers(round?.players?.[userId]?.cartelas || []);
}

function deadlineMs(round: Round | null | undefined) {
  if (!round?.selection_deadline) return 0;
  const parsed = new Date(round.selection_deadline).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

function expired(round: Round | null | undefined, offset = 0) {
  const deadline = deadlineMs(round);
  return Boolean(deadline && deadline <= Date.now() + offset);
}

function secondsLeft(round: Round | null | undefined, offset = 0) {
  const deadline = deadlineMs(round);
  if (!deadline) return SELECTION_DURATION;
  return Math.max(0, Math.ceil((deadline - (Date.now() + offset)) / 1000));
}

function hasPlayerEntry(round: Round | null | undefined, userId: string) {
  return Boolean(round?.players?.[userId]?.cartelas?.length);
}

function otherPendingNumbers(pending: PendingMap, userId: string) {
  const values: number[] = [];
  Object.entries(pending).forEach(([owner, numbers]) => {
    if (owner !== userId) values.push(...numbers);
  });
  return new Set(values);
}

function requestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `cartela-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function errorMessage(value: unknown) {
  return value instanceof Error && value.message ? value.message : "The selection update failed. Please try again.";
}

function calcDerash(playerCount: number, pending: PendingMap, stake: number) {
  const pendingCount = Object.values(pending).reduce((total, numbers) => total + numbers.length, 0);
  const totalCartelas = Math.max(0, Number(playerCount) || 0) + pendingCount;
  return Math.round(totalCartelas * stake * 0.8 * 100) / 100;
}

export default function CartelaSelect() {
  const [, navigate] = useLocation();
  const search = useSearch();
  const { player, applyPlayWallet } = usePlayer();
  const userId = String(player?.user_id || player?.id || "");
  const requestedStake = Number(new URLSearchParams(search).get("stake"));
  const stake = VALID_STAKES.includes(requestedStake) ? requestedStake : 10;

  const [round, setRound] = useState<Round | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [pending, setPending] = useState<PendingMap>({});
  const [taken, setTaken] = useState<Set<number>>(new Set());
  const [cards, setCards] = useState<Cartela[]>([]);
  const [seconds, setSeconds] = useState(SELECTION_DURATION);
  const [wallet, setWallet] = useState(0);
  const [derashPool, setDerashPool] = useState(0);
  const [loading, setLoading] = useState(true);
  const [transitioning, setTransitioning] = useState(false);
  const [error, setError] = useState("");
  const [activePreview, setActivePreview] = useState<number | null>(null);

  const roundRef = useRef<Round | null>(null);
  const selectedRef = useRef<number[]>([]);
  const pendingRef = useRef<PendingMap>({});
  const epochRef = useRef(0);
  const cleanupRef = useRef<Cleanup | null>(null);
  const timerRef = useRef<number | null>(null);
  const handoffRef = useRef(false);
  const playRunningRef = useRef(false);
  const playRerunRef = useRef(false);
  const lastTapRef = useRef(0);
  const serverOffsetRef = useRef(0);
  const mutationTailsRef = useRef(new Map<number, Promise<void>>());
  const currentRoundIdRef = useRef("");

  const publishSelected = useCallback((numbers: number[]) => {
    const next = normalizeNumbers(numbers).slice(0, MAX_CARTELAS);
    selectedRef.current = next;
    setSelected(next);
    setActivePreview((previous) => next.includes(previous || 0) ? previous : next[next.length - 1] || null);
  }, []);

  const cleanupSelection = useCallback(() => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
    cleanupRef.current?.();
    cleanupRef.current = null;
    handoffRef.current = false;
    currentRoundIdRef.current = "";
    roundRef.current = null;
  }, []);

  const navigateToGame = useCallback((next: Round) => {
    const id = roundIdOf(next);
    if (!id) return;
    cleanupSelection();
    setTransitioning(false);
    navigate(`/game?round=${encodeURIComponent(id)}`, { replace: true });
  }, [cleanupSelection, navigate]);

  const schedulePendingMutation = useCallback((roundId: string, number: number, selecting: boolean, epoch: number) => {
    const tails = mutationTailsRef.current;
    const previous = tails.get(number) || Promise.resolve();
    const task = previous.catch(() => undefined).then(async () => {
      if (epochRef.current !== epoch || currentRoundIdRef.current !== roundId) return;
      if (selecting) await playerApi.selectCartela(roundId, userId, number, requestId());
      else await playerApi.unselectCartela(roundId, userId, number, requestId());
    });
    const tracked = task.finally(() => {
      if (tails.get(number) === tracked) tails.delete(number);
    });
    tails.set(number, tracked);
    void tracked.catch((cause) => {
      if (epochRef.current !== epoch || currentRoundIdRef.current !== roundId) return;
      setError(errorMessage(cause));
      void playerApi.round(roundId).then(({ round: latest }) => {
        if (epochRef.current !== epoch || currentRoundIdRef.current !== roundId) return;
        const latestPending = normalizePending(latest.pending_selections);
        pendingRef.current = latestPending;
        setPending(latestPending);
        setTaken(new Set(normalizeNumbers(latest.taken_cartelas)));
      }).catch(() => undefined);
    });
  }, [userId]);

  const finishSelection = useCallback(async (epoch: number, selectedAtDeadline: number[], onRetry: () => void) => {
    if (handoffRef.current || epochRef.current !== epoch || !roundRef.current) return;
    handoffRef.current = true;
    setTransitioning(true);
    setError("");
    const roundId = currentRoundIdRef.current;
    const snapshot = normalizeNumbers(selectedAtDeadline).slice(0, MAX_CARTELAS);
    if (!snapshot.length) {
      cleanupSelection();
      setLoading(true);
      setTransitioning(false);
      onRetry();
      return;
    }
    try {
      const tails = Array.from(mutationTailsRef.current.values());
      if (tails.length) await Promise.allSettled(tails);
      if (epochRef.current !== epoch || currentRoundIdRef.current !== roundId) return;
      const latest = (await playerApi.round(roundId)).round;
      const serverSnapshot = roundSelections(latest, userId);
      const joinSelection = (serverSnapshot.length ? serverSnapshot : snapshot).slice(0, MAX_CARTELAS);
      if (hasPlayerEntry(latest, userId)) {
        navigateToGame(latest);
        return;
      }
      if (!joinSelection.length) {
        cleanupSelection();
        setLoading(true);
        onRetry();
        return;
      }
      const response = await playerApi.joinRound(roundId, userId, joinSelection, player?.username || player?.first_name || "Player", {
        requirePending: true,
        pendingRevision: Number(latest.pending_revision || 0),
      });
      if (epochRef.current !== epoch) return;
      const confirmed = response.round || latest;
      if (confirmed.players?.[userId]?.cartelas?.length || response.ok) {
        navigateToGame(confirmed);
        return;
      }
      throw new Error("The server did not confirm the selected cartelas.");
    } catch (cause) {
      if (epochRef.current !== epoch) return;
      handoffRef.current = false;
      setTransitioning(false);
      const message = errorMessage(cause).toLowerCase();
      if (message.includes("already started") || message.includes("no longer") || message.includes("completed") || message.includes("selecting")) {
        cleanupSelection();
        setLoading(true);
        onRetry();
      } else {
        setError(errorMessage(cause));
      }
    }
  }, [cleanupSelection, navigateToGame, player?.first_name, player?.username, userId]);

  const openRound = useCallback((next: Round, epoch: number, onRetry: () => void) => {
    if (epochRef.current !== epoch) return;
    const id = roundIdOf(next);
    if (!id) throw new Error("The round has no ID.");
    cleanupSelection();
    currentRoundIdRef.current = id;
    roundRef.current = next;
    pendingRef.current = normalizePending(next.pending_selections);
    setRound(next);
    setPending(pendingRef.current);
    setTaken(new Set(normalizeNumbers(next.taken_cartelas)));
    publishSelected([]);
    setWallet(walletValue(player?.play_wallet) || 0);
    setDerashPool(Number(next.derash) || calcDerash(Number(next.player_count || 0), pendingRef.current, stake));
    setSeconds(secondsLeft(next, serverOffsetRef.current));
    setLoading(false);
    setTransitioning(false);

    const applyRound = (latest: Round | null) => {
      if (!latest || epochRef.current !== epoch || currentRoundIdRef.current !== id) return;
      const mine = roundSelections(latest, userId);
      if (latest.status === "completed" || latest.status === "cancelled") {
        cleanupSelection();
        setLoading(true);
        onRetry();
        return;
      }
      if (latest.status === "playing") {
        if (hasPlayerEntry(latest, userId)) {
          navigateToGame(latest);
        } else if (Number(latest.player_count || 0) <= 0) {
          cleanupSelection();
          setLoading(true);
          onRetry();
        } else {
          cleanupSelection();
          navigateToGame(latest);
        }
        return;
      }
      roundRef.current = latest;
      setRound(latest);
      pendingRef.current = normalizePending(latest.pending_selections);
      setPending(pendingRef.current);
      setTaken(new Set(normalizeNumbers(latest.taken_cartelas)));
      setSeconds(secondsLeft(latest, serverOffsetRef.current));
      if (!selectedRef.current.length && mine.length) publishSelected(mine);
      if (Number.isFinite(Number(latest.derash))) setDerashPool(Number(latest.derash));
    };

    const unsubscribeRound = observeRound(id, applyRound, { fetchInitial: false });
    const unsubscribePool = observeCartelaPool(id, (message: PoolMessage) => {
      if (epochRef.current !== epoch || currentRoundIdRef.current !== id) return;
      const nextPending = normalizePending(message.pending_selections);
      pendingRef.current = nextPending;
      setPending(nextPending);
      setTaken(new Set(normalizeNumbers(message.taken_cartelas)));
      if (Number.isFinite(Number(message.play_wallet))) {
        setWallet(Number(message.play_wallet));
        applyPlayWallet(Number(message.play_wallet));
      }
      if (Number.isFinite(Number(message.derash_pool))) setDerashPool(Number(message.derash_pool));
    });
    const timer = window.setInterval(() => {
      if (epochRef.current !== epoch || currentRoundIdRef.current !== id) return;
      const remaining = secondsLeft(roundRef.current, serverOffsetRef.current);
      setSeconds(remaining);
      if (remaining <= 0) {
        if (selectedRef.current.length) void finishSelection(epoch, selectedRef.current, onRetry);
        else {
          cleanupSelection();
          setLoading(true);
          setTransitioning(false);
          onRetry();
        }
      }
    }, 200);
    timerRef.current = timer;
    cleanupRef.current = () => {
      window.clearInterval(timer);
      unsubscribeRound();
      unsubscribePool();
    };
  }, [applyPlayWallet, cleanupSelection, finishSelection, navigateToGame, player?.play_wallet, publishSelected, stake, userId]);

  const requestPlayNow = useCallback(async () => {
    if (playRunningRef.current) {
      playRerunRef.current = true;
      return;
    }
    playRunningRef.current = true;
    playRerunRef.current = false;
    const epoch = ++epochRef.current;
    cleanupSelection();
    setLoading(true);
    setTransitioning(false);
    setError("");
    try {
      let active: Round | null = null;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        active = (await playerApi.activeRounds(stake)).round || null;
        if (!active || (active.status === "selecting" && expired(active, serverOffsetRef.current) && Number(active.player_count || 0) <= 0)) {
          active = (await playerApi.createRound(stake)).round || null;
        }
        if (!active) continue;
        if (active.status === "selecting" && expired(active, serverOffsetRef.current)) {
          if (Number(active.player_count || 0) > 0) {
            navigateToGame(active);
            return;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 250));
          continue;
        }
        break;
      }
      if (!active) throw new Error("Unable to find a game.");
      if (epochRef.current !== epoch) return;
      if (active.status === "playing" || hasPlayerEntry(active, userId)) {
        navigateToGame(active);
        return;
      }
      openRound(active, epoch, () => { void requestPlayNow(); });
    } catch (cause) {
      if (epochRef.current !== epoch) return;
      setLoading(false);
      setError(errorMessage(cause));
    } finally {
      playRunningRef.current = false;
      if (playRerunRef.current) {
        playRerunRef.current = false;
        window.setTimeout(() => { void requestPlayNow(); }, 100);
      }
    }
  }, [cleanupSelection, navigateToGame, openRound, stake, userId]);

  useEffect(() => {
    void requestPlayNow();
    return () => {
      epochRef.current += 1;
      cleanupSelection();
      mutationTailsRef.current.clear();
    };
  }, [cleanupSelection, requestPlayNow]);

  useEffect(() => {
    if (!round?.selection_deadline) return;
    const started = Date.now();
    playerApi.time().then(({ iso }) => {
      const serverTime = new Date(iso).getTime();
      if (Number.isFinite(serverTime)) serverOffsetRef.current = serverTime - started;
    }).catch(() => undefined);
  }, [round?.selection_deadline]);

  useEffect(() => {
    const selectedNumbers = selected.filter((number) => !cards.some((card) => card.number === number));
    if (!selectedNumbers.length) return;
    setCards((previous) => [...previous, ...selectedNumbers.map((number) => fallbackCartela(number))]);
    Promise.all(selectedNumbers.map((number) => playerApi.cartela(number).then((response) => response.cartela).catch(() => null))).then((loaded) => {
      const valid = loaded.filter((card): card is Cartela => Boolean(card && Number(card.number)));
      if (valid.length) setCards((previous) => [...previous.filter((card) => !valid.some((item) => item.number === card.number)), ...valid]);
    });
  }, [cards, selected]);

  const otherTaken = useMemo(() => otherPendingNumbers(pending, userId), [pending, userId]);

  const toggleCard = useCallback((number: number) => {
    const now = Date.now();
    if (now - lastTapRef.current < 300) return;
    lastTapRef.current = now;
    if (!round || round.status !== "selecting" || seconds <= 0 || transitioning || !userId || !currentRoundIdRef.current) return;
    const current = selectedRef.current;
    const selecting = !current.includes(number);
    const isOtherTaken = taken.has(number) || otherTaken.has(number);
    if (selecting && (current.length >= MAX_CARTELAS || isOtherTaken)) return;
    const next = selecting ? [...current, number] : current.filter((item) => item !== number);
    publishSelected(next);
    setError("");
    schedulePendingMutation(currentRoundIdRef.current, number, selecting, epochRef.current);
  }, [otherTaken, publishSelected, round, schedulePendingMutation, seconds, taken, transitioning, userId]);

  const playerCount = useMemo(() => {
    const total = new Set<number>(Array.from(taken));
    Object.values(pending).forEach((numbers) => numbers.forEach((number) => total.add(number)));
    return Math.max(Number(round?.player_count || 0), total.size);
  }, [pending, round?.player_count, taken]);
  const displayWallet = wallet || walletValue(player?.play_wallet) || 0;
  const displayDerash = derashPool || calcDerash(playerCount, pending, stake);
  const closed = Boolean(round && (round.status !== "selecting" || seconds <= 0));

  return <div className="relative flex min-h-[calc(100vh-56px)] flex-col overflow-hidden bg-[linear-gradient(180deg,#0d0f22_0%,#151833_40%,#0d0f22_100%)]">
    <div className="absolute inset-0 pointer-events-none bg-[linear-gradient(180deg,rgba(13,15,34,0.4),rgba(13,15,34,0.1),rgba(13,15,34,0.4))]" />
    <div className="relative z-10 mx-auto flex min-h-[calc(100vh-56px)] w-full max-w-[420px] flex-col">
      <div className="flex items-center justify-between border-b border-white/5 px-4 pb-2 pt-4">
        <button onClick={() => { cleanupSelection(); navigate("/"); }} className="flex items-center gap-1 rounded-lg bg-indigo-600/90 px-3.5 py-1.5 text-xs font-bold text-white shadow-md transition-all hover:bg-indigo-700"><ArrowLeft className="h-3.5 w-3.5" /> Back</button>
        <h3 className="text-sm font-bold tracking-wide text-white">Select Cartela</h3><span className="w-[62px]" />
      </div>
      <div className="flex items-center justify-between gap-1 border-b border-white/5 bg-[#111326]/60 px-4 py-3 text-[11px] font-semibold text-gray-300">
        <div className="flex gap-2"><Summary label="Wallet" value={`${displayWallet} ETB`} tone="text-[#34D399]" /><Summary label="Stake" value={`${stake} ETB`} tone="text-[#FF8C00]" /><Summary label="DERASH" value={`${displayDerash} ETB`} tone="text-[#8B5CF6]" /></div>
        <div className="relative flex min-w-[55px] items-center justify-center overflow-hidden rounded-lg border border-emerald-500/30 bg-emerald-600/20 px-3.5 py-1.5 text-emerald-400"><div className="absolute inset-0 bg-gradient-to-r from-emerald-500 to-emerald-300 opacity-30" style={{ width: `${Math.max(0, Math.min(100, (seconds / SELECTION_DURATION) * 100))}%` }} /><span className="relative z-10 text-xs font-bold">{transitioning || closed ? "Starting…" : `${seconds}s`}</span></div>
      </div>
      {loading ? <div className="flex flex-1 items-center justify-center py-16 text-sm text-white/35"><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Finding game…</div> : <>
        <div className="card-select-grid grid min-h-0 flex-1 grid-cols-8 content-start gap-1.5 overflow-y-auto px-2 py-2 max-[360px]:grid-cols-7 max-[360px]:gap-1" aria-label="Available cartelas">{CARTELA_NUMBERS.map((number) => {
          const isSelected = selected.includes(number);
          const isTaken = !isSelected && (taken.has(number) || otherTaken.has(number));
          return <button key={number} type="button" disabled={closed || isTaken || transitioning} onClick={() => toggleCard(number)} className={`relative flex aspect-square items-center justify-center rounded-lg border text-[13px] font-extrabold transition-all duration-150 active:scale-[0.92] ${isSelected ? "z-10 scale-[1.05] border-emerald-400/60 bg-gradient-to-br from-emerald-500 to-emerald-600 text-white shadow-[0_0_20px_rgba(16,185,129,0.6),0_4px_12px_rgba(16,185,129,0.3)]" : isTaken ? "cursor-not-allowed border-orange-400/30 bg-gradient-to-br from-orange-500 to-orange-600 text-white opacity-85" : "border-white/10 bg-gradient-to-br from-[#1E2340] to-[#151833] text-white shadow-[0_2px_8px_rgba(0,0,0,0.3)]"}`}>{isTaken ? <span className="text-[8px] font-black tracking-[0.04em]">TAKEN</span> : isSelected ? <Check className="h-4 w-4" /> : number}</button>;
        })}</div>
        {selected.length > 0 && <div className="border-t border-white/5 bg-[#0e1026] px-3 py-2"><div className="flex justify-center gap-2">{selected.map((number) => <MiniPreview key={number} card={cards.find((item) => item.number === number) || fallbackCartela(number)} number={number} active={activePreview === number || (activePreview === null && number === selected[selected.length - 1])} onActivate={() => setActivePreview(number)} onRemove={() => toggleCard(number)} disabled={closed || transitioning} />)}</div></div>}
        <div className="border-t border-white/5 bg-[#0a0f1d] pb-4"><div className="flex items-center justify-between px-4 py-2 text-xs"><span className="font-semibold text-gray-400">Selected: <span className="font-bold text-emerald-400">{selected.length}/{MAX_CARTELAS}</span> cards</span><span className="font-semibold text-gray-400">Total Cost: <span className="font-bold text-orange-400">{selected.length * stake} ETB</span></span></div><div className="flex gap-3 px-4 py-2"><button onClick={() => { cleanupSelection(); navigate("/"); }} className="flex-1 rounded-xl bg-white/10 py-3 text-sm font-bold text-white transition-all hover:bg-white/20">Cancel</button></div>{error && <div className="px-4 pt-1 text-center text-[11px] text-red-300" role="alert">{error}</div>}</div>
      </>}
    </div>
  </div>;
}

function Summary({ label, value, tone }: { label: string; value: string; tone: string }) { return <div className="flex flex-col justify-center rounded-lg border border-white/5 bg-[#1E2340] px-2 py-1"><span className="text-[9px] uppercase leading-none text-gray-500">{label}</span><span className={`mt-0.5 font-bold leading-normal ${tone}`}>{value}</span></div>; }

function MiniPreview({ card, number, active, onActivate, onRemove, disabled }: { card: Cartela; number: number; active: boolean; onActivate: () => void; onRemove: () => void; disabled: boolean }) {
  const values = cardValues(card, number);
  return <div onClick={onActivate} className={`cursor-pointer overflow-hidden rounded-lg border-2 transition-all ${active ? "flex-[2] border-orange-400 shadow-[0_0_16px_rgba(255,140,0,0.3)]" : "flex-1 border-transparent opacity-60 scale-[0.95]"}`}><button type="button" onClick={(event) => { event.stopPropagation(); onRemove(); }} disabled={disabled} className="block w-full text-left disabled:opacity-50"><div className="bg-orange-500/10 py-0.5 text-center text-[10px] font-extrabold text-orange-400">CARTELA NO: {number}</div><div className="grid grid-cols-5 gap-0.5 px-1"><div className="col-span-5 grid grid-cols-5 gap-0.5">{["B", "I", "N", "G", "O"].map((letter, index) => <span key={letter} className="rounded-[3px] py-0.5 text-center text-[8px] font-black text-white" style={{ background: ["#3B82F6", "#8B5CF6", "#D946EF", "#10B981", "#F97316"][index] }}>{letter}</span>)}</div>{values.map((value, index) => <span key={`${value}-${index}`} className={`rounded-[3px] py-0.5 text-center text-[8px] font-extrabold ${index === 12 ? "bg-emerald-600 text-white" : "bg-white/5 text-gray-300"}`}>{index === 12 ? "★" : value}</span>)}</div></button><div className="py-1 text-center text-[10px] font-bold text-red-300">Tap to remove</div></div>;
}
