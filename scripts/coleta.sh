#!/bin/sh
# Uma passada da coleta. Chamado pelo launchd; ver scripts/com.mind.coleta.plist.
# caffeinate segura o laptop acordado durante a execução — laptop dormindo abre
# buraco silencioso na série, que é pior que coleta interrompida.
cd "$(dirname "$0")/.." || exit 1
exec caffeinate -i "$HOME/.local/bin/uv" run python -m mind_collect.run --ciclo
