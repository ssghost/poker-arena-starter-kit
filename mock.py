from __future__ import annotations

import argparse
import importlib
from typing import Callable

def test_postflop_short_stack_risk_factor() -> None:
    table = {
        "selfSeatNumber": 1,
        "boardCards": ["Ah", "Kd", "7c"],
        "potChips": 300,
        "bigBlindChips": 20,
        "seats": [
            {"seatNumber": 1, "stackChips": 250, "status": "Active"},
            {"seatNumber": 2, "stackChips": 1000, "status": "Active"}
        ],
        "allowedActions": {
            "canFold": True, "canCheck": False, "canCall": True, "canRaise": True,
            "callChips": 100, "raiseRange": {"min": 200, "max": 250},
            "availableActions": ["fold", "call", "raise"]
        }
    }
    res = decide(table)
    assert res is not None, "Decision must return a dictionary"
    assert "action" in res and res["action"] in ("fold", "call", "raise"), f"Invalid action: {res.get('action')}"
    print("[PASS] test_postflop_short_stack_risk_factor")

def test_preflop_short_stack_push_strong_hand() -> None:
    table = {
        "selfSeatNumber": 1,
        "boardCards": [],
        "potChips": 30,
        "bigBlindChips": 20,
        "seats": [
            {"seatNumber": 1, "stackChips": 200, "status": "Active", "holeCards": ["As", "Ks"]},
            {"seatNumber": 2, "stackChips": 1000, "status": "Active"}
        ],
        "allowedActions": {
            "canFold": True, "canCheck": False, "canCall": True, "canRaise": True,
            "callChips": 20, "raiseRange": {"min": 40, "max": 200},
            "availableActions": ["fold", "call", "raise"]
        }
    }
    res = decide(table)
    assert res.get("action") == "raise", f"Expected 'raise', got {res.get('action')}"
    assert res.get("amount") == 200, f"Expected amount 200 (All-in), got {res.get('amount')}"
    assert "Push short" in str(res.get("message")), f"Expected 'Push short' message, got {res.get('message')}"
    print("[PASS] test_preflop_short_stack_push_strong_hand")

def test_preflop_short_stack_fold_trash_hand() -> None:
    table = {
        "selfSeatNumber": 1,
        "boardCards": [],
        "potChips": 50,
        "bigBlindChips": 20,
        "seats": [
            {"seatNumber": 1, "stackChips": 200, "status": "Active", "holeCards": ["7s", "2d"]},
            {"seatNumber": 2, "stackChips": 1000, "status": "Active"}
        ],
        "allowedActions": {
            "canFold": True, "canCheck": False, "canCall": True, "canRaise": True,
            "callChips": 40, "raiseRange": {"min": 80, "max": 200},
            "availableActions": ["fold", "call", "raise"]
        }
    }
    res = decide(table)
    assert res.get("action") == "fold", f"Expected 'fold', got {res.get('action')}"
    assert "Fold short" in str(res.get("message")), f"Expected 'Fold short' message, got {res.get('message')}"
    print("[PASS] test_preflop_short_stack_fold_trash_hand")

def test_preflop_reshove_commitment_protection() -> None:
    table = {
        "selfSeatNumber": 1,
        "buttonSeatNumber": 2,
        "boardCards": [],
        "potChips": 110,
        "bigBlindChips": 20,
        "seats": [
            {"seatNumber": 1, "stackChips": 350, "status": "Active", "holeCards": ["As", "Ks"]},
            {"seatNumber": 2, "stackChips": 1000, "status": "Active"}
        ],
        "allowedActions": {
            "canFold": True, "canCheck": False, "canCall": True, "canRaise": True,
            "callChips": 60, "raiseRange": {"min": 120, "max": 350},
            "availableActions": ["fold", "call", "raise"]
        }
    }
    res = decide(table)
    assert res.get("action") == "raise", f"Expected 'raise', got {res.get('action')}"
    assert res.get("amount") == 350, f"Expected amount 350 (All-in), got {res.get('amount')}"
    assert "Dynamic Value 3bet" in str(res.get("message")), f"Expected 'Dynamic Value 3bet', got {res.get('message')}"
    print("[PASS] test_preflop_reshove_commitment_protection")

