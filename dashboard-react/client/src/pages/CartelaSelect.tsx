import { ArrowLeft, Check, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearch } from "wouter";
import { usePlayer } from "@/contexts/PlayerContext";
import { playerApi, type Cartela, type Round } from "@/lib/gateway";
import { walletValue } from "@/lib/format";
import { cardValues, fallbackCartela } from "@/lib/cartelaFallback";
import { observeCartelaPool, observeRound } from "@/lib/realtime";

const STAKES = [10, 20];
const MAX_SELECTIONS = 2;
const SELECTION_SECONDS = 45;
const CARTELA_NUMBERS = Array.from({ length: 500 }, (_, index) => index + 1);

type PoolResponse = {
  ok?: boolean;
  play_wallet?: number;
  selected_cartelas?: number[];
  taken_cartelas?: number[];
  player_count?: number;
  derash_pool?: number;
  pending_revision?: number;
  pending_selections?: Record<string, number[]>;
};

function normalizeNumbers(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return Array.from(new Set(value.map(Number).filter((number) => Number.isInteger(number) && number >= 1 && number <= 500))).slice(0, MAX_SELECTIONS);
}

function requestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `select-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function errorText(value: unknown) {
  if (value instanceof Error && value.message) return value.message;
  return "The cartela update failed. Please try again.";
}

function deadlineSeconds(round: Round | null, offset = 0) {
  const deadline = round?.selection_deadline ? new Date(round.selection_deadline).getTime() : 0;
  if (!deadline) return SELECTION_SECONDS;
  return Math.max(0, Math.ceil((deadline - (Date.now() + offset)) / 1000));
}

function selectedFromResponse(response: PoolResponse, userId: string, fallback: number[]) {
  if (response.pending_selections) return normalizeNumbers(response.pending_selections[userId] || []);
  if (response.selected_cartelas) return normalizeNumbers(response.selected_cartelas);
  return fallback;
}

function selectedFromRound(round: Round | null, userId: string) {
  return normalizeNumbers(round?.pending_selections?.[userId] || round?.players?.[userId]?.cartelas || []);
}

export default function CartelaSelect() {
  const [, navigate] = useLocation();
  const search = useSearch();
  const { player, applyPlayWallet } = usePlayer();
  const userId = String(player?.user_id || "");
  const requestedStake = Number(new URLSearchParams(search).get("stake"));
  const stake = STAKES.includes(requestedStake) ? requestedStake : 10;

  const [round, setRound] = useState<Round | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [taken, setTaken] = useState<Set<number>>(new Set());
  const [pending, setPending] = useState<Record<string, number[]>>({});
  const [cards, setCards] = useState<Cartela[]>([]);
  const [seconds, setSeconds] = useState(SELECTION_SECONDS);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mutating, setMutating] = useState<Set<number>>(new Set());
  const [walletOverride, setWalletOverride] = useState<number | null>(null);
  const [derashOverride, setDerashOverride] = useState<number | null>(null);
  const [reload, setReload] = useState(0);

  const roundRef = useRef<Round | null>(null);
  const selectedRef = useRef<number[]>([]);
  const revisionRef = useRef(0);
  const inFlightRef = useRef(new Set<number>());
  const pendingOperationsRef = useRef(new Set<Promise<unknown>>());
  const epochRef = useRef(0);
  const deadlineStartedRef = useRef(false);
  const serverOffsetRef = useRef(0);
  const cardFetchesRef = useRef(new Set<number>());

  const publishSelected = useCallback((numbers: number[]) => {
    const next = normalizeNumbers(numbers);
    selectedRef.current = next;
    setSelected((previous) => previous.length === next.length && previous.every((number, index) => number === next[index]) ? previous : next);
    return next;
  }, []);

  const installRound = useCallback((next: Round, epoch: number) => {
    if (epochRef.current !== epoch) return;
    const normalizedRound = { ...next, id: String(next.id || next.round_id || "") };
    const initialSelected = selectedFromRound(normalizedRound, userId);
    roundRef.current = normalizedRound;
    revisionRef.current = Math.max(0, Number(normalizedRound.pending_revision) || 0);
    setRound(normalizedRound);
    setPending(normalizedRound.pending_selections || {});
    setTaken(new Set((normalizedRound.taken_cartelas || []).map(Number)));
    publishSelected(initialSelected);
    setSeconds(deadlineSeconds(normalizedRound, serverOffsetRef.current));
    setDerashOverride(Number.isFinite(Number(normalizedRound.derash)) ? Number(normalizedRound.derash) : null);
    setLoading(false);
  }, [publishSelected, userId]);

  const startNewRound = useCallback((force = false) => {
    if (busy && !force) return;
    deadlineStartedRef.current = false;
    setError("");
    setBusy(false);
    setLoading(true);
    setRound(null);
    roundRef.current = null;
    revisionRef.current = 0;
    setPending({});
    setTaken(new Set());
    setDerashOverride(null);
    publishSelected([]);
    setReload((value) => value + 1);
  }, [busy, publishSelected]);

  const navigateToGame = useCallback((next: Round) => {
    const id = String(next.id || next.round_id || "");
    if (!id) return;
    roundRef.current = next;
    setBusy(false);
    navigate(`/game?round=${encodeURIComponent(id)}`, { replace: true });
  }, [navigate]);

  const finishSelection = useCallback(async (epoch: number) => {
    if (deadlineStartedRef.current || !roundRef.current || !userId) return;
    deadlineStartedRef.current = true;
    setBusy(true);
    setError("");
    const activeRound = roundRef.current;
    const roundId = String(activeRound.id || activeRound.round_id || "");
    try {
      const operations = Array.from(pendingOperationsRef.current);
      if (operations.length) await Promise.allSettled(operations);
      if (epochRef.current !== epoch || String(roundRef.current?.id || "") !== roundId) return;

      const latest = (await playerApi.round(roundId)).round;
      const joined = selectedFromRound(latest, userId);
      if (latest.status === "playing" && latest.players?.[userId]?.cartelas?.length) {
        navigateToGame(latest);
        return;
      }
      if (latest.status !== "selecting" || deadlineSeconds(latest, serverOffsetRef.current) <= 0) {
        if (!joined.length) {
          startNewRound(true);
          return;
        }
        const response = await playerApi.joinRound(roundId, userId, joined, player?.username || player?.first_name || "Player", { requirePending: true, pendingRevision: Number(latest.pending_revision || 0) });
        const confirmed = response.round || (await playerApi.round(roundId)).round;
        const committed = normalizeNumbers(confirmed.players?.[userId]?.cartelas || []);
        if (committed.length && joined.every((number) => committed.includes(number))) {
          navigateToGame(confirmed);
          return;
        }
        throw new Error("The server did not confirm the selected cartelas.");
      }
      deadlineStartedRef.current = false;
      setBusy(false);
      installRound(latest, epoch);
    } catch (cause) {
      if (epochRef.current !== epoch) return;
      setBusy(false);
      deadlineStartedRef.current = false;
      setError(errorText(cause));
    }
  }, [installRound, navigateToGame, player?.first_name, player?.username, startNewRound, userId]);

  useEffect(() => {
    let active = true;
    const epoch = ++epochRef.current;
    let cleanupRealtime: (() => void) | undefined;
    deadlineStartedRef.current = false;
    setLoading(true);
    setError("");
    setCards([]);
    setWalletOverride(null);
    publishSelected([]);

    const load = async () => {
      try {
        const { round: next } = await playerApi.createRound(stake);
        if (!active || epochRef.current !== epoch) return;
        if (!next) throw new Error("Unable to start the next round.");
        installRound(next, epoch);
        const id = String(next.id || next.round_id || "");
        if (!id) throw new Error("The round has no ID.");

        const applyRound = (latest: Round | null) => {
          if (!active || epochRef.current !== epoch || !latest) return;
          const latestRevision = Math.max(0, Number(latest.pending_revision) || 0);
          if (latestRevision < revisionRef.current) return;
          const joined = normalizeNumbers(latest.players?.[userId]?.cartelas || []);
          if (joined.length) {
            navigateToGame(latest);
            return;
          }
          if (latest.status === "playing") {
            setSeconds(0);
            void finishSelection(epoch);
            return;
          }
          revisionRef.current = latestRevision;
          roundRef.current = latest;
          setRound(latest);
          setPending(latest.pending_selections || {});
          setTaken(new Set((latest.taken_cartelas || []).map(Number)));
          if (!inFlightRef.current.size) publishSelected(selectedFromRound(latest, userId));
          setSeconds(deadlineSeconds(latest, serverOffsetRef.current));
        };

        const unsubscribePool = observeCartelaPool(id, (message) => {
          if (!active || epochRef.current !== epoch) return;
          const revision = Math.max(0, Number(message.pending_revision) || 0);
          if (revision < revisionRef.current) return;
          revisionRef.current = revision;
          setTaken(new Set((message.taken_cartelas || []).map(Number)));
          if (message.pending_selections) setPending(message.pending_selections);
          if (!inFlightRef.current.size) publishSelected(selectedFromResponse(message, userId, selectedRef.current));
          if (Number.isFinite(Number(message.play_wallet))) {
            setWalletOverride(Number(message.play_wallet));
            applyPlayWallet(Number(message.play_wallet));
          }
          if (Number.isFinite(Number(message.derash_pool))) setDerashOverride(Number(message.derash_pool));
        });
        const unsubscribeRound = observeRound(id, applyRound, { fetchInitial: false });
        const deadlineTimer = window.setInterval(() => {
          if (!active || epochRef.current !== epoch || !roundRef.current) return;
          const remaining = deadlineSeconds(roundRef.current, serverOffsetRef.current);
          setSeconds(remaining);
          if (remaining <= 0) void finishSelection(epoch);
        }, 1000);
        cleanupRealtime = () => {
          window.clearInterval(deadlineTimer);
          unsubscribePool();
          unsubscribeRound();
        };
      } catch (cause) {
        if (active && epochRef.current === epoch) {
          setLoading(false);
          setError(errorText(cause));
        }
      }
    };
    void load();

    return () => {
      active = false;
      cleanupRealtime?.();
      epochRef.current += 1;
      inFlightRef.current.clear();
      pendingOperationsRef.current.clear();
      setMutating(new Set());
    };
  }, [applyPlayWallet, finishSelection, installRound, navigateToGame, publishSelected, reload, stake, userId]);

  useEffect(() => {
    if (!round?.selection_deadline) return;
    const started = Date.now();
    playerApi.time().then(({ iso }) => {
      const serverTime = new Date(iso).getTime();
      if (Number.isFinite(serverTime)) serverOffsetRef.current = serverTime - started;
    }).catch(() => undefined);
  }, [round?.selection_deadline]);

  useEffect(() => {
    const missing = selected.filter((number) => !cards.some((card) => card.number === number) && !cardFetchesRef.current.has(number));
    if (!missing.length) return;
    missing.forEach((number) => cardFetchesRef.current.add(number));
    setCards((previous) => [...previous, ...missing.map((number) => fallbackCartela(number))]);
    Promise.all(missing.map(async (number) => (await playerApi.cartela(number)).cartela)).then((loaded) => {
      const valid = loaded.filter((card): card is Cartela => Boolean(card && Number(card.number)));
      if (valid.length) setCards((previous) => [...previous.filter((card) => !valid.some((item) => item.number === card.number)), ...valid]);
    }).catch(() => undefined);
  }, [cards, selected]);

  const toggleCard = useCallback((number: number) => {
    const current = selectedRef.current;
    const selecting = !current.includes(number);
    const activeRound = roundRef.current;
    const roundId = String(activeRound?.id || activeRound?.round_id || "");
    if (busy || !userId || !roundId || activeRound?.status !== "selecting" || seconds <= 0 || inFlightRef.current.has(number)) return;
    if (selecting && current.length >= MAX_SELECTIONS) return;
    if (selecting && taken.has(number)) return;

    const before = [...current];
    const optimistic = selecting ? [...current, number] : current.filter((item) => item !== number);
    const operationEpoch = epochRef.current;
    inFlightRef.current.add(number);
    setMutating((previous) => new Set(previous).add(number));
    publishSelected(optimistic);
    setError("");

    const operation = (selecting
      ? playerApi.selectCartela(roundId, userId, number, requestId())
      : playerApi.unselectCartela(roundId, userId, number, requestId()));
    pendingOperationsRef.current.add(operation);
    operation.then((response) => {
      if (epochRef.current !== operationEpoch) return;
      const result = response as PoolResponse;
      revisionRef.current = Math.max(revisionRef.current, Number(result.pending_revision) || 0);
      const authoritative = selectedFromResponse(result, userId, optimistic);
      setPending(result.pending_selections || {});
      setTaken(new Set((result.taken_cartelas || []).map(Number)));
      publishSelected(authoritative);
      if (Number.isFinite(Number(result.play_wallet))) {
        setWalletOverride(Number(result.play_wallet));
        applyPlayWallet(Number(result.play_wallet));
      }
      if (Number.isFinite(Number(result.derash_pool))) setDerashOverride(Number(result.derash_pool));
    }).catch((cause) => {
      if (epochRef.current !== operationEpoch) return;
      publishSelected(selecting ? selectedRef.current.filter((item) => item !== number) : Array.from(new Set([...selectedRef.current, ...before.filter((item) => item === number)])));
      setError(errorText(cause));
    }).finally(() => {
      pendingOperationsRef.current.delete(operation);
      inFlightRef.current.delete(number);
      setMutating((previous) => { const next = new Set(previous); next.delete(number); return next; });
    });
  }, [applyPlayWallet, busy, publishSelected, seconds, taken, userId]);

  const participantCount = useMemo(() => {
    const numbers = new Set<number>(Array.from(taken));
    Object.values(pending).forEach((values) => values.forEach((number) => numbers.add(Number(number))));
    return Math.max(Number(round?.player_count || 0), numbers.size);
  }, [pending, round?.player_count, taken]);
  const derash = derashOverride ?? Math.round(participantCount * stake * 0.8 * 100) / 100;
  const wallet = walletOverride ?? walletValue(player?.play_wallet) ?? 0;
  const closed = Boolean(round && (round.status !== "selecting" || seconds <= 0));

  return <div className="flex min-h-[calc(100vh-56px)] flex-col bg-[linear-gradient(180deg,#0d0f22_0%,#151833_40%,#0d0f22_100%)]">
    <div className="flex items-center justify-between border-b border-white/5 px-4 pb-2 pt-4"><button onClick={() => navigate("/")} className="flex items-center gap-1 rounded-lg bg-indigo-600/90 px-3.5 py-1.5 text-xs font-bold text-white"><ArrowLeft className="h-3.5 w-3.5" /> Back</button><h3 className="text-sm font-bold tracking-wide text-white">Select Cartela</h3><span className="w-[62px]" /></div>
    <div className="flex items-center justify-between gap-1 border-b border-white/5 bg-[#111326]/60 px-4 py-3 text-[11px] font-semibold text-gray-300"><div className="flex gap-2"><Summary label="PLAY WALLET" value={`${wallet.toLocaleString()} ETB`} tone="text-[#34D399]" /><Summary label="STAKE" value={`${stake} ETB`} tone="text-[#FF8C00]" /><Summary label="DERASH POOL" value={`${derash} ETB`} tone="text-[#8B5CF6]" /></div><div className={`rounded-lg border px-3.5 py-1.5 text-[10px] font-black ${closed ? "border-amber-400/30 bg-amber-500/15 text-amber-200" : "border-emerald-500/30 bg-emerald-600/20 text-emerald-400"}`}>{closed ? (busy ? "STARTING…" : "CLOSED") : `${seconds}s`}</div></div>
    <div className="flex-1 overflow-y-auto px-2 py-2" aria-label="Available cartelas">{loading ? <div className="flex items-center justify-center py-16 text-sm text-white/35"><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Finding game…</div> : error && !round ? <div className="flex flex-col items-center justify-center gap-3 py-16 text-center text-xs text-red-300"><p>{error}</p><button type="button" onClick={startNewRound} className="rounded-xl bg-[#FF8C00] px-4 py-2 font-black text-white">Retry</button></div> : <div className="grid grid-cols-8 content-start gap-1.5 max-[360px]:grid-cols-7 max-[360px]:gap-1">{CARTELA_NUMBERS.map((number) => { const isSelected = selected.includes(number); const isUpdating = mutating.has(number); const isTaken = !isSelected && (taken.has(number) || Object.entries(pending).some(([owner, values]) => owner !== userId && values.includes(number))); return <button key={number} type="button" disabled={closed || isUpdating || isTaken} onClick={() => toggleCard(number)} className={`relative aspect-square rounded-lg border text-[13px] font-extrabold transition-transform active:scale-[0.92] disabled:opacity-60 ${isSelected ? "border-emerald-400/60 bg-emerald-600 text-white shadow-[0_0_15px_rgba(16,185,129,0.35)]" : isTaken ? "border-orange-400/50 bg-orange-500/20 text-orange-200" : "border-white/10 bg-[#1E2340] text-white"}`}>{isUpdating ? <Loader2 className="mx-auto h-4 w-4 animate-spin" /> : isSelected ? <Check className="mx-auto h-4 w-4" /> : isTaken ? "TAKEN" : number}</button>; })}</div>}</div>
    {selected.length > 0 && <div className="sticky bottom-0 z-20 border-t border-orange-400/30 bg-[#0e1026]/95 px-3 py-2"><div className="mb-1 text-center text-[10px] font-black uppercase tracking-[0.2em] text-orange-300">Selected cartelas</div><div className="grid grid-cols-2 justify-items-center gap-2">{selected.map((number) => <MiniPreview key={number} card={cards.find((item) => item.number === number) || fallbackCartela(number)} number={number} updating={mutating.has(number)} onRemove={() => toggleCard(number)} disabled={closed} />)}</div></div>}
    {error && round && <div className="mx-3 mb-1 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-300" role="alert">{error}</div>}
  </div>;
}

function Summary({ label, value, tone }: { label: string; value: string; tone: string }) { return <div className="flex flex-col justify-center rounded-lg border border-white/5 bg-[#1E2340] px-2 py-1"><span className="text-[9px] leading-none text-gray-500">{label}</span><span className={`mt-0.5 font-bold leading-normal ${tone}`}>{value}</span></div>; }

function MiniPreview({ card, number, updating, onRemove, disabled }: { card: Cartela; number: number; updating: boolean; onRemove: () => void; disabled: boolean }) {
  const values = cardValues(card, number);
  return <button type="button" onClick={onRemove} disabled={disabled || updating} className="w-[46%] max-w-[170px] rounded-lg text-left disabled:opacity-50"><div className="w-full overflow-hidden rounded-lg border-2 border-orange-400 bg-[#1A1A2E]"><div className="bg-gradient-to-r from-[#FF8C00] to-[#FF6B00] py-0.5 text-center text-[7px] font-black tracking-wider text-white">CARTELA NO: {number}</div><div className="grid grid-cols-5 gap-px">{["B", "I", "N", "G", "O"].map((letter, index) => <div key={letter} className="py-0.5 text-center text-[6px] font-black text-white" style={{ background: ["#3B82F6", "#8B5CF6", "#D946EF", "#10B981", "#F97316"][index] }}>{letter}</div>)}{values.map((value, index) => <div key={`${value}-${index}`} className={`aspect-square text-center text-[6px] font-bold leading-3 ${index === 12 ? "bg-emerald-500 text-white" : "bg-[#151833] text-white/70"}`}>{index === 12 ? "★" : value}</div>)}</div></div><span className="mt-1 block text-center text-[10px] font-bold text-red-300">{updating ? "Updating…" : "Tap to remove"}</span></button>;
}
