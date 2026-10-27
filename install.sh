#!/usr/bin/env bash
# Instala el kit en ~/.claude SIN sobrescribir nada que ya tengas.
# Uso: ./install.sh --dry-run   (solo muestra qué copiaría)
#      ./install.sh             (copia lo que falte)
set -euo pipefail
DEST="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
HERE="$(cd "$(dirname "$0")" && pwd)"
n=0; skip=0
for sec in skills agents commands bin scripts; do
  [ -d "$HERE/$sec" ] || continue
  while IFS= read -r -d '' f; do
    rel="${f#$HERE/}"; out="$DEST/$rel"
    if [ -e "$out" ]; then skip=$((skip+1)); continue; fi
    n=$((n+1))
    if [ "$DRY" = 1 ]; then echo "copiaría: $rel"; else mkdir -p "$(dirname "$out")"; cp -p "$f" "$out"; fi
  done < <(find "$HERE/$sec" -type f ! -name '.DS_Store' -print0)
done
[ "$DRY" = 1 ] && echo "dry-run: $n archivos nuevos, $skip ya existían (no se tocan)" || echo "instalado: $n archivos nuevos en $DEST, $skip ya existían (no se tocaron)"
