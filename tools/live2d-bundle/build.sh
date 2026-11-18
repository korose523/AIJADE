#!/bin/sh
set -eu

case "${1:-}" in
  /*) root=$1 ;;
  *) printf 'Usage: sh %s /absolute/path/to/local-live2d-package\n' "$0" >&2; exit 2 ;;
esac

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
framework="$root/framework-5-r.5"
esbuild="$root/vendor/build-tool/node_modules/esbuild/bin/esbuild"
commit=198a3769c26ca3d7b600e932590433badd392edd
if [ "$(git -C "$framework" rev-parse --verify HEAD)" != "$commit" ] ||
   ! git -C "$framework" diff --quiet HEAD -- src Shaders; then
  printf 'Use the unmodified official Cubism Web Framework 5-r.5 checkout.\n' >&2
  exit 2
fi
if [ "$(node "$esbuild" --version)" != '0.25.12' ]; then
  printf 'Use the project-local installation of esbuild 0.25.12.\n' >&2
  exit 2
fi

runtime="$root/runtime"
mkdir -p "$runtime/shaders"
cp "$framework"/Shaders/WebGL/*.vert "$framework"/Shaders/WebGL/*.frag "$runtime/shaders/"
temporary=$(mktemp "$runtime/.live2d-backend.XXXXXXXX")
trap 'rm -f -- "$temporary"' EXIT HUP INT TERM
cd -- "$here"
node "$esbuild" live2d-backend.ts --bundle --format=esm --target=es2022 --minify \
  --legal-comments=inline --alias:cubism-framework="$framework/src" \
  --banner:js='/*! Uses Live2D Cubism Web Framework 5-r.5, copyright Live2D Inc. See https://www.live2d.com/eula/live2d-open-software-license-agreement_en.html. */' \
  --outfile="$temporary"
mv -- "$temporary" "$runtime/live2d-backend.js"
