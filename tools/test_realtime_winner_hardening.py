import asyncio
import os
import tempfile
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.pop("RENDER_API_ONLY", None)


def make_card(start):
    values = list(range(start, start + 24))
    card = []
    index = 0
    for row in range(5):
        for col in range(5):
            if row == 2 and col == 2:
                card.append(0)
            else:
                card.append(values[index])
                index += 1
    return card


def setup_round(db, round_id, players, called_numbers):
    db.collection("cartelas_master").document("1").set({"number": 1, "cartela": make_card(1)})
    db.collection("cartelas_master").document("2").set({"number": 2, "cartela": make_card(25)})
    for uid in players:
        db.collection("users").document(str(uid)).set({
            "first_name": f"Player {uid}",
            "play_wallet": 0,
            "wins": 0,
            "losses": 0,
        })
    db.collection("rounds").document(round_id).set({
        "status": "playing",
        "stake": 10,
        "players": players,
        "player_count": len(players),
        "called_numbers": called_numbers,
        "winners": [],
        "payout_processed": False,
    })


async def concurrent_claims(engine):
    return await asyncio.gather(
        engine.claim_bingo("round-concurrent", 1, 1),
        engine.claim_bingo("round-concurrent", 2, 2),
    )


with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'test.db'}"
    from firestore_db import MockFirestoreClient
    from game.round_engine import RoundEngine

    db = MockFirestoreClient()
    engine = RoundEngine(db)

    setup_round(
        db,
        "round-concurrent",
        {
            "1": {"name": "A", "cartelas": [1]},
            "2": {"name": "B", "cartelas": [2]},
        },
        list(range(1, 49)),
    )
    results = asyncio.run(concurrent_claims(engine))
    assert sum(1 for result in results if result.get("winner")) == 1, results
    round_data = db.collection("rounds").document("round-concurrent").get().to_dict()
    assert len(round_data["winners"]) == 1, round_data
    assert isinstance(round_data["winning_cartela"], int), round_data
    assert round_data["payout_processed"] is True, round_data

    setup_round(
        db,
        "round-two-cards",
        {"1": {"name": "A", "cartelas": [1, 2]}},
        list(range(1, 49)),
    )
    two_card_result = asyncio.run(engine.claim_bingo("round-two-cards", 1, 2))
    assert two_card_result.get("winner") is True, two_card_result
    two_card_round = db.collection("rounds").document("round-two-cards").get().to_dict()
    assert two_card_round["winners"] == ["1"], two_card_round
    assert two_card_round["winning_cartela"] == 2, two_card_round
    second_cartela_claim = asyncio.run(engine.claim_bingo("round-two-cards", 1, 1))
    assert second_cartela_claim.get("winner") is False, second_cartela_claim
    assert second_cartela_claim.get("error") == "This round was won with another cartela", second_cartela_claim

    rejected = asyncio.run(engine.end_round("round-two-cards", [1, 2]))
    assert rejected.get("error") == "Exactly one winner is required", rejected

admin_source = (REPO / "api" / "admin_api.py").read_text()
round_source = (REPO / "game" / "round_engine.py").read_text()
realtime_source = (REPO / "dashboard-react" / "client" / "src" / "lib" / "realtime.ts").read_text()
game_source = (REPO / "dashboard-react" / "client" / "src" / "pages" / "GameBoard.tsx").read_text()
player_context = (REPO / "dashboard-react" / "client" / "src" / "contexts" / "PlayerContext.tsx").read_text()
admin_context = (REPO / "dashboard-react" / "client" / "src" / "contexts" / "AdminContext.tsx").read_text()
wallet_source = (REPO / "dashboard-react" / "client" / "src" / "pages" / "Wallet.tsx").read_text()

assert "SystemEvent.id > last_id" not in admin_source
assert "_latest_event_cursor" in admin_source
assert "from sqlalchemy import and_, or_, text as sql_text" in admin_source
assert "_last_broadcast_fingerprints" in admin_source
assert "Exactly one winner is required" in round_source
assert "This round was won with another cartela" in round_source
assert "choose_single_winning_cartela" in round_source
assert "claim-bingo" in admin_source
assert "subscribe" in realtime_source
assert "reconnection" in realtime_source
assert "unsubscribe" in realtime_source
assert "subscribeCollection" in realtime_source and "observeAdminCollections" in realtime_source
assert "observePlayerPayments" in realtime_source and "admin_token" in realtime_source
assert "collection not in {\"users\", \"payments\"}" in admin_source
assert "broadcast_player_payment" in admin_source and '"user_id": str(user_id)' in admin_source
assert "observePlayer" in player_context and "playerApi.reconcile" in player_context
assert "observeAdminCollections" in admin_context and "realtimeRevision" in admin_context
assert "observePlayerPayments" in wallet_source and "cacheAt.current = 0" in wallet_source
assert "claimBingo" not in game_source
assert "complete_round" in admin_source and "winner_entries" in admin_source

print("realtime and single-winner hardening regression check: PASS")
