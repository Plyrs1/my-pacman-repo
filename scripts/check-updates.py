#!/usr/bin/env python3
"""Update supported package recipes from upstream GitHub releases."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_URL = "https://api.github.com/repos/ZSeven-W/openpencil/releases?per_page=100"
USER_AGENT = "pacman-repo-release-checker"
ASSET_NAMES = {
    "openpencil-desktop-linux-x86_64.tar.gz",
    "openpencil-desktop-linux-aarch64.tar.gz",
}
VERSION_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
ASSIGNMENT = re.compile(r"^(pkgver|pkgrel)=([^\n]*)$", re.MULTILINE)


class UpdateError(RuntimeError):
    """An upstream or recipe condition prevents a safe update."""


def _request_releases() -> list[dict[str, Any]]:
    request = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise UpdateError(f"GitHub release request failed: {exc}") from exc
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise UpdateError("GitHub releases response is malformed")
    return payload


def _version(tag: object) -> str | None:
    if not isinstance(tag, str):
        return None
    match = VERSION_TAG.fullmatch(tag)
    return match.group(1) if match else None


def _vercmp(left: str, right: str) -> int:
    try:
        result = subprocess.run(
            ["vercmp", left, right], check=True, capture_output=True, text=True
        )
        return int(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise UpdateError(f"Arch vercmp failed: {exc}") from exc


def _release_assets(release: dict[str, Any]) -> set[str]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("GitHub release has malformed assets")
    result = set()
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise UpdateError("GitHub release has malformed asset entry")
        if asset["name"] in ASSET_NAMES:
            if asset.get("state") == "uploaded":
                result.add(asset["name"])
    return result


def update_recipe(repo: Path, releases: list[dict[str, Any]]) -> str | None:
    package_dirs = sorted(path.parent for path in (repo / "pkgs").glob("*/PKGBUILD"))
    expected = [repo / "pkgs" / "openpencil-bin"]
    if package_dirs != expected:
        names = ", ".join(path.name for path in package_dirs) or "none"
        raise UpdateError(
            f"unsupported package set ({names}); add an explicit release adapter"
        )

    recipe = expected[0] / "PKGBUILD"
    text = recipe.read_text(encoding="utf-8")
    matches = list(ASSIGNMENT.finditer(text))
    versions = [match for match in matches if match.group(1) == "pkgver"]
    rels = [match for match in matches if match.group(1) == "pkgrel"]
    if len(versions) != 1 or len(rels) != 1:
        raise UpdateError("PKGBUILD must contain exactly one standalone pkgver= and pkgrel=")
    current = versions[0].group(2)
    if not re.fullmatch(r"\d+\.\d+\.\d+", current):
        raise UpdateError(f"unsupported current pkgver: {current}")

    published = []
    for release in releases:
        if release.get("draft") is True:
            continue
        if not isinstance(release.get("draft"), bool):
            raise UpdateError("GitHub release has malformed draft field")
        if not isinstance(release.get("published_at"), str) or not release["published_at"]:
            continue
        published.append(release)

    # GitHub orders releases newest first. Do not skip an unsupported asset-bearing release.
    for release in published:
        raw_assets = release.get("assets")
        if not isinstance(raw_assets, list):
            raise UpdateError("GitHub release has malformed assets")
        names = {
            asset.get("name")
            for asset in raw_assets
            if isinstance(asset, dict) and isinstance(asset.get("name"), str)
        }
        if names & ASSET_NAMES:
            if _version(release.get("tag_name")) is None:
                raise UpdateError(
                    f"newest asset-bearing release has unsupported tag {release.get('tag_name')!r}"
                )
            break

    newer = []
    for release in published:
        version = _version(release.get("tag_name"))
        if version is not None and _vercmp(version, current) > 0:
            newer.append((version, release))
    if not newer:
        return None

    selected_version, selected_release = newer[0]
    for version, release in newer[1:]:
        if _vercmp(version, selected_version) > 0:
            selected_version, selected_release = version, release
    missing = sorted(ASSET_NAMES - _release_assets(selected_release))
    if missing:
        raise UpdateError(
            f"release v{selected_version} is missing uploaded assets: {', '.join(missing)}"
        )

    updated = text[: versions[0].start(2)] + selected_version + text[versions[0].end(2) :]
    rel_match = next(
        match for match in ASSIGNMENT.finditer(updated) if match.group(1) == "pkgrel"
    )
    updated = updated[: rel_match.start(2)] + "1" + updated[rel_match.end(2) :]
    recipe.write_text(updated, encoding="utf-8")
    try:
        subprocess.run(
            ["updpkgsums", "PKGBUILD"],
            cwd=recipe.parent,
            check=True,
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        recipe.write_text(text, encoding="utf-8")
        raise UpdateError(f"checksum generation failed: {exc}") from exc
    return f"openpencil-bin to {selected_version}-1"


def main(repo: Path | None = None, releases: list[dict[str, Any]] | None = None) -> int:
    if repo is None:
        repo = Path(__file__).resolve().parent.parent
    try:
        release_data = _request_releases() if releases is None else releases
        summary = update_recipe(repo, release_data)
    except (UpdateError, OSError) as exc:
        print(f"check-updates: {exc}", file=sys.stderr)
        return 1
    if summary:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
