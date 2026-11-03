#!/usr/bin/env bash
# Build a package from pkgs/<name>/ and refresh the repo database.
# Usage: scripts/build.sh <pkgname>
set -euo pipefail

name="${1:?usage: scripts/build.sh <pkgname>}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pkgdir="$root/pkgs/$name"
repo="$root/x86_64"

[ -f "$pkgdir/PKGBUILD" ] || { echo "no pkgs/$name/PKGBUILD" >&2; exit 1; }
mkdir -p "$repo"

# Sources are cached in the pkgs dir (SRCDEST) and removed after the move
# below, keeping the working tree clean.
cd "$pkgdir"
SRCDEST="$pkgdir" makepkg -f

# keep only the newest build of this package
rm -f "$repo/$name"-*.pkg.tar.*

# move every built package (looping guards against glob surprises with set -u)
shopt -s nullglob
pkgs=( "$name"-*.pkg.tar.* )
shopt -u nullglob
[ "${#pkgs[@]}" -gt 0 ] || { echo "build produced no package" >&2; exit 1; }
mv "${pkgs[@]}" "$repo/"
rm -rf "$pkgdir/src" "$pkgdir/pkg"
find "$pkgdir" -maxdepth 1 -type f ! -name PKGBUILD -delete

cd "$repo"
rm -f personal.db personal.db.tar.gz personal.files personal.files.tar.gz
repo-add personal.db.tar.gz *.pkg.tar.zst
ln -sf personal.db.tar.gz personal.db
ln -sf personal.files.tar.gz personal.files

echo "done: $name -> $repo"
