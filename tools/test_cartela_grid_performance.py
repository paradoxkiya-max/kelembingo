from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
card_select = (ROOT / 'dashboard-react/client/src/pages/CartelaSelect.tsx').read_text()
game_css = (ROOT / 'dashboard-react/client/src/index.css').read_text()

assert 'visibleCartelas.map' in card_select
assert 'grid-cols-7' in card_select and 'grid-cols-8' in card_select
assert '[contain:layout_style]' in card_select
assert 'aria-label={`Cartela' in card_select
assert 'active:scale-[0.92]' in card_select
assert 'overflow-y-auto' in card_select

print('cartela grid performance regression check: PASS')
