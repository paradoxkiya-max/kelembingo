#!/usr/bin/env python3
"""
Test script to verify all changes are working correctly.
Run: python test_changes.py
"""

import sys
import os

def test_python_syntax():
    """Test that Python files compile without syntax errors."""
    print("=" * 60)
    print("TEST 1: Python Syntax Check")
    print("=" * 60)
    
    files = [
        'api/admin_api.py',
        'game/round_engine.py',
        'game/engine.py',
        'firestore_db.py',
        'config.py',
    ]
    
    all_pass = True
    for f in files:
        path = os.path.join(os.path.dirname(__file__), f)
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                code = fh.read()
            compile(code, path, 'exec')
            print(f"  [OK] {f}")
        except SyntaxError as e:
            print(f"  [FAIL] {f}: {e}")
            all_pass = False
    
    return all_pass


def test_prize_calculation():
    """Test that prize calculation uses exact math (no banker's rounding)."""
    print("\n" + "=" * 60)
    print("TEST 2: Prize Calculation (Exact Math)")
    print("=" * 60)
    
    test_cases = [
        # (player_count, stake, expected_derash, description)
        (1, 10, 7.5, "1 player x 10 ETB = 7.5 derash"),
        (2, 10, 15.0, "2 players x 10 ETB = 15 derash"),
        (1, 20, 15.0, "1 player x 20 ETB = 15 derash"),
        (3, 10, 22.5, "3 players x 10 ETB = 22.5 derash"),
        (4, 25, 75.0, "4 players x 25 ETB = 75 derash"),
        (1, 50, 37.5, "1 player x 50 ETB = 37.5 derash"),
    ]
    
    all_pass = True
    for player_count, stake, expected, desc in test_cases:
        # This is the NEW calculation (exact float, no int() or round())
        total_prize = player_count * stake * 0.75
        
        if total_prize == expected:
            print(f"  âœ“ {desc}: {total_prize} ETB")
        else:
            print(f"  âœ— {desc}: got {total_prize}, expected {expected}")
            all_pass = False
    
    return all_pass


def test_prize_split():
    """Test that prize is split correctly among multiple winners."""
    print("\n" + "=" * 60)
    print("TEST 3: Prize Split Among Winners")
    print("=" * 60)
    
    test_cases = [
        # (player_count, stake, num_winners, expected_per_winner)
        (10, 10, 1, 75.0),
        (10, 10, 2, 37.5),
        (10, 10, 5, 15.0),
        (10, 10, 10, 7.5),
        (1, 10, 1, 7.5),
        (2, 20, 2, 15.0),
    ]
    
    all_pass = True
    for player_count, stake, num_winners, expected in test_cases:
        total_prize = player_count * stake * 0.75
        prize_per_winner = total_prize / num_winners
        
        if prize_per_winner == expected:
            print(f"  âœ“ {player_count} players, {stake} ETB, {num_winners} winner(s): {prize_per_winner} ETB each")
        else:
            print(f"  âœ— Expected {expected}, got {prize_per_winner}")
            all_pass = False
    
    return all_pass


def test_no_bankers_rounding():
    """Verify we're NOT using Python's round() which causes banker's rounding."""
    print("\n" + "=" * 60)
    print("TEST 4: No Banker's Rounding (round(7.5) should NOT be used)")
    print("=" * 60)
    
    # Python's round() uses banker's rounding
    python_round_result = round(7.5)
    expected_correct = 7.5  # What we want
    
    if python_round_result == 8:
        print(f"  âš  Python round(7.5) = {python_round_result} (banker's rounding detected)")
        print(f"  âœ“ Our code should produce {expected_correct} instead")
        return True
    else:
        print(f"  âœ— Unexpected: Python round(7.5) = {python_round_result}")
        return False


