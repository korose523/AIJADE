#!/usr/bin/env bash
# The normal companion host: one server and PostgreSQL. Existing DATABASE_URL / gateway / bot settings still apply.
set -euo pipefail
AIJADE_SOURCE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$AIJADE_SOURCE_ROOT"
if [[ -z "${AIJADE_DOTNET_BIN:-}" ]]; then
  AIJADE_DOTNET_BIN="$(command -v dotnet || true)"
  if [[ -z "$AIJADE_DOTNET_BIN" ]] || ! "$AIJADE_DOTNET_BIN" --version >/dev/null 2>&1; then
    AIJADE_DOTNET_BIN="$HOME/.dotnet/dotnet"
  fi
fi
if ! "$AIJADE_DOTNET_BIN" --version >/dev/null 2>&1; then
  echo 'Install the .NET SDK pinned in global.json, or set AIJADE_DOTNET_BIN.' >&2
  exit 1
fi
export PATH="$(dirname -- "$AIJADE_DOTNET_BIN"):$PATH"
export AIJADE_ARTIFACTS="${AIJADE_ARTIFACTS:-$HOME/.cache/aijade-next-artifacts}"
exec "$AIJADE_DOTNET_BIN" run --project src/Aijade.Server -c "${AIJADE_CONFIGURATION:-Release}" --no-launch-profile -- --Aijade:Profile=companion "$@"
