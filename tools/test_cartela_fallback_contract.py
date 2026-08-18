from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fallback = (ROOT / "dashboard-react/client/src/lib/cartelaFallback.ts").read_text(encoding="utf-8")
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text(encoding="utf-8")
board = (ROOT / "dashboard-react/client/src/pages/GameBoard.tsx").read_text(encoding="utf-8")

assert "class PythonRandom" in fallback
assert "number * 1337" in fallback
assert "export function fallbackCartela" in fallback
assert "export function isValidCartela" in fallback
assert "values[12] === 0" in fallback
assert "fallbackCartela(number)" in select
assert "playerApi.cartela(number)" in select
assert "const valid = loaded.filter" in select
assert "fallbackCartela(number)" in board
assert "isValidCartela(card, number)" in board
assert "fallbackCartela(number)" in select and "setCards" in select
assert "Showing the verified local cartela while the server card is unavailable." in board

print("cartela fallback and background hydration contract check: PASS")
