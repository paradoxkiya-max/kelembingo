from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
game = (ROOT / "dashboard-react/client/src/pages/GameBoard.tsx").read_text()
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text()
gateway = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text()
audio_root = ROOT / "dashboard-react/client/public/audio"

assert "playerApi.cartela(number)" in game
assert "card?.cartela || card?.data || card?.grid" in game
assert "card?.cartela || card?.data || card?.grid" in select
assert "playNumberAudio" in game and "/audio/${letter}${number}.mp3" in game
assert "playCartelaAudio" in game and "/audio/cartela_bingo/cartela_${number}.mp3" in game
assert "speechSynthesis" not in game
assert "SpeechSynthesisUtterance" not in game
assert "cartela?: number[]" in gateway

number_audio = [path for path in audio_root.glob("*.mp3") if path.stem[:1] in {"B", "I", "N", "G", "O"}]
cartela_audio = list((audio_root / "cartela_bingo").glob("cartela_*.mp3"))
assert len(number_audio) == 375, len(number_audio)
assert len(cartela_audio) == 500, len(cartela_audio)

print("two-card and local-audio contract check: PASS")
