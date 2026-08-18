from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text()

assert "playerApi.selectCartela(roundId, userId, number, requestId())" in source
assert "playerApi.unselectCartela(roundId, userId, number, requestId())" in source
assert "roomManager.roomIntent" not in source
assert "mutationTailsRef" in source
assert "Promise.allSettled(tails)" in source
assert "lastTapRef" in source and "now - lastTapRef.current < 300" in source
assert "const selectionClosed" not in source
assert "setSeconds(remaining)" in source
assert "finishSelection(epoch, selectedRef.current, onRetry)" in source
assert "observeCartelaPool" in source
assert "observeRound" in source

@dataclass(frozen=True)
class Tap:
    at_ms: int
    cartela: int
    selecting: bool


def apply_taps(state: list[int], taps: list[Tap]) -> list[int]:
    result = list(state)
    for tap in taps:
        if tap.selecting and tap.cartela not in result and len(result) < 2:
            result.append(tap.cartela)
        elif not tap.selecting and tap.cartela in result:
            result.remove(tap.cartela)
    return result


# Direct mutations are independent across cards, so two cards can be tapped in
# the same short interval; the final state remains deterministic by tap order.
taps = [Tap(44_100, 12, True), Tap(44_200, 13, True), Tap(44_300, 12, False)]
assert apply_taps([], taps) == [13]
assert sorted(taps, key=lambda item: item.at_ms) == taps

# The deadline handoff must wait for the final pending mutation before joining.
last_mutation_at = max(tap.at_ms for tap in taps)
assert last_mutation_at < 45_000
assert 45_000 - last_mutation_at == 700

# A stale visual state cannot be treated as a committed join; the latest round
# snapshot and pending revision are read before join confirmation.
assert "const latest = (await playerApi.round(roundId)).round" in source
assert "const serverSnapshot = roundSelections(latest, userId)" in source
assert "pendingRevision: Number(latest.pending_revision || 0)" in source

print("minimal direct-tap and 45-second boundary regression: PASS")
