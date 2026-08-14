"""Regression test for separate admin and player history semantics."""

import asyncio
import os
from pathlib import Path
import sys

os.environ["DATABASE_URL"] = f"sqlite:///{Path('/tmp/kelembingo-player-history-contract.db')}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import admin_api


class StubEngine:
    async def get_recent_rounds(self, limit: int = 20):
        rounds = [
            {"id": "winner-new", "status": "completed", "winners": ["10"]},
            {"id": "spectator-empty", "status": "completed", "winners": []},
            {"id": "winner-old", "status": "completed", "winners": ["11"]},
            {"id": "selecting", "status": "selecting", "winners": []},
            {"id": "winner-middle", "status": "completed", "winners": ["12"]},
        ][:limit]
        return rounds


async def main():
    original_engine = admin_api.engine
    admin_api.engine = StubEngine()
    try:
        admin_result = await admin_api.get_rounds(limit=500)
        assert admin_result["count"] == 5
        assert [item["id"] for item in admin_result["rounds"]] == [
            "winner-new", "spectator-empty", "winner-old", "selecting", "winner-middle"
        ]

        player_result = await admin_api.get_rounds(limit=3, status="completed", winners_only=True)
        assert player_result["count"] == 3
        assert [item["id"] for item in player_result["rounds"]] == [
            "winner-new", "winner-old", "winner-middle"
        ]
    finally:
        admin_api.engine = original_engine


asyncio.run(main())
print("separate admin/player history contract check: PASS")
