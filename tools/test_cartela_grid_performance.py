from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
card_select = (ROOT / 'dashboard/js/card-select.js').read_text()
game_html = (ROOT / 'dashboard/game.html').read_text()
game_css = (ROOT / 'dashboard/css/game.css').read_text()
components_css = (ROOT / 'dashboard/css/components.css').read_text()

assert 'document.createDocumentFragment()' in card_select
assert 'grid.replaceChildren(fragment)' in card_select
assert 'grid.addEventListener(\'click\', _gridClickHandler' in card_select
assert '_cardCellByNumber' in card_select
assert '_lastSelectionRealtimeKey' in card_select
assert 'grid.querySelectorAll(\'.card-tile\')' not in card_select
assert "css/game.css?v=grid-1" in game_html
assert "css/components.css?v=grid-1" in game_html
assert "js/card-select.js?v=grid-1" in game_html
assert 'contain: layout style' in game_css
assert 'touch-action: pan-y' in game_css
assert 'transition: transform 0.15s ease' in components_css

print('cartela grid performance regression check: PASS')
