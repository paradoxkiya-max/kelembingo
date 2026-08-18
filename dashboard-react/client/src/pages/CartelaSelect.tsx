// Style reminder: replicate legacy card-select.html: compact Back/title row, three summary chips, eight-column touch grid, directly removable selected previews, and timer bar.

import { ArrowLeft, Check, Loader2 } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearch } from "wouter";
import { usePlayer } from "@/contexts/PlayerContext";
import { playerApi, type Cartela, type Round } from "@/lib/gateway";
import { walletValue } from "@/lib/format";
import { cardValues, fallbackCartela, isValidCartela } from "@/lib/cartelaFallback";
import { observeCartelaPool, observeRealtimeReconnect, observeRound, primeRoundSnapshot, roomManager } from "@/lib/realtime";

const STAKES = [10, 20];
const MAX_SELECTIONS = 2;
const SELECTION_SECONDS = 45;
const CARTELA_POOL: Cartela[] = Array.from({ length: 500 }, (_, index) => ({ number: index + 1 }));

type PoolSnapshot = { taken_cartelas?: number[]; player_count?: number; derash_pool?: number; pending_revision?: number; pending_selections?: Record<string, number[]>; selected_cartelas?: number[] };
type PoolStateLike = Pick<PoolSnapshot, "taken_cartelas" | "pending_revision" | "pending_selections">;

function poolStateFingerprint(snapshot: PoolStateLike, revision = Math.max(0, Number(snapshot.pending_revision) || 0)) {
  const pending = Object.entries(snapshot.pending_selections || {})
    .map(([userId, numbers]) => [String(userId), normalizeCartelas(numbers)] as const)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify({
    revision,
    taken_cartelas: (snapshot.taken_cartelas || []).map(Number).sort((a, b) => a - b),
    pending_selections: pending,
  });
}

function selectionRequestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `selection-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function roundDeadlinePassed(round?: Pick<Round, "selection_deadline"> | null) {
  const deadline = round?.selection_deadline ? new Date(round.selection_deadline).getTime() : 0;
  return Boolean(deadline && Number.isFinite(deadline) && deadline <= Date.now());
}

function mergePendingVisual(authoritative: number[], pending: Map<number, boolean>) {
  const next = new Set(normalizeCartelas(authoritative));
  pending.forEach((selecting, number) => selecting ? next.add(number) : next.delete(number));
  return normalizeCartelas(Array.from(next));
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
  const [mutatingCards, setMutatingCards] = useState<Set<number>>(new Set());
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [expired, setExpired] = useState(false);
  const [walletPreview, setWalletPreview] = useState<number | null>(null);
  const [committedWallet, setCommittedWallet] = useState<number | null>(null);
  const [serverClockOffset, setServerClockOffset] = useState(0);
  const [liveDerashPool, setLiveDerashPool] = useState<number | null>(null);
  const confirmStarted = useRef(false);
  const previewFetches = useRef(new Set<number>());
  const pendingRevision = useRef(0);
  const lastPoolSnapshotFingerprint = useRef("");
  const selectedRef = useRef<number[]>([]);
  const authoritativeSelectedRef = useRef<number[]>([]);
  const mutationCounts = useRef(new Map<number, number>());
  const pendingVisual = useRef(new Map<number, boolean>());
  const deadlineRetryTimer = useRef<number | null>(null);
  const previewSlotByCartela = useRef(new Map<number, number>());
  const selectionRequests = useRef(new Set<Promise<void>>());
  const selectionTails = useRef(new Map<number, Promise<void>>());
  const selectionEpoch = useRef(0);
  const currentRoundId = useRef("");
  const deadlineHandoff = useRef(false);

  const abortSelectionQueue = useCallback(() => {
    if (deadlineRetryTimer.current !== null) { window.clearTimeout(deadlineRetryTimer.current); deadlineRetryTimer.current = null; }
    selectionEpoch.current += 1;
    currentRoundId.current = "";
    mutationCounts.current.clear();
    pendingVisual.current.clear();
    setMutatingCards(new Set());
    selectionRequests.current.clear();
    selectionTails.current.clear();
  }, []);

  const wallet = walletValue(player?.play_wallet);
  const displayedWallet = walletPreview ?? committedWallet ?? wallet;
  const sharedCartelaCount = useMemo(() => {
    const allRoundCartelas = new Set<number>(Array.from(taken));
    Object.values(pending).forEach((numbers) => (numbers || []).forEach((number) => allRoundCartelas.add(Number(number))));
    selected.forEach((number) => allRoundCartelas.add(Number(number)));
    return Math.max(Number(round?.player_count || 0), allRoundCartelas.size);
  }, [pending, round?.player_count, selected, taken]);
  const sharedDerashPool = liveDerashPool ?? Math.round(sharedCartelaCount * stake * 0.80 * 100) / 100;
  const selectionClosed = expired || round?.status !== "selecting" || seconds <= 0;

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

  const restartSelection = useCallback(() => {
    if (deadlineHandoff.current) return;
    deadlineHandoff.current = true;
    abortSelectionQueue();
    setBusy(false);
    setExpired(false);
    setLoading(true);
    setLoadError("");
    setError("");
    setRound(null);
    setTaken(new Set());
    setPending({});
    setLiveDerashPool(null);
    setWalletPreview(null);
    publishSelected([]);
    setLoadAttempt((value) => value + 1);
  }, [abortSelectionQueue, publishSelected]);

  const applyPoolSnapshot = useCallback((snapshot: PoolSnapshot) => {
    const revision = Math.max(0, Number(snapshot.pending_revision) || 0);
    if ((!revision && pendingRevision.current > 0) || (revision && revision < pendingRevision.current)) return null;
    const nextPending = snapshot.pending_selections || {};
    const fingerprint = poolStateFingerprint(snapshot, revision);
    // A duplicate revision must describe the same committed transaction. If
    // it does not, the event bridge delivered an older conflicting snapshot;
    // applying it would resurrect a deselected card or make it appear taken.
    if (revision === pendingRevision.current && lastPoolSnapshotFingerprint.current && fingerprint !== lastPoolSnapshotFingerprint.current) return null;
    if (revision) pendingRevision.current = revision;
    lastPoolSnapshotFingerprint.current = fingerprint;
    const authoritative = snapshot.pending_selections !== undefined
      ? normalizeCartelas(nextPending[String(player?.user_id || "")] || [])
      : normalizeCartelas(snapshot.selected_cartelas || []);
    authoritativeSelectedRef.current = authoritative;
    setTaken(new Set((snapshot.taken_cartelas || []).map(Number)));
    if (snapshot.pending_selections !== undefined) setPending(nextPending);
    const visible = publishSelected(mergePendingVisual(authoritative, pendingVisual.current));
    if (Number.isFinite(Number(snapshot.derash_pool))) setLiveDerashPool(Math.round(Math.max(0, Number(snapshot.derash_pool)) * 100) / 100);
    return { authoritative, visible };
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
    let unsubscribeReconnect: (() => void) | null = null;
    setLoadError("");
    setError("");
    selectionRequests.current.clear();
    selectionTails.current.clear();
    currentRoundId.current = "";
    // createRound is atomic: it returns the existing active round or creates
    // the next one. One request removes the post-round monitor gap and makes
    // the stake-to-cartela transition faster than lookup-then-create.
    playerApi.createRound(stake).then((createResponse) => {
      if (!active || selectionEpoch.current !== epoch) return;
      const nextRound = createResponse.round || null;
      if (!nextRound) {
        setRound(null);
        setCartelas([]);
        setTaken(new Set());
        setPending({});
        publishSelected([]);
        setExpired(false);
        setLoadError("Unable to start the next round. Please try again.");
        return;
      }
      setCartelas([]);
      setSeconds(SELECTION_SECONDS);
      previewFetches.current.clear();
      confirmStarted.current = false;
      deadlineHandoff.current = false;
      setRound(nextRound);
      // The supplied production UI starts the selection screen and timer as soon
      // as a round exists. Cartela previews and realtime handshakes must never
      // keep the 500-card selector behind a full-page loading gate.
      setLoading(false);
      setLiveDerashPool(null);
      setCommittedWallet(null);
      pendingRevision.current = Math.max(0, Number(nextRound?.pending_revision) || 0);
      lastPoolSnapshotFingerprint.current = "";
      authoritativeSelectedRef.current = normalizeCartelas(nextRound?.pending_selections?.[String(player?.user_id || "")] || []);
      if (nextRound?.id) primeRoundSnapshot(String(nextRound.id), nextRound);
      setTaken(new Set((nextRound?.taken_cartelas || []).map(Number)));
      setPending(nextRound?.pending_selections || {});
      publishSelected(authoritativeSelectedRef.current);
      setExpired(false);
      const deadline = nextRound?.selection_deadline ? new Date(nextRound.selection_deadline).getTime() : 0;
      if (deadline) setSeconds(Math.max(0, Math.ceil((deadline - (Date.now() + serverClockOffset)) / 1000)));
      if (nextRound?.id) {
        currentRoundId.current = String(nextRound.id);
        unsubscribePool = observeCartelaPool(nextRound.id, (message) => {
          if (active && selectionEpoch.current === epoch) applyPoolSnapshot(message);
        });
        const applyRoundSnapshot = (latest: Round) => {
          if (!active || selectionEpoch.current !== epoch || String(latest.id || nextRound.id) !== String(nextRound.id)) return;
          const currentRevision = pendingRevision.current;
          const nextRevision = Math.max(0, Number(latest.pending_revision) || 0);
          const hasPoolState = latest.pending_selections !== undefined || latest.taken_cartelas !== undefined;
          const nextFingerprint = hasPoolState ? poolStateFingerprint(latest, nextRevision) : "";
          // A full round snapshot can arrive after a newer cartela_pool event.
          // Never let it roll the client back to an older revision or replace a
          // same-revision pool with conflicting contents.
          if (hasPoolState && nextRevision < currentRevision) return;
          if (hasPoolState && nextRevision === currentRevision && currentRevision > 0 && lastPoolSnapshotFingerprint.current && nextFingerprint !== lastPoolSnapshotFingerprint.current) return;
          const playerId = String(player?.user_id || "");
          const joinedCartelas = normalizeCartelas(latest.players?.[playerId]?.cartelas || []);
          setRound(latest);
          if (hasPoolState) {
            pendingRevision.current = nextRevision;
            lastPoolSnapshotFingerprint.current = nextFingerprint;
            const authoritative = normalizeCartelas(latest.pending_selections?.[playerId] || []);
            authoritativeSelectedRef.current = authoritative;
            setTaken(new Set((latest.taken_cartelas || []).map(Number)));
            setPending(latest.pending_selections || {});
            publishSelected(mergePendingVisual(authoritative, pendingVisual.current));
          }
          // A joined player must never remain on the selection grid. The
          // players snapshot can arrive just before the status=playing snapshot,
          // so redirect on either signal without waiting for another event.
          if (joinedCartelas.length > 0) {
            const targetId = String(latest.id || nextRound.id);
            abortSelectionQueue();
            primeRoundSnapshot(targetId, latest);
            publishSelected([]);
            setWalletPreview(null);
            setExpired(true);
            navigate(`/game?round=${encodeURIComponent(targetId)}`, { replace: true });
          } else if (latest.status === "playing") {
            setExpired(true);
            if (!confirmStarted.current) {
              confirmStarted.current = true;
              void confirmSelection();
            } else if (!selectedRef.current.length && selectionRequests.current.size === 0) {
              restartSelection();
            }
          } else if (latest.status === "completed") restartSelection();
        };
        void roomManager.roomJoin(String(nextRound.id), String(player?.user_id || "")).then((roomSnapshot) => {
          if (!active || selectionEpoch.current !== epoch) return;
          const authoritativeRound = roomSnapshot.round;
          if (authoritativeRound) applyRoundSnapshot(authoritativeRound);
        }).catch(() => undefined);
        unsubscribeRound = observeRound(nextRound.id, (latest) => {
          if (latest) applyRoundSnapshot(latest);
        }, { fetchInitial: false });
        unsubscribeReconnect = observeRealtimeReconnect(() => {
          void playerApi.round(String(nextRound.id)).then(({ round: latest }) => applyRoundSnapshot(latest)).catch(() => undefined);
        });
        const joinedCartelas = normalizeCartelas(nextRound.players?.[String(player?.user_id || "")]?.cartelas || []);
        if (nextRound.status === "playing" || joinedCartelas.length > 0) { const targetId = String(nextRound.id); abortSelectionQueue(); primeRoundSnapshot(targetId, nextRound); publishSelected([]); setWalletPreview(null); setExpired(true); navigate(`/game?round=${encodeURIComponent(targetId)}`, { replace: true }); }
        else if (nextRound.status === "completed") restartSelection();
      }
    }).catch((e) => active && selectionEpoch.current === epoch && setLoadError(e instanceof Error ? e.message : "Unable to load this round")).finally(() => active && selectionEpoch.current === epoch && setLoading(false));
    return () => { active = false; if (deadlineRetryTimer.current !== null) { window.clearTimeout(deadlineRetryTimer.current); deadlineRetryTimer.current = null; } selectionEpoch.current += 1; currentRoundId.current = ""; selectionRequests.current.clear(); selectionTails.current.clear(); unsubscribePool?.(); unsubscribeRound?.(); unsubscribeReconnect?.(); };
  }, [abortSelectionQueue, applyPoolSnapshot, loadAttempt, navigate, publishSelected, restartSelection, stake, player?.user_id]);

  useEffect(() => {
    let active = true;
    const sync = () => {
      const requestStarted = Date.now();
      void playerApi.time().then(({ iso }) => {
        const requestFinished = Date.now();
        const serverNow = new Date(iso).getTime();
        if (active && Number.isFinite(serverNow)) setServerClockOffset(serverNow - ((requestStarted + requestFinished) / 2));
      }).catch(() => undefined);
    };
    sync();
    const interval = window.setInterval(sync, 30000);
    return () => { active = false; window.clearInterval(interval); };
  }, []);

  useEffect(() => {
    const deadline = round?.selection_deadline ? new Date(round.selection_deadline).getTime() : 0;
    if (!deadline || round?.status !== "selecting") return;
    const sync = () => setSeconds(Math.max(0, Math.ceil((deadline - (Date.now() + serverClockOffset)) / 1000)));
    sync();
    const timer = window.setInterval(sync, 250);
    return () => window.clearInterval(timer);
  }, [round?.selection_deadline, round?.status, serverClockOffset]);

  useEffect(() => {
    if (seconds > 0 || !round?.id || confirmStarted.current) return;
    setExpired(true);
    // A tap can still be waiting on Socket.IO/REST when the clock reaches zero.
    // Join confirmation owns the queue drain; never restart the round before
    // the last select/deselect result has been applied.
    confirmStarted.current = true;
    setError("");
    void confirmSelection();
  }, [round?.id, seconds, selected.length]);

  useEffect(() => {
    const missing = selected.filter((number) => !cartelas.some((card) => card.number === number) && !previewFetches.current.has(number));
    if (!missing.length) return;
    let active = true;
    missing.forEach((number) => previewFetches.current.add(number));
    // Render the exact deterministic backend card immediately. The server
    // response remains authoritative and will replace this fallback below.
    setCartelas((old) => [...old, ...missing.map((number) => fallbackCartela(number))]);
    Promise.all(missing.map(async (number) => ({ number, card: (await playerApi.cartela(number)).cartela })))
      .then((items) => {
        if (!active) return;
        const validItems = items.filter(({ number, card }) => isValidCartela(card, number)).map(({ card }) => card as Cartela);
        if (validItems.length) setCartelas((old) => [...old.filter((card) => !validItems.some((item) => item.number === card.number)), ...validItems]);
        if (validItems.length < missing.length) setError("Showing the verified local cartela while the server card is unavailable.");
      })
      .catch(() => { if (active) setError("Showing the verified local cartela while the server card is unavailable."); });
    return () => { active = false; };
  }, [cartelas, selected]);

  const visibleCartelas = useMemo(() => CARTELA_POOL, []);

  const toggleCard = useCallback((number: number) => {
    const current = selectedRef.current;
    const userId = String(player?.user_id || "");
    const selecting = !current.includes(number);
    const roundId = String(round?.id || "");
    if (busy || (!selecting && !current.includes(number)) || (selecting && taken.has(number)) || !userId || selectionClosed || !roundId) return;
    if (selecting && current.length >= MAX_SELECTIONS) return;
    const requestId = selectionRequestId();
    const epoch = selectionEpoch.current;
    mutationCounts.current.set(number, (mutationCounts.current.get(number) || 0) + 1);
    pendingVisual.current.set(number, selecting);
    setMutatingCards((previous) => new Set(previous).add(number));
    publishSelected(selecting ? [...current, number] : current.filter((item) => item !== number));
    setError("");
    const execute = async () => {
      if (selectionEpoch.current !== epoch || currentRoundId.current !== roundId || deadlineHandoff.current) return;
      try {
        let result: PoolSnapshot & { ok?: boolean; play_wallet?: number; error?: string };
        try {
          result = await roomManager.roomIntent({ round_id: roundId, user_id: userId, intent_id: requestId, action: selecting ? "select" : "unselect", cartela_number: number });
          if (!result.ok && /room_protocol_disabled|realtime connection unavailable|realtime request timed out|invalid realtime response/i.test(result.error || "")) throw new Error(result.error || "Realtime fallback");
          if (!result.ok) throw new Error(result.error || "Selection failed");
        } catch (roomError) {
          if (!/room_protocol_disabled|realtime connection unavailable|realtime request timed out|invalid realtime response/i.test(roomError instanceof Error ? roomError.message : "")) throw roomError;
          result = await (selecting
            ? playerApi.selectCartela(roundId, userId, number, requestId)
            : playerApi.unselectCartela(roundId, userId, number, requestId));
        }
        if (selectionEpoch.current !== epoch || currentRoundId.current !== roundId) return;
        if (pendingVisual.current.get(number) === selecting) pendingVisual.current.delete(number);
        applyPoolSnapshot(result);
        if (Number.isFinite(Number(result.play_wallet))) {
          const balance = Number(result.play_wallet);
          setCommittedWallet(balance);
          applyPlayWallet(balance);
          setWalletPreview(null);
        }
      } catch (e) {
        if (selectionEpoch.current !== epoch || currentRoundId.current !== roundId) return;
        const message = e instanceof Error ? e.message : "Selection failed";
        const latest = /already joined|opening the game board|selection window closed|round not in selecting/i.test(message)
          ? await playerApi.round(roundId).then((response) => response.round).catch(() => null)
          : null;
        const joined = normalizeCartelas(latest?.players?.[userId]?.cartelas || []);
        if (latest?.id && joined.length > 0) {
          primeRoundSnapshot(roundId, latest);
          abortSelectionQueue();
          setWalletPreview(null);
          navigate(`/game?round=${encodeURIComponent(roundId)}`, { replace: true });
          return;
        }
        if (latest && (latest.status !== "selecting" || roundDeadlinePassed(latest))) {
          restartSelection();
          return;
        }
        if (pendingVisual.current.get(number) === selecting) {
          pendingVisual.current.delete(number);
          publishSelected(authoritativeSelectedRef.current);
        }
        setError(message);
      } finally {
        if (selectionEpoch.current === epoch && currentRoundId.current === roundId) {
          const remaining = Math.max(0, (mutationCounts.current.get(number) || 1) - 1);
          if (remaining) mutationCounts.current.set(number, remaining);
          else {
            mutationCounts.current.delete(number);
            setMutatingCards((previous) => { const next = new Set(previous); next.delete(number); return next; });
          }
        }
      }
    };
    const previous = selectionTails.current.get(number) || Promise.resolve();
    const operation = previous.then(execute);
    const tail = operation.catch(() => undefined);
    selectionTails.current.set(number, tail);
    selectionRequests.current.add(operation);
    void operation.finally(() => {
      selectionRequests.current.delete(operation);
      if (selectionTails.current.get(number) === tail) selectionTails.current.delete(number);
    }).catch(() => undefined);
  }, [abortSelectionQueue, applyPlayWallet, applyPoolSnapshot, busy, navigate, player?.user_id, restartSelection, round?.id, selectionClosed, taken]);

  async function confirmSelection() {
    if (busy || !player?.user_id || !round?.id) return;
    setBusy(true);
    const activeRoundId = String(round.id);
    const userId = String(player.user_id);
    const epoch = selectionEpoch.current;
    const displayName = player.username ? `@${player.username.replace(/^@/, "")}` : player.first_name || "Player";
    try {
      // Every tap is a durable mutation. Joining before this queue drains can
      // race the last select/deselect and either strand a card or charge twice.
      const queuedOperations = Array.from(selectionRequests.current);
      if (queuedOperations.length) await Promise.allSettled(queuedOperations);
      if (selectionEpoch.current !== epoch || currentRoundId.current !== activeRoundId) return;

      const latest = await playerApi.round(activeRoundId).then((response) => response.round);
      if (!latest?.id) throw new Error("Round is no longer available");
      const joinedAlready = normalizeCartelas(latest.players?.[userId]?.cartelas || []);
      if (joinedAlready.length > 0) {
        primeRoundSnapshot(activeRoundId, latest);
        abortSelectionQueue();
        setWalletPreview(null);
        navigate(`/game?round=${encodeURIComponent(activeRoundId)}`, { replace: true });
        return;
      }

      applyPoolSnapshot(latest);
      const committedSelection = normalizeCartelas(latest.pending_selections?.[userId] || []);
      if (!committedSelection.length) {
        publishSelected([]);
        setWalletPreview(null);
        restartSelection();
        return;
      }

      const response = await playerApi.joinRound(activeRoundId, userId, committedSelection, displayName, {
        requirePending: true,
        pendingRevision: Number(latest.pending_revision || 0),
      });
      const joinedRound = response.round || await playerApi.round(activeRoundId).then((result) => result.round);
      const committedOnServer = normalizeCartelas(joinedRound?.players?.[userId]?.cartelas || []);
      if (!committedOnServer.length || !committedSelection.every((number) => committedOnServer.includes(number))) {
        throw new Error("The server did not confirm the selected cartelas");
      }
      primeRoundSnapshot(activeRoundId, joinedRound);
      abortSelectionQueue();
      publishSelected([]);
      setWalletPreview(null);
      navigate(`/game?round=${encodeURIComponent(activeRoundId)}`, { replace: true });
    } catch (e) {
      if (selectionEpoch.current !== epoch || currentRoundId.current !== activeRoundId) return;
      const message = e instanceof Error ? e.message : "Could not join the round";
      const latest = await playerApi.round(activeRoundId).then((response) => response.round).catch(() => null);
      const joined = normalizeCartelas(latest?.players?.[userId]?.cartelas || []);
      if (latest?.id && joined.length > 0) {
        primeRoundSnapshot(activeRoundId, latest);
        abortSelectionQueue();
        setWalletPreview(null);
        navigate(`/game?round=${encodeURIComponent(activeRoundId)}`, { replace: true });
        return;
      }
      if (!latest) {
        setError("Reconnecting to confirm your cartela…");
        confirmStarted.current = false;
        if (deadlineRetryTimer.current === null) {
          deadlineRetryTimer.current = window.setTimeout(() => {
            deadlineRetryTimer.current = null;
            if (selectionEpoch.current === epoch && currentRoundId.current === activeRoundId) {
              confirmStarted.current = true;
              void confirmSelection();
            }
          }, 600);
        }
        return;
      }
      if (latest && (latest.status !== "selecting" || roundDeadlinePassed(latest))) {
        restartSelection();
        return;
      }
      setError(message);
    } finally {
      if (selectionEpoch.current === epoch) setBusy(false);
    }
  }

  return <div className="flex min-h-[calc(100vh-56px)] flex-col bg-[linear-gradient(180deg,#0d0f22_0%,#151833_40%,#0d0f22_100%)]">
    <div className="flex items-center justify-between border-b border-white/5 px-4 pb-2 pt-4"><button onClick={() => navigate("/")} className="flex items-center gap-1 rounded-lg bg-indigo-600/90 px-3.5 py-1.5 text-xs font-bold text-white shadow-md transition-transform active:scale-[0.97]"><ArrowLeft className="h-3.5 w-3.5" /> Back</button><h3 className="text-sm font-bold tracking-wide text-white">Select Cartela</h3><span className="w-[62px]" /></div>
    <div className="flex items-center justify-between gap-1 border-b border-white/5 bg-[#111326]/60 px-4 py-3 text-[11px] font-semibold text-gray-300"><div className="flex gap-2"><Summary label="PLAY WALLET" value={`${displayedWallet.toLocaleString()} ETB`} tone="text-[#34D399]" /><Summary label="STAKE" value={`${stake} ETB`} tone="text-[#FF8C00]" /><Summary label="DERASH POOL" value={`${sharedDerashPool} ETB`} tone="text-[#8B5CF6]" /></div><div className={`relative flex min-w-[68px] items-center justify-center overflow-hidden rounded-lg border px-3.5 py-1.5 ${expired ? "border-amber-400/30 bg-amber-500/15 text-amber-200" : "border-emerald-500/30 bg-emerald-600/20 text-emerald-400"}`}><div className="absolute inset-y-0 left-0 bg-gradient-to-r from-[#10B981] to-[#34D399] opacity-30 transition-[width] duration-300" style={{ width: `${Math.min(100, Math.max(0, (seconds / SELECTION_SECONDS) * 100))}%` }} /><span className="relative z-10 text-[10px] font-black">{selectionClosed ? (busy ? "STARTING…" : "CLOSED") : seconds > 0 ? `${seconds}s` : "GO"}</span></div></div>
    <div className="card-select-grid-enhanced flex-1 overflow-y-auto px-2 py-2 [contain:layout_style]" aria-label="Available cartelas">{!round ? (loading ? <div className="flex items-center justify-center py-16 text-sm text-white/35"><Loader2 className="mr-2 h-4 w-4" /> Finding game…</div> : loadError ? <div className="flex flex-col items-center justify-center gap-3 px-4 py-16 text-center text-xs text-red-300"><p>{loadError}</p><button type="button" onClick={() => { setLoading(true); setLoadError(""); setLoadAttempt((value) => value + 1); }} className="rounded-xl bg-[#FF8C00] px-4 py-2 font-black text-white">Retry</button></div> : null) : <CartelaGrid selected={selected} pending={pending} taken={taken} mutating={mutatingCards} closed={selectionClosed} playerId={String(player?.user_id || "")} onToggle={toggleCard} />}</div>
    {selected.length > 0 && <div className="sticky bottom-0 z-20 border-t border-orange-400/30 bg-[#0e1026]/95 px-3 py-2 shadow-[0_-10px_25px_rgba(0,0,0,0.35)] backdrop-blur-md"><div className="mb-1 text-center text-[10px] font-black uppercase tracking-[0.2em] text-orange-300">Selected cartelas</div><p className="mb-2 text-center text-[10px] font-semibold text-white/50">Tap a selected cartela to remove it</p><div className="grid grid-cols-2 justify-items-center gap-2">{[0, 1].map((slot) => { const number = selected.find((candidate) => previewSlotByCartela.current.get(candidate) === slot); const card = number === undefined ? undefined : cartelas.find((item) => item.number === number); return number === undefined ? <div key={`empty-slot-${slot}`} className="w-[46%] max-w-[170px]" aria-hidden="true" /> : <button key={number} type="button" onClick={() => void toggleCard(number)} disabled={selectionClosed || busy || mutatingCards.has(number)} aria-label={`Remove selected Cartela ${number}`} className="w-[46%] max-w-[170px] rounded-lg text-left transition-transform active:scale-[0.97] disabled:opacity-50"><MiniPreview card={card} /><span className="mt-1 block text-center text-[10px] font-bold text-red-300">Tap to remove</span></button>; })}</div></div>}
    {error && <div className="mx-3 mb-1 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-300" role="alert">{error}</div>}
  </div>;
}

function Summary({ label, value, tone }: { label: string; value: string; tone: string }) { return <div className="flex flex-col justify-center rounded-lg border border-white/5 bg-[#1E2340] px-2 py-1"><span className="text-[9px] leading-none text-gray-500">{label}</span><span className={`mt-0.5 font-bold leading-normal ${tone}`}>{value}</span></div>; }
const CartelaGrid = memo(function CartelaGrid({ selected, pending, taken, mutating, closed, playerId, onToggle }: { selected: number[]; pending: Record<string, number[]>; taken: Set<number>; mutating: Set<number>; closed: boolean; playerId: string; onToggle: (number: number) => void }) {
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const pendingTaken = useMemo(() => {
    const next = new Set<number>();
    Object.entries(pending).forEach(([userId, numbers]) => { if (userId !== playerId) (numbers || []).forEach((number) => next.add(Number(number))); });
    return next;
  }, [pending, playerId]);
  return <div className="grid grid-cols-8 content-start gap-1.5 max-[360px]:grid-cols-7 max-[360px]:gap-1">{CARTELA_POOL.map((card) => {
    const isSelected = selectedSet.has(card.number);
    const isMutating = mutating.has(card.number);
    const isTaken = !isSelected && (taken.has(card.number) || pendingTaken.has(card.number));
    return <button key={card.number} disabled={closed || isTaken || isMutating} onClick={() => onToggle(card.number)} aria-label={`Cartela ${card.number}${isMutating ? ", updating" : isTaken ? ", taken" : isSelected ? ", selected" : ""}`} className={`relative aspect-square rounded-lg border text-[13px] font-extrabold transition-transform active:scale-[0.92] ${isTaken ? "pointer-events-none border-[#FF8C00] bg-[#FF8C00]/25 text-[#FFB45C] shadow-[0_0_12px_rgba(255,140,0,0.35)]" : isSelected ? "z-[1] scale-[1.04] border-emerald-400/60 bg-gradient-to-br from-[#10B981] to-[#059669] text-white shadow-[0_0_16px_rgba(16,185,129,0.45)]" : "border-white/10 bg-gradient-to-br from-[#1E2340] to-[#151833] text-white shadow-[0_2px_8px_rgba(0,0,0,0.3)]"}`}>{isMutating ? <Loader2 className="mx-auto h-4 w-4 animate-spin" /> : isSelected ? <Check className="mx-auto h-4 w-4" /> : isTaken ? <span className="text-[10px]">TAKEN</span> : card.number}</button>;
  })}</div>;
});
function MiniPreview({ card }: { card?: Cartela }) { const values = cardValues(card, card?.number); return <div className="w-full overflow-hidden rounded-lg border-2 border-orange-400 bg-[#1A1A2E] shadow-[0_0_14px_rgba(255,140,0,0.25)]"><div className="bg-gradient-to-r from-[#FF8C00] to-[#FF6B00] py-0.5 text-center text-[7px] font-black tracking-wider text-white">CARTELA NO: {card?.number || "—"}</div><div className="grid grid-cols-5 gap-px">{["B", "I", "N", "G", "O"].map((letter, index) => <div key={letter} className="py-0.5 text-center text-[6px] font-black text-white" style={{ background: ["#3B82F6", "#8B5CF6", "#D946EF", "#10B981", "#F97316"][index] }}>{letter}</div>)}{values.map((number, index) => <div key={`${number}-${index}`} className={`aspect-square text-center text-[6px] font-bold leading-3 ${index === 12 ? "bg-emerald-500 text-white" : "bg-[#151833] text-white/70"}`}>{index === 12 ? "★" : number}</div>)}</div></div>; }
function normalizeCartelas(values: unknown) { return Array.isArray(values) ? Array.from(new Set(values.map(Number).filter((value) => Number.isInteger(value) && value >= 1 && value <= 500))).slice(0, MAX_SELECTIONS) : []; }
function flattenCartela(card?: Cartela) { const source: unknown = card?.cartela || card?.data || card?.grid || []; const values = Array.isArray(source) && Array.isArray(source[0]) ? (source as number[][]).reduce<number[]>((all, row) => all.concat(row), []) : Array.isArray(source) ? source as number[] : []; return values.length === 25 ? values : Array.from({ length: 25 }, (_, index) => index + 1); }