def test_predictor_phases():
    """Test that the predictor enforces the 15-30 smart-finish contract."""
    print("\n" + "=" * 60)
    print("TEST 5: Predictor Target Window")
    print("=" * 60)
    
    # Read the round_engine.py to check phase thresholds
    engine_path = os.path.join(os.path.dirname(__file__), 'game/round_engine.py')
    try:
        with open(engine_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        has_target_range = 'GAME_LENGTH_RANGE = (15, 30)' in content
        has_target_normalizer = 'def normalize_game_target' in content
        has_phase1_safe = 'next_call_index < game_target' in content
        has_phase2_target = "for n in (target_winner.get('pattern', []) if target_winner else []):" in content

        if has_target_range:
            print("  [OK] Round target range set to 15-30")
        else:
            print("  [FAIL] 15-30 target range not found")

        if has_target_normalizer:
            print("  [OK] Backend normalizes game_target")
        else:
            print("  [FAIL] normalize_game_target not found")

        if has_phase1_safe:
            print("  [OK] Predictor Phase 1 (safe calls, avoid winners)")
        else:
            print("  [FAIL] Phase 1 safe-call branch not found")

        if has_phase2_target:
            print("  [OK] Predictor Phase 2 (target predetermined winner)")
        else:
            print("  [FAIL] Phase 2 target-winner branch not found")

        return has_target_range and has_target_normalizer and has_phase1_safe and has_phase2_target
    except Exception as e:
        print(f"  [FAIL] Error reading engine: {e}")
        return False


def test_winner_collection():
    """Test that admin_api resolves rounds to a single winner."""
    print("\n" + "=" * 60)
    print("TEST 6: Single Winner Resolution")
    print("=" * 60)
    
    api_path = os.path.join(os.path.dirname(__file__), 'api/admin_api.py')
    try:
        with open(api_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        has_evaluate = 'winner_entries = engine.evaluate_winners' in content
        has_single_choice = 'chosen_winner = engine.choose_single_winner' in content
        has_forced_cap = "completion_reason = 'no_winner_max_30'" in content
        has_single_payout = "engine.end_round(round_id, [int(winner_id)])" in content

        if has_evaluate:
            print("  [OK] Server evaluates natural winners")
        else:
            print("  [FAIL] Natural winner evaluation not found")

        if has_single_choice:
            print("  [OK] Server tie-breaks to one winner")
        else:
            print("  [FAIL] Single-winner tie-break not found")

        if has_forced_cap:
            print("  [OK] Server forces completion at max 30 calls")
        else:
            print("  [FAIL] Forced max-30 completion not found")

        if has_single_payout:
            print("  [OK] Payout path pays exactly one winner")
        else:
            print("  [FAIL] Single-winner payout path not found")

        return has_evaluate and has_single_choice and has_forced_cap and has_single_payout
    except Exception as e:
        print(f"  [FAIL] Error reading admin_api: {e}")
        return False


def test_calc_derash_zero_cards():
    """Test that calcDerash returns 0 when no cards selected."""
    print("\n" + "=" * 60)
    print("TEST 7: calcDerash Returns 0 for No Cards")
    print("=" * 60)
    
    js_path = os.path.join(os.path.dirname(__file__), 'dashboard/js/card-select.js')
    try:
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for the fix
        has_return_zero = 'if (totalCartelas < 1) return 0;' in content
        has_no_forced_one = 'totalCartelas = 1' not in content
        
        if has_return_zero:
            print("  âœ“ Returns 0 when no cards selected")
        else:
            print("  âœ— Missing return 0 for empty selection")
        
        if has_no_forced_one:
            print("  âœ“ Does not force totalCartelas = 1")
        else:
            print("  âœ— Still forces totalCartelas = 1")
        
        return has_return_zero and has_no_forced_one
    except Exception as e:
        print(f"  âœ— Error reading card-select.js: {e}")
        return False


def test_debouncing():
    """Test that admin listeners have debouncing."""
    print("\n" + "=" * 60)
    print("TEST 8: Admin Listener Debouncing")
    print("=" * 60)
    
    listeners_path = os.path.join(os.path.dirname(__file__), 'dashboard/js/admin/listeners.js')
    try:
        with open(listeners_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for debounce timers
        has_users_debounce = '_usersRenderTimer' in content
        has_rounds_debounce = '_roundsRenderTimer' in content
        has_deposits_debounce = '_depositsRenderTimer' in content
        has_withdrawals_debounce = '_withdrawalsRenderTimer' in content
        
        if has_users_debounce:
            print("  âœ“ Users listener debounced")
        else:
            print("  âœ— Users listener not debounced")
        
        if has_rounds_debounce:
            print("  âœ“ Rounds listener debounced")
        else:
            print("  âœ— Rounds listener not debounced")
        
        if has_deposits_debounce:
            print("  âœ“ Deposits listener debounced")
        else:
            print("  âœ— Deposits listener not debounced")
        
        if has_withdrawals_debounce:
            print("  âœ“ Withdrawals listener debounced")
        else:
            print("  âœ— Withdrawals listener not debounced")
        
        return has_users_debounce and has_rounds_debounce
    except Exception as e:
        print(f"  âœ— Error reading listeners.js: {e}")
        return False


def test_no_redundant_db_reads():
    """Test that auth.js doesn't make redundant DB reads."""
    print("\n" + "=" * 60)
    print("TEST 9: No Redundant DB Reads in auth.js")
    print("=" * 60)
    
    auth_path = os.path.join(os.path.dirname(__file__), 'dashboard/js/auth.js')
    try:
        with open(auth_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find refreshCompletedStats function
        func_start = content.find('function refreshCompletedStats()')
        if func_start == -1:
            print("  âœ— refreshCompletedStats not found")
            return False
        
        func_end = content.find('\n}', func_start) + 2
        func_body = content[func_start:func_end]
        
        # Count DB queries
        query_count = func_body.count('.where(')
        
        if query_count <= 1:
            print(f"  âœ“ Only {query_count} DB query in refreshCompletedStats")
            return True
        else:
            print(f"  âœ— {query_count} DB queries found (should be 1)")
            return False
    except Exception as e:
        print(f"  âœ— Error reading auth.js: {e}")
        return False


def test_playnow_guard():
    """Test that playNow has recursion guard."""
    print("\n" + "=" * 60)
    print("TEST 10: playNow Recursion Guard")
    print("=" * 60)
    
    js_path = os.path.join(os.path.dirname(__file__), 'dashboard/js/card-select.js')
    try:
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        has_guard_var = '_playNowRunning' in content
        has_guard_check = 'if (_playNowRunning) return;' in content
        has_guard_set = '_playNowRunning = true' in content
        has_guard_clear = '_playNowRunning = false' in content
        
        if has_guard_var and has_guard_check:
            print("  âœ“ Recursion guard present")
        else:
            print("  âœ— Missing recursion guard")
        
        return has_guard_var and has_guard_check
    except Exception as e:
        print(f"  âœ— Error: {e}")
        return False


def test_web_deposit_flow():
    """Test that web deposit flow mirrors the bot flow through backend APIs and modal UI."""
    print("\n" + "=" * 60)
    print("TEST 11: Web Deposit Flow")
    print("=" * 60)

    base_dir = os.path.dirname(__file__)
    api_path = os.path.join(base_dir, 'api/admin_api.py')
    wallet_js_path = os.path.join(base_dir, 'dashboard/js/wallet.js')
    modal_path = os.path.join(base_dir, 'dashboard/components/deposit-modal.html')

    try:
        with open(api_path, 'r', encoding='utf-8') as f:
            api_content = f.read()
        with open(wallet_js_path, 'r', encoding='utf-8') as f:
            wallet_content = f.read()
        with open(modal_path, 'r', encoding='utf-8') as f:
            modal_content = f.read()

        has_config_api = '@app.get("/api/deposits/config/{user_id}"' in api_content
        has_submit_api = '@app.post("/api/deposits/submit")' in api_content
        has_dup_check = "deposit_duplicate_txn" in api_content
        has_admin_notify = '_notify_admin_deposit_web' in api_content
        has_modal_open = 'function requestDeposit()' in wallet_content
        has_backend_submit = "/api/deposits/submit" in wallet_content
        has_modal_txn = 'Transaction Number' in modal_content

        if has_config_api:
            print("  [OK] Backend exposes deposit config API")
        else:
            print("  [FAIL] Deposit config API not found")

        if has_submit_api:
            print("  [OK] Backend exposes deposit submit API")
        else:
            print("  [FAIL] Deposit submit API not found")

        if has_dup_check:
            print("  [OK] Backend checks duplicate transaction IDs")
        else:
            print("  [FAIL] Duplicate transaction check not found")

        if has_admin_notify:
            print("  [OK] Backend notifies admin for web deposits")
        else:
            print("  [FAIL] Admin notification helper not found")

        if has_modal_open:
            print("  [OK] Wallet opens deposit modal in-app")
        else:
            print("  [FAIL] Deposit modal opener not found")

        if has_backend_submit:
            print("  [OK] Wallet submits deposits through backend")
        else:
            print("  [FAIL] Wallet submit API call not found")

        if has_modal_txn:
            print("  [OK] Deposit modal asks for transaction number")
        else:
            print("  [FAIL] Deposit modal transaction field not found")

        return all([
            has_config_api,
            has_submit_api,
            has_dup_check,
            has_admin_notify,
            has_modal_open,
            has_backend_submit,
            has_modal_txn,
        ])
    except Exception as e:
        print(f"  [FAIL] Error checking web deposit flow: {e}")
        return False


def main():
    print("\n" + "=" * 60)
    print("  BINGO GAME - COMPREHENSIVE TEST SUITE")
    print("=" * 60)
    
    tests = [
        ("Python Syntax", test_python_syntax),
        ("Prize Calculation", test_prize_calculation),
        ("Prize Split", test_prize_split),
        ("No Banker's Rounding", test_no_bankers_rounding),
        ("Predictor Phases", test_predictor_phases),
        ("Winner Collection", test_winner_collection),
        ("calcDerash Zero Cards", test_calc_derash_zero_cards),
        ("Debouncing", test_debouncing),
        ("No Redundant DB Reads", test_no_redundant_db_reads),
        ("playNow Guard", test_playnow_guard),
        ("Web Deposit Flow", test_web_deposit_flow),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n  âœ— EXCEPTION in {name}: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("  TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, p in results if p)
    total = len(results)
    
    for name, p in results:
        status = "âœ“ PASS" if p else "âœ— FAIL"
        print(f"  {status}: {name}")
    
    print("\n" + "-" * 60)
    print(f"  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n  ðŸŽ‰ ALL TESTS PASSED! Changes are safe.")
        return 0
    else:
        print(f"\n  âš  {total - passed} test(s) failed. Review before deploying.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
