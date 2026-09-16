#!/bin/sh
# Uma passada da coleta. Chamada pelo job Nix `org.nixos.mind-coleta`.
# caffeinate segura o laptop acordado durante a execução — laptop dormindo abre
# buraco silencioso na série, que é pior que coleta interrompida.
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.nix-profile/bin:/etc/profiles/per-user/$USER/bin:/run/current-system/sw/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
exec caffeinate -i "$HOME/.local/bin/uv" run python -m mind_collect.run --ciclo --sem-transcricao
