"""
Kelem Bingo — Round-Based Multiplayer Engine
=============================================
Manages 500 fixed cartelas, round lifecycle, number calling, bingo checking,
and prize distribution.
"""

import random
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from firestore_db import (
    FieldFilter,
    transactional as firestore_transactional,
    run_idempotent,
    Increment,
    ArrayUnion,
)
from firestore_db import MockFirestoreClient

logger = logging.getLogger(__name__)


# ─── Constants ───
TOTAL_CARTELAS = 500
DEFAULT_STAKE = 10
VALID_STAKES = [10, 20]
ADMIN_CUT_RATIO = 0.25          # 25% of pool goes to admin
SELECTION_DURATION = 45          # seconds for card selection phase
NUMBER_CALL_INTERVAL = 5        # seconds between each called number (5s countdown)
MAX_CARTELAS_PER_PLAYER = 2
BINGO_NUMBERS = range(1, 76)    # 1-75
GAME_LENGTH_RANGE = (15, 30)    # random target: each round ends between 15-30 numbers

_CARTELA_CACHE = {}   # Global cache: cartela_number -> flat cartela list
_PATTERN_CACHE = {}    # Global cache: tuple(flat_cartela) -> list of patterns


def _parse_dt(value):
    """Parse a stored datetime (ISO string or datetime) into a tz-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
    return None


def _grid_next_number_at(game_started_at, calls_made: int) -> datetime:
    """
    Strict 5s cadence: the deadline for the NEXT call is anchored to the round's
    game_started_at, not to when the previous call finished. This keeps intervals
    exactly NUMBER_CALL_INTERVAL apart across the whole round (no drift) and makes
    every device's countdown agree on the same absolute timeline.
    """
    started = _parse_dt(game_started_at)
    now = datetime.now(tz=timezone.utc)
    minimum_deadline = now + timedelta(seconds=NUMBER_CALL_INTERVAL)
    if started is None:
        return minimum_deadline
    anchored_deadline = started + timedelta(seconds=(calls_made + 1) * NUMBER_CALL_INTERVAL)
    # Preserve the anchored cadence when processing is on time; otherwise give
    # the client a full visible interval instead of publishing an expired timer.
    return max(anchored_deadline, minimum_deadline)

class RoundEngine:
    def __init__(self, db):
        self.db = db
        self.master_ref = db.collection('cartelas_master')
        self.rounds_ref = db.collection('rounds')
        self._round_locks = {}
        self._user_locks = {}

    # ═══════════════════════════════════════════════════════════════
    # Cartela Generation (one-time, admin-triggered)
    # ═══════════════════════════════════════════════════════════════
    def _generate_single_cartela(self, seed: int) -> List[int]:
        """Generate a deterministic 5×5 bingo card as flat 25-int list.
        Uses seed so the same cartela number always produces the same card."""
        rng = random.Random(seed)
        cols = {
            'B': rng.sample(range(1, 16), 5),
            'I': rng.sample(range(16, 31), 5),
            'N': rng.sample(range(31, 46), 5),
            'G': rng.sample(range(46, 61), 5),
            'O': rng.sample(range(61, 76), 5),
        }
        flat = []
        for row_idx in range(5):
            flat.append(cols['B'][row_idx])
            flat.append(cols['I'][row_idx])
            # Free center space
            flat.append(0 if row_idx == 2 else cols['N'][row_idx])
            flat.append(cols['G'][row_idx])
            flat.append(cols['O'][row_idx])
        return flat

    async def generate_all_cartelas(self) -> dict:
        """Generate 500 fixed cartelas in cartelas_master. Idempotent."""
        return await asyncio.to_thread(self._generate_all_cartelas_sync)

    def _generate_all_cartelas_sync(self) -> dict:
        import threading, time as _time
        t_start = _time.monotonic()
        logger.info(f"[CART-DBG] _sync ENTERED thread={threading.current_thread().name}")
        logger.info("[CART-DBG] Checking for existing cartelas...")
        t0 = _time.monotonic()
        existing = list(self.master_ref.limit(1).get())
        logger.info(f"[CART-DBG] Existence check took {round(_time.monotonic()-t0, 2)}s, found={len(existing)}")
        if existing:
            t0 = _time.monotonic()
            count = len(list(self.master_ref.get()))
            logger.info(f"[CART-DBG] Cartelas already exist, count={count} (count query took {round(_time.monotonic()-t0, 2)}s)")
            return {'status': 'already_exists', 'count': count}

        logger.info("[CART-DBG] Starting generation of 500 cartelas...")
        batch_size = 100
        generated = 0
        for start in range(1, TOTAL_CARTELAS + 1, batch_size):
            t_batch = _time.monotonic()
            batch = self.db.batch(skip_events=True)
            end = min(start + batch_size, TOTAL_CARTELAS + 1)
            for num in range(start, end):
                cartela = self._generate_single_cartela(num * 1337)
                doc_ref = self.master_ref.document(str(num))
                batch.set(doc_ref, {
                    'number': num,
                    'cartela': cartela,
                    'generated_at': datetime.now(tz=timezone.utc),
                })
                generated += 1
            batch.commit()
            logger.info(f"[CART-DBG] Batch {start}-{end-1} committed in {round(_time.monotonic()-t_batch, 2)}s ({generated}/{TOTAL_CARTELAS})")

        total = round(_time.monotonic() - t_start, 2)
        logger.info(f"[CART-DBG] Generated {generated} cartelas in {total}s")
        return {'status': 'generated', 'count': generated}

    async def get_all_cartelas(self) -> List[dict]:
        """Return all 500 master cartelas."""
        docs = self.master_ref.order_by('number').get()
        return [{'id': doc.id, **doc.to_dict()} for doc in docs]

    async def get_cartela(self, number: int) -> Optional[dict]:
        """Get a single cartela by number."""
        doc = self.master_ref.document(str(number)).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    # ═══════════════════════════════════════════════════════════════
    # Round Lifecycle
    # ═══════════════════════════════════════════════════════════════
    async def get_active_round(self, stake: int = DEFAULT_STAKE) -> Optional[dict]:
        """Find the newest selecting/playing round with one database query."""
        docs = list(self.rounds_ref
                   .where('status', 'in', ['selecting', 'playing'])
                   .where('stake', '==', stake)
                   .order_by('created_at', 'DESCENDING')
                   .limit(1)
                   .get())
        if docs:
            doc = docs[0]
            return {'id': doc.id, **doc.to_dict()}
        return None

    async def create_round(self, stake: int = DEFAULT_STAKE) -> dict:
        """Create a new round in 'selecting' state."""
        if stake not in VALID_STAKES:
            stake = DEFAULT_STAKE

        def _apply(transaction):
            # The account lock makes the active-round check and creation one
            # cross-process critical section. A read-then-write check here can
            # otherwise create two same-stake rounds under simultaneous joins.
            active_query = (self.rounds_ref
                            .where('status', 'in', ['selecting', 'playing'])
                            .where('stake', '==', stake)
                            .order_by('created_at', 'DESCENDING')
                            .limit(1))
            active_docs = list(transaction.query(active_query).get())
            if active_docs:
                doc = active_docs[0]
                return {'id': doc.id, **doc.to_dict()}

            now = datetime.now(tz=timezone.utc)
            game_target = self.normalize_game_target()
            round_data = {
                'status': 'selecting',
                'stake': stake,
                'players': {},
                'player_count': 0,
                'taken_cartelas': [],
                'called_numbers': [],
                'winners': [],
                'prize_per_winner': 0,
                'admin_profit': 0,
                'game_target': game_target,
                'selection_deadline': now + timedelta(seconds=SELECTION_DURATION),
                'created_at': now,
                'completed_at': None,
            }
            doc_ref = self.rounds_ref.document()
            transaction.set(doc_ref, round_data)
            return {'id': doc_ref.id, **round_data}

        return await asyncio.to_thread(
            lambda: run_idempotent(
                f'round-create:{stake}:{uuid.uuid4().hex}',
                'round_create',
                _apply,
                lock_key=f'active-round:{stake}',
            )
        )

    def join_round_sync(self, round_id: str, user_id: int, 
                        cartela_numbers: List[int], user_name: str) -> dict:
        """Synchronous implementation of player joining a round."""
        from settlement import join_round
        operation_key = (
            f"{round_id}:{user_id}:"
            f"{','.join(str(number) for number in cartela_numbers)}"
        )
        return join_round(
            self.db,
            round_id,
            user_id,
            cartela_numbers,
            user_name,
            max_cartelas=MAX_CARTELAS_PER_PLAYER,
            total_cartelas=TOTAL_CARTELAS,
            idempotency_key=operation_key,
        )
    async def join_round(self, round_id: str, user_id: int, 
                         cartela_numbers: List[int], user_name: str) -> dict:
        """Player joins a round with chosen cartelas (max 2).
        Serialized per round via asyncio.Lock to prevent DB lock contention and RAM spikes under high concurrency.
        """
        if user_id not in self._user_locks:
            self._user_locks[user_id] = asyncio.Lock()
        if round_id not in self._round_locks:
            self._round_locks[round_id] = asyncio.Lock()

        # Lock the user first so one wallet cannot be reserved by two rounds in
        # this gateway process. The database-level is_playing guard remains the
        # source of truth across restarts and separate services.
        async with self._user_locks[user_id]:
            async with self._round_locks[round_id]:
                return await asyncio.to_thread(
                    self.join_round_sync, round_id, user_id, cartela_numbers, user_name
                )

    async def start_round(self, round_id: str) -> dict:
        """Transition round from 'selecting' to 'playing'."""
        round_doc = self.rounds_ref.document(round_id).get()
        if not round_doc.exists:
            return {'error': 'Round not found'}

        data = round_doc.to_dict()
        if data['status'] != 'selecting':
            return {'error': 'Round already started or completed'}

        player_count = data.get('player_count', 0)
        round_stake = data.get('stake', DEFAULT_STAKE)
        total_pool = player_count * round_stake
        derash = total_pool * 0.75

        now = datetime.now(tz=timezone.utc)
        game_target = self.normalize_game_target(data.get('game_target'))
        self.rounds_ref.document(round_id).update({
            'status': 'playing',
            'game_target': game_target,
            'game_started_at': now,
            'derash': derash,
            'next_number_at': now + timedelta(seconds=NUMBER_CALL_INTERVAL),
        })

        return {'status': 'playing', 'player_count': player_count, 'derash': derash, 'game_target': game_target}

    def normalize_game_target(self, game_target: Optional[int] = None) -> int:
        """Return a random call number between 15-30 where Phase 2
        (targeted winner making) begins. The exact game-end depends
        on how many extra calls Phase 2 needs to complete the target
        pattern (typically 0-2)."""
        min_calls, max_calls = GAME_LENGTH_RANGE
        if game_target is None:
            return random.randint(min_calls, max_calls)
        try:
            target = int(game_target)
        except (TypeError, ValueError):
            return random.randint(min_calls, max_calls)
        return max(min_calls, min(max_calls, target))

    def build_player_cartelas(self, players: Dict[str, dict]) -> Dict[str, List[dict]]:
        """Load all cartelas + cached patterns for active players."""
        if not _CARTELA_CACHE:
            try:
                docs = self.master_ref.get()
                for doc in docs:
                    _CARTELA_CACHE[doc.id] = doc.to_dict().get('cartela', [])
            except Exception:
                pass

        player_cartelas = {}
        for uid_str, p_info in (players or {}).items():
            player_cartelas[uid_str] = []
            for cnum in p_info.get('cartelas', []):
                ctype = str(cnum)
                flat = _CARTELA_CACHE.get(ctype)
                if flat is None:
                    cdoc = self.master_ref.document(ctype).get()
                    if not cdoc.exists:
                        continue
                    flat = cdoc.to_dict().get('cartela', [])
                    _CARTELA_CACHE[ctype] = flat
                patterns = self.get_cartela_patterns(flat)
                player_cartelas[uid_str].append({
                    'cartela_number': int(cnum),
                    'flat': flat,
                    'patterns': patterns,
                })
        return player_cartelas

    def _entry_patterns(self, entry: dict) -> List[List[int]]:
        patterns = entry.get('patterns')
        if patterns is None:
            patterns = self.get_cartela_patterns(entry.get('flat', []))
            entry['patterns'] = patterns
        return patterns

    def _has_winner(self, patterns: List[List[int]], called_set: set) -> bool:
        for pattern in patterns:
            if all(n in called_set for n in pattern):
                return True
        return False

    def evaluate_winners(self, player_cartelas: Dict[str, List[dict]],
                          called_numbers: List[int]) -> List[dict]:
        called_set = set(called_numbers)
        winners = []
        for uid_str, cartelas in player_cartelas.items():
            for entry in cartelas:
                if self._has_winner(self._entry_patterns(entry), called_set):
                    winners.append({
                        'user_id': uid_str,
                        'cartela_number': int(entry.get('cartela_number', 0)),
                    })
                    break
        return winners

    def _winner_sort_key(self, user_id: str, cartela_number: int, players: Dict[str, dict]) -> Tuple[str, int, str]:
        joined_at = (players or {}).get(user_id, {}).get('joined_at') or "9999-12-31T23:59:59"
        return (str(joined_at), int(cartela_number), str(user_id))

    def choose_single_winner(self, winners: List[dict], players: Dict[str, dict]) -> Optional[dict]:
        """Pick exactly one winner deterministically when multiple players hit on the same call."""
        if not winners:
            return None
        return min(
            winners,
            key=lambda item: self._winner_sort_key(
                item.get('user_id', ''),
                item.get('cartela_number', 0),
                players,
            ),
        )

    def _candidate_progress(self, player_cartelas: Dict[str, List[dict]],
                             simulated_called: List[int]) -> int:
        """Return the minimum number of additional calls needed for ANY player
        to complete a winning pattern with these called numbers.
        Lower = closer to a real bingo. 0 means a winner already exists."""
        called_set = set(simulated_called)
        min_missing = 999
        for uid_str, cartelas in player_cartelas.items():
            for entry in cartelas:
                for pattern in self._entry_patterns(entry):
                    missing = 0
                    for n in pattern:
                        if n not in called_set:
                            missing += 1
                            if missing >= min_missing:
                                break
                    if missing == 0:
                        return 0
                    if missing < min_missing:
                        min_missing = missing
        return min_missing

    def _select_predetermined_winner(self, player_cartelas: Dict[str, List[dict]]) -> Optional[dict]:
        """Pick a random player and a random winning pattern from their cartela.
        This guarantees a winner exists — the engine just calls their remaining numbers in Phase 2."""
        if not player_cartelas:
            return None
        user_ids = list(player_cartelas.keys())
        winner_uid = random.choice(user_ids)
        entries = player_cartelas[winner_uid]
        entry = random.choice(entries)
        patterns = self._entry_patterns(entry)
        pattern = random.choice(patterns)
        return {
            'user_id': winner_uid,
            'cartela_number': entry['cartela_number'],
            'pattern': pattern,
        }

    def _pick_target_winner(self, player_cartelas: Dict[str, List[dict]],
                             called_numbers: List[int],
                             players: Dict[str, dict]) -> Optional[dict]:
        """Pick a player/cartela/pattern closest to completion."""
        called_set = set(called_numbers)
        candidates = []
        for uid_str, cartelas in player_cartelas.items():
            for entry in cartelas:
                for pattern in self._entry_patterns(entry):
                    missing = [n for n in pattern if n not in called_set]
                    if not missing:
                        continue
                    candidates.append({
                        'user_id': uid_str,
                        'cartela_number': entry['cartela_number'],
                        'pattern': pattern,
                        'missing': len(missing),
                    })
        if not candidates:
            return None
        min_missing = min(c['missing'] for c in candidates)
        tier = [c for c in candidates if c['missing'] == min_missing]
        return random.choice(tier)

    async def _db(self, call):
        """Run a sync DB call in a thread to avoid blocking the event loop."""
        return await asyncio.to_thread(call)

    async def call_number(self, round_id: str) -> Optional[int]:
        """Call the next number for the round.

        Runs the CPU-heavy predictor in a worker thread so the asyncio event loop
        stays responsive — this keeps Socket.IO broadcasts and the 5s cadence tight.
        """
        return await asyncio.to_thread(self._call_number_sync, round_id)

    def _call_number_sync(self, round_id: str) -> Optional[int]:
        """Phase 1 (calls 1-15): random safe numbers, avoid any winner.
        Phase 2 (calls 16+): target a winner and complete their pattern."""
        round_doc = self.rounds_ref.document(round_id).get()
        if not round_doc.exists:
            return None

        data = round_doc.to_dict()
        if data['status'] != 'playing':
            return None

        called = list(data.get('called_numbers', []))
        called_set = set(called)
        available = [n for n in BINGO_NUMBERS if n not in called_set]
        if not available:
            return None

        next_call_index = len(called) + 1
        game_target = self.normalize_game_target(data.get('game_target'))
        players = data.get('players', {})
        player_cartelas = self.build_player_cartelas(players)

        number = available[0]

        # Ensure a predetermined winner is selected; the durable commit below
        # persists it together with the first successful number call.
        target_winner = data.get('target_winner')
        if not target_winner:
            target_winner = self._select_predetermined_winner(player_cartelas)

        winning_pattern = set(target_winner.get('pattern', [])) if target_winner else set()

        # ── Phase 1: safe, avoid winner, prefer winner's pattern numbers ──
        if next_call_index < game_target:
            random.shuffle(available)
            chosen = None

            # Prefer winner's pattern numbers, but leave at least 1 for Phase 2
            if target_winner and len(winning_pattern - called_set) > 1:
                for candidate in available:
                    if candidate in winning_pattern:
                        sim_set = called_set | {candidate}
                        safe = True
                        for uid_str, cartelas in player_cartelas.items():
                            if not safe:
                                break
                            for entry in cartelas:
                                if self._has_winner(self._entry_patterns(entry), sim_set):
                                    safe = False
                                    break
                        if safe:
                            chosen = candidate
                            break

            if chosen is None:
                for candidate in available:
                    sim_set = called_set | {candidate}
                    safe = True
                    for uid_str, cartelas in player_cartelas.items():
                        if not safe:
                            break
                        for entry in cartelas:
                            if self._has_winner(self._entry_patterns(entry), sim_set):
                                safe = False
                                break
                    if safe:
                        chosen = candidate
                        break

            number = chosen if chosen else available[0]

        else:
            # ── Phase 2: call winner's remaining numbers ──
            picked = None
            for n in (target_winner.get('pattern', []) if target_winner else []):
                if n not in called_set:
                    picked = n
                    break

            if picked is not None:
                number = picked
            else:
                random.shuffle(available)
                for candidate in available:
                    sim_set = called_set | {candidate}
                    safe = True
                    for uid_str, cartelas in player_cartelas.items():
                        if not safe:
                            break
                        for entry in cartelas:
                            if self._has_winner(self._entry_patterns(entry), sim_set):
                                safe = False
                                break
                    if safe:
                        number = candidate
                        break

        from settlement import commit_round_number
        result = commit_round_number(
            self.db,
            round_id,
            len(called),
            number,
            game_target=game_target,
            target_winner=target_winner,
        )
        return result.get('number')

    def get_cartela_patterns(self, flat_cartela: List[int]) -> List[List[int]]:
        """Return all winning patterns for a cartela, cached globally."""
        key = tuple(flat_cartela)
        cached = _PATTERN_CACHE.get(key)
        if cached is not None:
            return cached
        grid = [flat_cartela[i * 5:(i + 1) * 5] for i in range(5)]
        patterns = []
        patterns.extend([[n for n in row if n != 0] for row in grid])
        for col in range(5):
            patterns.append([grid[row][col] for row in range(5) if grid[row][col] != 0])
        patterns.append([grid[i][i] for i in range(5) if grid[i][i] != 0])
        patterns.append([grid[i][4 - i] for i in range(5) if grid[i][4 - i] != 0])
        patterns.append([flat_cartela[0], flat_cartela[4], flat_cartela[20], flat_cartela[24]])
        _PATTERN_CACHE[key] = patterns
        return patterns

    def check_bingo_for_cartela(self, flat_cartela: List[int],
                                 called_numbers: List[int]) -> bool:
        """Check bingo using cached patterns (no grid rebuild)."""
        called_set = set(called_numbers)
        for pattern in self.get_cartela_patterns(flat_cartela):
            if all(n in called_set for n in pattern):
                return True
        return False

    async def check_bingo(self, round_id: str, user_id: int) -> dict:
        """Check if a player has bingo in the current round."""
        round_doc = self.rounds_ref.document(round_id).get()
        if not round_doc.exists:
            return {'bingo': False, 'error': 'Round not found'}

        data = round_doc.to_dict()
        uid_str = str(user_id)
        player_info = data.get('players', {}).get(uid_str)
        if not player_info:
            return {'bingo': False, 'error': 'Player not in round'}

        called = data.get('called_numbers', [])
        winning_cartelas = []

        for cartela_num in player_info.get('cartelas', []):
            cartela_doc = self.master_ref.document(str(cartela_num)).get()
            if not cartela_doc.exists:
                continue
            flat = cartela_doc.to_dict().get('cartela', [])
            if self.check_bingo_for_cartela(flat, called):
                winning_cartelas.append(cartela_num)

        return {'bingo': len(winning_cartelas) > 0, 'winning_cartelas': winning_cartelas}

    def _winning_cartelas_for_player(self, players: Dict[str, dict], user_id: int,
                                      called_numbers: List[int]) -> List[int]:
        """Return this joined player's currently winning cartelas in stable order."""
        player_info = (players or {}).get(str(user_id))
        if not player_info:
            return []
        called_set = set(called_numbers or [])
        winning = []
        for cartela_num in player_info.get('cartelas', []) or []:
            cartela_doc = self.master_ref.document(str(cartela_num)).get()
            if not cartela_doc.exists:
                continue
            flat = cartela_doc.to_dict().get('cartela', [])
            if any(all(n in called_set for n in pattern)
                   for pattern in self.get_cartela_patterns(flat)):
                winning.append(int(cartela_num))
        return sorted(set(winning))

    def _complete_sync(self, round_id: str, user_id: int,
                       winning_cartela: Optional[int] = None,
                       completion_reason: str = 'bingo_claim',
                       expected_call_count: Optional[int] = None) -> dict:
        """Atomically choose one winner for a round; first valid completion wins."""
        claim_version = 'unknown' if expected_call_count is None else int(expected_call_count)
        operation_key = (
            f"round-winner:{round_id}:{user_id}:"
            f"{winning_cartela if winning_cartela is not None else 'any'}:{claim_version}"
        )

        def _apply(transaction):
            round_ref = self.rounds_ref.document(round_id)
            round_doc = transaction.get(round_ref)
            if not round_doc.exists:
                return {'ok': False, 'error': 'Round not found'}

            data = round_doc.to_dict()
            existing = [str(w) for w in (data.get('winners') or [])]
            if data.get('status') == 'completed':
                # Idempotent replay: expose the already authoritative winner so
                # competing clients never create a second winner.
                if len(existing) == 1:
                    return {
                        'ok': existing[0] == str(user_id),
                        'winner': existing[0] == str(user_id),
                        'winner_ids': [int(existing[0])],
                        'winning_cartela': data.get('winning_cartela'),
                        'already_completed': True,
                        'error': None if existing[0] == str(user_id) else 'Another player already won',
                    }
                if not existing:
                    return {
                        'ok': False,
                        'winner': False,
                        'winner_ids': [],
                        'already_completed': True,
                        'error': 'Round already completed without a winner',
                    }
                return {'ok': False, 'error': 'Round contains invalid multiple winners'}
            if data.get('status') != 'playing':
                return {'ok': False, 'error': 'Round is not playing'}

            players = data.get('players', {}) or {}
            uid_str = str(user_id)
            if uid_str not in players:
                return {'ok': False, 'error': 'Player not in round'}

            winning = self._winning_cartelas_for_player(
                players, user_id, data.get('called_numbers', [])
            )
            if winning_cartela is not None:
                try:
                    requested_cartela = int(winning_cartela)
                except (TypeError, ValueError):
                    return {'ok': False, 'error': 'Invalid cartela number'}
                if requested_cartela not in winning:
                    return {'ok': False, 'error': 'Cartela is not a valid winner'}
                canonical_cartela = requested_cartela
            elif winning:
                canonical_cartela = winning[0]
            else:
                return {'ok': False, 'error': 'Bingo is not valid yet'}

            now = datetime.now(tz=timezone.utc)
            player_name = players.get(uid_str, {}).get('name', 'Player')
            player_count = int(data.get('player_count', 0) or 0)
            stake = float(data.get('stake', DEFAULT_STAKE) or DEFAULT_STAKE)
            total_pool = player_count * stake
            transaction.update(round_ref, {
                'status': 'completed',
                'winners': [uid_str],
                'winner_name': player_name,
                'winning_cartela': canonical_cartela,
                'prize_per_winner': total_pool * 0.75,
                'admin_profit': total_pool * 0.25,
                'completion_reason': completion_reason,
                'completed_at': now,
            })
            return {
                'ok': True,
                'winner': True,
                'winner_ids': [int(user_id)],
                'winning_cartela': canonical_cartela,
                'already_completed': False,
            }

        return run_idempotent(
            operation_key,
            'round_winner_selection',
            _apply,
            lock_key=f'round:{round_id}',
        )

    async def complete_round(self, round_id: str, user_id: int,
                             winning_cartela: Optional[int] = None,
                             completion_reason: str = 'bingo_claim',
                             expected_call_count: Optional[int] = None) -> dict:
        """Atomically complete a round with exactly one validated winner."""
        if expected_call_count is None:
            snapshot = await asyncio.to_thread(self.rounds_ref.document(round_id).get)
            if snapshot.exists:
                expected_call_count = len(snapshot.to_dict().get('called_numbers', []) or [])
        return await asyncio.to_thread(
            self._complete_sync, round_id, user_id, winning_cartela,
            completion_reason, expected_call_count
        )

    async def claim_bingo(self, round_id: str, user_id: int,
                          winning_cartela: Optional[int] = None) -> dict:
        """Validate and claim Bingo; a losing claim never consumes the winner key."""
        round_doc = await asyncio.to_thread(self.rounds_ref.document(round_id).get)
        if not round_doc.exists:
            return {'ok': False, 'winner': False, 'error': 'Round not found'}
        data = round_doc.to_dict()
        if data.get('status') == 'completed':
            winners = [str(w) for w in (data.get('winners') or [])]
            return {
                'ok': bool(winners and winners[0] == str(user_id)),
                'winner': bool(winners and winners[0] == str(user_id)),
                'winner_ids': [int(winners[0])] if len(winners) == 1 else [],
                'winning_cartela': data.get('winning_cartela'),
                'error': None if winners and winners[0] == str(user_id) else 'Another player already won',
            }
        current_winners = self._winning_cartelas_for_player(
            data.get('players', {}) or {}, user_id, data.get('called_numbers', [])
        )
        if winning_cartela is not None:
            try:
                if int(winning_cartela) not in current_winners:
                    return {'ok': False, 'winner': False, 'error': 'Cartela is not a valid winner'}
            except (TypeError, ValueError):
                return {'ok': False, 'winner': False, 'error': 'Invalid cartela number'}
        elif not current_winners:
            return {'ok': False, 'winner': False, 'error': 'Bingo is not valid yet'}
        result = await self.complete_round(
            round_id, user_id, winning_cartela, 'bingo_claim', len(data.get('called_numbers', []) or [])
        )
        if not result.get('ok'):
            return result
        payout = await self.end_round(round_id, result.get('winner_ids', []))
        if isinstance(payout, dict) and payout.get('error'):
            return {'ok': False, 'winner': False, 'error': payout['error']}
        return {**result, 'payout_processed': True}

    async def end_round(self, round_id: str, winner_ids: List[int]) -> dict:
        """End the round and distribute one authoritative winner payout.

        Multiple distinct winner IDs are rejected. Winner selection must happen
        through ``complete_round`` so a manual or stale caller cannot bypass
        called-number validation.
        """
        if not winner_ids:
            return {'error': 'A validated winner is required; use refund_no_winner for no-winner rounds'}
        if len({str(w) for w in winner_ids}) != 1:
            return {'error': 'Exactly one winner is required'}
        if winner_ids:
            completion = await self.complete_round(
                round_id, int(winner_ids[0]), None, 'manual_or_engine_completion'
            )
            if not completion.get('ok'):
                return completion
            winner_ids = completion.get('winner_ids') or winner_ids[:1]
        if round_id not in self._round_locks:
            self._round_locks[round_id] = asyncio.Lock()
        async with self._round_locks[round_id]:
            return await asyncio.to_thread(self._end_sync, round_id, winner_ids)

    def _end_sync(self, round_id: str, winner_ids: List[int]) -> dict:
        """Apply one payout atomically and return the same result on retry.

        The caller holds the in-process round lock; ``run_idempotent`` below
        provides the cross-process lock and exactly-once database guard.
        """
        operation_key = f"round-payout:{round_id}"

        def _apply(transaction):
            round_ref = self.rounds_ref.document(round_id)
            round_doc = transaction.get(round_ref)
            if not round_doc.exists:
                return {'error': 'Round not found'}

            data = round_doc.to_dict()
            if data.get('payout_processed'):
                return {
                    'status': 'completed',
                    'winners': [int(w) for w in (data.get('winners') or [])],
                    'prize_per_winner': data.get('prize_per_winner', 0),
                    'admin_profit': data.get('admin_profit', 0),
                    'already_processed': True,
                }
            if data.get('status') not in ('playing', 'completed'):
                return {'error': 'Round not in a valid state for ending'}

            player_count = data.get('player_count', 0)
            round_stake = data.get('stake', DEFAULT_STAKE)
            total_pool = player_count * round_stake
            derash = total_pool * 0.75
            admin_profit = total_pool * 0.25

            # Only joined players may win, and duplicate IDs count once.
            players = data.get('players', {}) or {}
            valid_winner_ids = []
            seen_winners = set()
            for wid in winner_ids:
                wid_str = str(wid)
                if wid_str in players and wid_str not in seen_winners:
                    valid_winner_ids.append(int(wid))
                    seen_winners.add(wid_str)
            invalid_ids = [w for w in winner_ids if str(w) not in seen_winners]
            if invalid_ids:
                logger.warning(f"end_round {round_id}: ignoring non-member/duplicate winners {invalid_ids}")

            prize_per_winner = derash / len(valid_winner_ids) if valid_winner_ids else 0
            now = datetime.now(tz=timezone.utc)

            def _finish_user(user_ref, user_data, update):
                active_round = user_data.get('active_round_id')
                if active_round in (None, round_id):
                    update['is_playing'] = False
                    update['active_round_id'] = None
                update['updated_at'] = now
                transaction.update(user_ref, update)

            for wid in valid_winner_ids:
                user_ref = self.db.collection('users').document(str(wid))
                user_doc = transaction.get(user_ref)
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    _finish_user(user_ref, user_data, {
                        'play_wallet': user_data.get('play_wallet', 0) + prize_per_winner,
                        'total_games': int(user_data.get('total_games', 0) or 0) + 1,
                        'wins': user_data.get('wins', 0) + 1,
                    })

            for uid_str in data.get('players', {}):
                try:
                    uid_int = int(uid_str)
                except (TypeError, ValueError):
                    continue
                if uid_int not in valid_winner_ids:
                    user_ref = self.db.collection('users').document(uid_str)
                    user_doc = transaction.get(user_ref)
                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        _finish_user(user_ref, user_data, {
                            'total_games': int(user_data.get('total_games', 0) or 0) + 1,
                            'losses': user_data.get('losses', 0) + 1,
                        })

            winner_names = []
            for wid in valid_winner_ids:
                user_ref = self.db.collection('users').document(str(wid))
                user_doc = transaction.get(user_ref)
                winner_names.append(user_doc.to_dict().get('first_name', 'Unknown') if user_doc.exists else 'Unknown')

            result = {
                'status': 'completed',
                'winners': valid_winner_ids,
                'prize_per_winner': prize_per_winner,
                'admin_profit': admin_profit,
            }
            transaction.update(round_ref, {
                'status': 'completed',
                'winners': [str(w) for w in valid_winner_ids],
                'winner_name': winner_names[0] if len(winner_names) == 1 else ', '.join(winner_names),
                'prize_per_winner': prize_per_winner,
                'admin_profit': admin_profit,
                'payout_processed': True,
                'completed_at': now,
            })
            return result

        snapshot = self.rounds_ref.document(round_id).get()
        snapshot_players = snapshot.to_dict().get('players', {}) if snapshot.exists else {}
        lock_keys = [f"round:{round_id}"] + [
            f"user:{uid}" for uid in snapshot_players.keys()
        ]
        return run_idempotent(
            operation_key,
            'round_payout',
            _apply,
            lock_keys=lock_keys,
        )

    async def get_round(self, round_id: str) -> Optional[dict]:
        """Get round data by ID."""
        doc = self.rounds_ref.document(round_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    async def get_recent_rounds(self, limit: int = 20) -> List[dict]:
        """Get recent rounds."""
        docs = (self.rounds_ref
                .order_by('created_at', direction='DESCENDING')
                .limit(limit)
                .get())
        return [{'id': doc.id, **doc.to_dict()} for doc in docs]
