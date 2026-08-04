"""
Kelem Bingo — Round-Based Multiplayer Engine
=============================================
Manages 500 fixed cartelas, round lifecycle, number calling, bingo checking,
and prize distribution.
"""

import random
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from firestore_db import FieldFilter, transactional as firestore_transactional, Increment, ArrayUnion
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

class RoundEngine:
    def __init__(self, db):
        self.db = db
        self.master_ref = db.collection('cartelas_master')
        self.rounds_ref = db.collection('rounds')
        self._round_locks = {}

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
        """Find the current active round (selecting or playing) for a given stake."""
        for status in ['selecting', 'playing']:
            docs = list(self.rounds_ref
                       .where('status', '==', status)
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
        # Check for existing active round with same stake
        active = await self.get_active_round(stake=stake)
        if active:
            return active

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
        doc_ref.set(round_data)
        return {'id': doc_ref.id, **round_data}

    def join_round_sync(self, round_id: str, user_id: int, 
                        cartela_numbers: List[int], user_name: str) -> dict:
        """Synchronous implementation of player joining a round."""
        if len(cartela_numbers) > MAX_CARTELAS_PER_PLAYER:
            return {'error': f'Maximum {MAX_CARTELAS_PER_PLAYER} cartelas allowed'}
        if len(cartela_numbers) == 0:
            return {'error': 'Must select at least 1 cartela'}

        # Validate cartela numbers
        for num in cartela_numbers:
            if num < 1 or num > TOTAL_CARTELAS:
                return {'error': f'Invalid cartela number: {num}'}

        # Check for duplicates in selection
        if len(cartela_numbers) != len(set(cartela_numbers)):
            return {'error': 'Duplicate cartela numbers in selection'}

        round_doc = self.rounds_ref.document(round_id).get()
        if not round_doc.exists:
            return {'error': 'Round not found'}

        round_data = round_doc.to_dict()
        status = round_data.get('status')
        called = round_data.get('called_numbers', [])
        if status != 'selecting' and not (status == 'playing' and len(called) == 0):
            return {'error': 'Round is no longer accepting players'}

        # Check if cartelas are already taken
        taken = set(round_data.get('taken_cartelas', []))
        for num in cartela_numbers:
            if num in taken:
                return {'error': f'Cartela #{num} is already taken'}

        # Check if user already joined
        uid_str = str(user_id)
        if uid_str in round_data.get('players', {}):
            return {'error': 'You already joined this round'}

        # Deduct play wallet
        round_stake = round_data.get('stake', DEFAULT_STAKE)
        total_cost = round_stake * len(cartela_numbers)
        user_ref = self.db.collection('users').document(uid_str)
        user_doc = user_ref.get()
        if not user_doc.exists:
            user_data = {
                'user_id': user_id,
                'first_name': user_name or 'Player',
                'username': '',
                'balance': 0,
                'play_wallet': 0.0,
                'bonus': 0,
                'phone': '',
                'registered': False,
                'total_games': 0,
                'wins': 0,
                'losses': 0,
                'is_playing': False,
                'created_at': datetime.now(tz=timezone.utc),
                'updated_at': datetime.now(tz=timezone.utc),
            }
            user_ref.set(user_data)
        else:
            user_data = user_doc.to_dict()

        pw = float(user_data.get('play_wallet', 0))
        if pw < total_cost:
            return {'error': f'Not enough balance. Need {total_cost} ETB, have {pw} ETB'}

        # Deduct and update
        user_ref.update({
            'play_wallet': pw - total_cost,
            'is_playing': True,
            'updated_at': datetime.now(tz=timezone.utc),
        })

        # Second validation check right before update (reduce race condition window)
        round_doc_final = self.rounds_ref.document(round_id).get()
        if round_doc_final.exists:
            round_data_final = round_doc_final.to_dict()
            status_final = round_data_final.get('status')
            called_final = round_data_final.get('called_numbers', [])
            if status_final != 'selecting' and not (status_final == 'playing' and len(called_final) == 0):
                # Rollback: refund the user
                user_ref.update({
                    'play_wallet': pw,
                    'is_playing': False,
                    'updated_at': datetime.now(tz=timezone.utc),
                })
                return {'error': 'Round is no longer accepting players'}

            taken_final = set(round_data_final.get('taken_cartelas', []))
            for num in cartela_numbers:
                if num in taken_final:
                    # Rollback: refund the user
                    user_ref.update({
                        'play_wallet': pw,
                        'is_playing': False,
                        'updated_at': datetime.now(tz=timezone.utc),
                    })
                    return {'error': f'Cartela #{num} was just taken by another player. Please select different cards.'}

        new_pc = round_data.get('player_count', 0) + len(cartela_numbers)
        total_pool = new_pc * round_stake
        derash = total_pool * 0.75

        self.rounds_ref.document(round_id).update({
            f'players.{uid_str}': {
                'cartelas': cartela_numbers,
                'name': user_name,
                'joined_at': datetime.now(tz=timezone.utc).isoformat(),
            },
            'player_count': Increment(len(cartela_numbers)),
            'taken_cartelas': ArrayUnion(cartela_numbers),
            'derash': derash,
        })

        return {
            'status': 'joined',
            'cost': total_cost,
            'cartelas': cartela_numbers,
            'player_count': new_pc,
        }

    async def join_round(self, round_id: str, user_id: int, 
                         cartela_numbers: List[int], user_name: str) -> dict:
        """Player joins a round with chosen cartelas (max 2).
        Serialized per round via asyncio.Lock to prevent DB lock contention and RAM spikes under high concurrency.
        """
        if round_id not in self._round_locks:
            self._round_locks[round_id] = asyncio.Lock()

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
        Phase 1 (calls 1-15): random safe numbers, avoid any winner.
        Phase 2 (calls 16+): target a winner and complete their pattern."""
        round_doc = await self._db(lambda: self.rounds_ref.document(round_id).get())
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

        if data.get('game_target') != game_target:
            await self._db(lambda: self.rounds_ref.document(round_id).update({'game_target': game_target}))

        number = available[0]

        # Ensure predetermined winner exists (pick at round start, persist in DB)
        target_winner = data.get('target_winner')
        if not target_winner:
            target_winner = self._select_predetermined_winner(player_cartelas)
            if target_winner:
                await self._db(lambda: self.rounds_ref.document(round_id).update({
                    'target_winner': target_winner,
                }))

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

        called.append(number)
        now = datetime.now(tz=timezone.utc)
        await self._db(lambda: self.rounds_ref.document(round_id).update({
            'called_numbers': called,
            'last_called_number': number,
            'last_called_at': now,
            'next_number_at': now + timedelta(seconds=NUMBER_CALL_INTERVAL),
        }))
        return number

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

    async def end_round(self, round_id: str, winner_ids: List[int]) -> dict:
        """End the round, distribute prizes.

        Payout-guarded: each round can be paid out exactly once. The guard
        relies on the round's `payout_processed` flag plus an in-process lock,
        which is sufficient because all payout paths (game loop + admin
        endpoint) run inside the same gateway process.
        """
        if round_id not in self._round_locks:
            self._round_locks[round_id] = asyncio.Lock()

        async with self._round_locks[round_id]:
            return await asyncio.to_thread(self._end_sync, round_id, winner_ids)

    def _end_sync(self, round_id: str, winner_ids: List[int]) -> dict:
        round_doc = self.rounds_ref.document(round_id).get()
        if not round_doc.exists:
            return {'error': 'Round not found'}

        data = round_doc.to_dict()
        if data.get('payout_processed'):
            return {'error': 'Round already paid out'}

        if data['status'] not in ('playing', 'completed'):
            return {'error': 'Round not in a valid state for ending'}

        player_count = data.get('player_count', 0)
        round_stake = data.get('stake', DEFAULT_STAKE)
        total_pool = player_count * round_stake
        derash = total_pool * 0.75
        admin_profit = total_pool * 0.25

        # Only players who actually joined this round may be declared winners.
        players = data.get('players', {}) or {}
        valid_winner_ids = []
        for wid in winner_ids:
            if str(wid) in players:
                valid_winner_ids.append(wid)
        invalid_ids = [w for w in winner_ids if w not in valid_winner_ids]
        if invalid_ids:
            logger.warning(f"end_round {round_id}: ignoring non-member winners {invalid_ids}")
        winner_ids = valid_winner_ids

        prize_per_winner = 0
        if winner_ids:
            prize_per_winner = derash / len(winner_ids)
            for wid in winner_ids:
                user_ref = self.db.collection('users').document(str(wid))
                user_doc = user_ref.get()
                if user_doc.exists:
                    ud = user_doc.to_dict()
                    user_ref.update({
                        'play_wallet': ud.get('play_wallet', 0) + prize_per_winner,
                        'wins': ud.get('wins', 0) + 1,
                        'is_playing': False,
                        'updated_at': datetime.now(tz=timezone.utc),
                    })

        for uid_str in data.get('players', {}):
            try:
                uid_int = int(uid_str)
            except ValueError:
                continue
            if uid_int not in winner_ids:
                user_ref = self.db.collection('users').document(uid_str)
                user_doc = user_ref.get()
                if user_doc.exists:
                    ud = user_doc.to_dict()
                    user_ref.update({
                        'losses': ud.get('losses', 0) + 1,
                        'is_playing': False,
                        'updated_at': datetime.now(tz=timezone.utc),
                    })

        winner_names = []
        for wid in winner_ids:
            user_ref = self.db.collection('users').document(str(wid))
            user_doc = user_ref.get()
            if user_doc.exists:
                winner_names.append(user_doc.to_dict().get('first_name', 'Unknown'))
            else:
                winner_names.append('Unknown')

        self.rounds_ref.document(round_id).update({
            'status': 'completed',
            'winners': [str(w) for w in winner_ids],
            'winner_name': winner_names[0] if len(winner_names) == 1 else ', '.join(winner_names),
            'prize_per_winner': prize_per_winner,
            'admin_profit': admin_profit,
            'payout_processed': True,
            'completed_at': datetime.now(tz=timezone.utc),
        })

        return {
            'status': 'completed',
            'winners': winner_ids,
            'prize_per_winner': prize_per_winner,
            'admin_profit': admin_profit,
        }

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