def test_postflop_cbet_commitment_pot_control() -> None:
    table = {
        "selfSeatNumber": 1,
        "boardCards": ["Ah", "7d", "2c"],
        "potChips": 1200,
        "bigBlindChips": 20,
        "seats": [
            {"seatNumber": 1, "stackChips": 500, "status": "Active", "holeCards": ["7s", "8s"]},
            {"seatNumber": 2, "stackChips": 2000, "status": "Active"}
        ],
        "allowedActions": {
            "canFold": False, "canCheck": True, "canCall": False, "canBet": True, "canRaise": False,
            "callChips": 0, "betRange": {"min": 200, "max": 500},
            "availableActions": ["check", "bet"]
        }
    }
    res = decide(table)
    assert res.get("action") == "bet", f"Expected 'bet', got {res.get('action')}"
    assert res.get("amount") <= int(500 * 0.65), f"Bet size {res.get('amount')} exceeded commitment threshold"
    print("[PASS] test_postflop_cbet_commitment_pot_control")

def test_preflop_short_stack_facing_allin_call() -> None:
    table = {
        "selfSeatNumber": 1,
        "boardCards": [],
        "potChips": 250,
        "bigBlindChips": 20,
        "seats": [
            {"seatNumber": 1, "stackChips": 200, "status": "Active", "holeCards": ["As", "Ks"]},
            {"seatNumber": 2, "stackChips": 0, "status": "Active"}
        ],
        "allowedActions": {
            "canFold": True, "canCheck": False, "canCall": True, "canRaise": False,
            "callChips": 200,
            "availableActions": ["fold", "call"]
        }
    }
    res = decide(table)
    assert res.get("action") == "call", f"Expected 'call', got {res.get('action')}"
    assert "Call all-in short" in str(res.get("message")), f"Expected 'Call all-in short', got {res.get('message')}"
    print("[PASS] test_preflop_short_stack_facing_allin_call")

def test_preflop_short_stack_bb_free_check() -> None:
    table = {
        "selfSeatNumber": 1,
        "boardCards": [],
        "potChips": 40,
        "bigBlindChips": 20,
        "seats": [
            {"seatNumber": 1, "stackChips": 200, "status": "Active", "holeCards": ["8c", "3d"]},
            {"seatNumber": 2, "stackChips": 1000, "status": "Active"}
        ],
        "allowedActions": {
            "canFold": False, "canCheck": True, "canCall": False, "canRaise": True,
            "callChips": 0, "raiseRange": {"min": 40, "max": 200},
            "availableActions": ["check", "raise"]
        }
    }
    res = decide(table)
    assert res.get("action") == "check", f"Expected 'check', got {res.get('action')}"
    assert "Check short" in str(res.get("message")), f"Expected 'Check short', got {res.get('message')}"
    print("[PASS] test_preflop_short_stack_bb_free_check")

def test_postflop_risk_fold_compressed() -> None:
    table = {
        "selfSeatNumber": 1,
        "boardCards": ["Ah", "Kd", "7c"],
        "potChips": 160,
        "bigBlindChips": 20,
        "seats": [
            {"seatNumber": 1, "stackChips": 100, "status": "Active", "holeCards": ["2h", "3s"]},
            {"seatNumber": 2, "stackChips": 1000, "status": "Active"}
        ],
        "allowedActions": {
            "canFold": True, "canCheck": False, "canCall": True, "canRaise": False,
            "callChips": 40,
            "availableActions": ["fold", "call"]
        }
    }
    res = decide(table)
    assert res.get("action") == "fold", f"Expected 'fold', got {res.get('action')}"
    assert "Risk fold Postflop" in str(res.get("message")), f"Expected 'Risk fold Postflop', got {res.get('message')}"
    print("[PASS] test_postflop_risk_fold_compressed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("module", nargs="?", default=None)
    parser.add_argument("-m", "--module", dest="opt_module", default=None)
    args = parser.parse_args()

    module_name = args.opt_module or args.module
    if not module_name:
        print("Error: Target module name not provided.")

    mod = importlib.import_module(module_name)
    decide = getattr(mod, "decide")

    tests: list[Callable[[], None]] = [
        test_postflop_short_stack_risk_factor,
        test_preflop_short_stack_push_strong_hand,
        test_preflop_short_stack_fold_trash_hand,
        test_preflop_reshove_commitment_protection,
        test_postflop_cbet_commitment_pot_control,
        test_preflop_short_stack_facing_allin_call,
        test_preflop_short_stack_bb_free_check,
        test_postflop_risk_fold_compressed,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {test.__name__}: Unexpected error {e}")
            failed += 1

    if failed == 0:
        print("\nAll mock test cases passed.")
    else:
        print(f"\n{failed} test(s) failed.")