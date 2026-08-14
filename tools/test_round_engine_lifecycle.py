import asyncio
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("RENDER_API_ONLY", None)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'round-engine.sqlite3'}"

    from firestore_db import MockFirestoreClient
    from game.round_engine import RoundEngine
    from settlement import refund_no_winner

    db = MockFirestoreClient()
    engine = RoundEngine(db)

    async def create_same_stake_rounds():
        return await asyncio.gather(
            engine.create_round(10),
            engine.create_round(10),
            engine.create_round(10),
        )

    created = asyncio.run(create_same_stake_rounds())
    assert len({item["id"] for item in created}) == 1, created
    assert len(db.collection("rounds").where("stake", "==", 10).get()) == 1

    db.collection("users").document("1").set({
        "play_wallet": 100,
        "total_games": 0,
        "wins": 0,
        "losses": 0,
        "is_playing": False,
        "active_round_id": None,
    })
    round_id = created[0]["id"]
    db.collection("rounds").document(round_id).update({
        "status": "playing",
        "players": {},
        "player_count": 0,
        "called_numbers": [],
        "game_started_at": datetime.now(tz=timezone.utc),
    })
    late_join = asyncio.run(engine.join_round(round_id, 1, [1], "Player 1"))
    assert "no longer accepting" in late_join["error"].lower(), late_join

    db.collection("cartelas_master").document("1").set({
        "number": 1,
        "cartela": engine._generate_single_cartela(1337),
    })
    db.collection("rounds").document("round-calls").set({
        "status": "playing",
        "stake": 10,
        "players": {"1": {"name": "Player 1", "cartelas": [1], "joined_at": "2026-01-01T00:00:00+00:00"}},
        "player_count": 1,
        "called_numbers": [],
        "winners": [],
        "game_target": 15,
        "game_started_at": datetime.now(tz=timezone.utc),
        "payout_processed": False,
    })
    calls = [asyncio.run(engine.call_number("round-calls")) for _ in range(16)]
    assert all(isinstance(number, int) for number in calls), calls
    assert len(set(calls)) == 16, calls
    assert len(db.collection("rounds").document("round-calls").get().to_dict()["called_numbers"]) == 16

    db.collection("cartelas_master").document("2").set({
        "number": 2,
        "cartela": engine._generate_single_cartela(2674),
    })
    db.collection("users").document("2").set({
        "play_wallet": 0,
        "total_games": 4,
        "wins": 1,
        "losses": 3,
        "is_playing": True,
        "active_round_id": "round-person",
    })
    db.collection("rounds").document("round-person").set({
        "status": "playing",
        "stake": 10,
        "players": {"2": {"name": "Player 2", "cartelas": [1, 2], "joined_at": "2026-01-01T00:00:00+00:00"}},
        "player_count": 2,
        "called_numbers": list(range(1, 76)),
        "winners": [],
        "payout_processed": False,
    })
    winner = asyncio.run(engine.claim_bingo("round-person", 2, 2))
    assert winner.get("winner") is True, winner
    person_round = db.collection("rounds").document("round-person").get().to_dict()
    assert person_round["winners"] == ["2"], person_round
    assert person_round["winning_cartela"] == 2, person_round
    person_user = db.collection("users").document("2").get().to_dict()
    assert person_user["total_games"] == 5, person_user
    assert person_user["wins"] == 2, person_user
    retry = asyncio.run(engine.end_round("round-person", [2]))
    assert retry.get("status") == "completed", retry
    assert retry.get("winners") == [2], retry
    assert db.collection("users").document("2").get().to_dict()["wins"] == 2

    empty_end = asyncio.run(engine.end_round("round-calls", []))
    assert empty_end.get("error") == "A validated winner is required; use refund_no_winner for no-winner rounds", empty_end

    db.collection("users").document("3").set({
        "play_wallet": 0,
        "total_games": 2,
        "wins": 0,
        "losses": 2,
        "is_playing": True,
        "active_round_id": "round-refund",
    })
    db.collection("rounds").document("round-refund").set({
        "status": "playing",
        "stake": 10,
        "players": {"3": {"name": "Player 3", "cartelas": [1]}},
        "player_count": 1,
        "winners": [],
        "payout_processed": False,
    })
    refund = refund_no_winner(db, "round-refund")
    assert refund.get("ok") is True, refund
    refunded_user = db.collection("users").document("3").get().to_dict()
    assert refunded_user["play_wallet"] == 10, refunded_user
    assert refunded_user["total_games"] == 3, refunded_user
    assert refunded_user["losses"] == 3, refunded_user

print("round-engine lifecycle regression check: PASS")
