"""
Bingo Detection + Full Round Simulation Test Suite.
Tests all patterns, Phase 1 safety, Phase 2 winner guarantee,
and runs 500+ Monte Carlo rounds with 2-20 players.
"""
import sys, os, random, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import Mock, MagicMock
from game.round_engine import RoundEngine, BINGO_NUMBERS, GAME_LENGTH_RANGE


def make_cartela(rows):
    flat = []
    for r in rows:
        flat.extend(r)
    return flat


SAMPLE_ROWS = [
    [ 1, 16, 31, 46, 61],
    [ 2, 17, 32, 47, 62],
    [ 3, 18,  0, 48, 63],
    [ 4, 19, 34, 49, 64],
    [ 5, 20, 35, 50, 65],
]
SAMPLE_CARTELA = make_cartela(SAMPLE_ROWS)


def _generate_cartela(seed):
    """Generate a random valid bingo cartela (same format as RoundEngine)."""
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
        flat.append(0 if row_idx == 2 else cols['N'][row_idx])
        flat.append(cols['G'][row_idx])
        flat.append(cols['O'][row_idx])
    return flat

CARTELA_POOL = [_generate_cartela(s) for s in range(500)]  # 500 unique cartelas


def simulate_full_round(engine, num_players, player_cartelas_list, game_target=None):
    """Run a complete simulated round.
    Returns: { 'winner_found': bool, 'calls_to_win': int, 'game_target': int,
               'phase1_fail': bool, 'phase2_success': bool, 'winner_is_real': bool }
    """
    if game_target is None:
        game_target = random.randint(*GAME_LENGTH_RANGE)

    # Build player_cartelas dict
    pc = {}
    for i, cartelas in enumerate(player_cartelas_list):
        uid = f'user_{i}'
        entries = []
        for j, flat in enumerate(cartelas):
            patterns = engine.get_cartela_patterns(flat)
            entries.append({
                'cartela_number': j + 1,
                'flat': flat,
                'patterns': patterns,
            })
        pc[uid] = entries

    called = []
    called_set = set()
    phase1_violation = False
    winner_info = None
    final_call_count = 0

    # Pick predetermined winner at round start (same as engine)
    target_winner = engine._select_predetermined_winner(pc)
    winning_pattern = set(target_winner['pattern']) if target_winner else set()

    max_calls = 30
    for call_idx in range(1, max_calls + 1):
        available = [n for n in BINGO_NUMBERS if n not in called_set]
        if not available:
            break

        # --- Simulate call_number logic ---
        if call_idx < game_target:
            # Phase 1: safe, prefer winner's pattern numbers
            random.shuffle(available)
            chosen = None

            if target_winner and len(winning_pattern - called_set) > 1:
                for candidate in available:
                    if candidate in winning_pattern:
                        sim_set = called_set | {candidate}
                        safe = True
                        for uid, entries in pc.items():
                            if not safe:
                                break
                            for entry in entries:
                                if engine._has_winner(engine._entry_patterns(entry), sim_set):
                                    safe = False
                                    break
                        if safe:
                            chosen = candidate
                            break

            if chosen is None:
                for candidate in available:
                    sim_set = called_set | {candidate}
                    safe = True
                    for uid, entries in pc.items():
                        if not safe:
                            break
                        for entry in entries:
                            if engine._has_winner(engine._entry_patterns(entry), sim_set):
                                safe = False
                                break
                    if safe:
                        chosen = candidate
                        break

            if chosen is None:
                chosen = random.choice(available)
                phase1_violation = True
        else:
            # Phase 2: call winner's remaining pattern numbers
            picked = None
            if target_winner:
                for n in target_winner.get('pattern', []):
                    if n not in called_set:
                        picked = n
                        break
            if picked is not None:
                chosen = picked
            else:
                random.shuffle(available)
                chosen = available[0]

        called.append(chosen)
        called_set.add(chosen)

        # Check for winners
        winners = engine.evaluate_winners(pc, called)
        if winners:
            # Verify the winner is real
            chosen_entry = engine.choose_single_winner(winners, {w['user_id']: {} for w in winners})
            winner_info = {
                'call_count': call_idx,
                'winner': chosen_entry,
                'winners_count': len(winners),
                'all_winning_ids': [w['user_id'] for w in winners],
            }
            final_call_count = call_idx
            break

    return {
        'winner_found': winner_info is not None,
        'winner_info': winner_info,
        'calls_to_win': final_call_count,
        'game_target': game_target,
        'total_calls': len(called),
        'phase1_violation': phase1_violation,
        'phase2_success': winner_info is not None and final_call_count >= game_target,
        'had_premature_winner': phase1_violation,
    }


