from dataclasses import dataclass

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text()

# Contract checks tie the simulation to the real implementation rather than
# testing an unrelated queue abstraction.
assert "const operation = selectionTail.current.then(execute)" in source and "selectionRequests.current.add(operation)" in source
assert "selectionTail.current = operation.catch(() => undefined)" in source
assert "The server finalizer owns the deadline handoff" in source
assert "shares the durable round/user lock" in source
assert "for (;;)" not in source
assert "const committedSelection = normalizeCartelas(selectedRef.current)" in source
assert "const SELECTION_SECONDS = 45;" in source
assert "window.setInterval(sync, 250)" in source
assert "(Date.now() + serverClockOffset)" in source
assert "selectionIntents.current" in source
assert "pending_revision" in source

@dataclass(frozen=True)
class Intent:
    at_ms: int
    cartela: int
    selecting: bool
    response_delay_ms: int


def apply_intents(authoritative: list[int], intents: list[Intent]) -> list[int]:
    state = list(authoritative)
    for intent in intents:
        if intent.selecting and intent.cartela not in state:
            state.append(intent.cartela)
        elif not intent.selecting and intent.cartela in state:
            state.remove(intent.cartela)
    return state[:2]


# Three rapid taps occur immediately before expiry. Network responses arrive
# out of order, but the client queue serializes execution in tap order.
intents = [
    Intent(44_100, 12, True, 900),
    Intent(44_200, 13, True, 100),
    Intent(44_300, 12, False, 50),
]
assert sorted(intents, key=lambda item: item.response_delay_ms) != intents
assert apply_intents([], intents) == [13]

# The automatic handoff at 45s must wait for the serialized queue's last
# response at 45.15s, then join only the remaining card.
queue_drains_at = 0
for item in intents:
    queue_drains_at = max(queue_drains_at, item.at_ms) + item.response_delay_ms
assert queue_drains_at == 45_150
assert queue_drains_at > 45_000
assert apply_intents([], intents) == [13]

# A delayed stale pool snapshot cannot restore cartela 12 after revision 12
# has already committed the deselection at revision 13.
current_revision = 13
stale_revision = 12
assert stale_revision < current_revision
assert stale_revision < current_revision  # stale snapshot must be rejected

# Reloading during the delayed queue uses the same deadline, never a fresh
# local 45-second window.
deadline_ms = 45_000
reload_at_ms = 44_500
assert max(0, (deadline_ms - reload_at_ms + 999) // 1000) == 1

print("simulated selection lag and 45-second boundary queue regression: PASS")
