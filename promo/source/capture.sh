#!/bin/zsh
# Run only with Anki closed: read-only copies of the collection + focus log, then the captures.
S=/private/tmp/claude-501/-Users-jerryshen-Documents-Stanford-Med-Anki-Addons/9c59ddce-b604-4a22-8bcb-34f73bdee8c5/scratchpad
A="$HOME/Library/Application Support/Anki2/addons21/Interactive Heatmap"
PY="/Users/jerryshen/Library/Application Support/AnkiProgramFiles/.venv/bin/python"
cd $S
BB="$A/builtin_backgrounds"
run() { COL=promo_col "$@" "$PY" promo_deck.py 2>&1 | grep -v "^qt\.\|Populating\|propagate\|blocked main\|^js:" | tail -12; }
run env OUT=hero_forest H=900 PHOTO="$BB/forest_trail.webp" PHOTO_OPACITY=0.5 MODES=volume CFG='{"show_mode_time": true, "heatmap_theme": "forest_trail", "display_mode": "volume"}'
run env OUT=hero_napali H=900 PHOTO="$BB/na_pali.webp" PHOTO_OPACITY=0.55 MODES=volume CFG='{"show_mode_time": true, "heatmap_theme": "na_pali", "display_mode": "volume"}'
