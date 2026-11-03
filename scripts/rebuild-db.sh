#!/usr/bin/env bash
# Regenerate the repo database from all packages in x86_64/.
# Usage: scripts/rebuild-db.sh
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$root/x86_64"
cd "$repo"

shopt -s nullglob
pkgs=( *.pkg.tar.zst )
shopt -u nullglob
[ "${#pkgs[@]}" -gt 0 ] || { echo "no packages in x86_64/" >&2; exit 1; }

rm -f personal.db personal.db.tar.gz personal.files personal.files.tar.gz
repo-add personal.db.tar.gz "${pkgs[@]}"
ln -sf personal.db.tar.gz personal.db
ln -sf personal.files.tar.gz personal.files

echo "db rebuilt from ${#pkgs[@]} package(s)"