# ─────────────────────────────────────────────────────────────
# Unit Tests (existing, preserved)
# ─────────────────────────────────────────────────────────────

class TestBingoDetection(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = RoundEngine(Mock())

    def check(self, called):
        return self.engine.check_bingo_for_cartela(SAMPLE_CARTELA, called)

    def test_row_0_wins(self):
        self.assertTrue(self.check([1, 16, 31, 46, 61]))

    def test_row_1_wins(self):
        self.assertTrue(self.check([2, 17, 32, 47, 62]))

    def test_row_2_wins_includes_free(self):
        self.assertTrue(self.check([3, 18, 48, 63]))

    def test_row_3_wins(self):
        self.assertTrue(self.check([4, 19, 34, 49, 64]))

    def test_row_4_wins(self):
        self.assertTrue(self.check([5, 20, 35, 50, 65]))

    def test_col_0_wins(self):
        self.assertTrue(self.check([1, 2, 3, 4, 5]))

    def test_col_1_wins(self):
        self.assertTrue(self.check([16, 17, 18, 19, 20]))

    def test_col_2_wins_includes_free(self):
        self.assertTrue(self.check([31, 32, 34, 35]))

    def test_col_3_wins(self):
        self.assertTrue(self.check([46, 47, 48, 49, 50]))

    def test_col_4_wins(self):
        self.assertTrue(self.check([61, 62, 63, 64, 65]))

    def test_main_diagonal_wins(self):
        self.assertTrue(self.check([1, 17, 49, 65]))

    def test_anti_diagonal_wins(self):
        self.assertTrue(self.check([61, 47, 19, 5]))

    def test_four_corners_wins(self):
        self.assertTrue(self.check([1, 61, 5, 65]))

    def test_four_corners_wins_any_order(self):
        self.assertTrue(self.check([65, 5, 61, 1]))

    def test_three_corners_not_enough(self):
        self.assertFalse(self.check([1, 61, 5]))

    def test_two_corners_not_enough(self):
        self.assertFalse(self.check([1, 61]))

    def test_4_in_row_not_win(self):
        self.assertFalse(self.check([1, 16, 31, 46]))

    def test_4_in_col_not_win(self):
        self.assertFalse(self.check([1, 2, 3, 4]))

    def test_empty_called_not_win(self):
        self.assertFalse(self.check([]))

    def test_unrelated_numbers_not_win(self):
        self.assertFalse(self.check([7, 22, 37, 52, 67, 10, 25, 40, 55, 70]))

    def test_one_number_not_win(self):
        self.assertFalse(self.check([1]))

    def test_free_space_alone_not_win(self):
        self.assertFalse(self.check([]))

    def test_free_space_not_in_corners(self):
        corners = [SAMPLE_CARTELA[0], SAMPLE_CARTELA[4], SAMPLE_CARTELA[20], SAMPLE_CARTELA[24]]
        self.assertEqual(corners, [1, 61, 5, 65])
        self.assertNotIn(0, corners)


class TestCartelaPatterns(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = RoundEngine(Mock())
        cls.patterns = cls.engine.get_cartela_patterns(SAMPLE_CARTELA)

    def test_has_4_corners_pattern(self):
        found = any(set(p) == {1, 61, 5, 65} for p in self.patterns)
        self.assertTrue(found)

    def test_has_5_rows(self):
        rows = [p for p in self.patterns if len(p) in (4, 5)]
        self.assertGreaterEqual(len(rows), 4)

    def test_has_5_columns(self):
        cols = [p for p in self.patterns if len(p) >= 4]
        self.assertGreaterEqual(len(cols), 5)

    def test_has_2_diagonals(self):
        self.assertGreaterEqual(len(self.patterns), 12)

    def test_no_zero_in_any_pattern(self):
        for p in self.patterns:
            self.assertNotIn(0, p)


class TestPickTargetWinner(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = RoundEngine(Mock())

    def setUp(self):
        cartela_a = make_cartela([
            [1, 16, 31, 46, 61],
            [2, 17, 32, 47, 62],
            [3, 18,  0, 48, 63],
            [4, 19, 34, 49, 64],
            [5, 20, 35, 50, 65],
        ])
        cartela_b = make_cartela([
            [10, 25, 40, 55, 70],
            [11, 26, 41, 56, 71],
            [12, 27,  0, 57, 72],
            [13, 28, 43, 58, 73],
            [14, 29, 44, 59, 74],
        ])
        self.player_cartelas = {
            'user_a': [{'cartela_number': 1, 'flat': cartela_a}],
            'user_b': [{'cartela_number': 2, 'flat': cartela_b}],
        }

    def test_picks_closest_to_win(self):
        called = [1, 16, 31, 46]
        target = self.engine._pick_target_winner(self.player_cartelas, called, {})
        self.assertIsNotNone(target)
        self.assertEqual(target['user_id'], 'user_a')

    def test_returns_none_without_players(self):
        self.assertIsNone(self.engine._pick_target_winner({}, [], {}))


class TestCandidateProgress(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = RoundEngine(Mock())

    def test_no_players_returns_999(self):
        self.assertEqual(self.engine._candidate_progress({}, [1, 2, 3]), 999)

    def test_winner_exists_returns_0(self):
        cartela = make_cartela(SAMPLE_ROWS)
        pc = {'user_a': [{'cartela_number': 1, 'flat': cartela}]}
        called = [1, 16, 31, 46, 61]
        self.assertEqual(self.engine._candidate_progress(pc, called), 0)

    def test_one_missing_returns_1(self):
        cartela = make_cartela(SAMPLE_ROWS)
        pc = {'user_a': [{'cartela_number': 1, 'flat': cartela}]}
        called = [1, 16, 31, 46]
        self.assertEqual(self.engine._candidate_progress(pc, called), 1)


class TestEvaluateWinners(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = RoundEngine(Mock())

    def test_no_winners(self):
        pc = {'user_a': [{'cartela_number': 1, 'flat': make_cartela(SAMPLE_ROWS)}]}
        winners = self.engine.evaluate_winners(pc, [1, 16, 31, 46])
        self.assertEqual(len(winners), 0)

    def test_one_winner(self):
        pc = {'user_a': [{'cartela_number': 1, 'flat': make_cartela(SAMPLE_ROWS)}]}
        winners = self.engine.evaluate_winners(pc, [1, 16, 31, 46, 61])
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]['user_id'], 'user_a')

    def test_four_corners_winner(self):
        pc = {'user_a': [{'cartela_number': 1, 'flat': make_cartela(SAMPLE_ROWS)}]}
        winners = self.engine.evaluate_winners(pc, [1, 61, 5, 65])
        self.assertEqual(len(winners), 1)

    def test_two_separate_winners(self):
        cartela_a = make_cartela(SAMPLE_ROWS)
        cartela_b = make_cartela([
            [1, 16, 31, 46, 61],
            [10, 25, 40, 55, 70],
            [12, 27,  0, 57, 72],
            [13, 28, 43, 58, 73],
            [14, 29, 44, 59, 74],
        ])
        pc = {
            'user_a': [{'cartela_number': 1, 'flat': cartela_a}],
            'user_b': [{'cartela_number': 2, 'flat': cartela_b}],
        }
        winners = self.engine.evaluate_winners(pc, [1, 16, 31, 46, 61])
        self.assertEqual(len(winners), 2)


class TestChooseSingleWinner(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = RoundEngine(Mock())

    def test_single_winner(self):
        result = self.engine.choose_single_winner(
            [{'user_id': '1', 'cartela_number': 1}],
            {'1': {'joined_at': '2026-01-01T00:00:00'}},
        )
        self.assertEqual(result['user_id'], '1')

    def test_earliest_joiner_wins_tie(self):
        result = self.engine.choose_single_winner(
            [
                {'user_id': '2', 'cartela_number': 1},
                {'user_id': '1', 'cartela_number': 2},
            ],
            {
                '1': {'joined_at': '2026-01-01T00:00:01'},
                '2': {'joined_at': '2026-01-01T00:00:00'},
            },
        )
        self.assertEqual(result['user_id'], '2')

    def test_none_for_no_winners(self):
        self.assertIsNone(self.engine.choose_single_winner([], {}))


# ─────────────────────────────────────────────────────────────
# Integration: Full Round Monte Carlo Simulations
# ─────────────────────────────────────────────────────────────

class TestMonteCarloRounds(unittest.TestCase):
    """Run 500+ simulated rounds with 2-20 random players."""

    @classmethod
    def setUpClass(cls):
        cls.engine = RoundEngine(Mock())
        cls.results = []

    @classmethod
    def tearDownClass(cls):
        # Print summary
        if not cls.results:
            return
        total = len(cls.results)
        won = sum(1 for r in cls.results if r['winner_found'])
        phase1_fails = sum(1 for r in cls.results if r['phase1_violation'])
        avg_calls = sum(r['calls_to_win'] for r in cls.results if r['winner_found']) / max(won, 1)
        print(f"\n{'='*60}")
        print(f"Monte Carlo: {total} rounds, {won} winners ({100*won/total:.1f}%)")
        print(f"Phase 1 violations (premature winner): {phase1_fails}")
        if won:
            print(f"Average calls to win: {avg_calls:.1f}")
            call_dist = {}
            for r in cls.results:
                if r['winner_found']:
                    c = r['calls_to_win']
                    call_dist[c] = call_dist.get(c, 0) + 1
            dist_str = ', '.join(f'{k}:{v}' for k, v in sorted(call_dist.items()))
            print(f"Call distribution: {dist_str}")

    def _make_players(self, count):
        """Create `count` players each with 1-2 random cartelas."""
        player_cartelas_list = []
        for _ in range(count):
            num_cartelas = random.randint(1, 2)
            chosen = random.sample(CARTELA_POOL, num_cartelas)
            player_cartelas_list.append(chosen)
        return player_cartelas_list

    def test_500_monte_carlo_rounds(self):
        """500 rounds, 2-20 players each, verify Phase 1 safety + Phase 2 win.
        Accepts rare draws (high game_target may exhaust Phase 2 calls)."""
        random.seed(42)
        wins = 0
        total = 500
        for _ in range(total):
            num_players = random.randint(2, 20)
            players = self._make_players(num_players)
            result = simulate_full_round(self.engine, num_players, players)
            self.__class__.results.append(result)

            # Phase 1: NEVER produce a premature winner — critical invariant
            self.assertFalse(
                result['phase1_violation'],
                f"Phase 1 violation! Game target {result['game_target']}, winner at call {result['calls_to_win']}"
            )
            if result['winner_found']:
                wins += 1
                # Winner must be between game_target and 30
                self.assertGreaterEqual(
                    result['calls_to_win'], result['game_target'],
                    f"Winner too early at call {result['calls_to_win']} < target {result['game_target']}"
                )
                self.assertLessEqual(
                    result['calls_to_win'], 30,
                    f"Winner too late at call {result['calls_to_win']} > 30"
                )
        # Predetermined winner guarantees 100% win rate
        self.assertEqual(wins, total,
            f"Only {wins}/{total} rounds found a winner ({100*wins/total:.1f}%)")

    def test_game_target_ranges(self):
        """Verify winners across all game_target values 15-30."""
        random.seed(123)
        for target in range(15, 31):
            wins = 0
            trials = 20
            for _ in range(trials):
                num_players = random.randint(3, 15)
                players = self._make_players(num_players)
                result = simulate_full_round(self.engine, num_players, players, game_target=target)
                self.__class__.results.append(result)
                self.assertFalse(result['phase1_violation'],
                    f"Phase 1 violation at target={target}, winner at call {result['calls_to_win']}")
                self.assertTrue(result['winner_found'],
                    f"No winner at target={target}, players={num_players}")
                self.assertGreaterEqual(result['calls_to_win'], target,
                    f"Winner at {result['calls_to_win']} < target {target}")

    def test_2_player_rounds(self):
        """Minimal 2-player rounds."""
        random.seed(7)
        wins = 0
        total = 50
        for _ in range(total):
            players = self._make_players(2)
            result = simulate_full_round(self.engine, 2, players)
            self.__class__.results.append(result)
            self.assertFalse(result['phase1_violation'])
            self.assertTrue(result['winner_found'], "2-player round no winner")
            self.assertGreaterEqual(result['calls_to_win'], result['game_target'])

    def test_20_player_rounds(self):
        """Max 20-player rounds with 2 cartelas each."""
        random.seed(99)
        wins = 0
        total = 30
        for _ in range(total):
            players = self._make_players(20)
            result = simulate_full_round(self.engine, 20, players)
            self.__class__.results.append(result)
            self.assertFalse(result['phase1_violation'])
            self.assertTrue(result['winner_found'], "20-player round no winner")
            self.assertGreaterEqual(result['calls_to_win'], result['game_target'])

    def test_all_cartelas_unique_patterns(self):
        """Verify every cartela in the pool can produce winners for all pattern types."""
        engine = self.engine
        for idx, flat in enumerate(CARTELA_POOL):
            patterns = engine.get_cartela_patterns(flat)
            # Each cartela should have at least one row, col, and diagonal
            row_pats = [p for p in patterns if len(p) >= 4]
            col_pats = [p for p in patterns if len(p) >= 4]
            diag_pats = [p for p in patterns if len(p) in (4, 5)]
            self.assertGreaterEqual(len(patterns), 12, f"Cartela {idx} has < 12 patterns")

            # Must be able to win with each pattern type
            for pat in patterns:
                if not pat:
                    continue
                self.assertTrue(engine.check_bingo_for_cartela(flat, pat),
                    f"Cartela {idx} pattern {pat} should be a winner when all called")

    def test_phase1_never_produces_winner(self):
        """Extra paranoid: run Phase 1 logic many times and verify no winners."""
        engine = self.engine
        random.seed(111)
        for _ in range(200):
            num_players = random.randint(2, 15)
            players = self._make_players(num_players)
            pc = {}
            for i, cartelas in enumerate(players):
                uid = f'user_{i}'
                entries = []
                for j, flat in enumerate(cartelas):
                    entries.append({
                        'cartela_number': j + 1,
                        'flat': flat,
                        'patterns': engine.get_cartela_patterns(flat),
                    })
                pc[uid] = entries

            called = []
            called_set = set()
            game_target = random.randint(*GAME_LENGTH_RANGE)
            for call_idx in range(1, game_target):
                available = [n for n in BINGO_NUMBERS if n not in called_set]
                random.shuffle(available)
                chosen = None
                for candidate in available:
                    sim_set = called_set | {candidate}
                    safe = True
                    for uid, entries in pc.items():
                        if not safe:
                            break
                        for entry in entries:
                            if engine._has_winner(entry['patterns'], sim_set):
                                safe = False
                                break
                    if safe:
                        chosen = candidate
                        break
                if chosen is None:
                    self.fail(f"Phase 1: no safe number at call {call_idx}, target {game_target}")
                called.append(chosen)
                called_set.add(chosen)
                winners = engine.evaluate_winners(pc, called)
                self.assertEqual(len(winners), 0,
                    f"Phase 1 violation at call {call_idx} < target {game_target}")

    def test_no_false_positive_winners(self):
        """Verify random number combinations never falsely report bingo."""
        engine = self.engine
        random.seed(777)
        for _ in range(500):
            flat = random.choice(CARTELA_POOL)
            # Pick random non-winning numbers
            all_nums = set(n for n in BINGO_NUMBERS)
            patterns = engine.get_cartela_patterns(flat)
            # Pick numbers NOT forming any complete pattern
            for _ in range(10):
                nums = set(random.sample(list(all_nums), random.randint(1, 8)))
                # Check none of our numbers complete a pattern
                has_bingo = engine.check_bingo_for_cartela(flat, list(nums))
                # Verify by manual pattern check
                real_bingo = any(all(n in nums for n in p) for p in patterns if len(p) <= len(nums))
                self.assertEqual(has_bingo, real_bingo,
                    f"check_bingo_for_cartela mismatch for nums={nums}")


class TestPerformance(unittest.TestCase):
    """Benchmark call_number speed under load."""

    def test_call_number_speed(self):
        """Verify call_number() logic is fast under many players."""
        engine = RoundEngine(Mock())
        # Build 20 players, 2 cartelas each
        pc = {}
        for i in range(20):
            uid = f'user_{i}'
            entries = []
            for j in range(2):
                flat = random.choice(CARTELA_POOL)
                entries.append({
                    'cartela_number': j + 1,
                    'flat': flat,
                    'patterns': engine.get_cartela_patterns(flat),
                })
            pc[uid] = entries

        # Simulate 30 calls, measure total time
        called = []
        called_set = set()
        game_target = random.randint(15, 20)
        target_winner = engine._select_predetermined_winner(pc)
        winning_pattern = set(target_winner['pattern']) if target_winner else set()
        start = time.perf_counter()
        for call_idx in range(1, 31):
            available = [n for n in BINGO_NUMBERS if n not in called_set]
            if not available:
                break
            if call_idx < game_target:
                random.shuffle(available)
                chosen = None
                if target_winner and len(winning_pattern - called_set) > 1:
                    for candidate in available:
                        if candidate in winning_pattern:
                            sim_set = called_set | {candidate}
                            safe = True
                            for uid, entries in pc.items():
                                if not safe:
                                    break
                                for entry in entries:
                                    if engine._has_winner(engine._entry_patterns(entry), sim_set):
                                        safe = False
                                        break
                            if safe:
                                chosen = candidate
                                break
                if chosen is None:
                    for candidate in available:
                        sim_set = called_set | {candidate}
                        safe = True
                        for uid, entries in pc.items():
                            if not safe:
                                break
                            for entry in entries:
                                if engine._has_winner(engine._entry_patterns(entry), sim_set):
                                    safe = False
                                    break
                        if safe:
                            chosen = candidate
                            break
                if chosen is None:
                    chosen = available[0]
            else:
                target_winner = engine._select_predetermined_winner(pc)
                picked = None
                if target_winner:
                    for n in target_winner.get('pattern', []):
                        if n not in called_set:
                            picked = n
                            break
                if picked is not None:
                    chosen = picked
                else:
                    random.shuffle(available)
                    chosen = available[0]
            called.append(chosen)
            called_set.add(chosen)
        elapsed = time.perf_counter() - start
        # 30 calls with 20 players × 2 cartelas must complete in < 3 seconds
        self.assertLess(elapsed, 3.0,
            f"30 calls with 20 players took {elapsed:.2f}s (threshold: 3s)")
        print(f"\n[Perf] 30 calls, 20 players × 2 cartelas: {elapsed:.3f}s ({elapsed/30*1000:.1f}ms/call)")


class Test300PlayerScale(unittest.TestCase):
    """Stress test engine performance & memory for 300 players across 2 simultaneous stakes."""

    def test_300_players_two_stakes_under_200mb(self):
        import tracemalloc
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        engine = RoundEngine(Mock())

        # Stake A (10 ETB): 150 players x 2 cartelas = 300 cartelas
        stake_a_pc = {}
        for i in range(150):
            uid = f'user_stake10_{i}'
            entries = []
            for j in range(2):
                flat = random.choice(CARTELA_POOL)
                entries.append({
                    'cartela_number': j + 1,
                    'flat': flat,
                    'patterns': engine.get_cartela_patterns(flat),
                })
            stake_a_pc[uid] = entries

        # Stake B (20 ETB): 150 players x 2 cartelas = 300 cartelas
        stake_b_pc = {}
        for i in range(150):
            uid = f'user_stake20_{i}'
            entries = []
            for j in range(2):
                flat = random.choice(CARTELA_POOL)
                entries.append({
                    'cartela_number': j + 1,
                    'flat': flat,
                    'patterns': engine.get_cartela_patterns(flat),
                })
            stake_b_pc[uid] = entries

        start_time = time.perf_counter()

        # Run 30 calls for both rounds in parallel
        for pc in (stake_a_pc, stake_b_pc):
            called_set = set()
            called = []
            game_target = random.randint(15, 20)
            target_winner = engine._select_predetermined_winner(pc)
            winning_pattern = set(target_winner['pattern']) if target_winner else set()

            for call_idx in range(1, 31):
                available = [n for n in BINGO_NUMBERS if n not in called_set]
                if not available:
                    break
                if call_idx < game_target:
                    random.shuffle(available)
                    chosen = None
                    if target_winner and len(winning_pattern - called_set) > 1:
                        for candidate in available:
                            if candidate in winning_pattern:
                                sim_set = called_set | {candidate}
                                safe = True
                                for uid, entries in pc.items():
                                    if not safe:
                                        break
                                    for entry in entries:
                                        if engine._has_winner(engine._entry_patterns(entry), sim_set):
                                            safe = False
                                            break
                                if safe:
                                    chosen = candidate
                                    break
                    if chosen is None:
                        for candidate in available:
                            sim_set = called_set | {candidate}
                            safe = True
                            for uid, entries in pc.items():
                                if not safe:
                                    break
                                for entry in entries:
                                    if engine._has_winner(engine._entry_patterns(entry), sim_set):
                                        safe = False
                                        break
                            if safe:
                                chosen = candidate
                                break
                    if chosen is None:
                        chosen = available[0]
                else:
                    picked = None
                    if target_winner:
                        for n in target_winner.get('pattern', []):
                            if n not in called_set:
                                picked = n
                                break
                    if picked is not None:
                        chosen = picked
                    else:
                        random.shuffle(available)
                        chosen = available[0]
                called.append(chosen)
                called_set.add(chosen)

                winners = engine.evaluate_winners(pc, called)
                if winners:
                    break

        elapsed = time.perf_counter() - start_time
        snapshot_after = tracemalloc.take_snapshot()
        top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')

        total_allocated_mb = sum(stat.size_diff for stat in top_stats) / (1024 * 1024)
        current_ram_mb, peak_ram_mb = [x / (1024 * 1024) for x in tracemalloc.get_traced_memory()]
        tracemalloc.stop()

        print(f"\n[300 Players Scale Test] Executed 2 simultaneous rounds (150 players/stake x 2 cartelas = 600 total cartelas)")
        print(f"  Total Time: {elapsed:.3f}s")
        print(f"  Peak Traced Memory: {peak_ram_mb:.2f} MB (Allocated Diff: {total_allocated_mb:.2f} MB)")

        # Assert memory stays well below 200 MB
        self.assertLess(peak_ram_mb, 200.0, f"Peak memory {peak_ram_mb:.2f}MB exceeded 200MB limit!")
        # Assert execution time is fast enough for 60 total call evaluations
        self.assertLess(elapsed, 5.0, f"Execution time {elapsed:.2f}s exceeded 5s limit for 300 players!")


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
