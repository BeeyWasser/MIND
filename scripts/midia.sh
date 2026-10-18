#!/bin/sh
# Worker exclusivo de Whisper + keyframes/OCR. A trava no Python impede duas
# instâncias de disputar Metal, rede e os mesmos originais.
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.nix-profile/bin:/etc/profiles/per-user/$USER/bin:/run/current-system/sw/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
exec caffeinate -i "$HOME/.local/bin/uv" run python -m mind_collect.run \
  --worker-midia \
  --limite "${MIND_MEDIA_BATCH:-3}" \
  --espera "${MIND_MEDIA_WAIT:-60}"
