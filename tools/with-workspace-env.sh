#!/usr/bin/env bash
# Keep local working files under one declared workspace. This configures paths; it is not a command sandbox.
set -euo pipefail
if [[ $# -eq 0 ]]; then
  echo 'Usage: tools/with-workspace-env.sh COMMAND [ARGS...]' >&2
  exit 64
fi
AIJADE_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
AIJADE_WORKSPACE_ROOT="${AIJADE_WORKSPACE_ROOT:-$AIJADE_REPO_ROOT}"
mkdir -p "$AIJADE_WORKSPACE_ROOT"
AIJADE_WORKSPACE_ROOT="$(cd -- "$AIJADE_WORKSPACE_ROOT" && pwd -P)"
export AIJADE_WORKSPACE_ROOT
export AIJADE_ARTIFACTS="${AIJADE_ARTIFACTS:-$AIJADE_WORKSPACE_ROOT/.runtime/build-artifacts}"
export AIJADE_DATA_DIR="${AIJADE_DATA_DIR:-$AIJADE_WORKSPACE_ROOT/.runtime/data}"
export TMPDIR="$AIJADE_WORKSPACE_ROOT/.runtime/tmp/"
export TMP="$TMPDIR" TEMP="$TMPDIR"
export XDG_CACHE_HOME="$AIJADE_WORKSPACE_ROOT/.runtime/cache"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$XDG_CACHE_HOME/python"
export MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib"
export CLANG_MODULE_CACHE_PATH="$XDG_CACHE_HOME/clang-modules"
export SWIFT_MODULECACHE_PATH="$XDG_CACHE_HOME/swift-modules"
export UV_CACHE_DIR="$XDG_CACHE_HOME/uv"
export HF_HOME="$XDG_CACHE_HOME/huggingface"
export TORCH_HOME="$XDG_CACHE_HOME/torch"
export NPM_CONFIG_CACHE="$XDG_CACHE_HOME/npm"
export PLAYWRIGHT_BROWSERS_PATH="$XDG_CACHE_HOME/playwright-browsers"
export NUGET_PACKAGES="$AIJADE_WORKSPACE_ROOT/.runtime/nuget/packages"
export NUGET_HTTP_CACHE_PATH="$XDG_CACHE_HOME/nuget-http"
export DOTNET_CLI_HOME="$AIJADE_WORKSPACE_ROOT/.runtime/dotnet-home"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_CLI_USE_MSBUILD_SERVER=0 MSBUILDDISABLENODEREUSE=1
export UseSharedCompilation=false
export DOTNET_PROCESSOR_COUNT="${DOTNET_PROCESSOR_COUNT:-2}"
export COLIMA_HOME="$AIJADE_WORKSPACE_ROOT/.runtime/colima"
export LIMA_HOME="$AIJADE_WORKSPACE_ROOT/.runtime/lima"
export DOCKER_CONFIG="$AIJADE_WORKSPACE_ROOT/.runtime/docker"
export OLLAMA_MODELS="$AIJADE_WORKSPACE_ROOT/.runtime/ollama-models"
for name in AIJADE_ARTIFACTS AIJADE_DATA_DIR TMPDIR XDG_CACHE_HOME NUGET_PACKAGES DOTNET_CLI_HOME; do
  value="${!name}"
  case "$value" in
    "$AIJADE_WORKSPACE_ROOT"|"$AIJADE_WORKSPACE_ROOT"/*) ;;
    *) echo "$name must be inside AIJADE_WORKSPACE_ROOT." >&2; exit 64 ;;
  esac
  if [[ "$value" == *'/../'* || "$value" == */.. ]]; then
    echo "$name must use a normalized workspace path." >&2; exit 64
  fi
  parent="$value"
  while [[ ! -d "$parent" ]]; do parent="$(dirname -- "$parent")"; done
  parent="$(cd -- "$parent" && pwd -P)"
  case "$parent" in
    "$AIJADE_WORKSPACE_ROOT"|"$AIJADE_WORKSPACE_ROOT"/*) ;;
    *) echo "$name resolves through a directory outside AIJADE_WORKSPACE_ROOT." >&2; exit 64 ;;
  esac
done
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$NUGET_PACKAGES" "$DOTNET_CLI_HOME" "$DOCKER_CONFIG"
export AIJADE_LOCAL_ENV_READY=1
exec "$@"
