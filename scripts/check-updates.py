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
from typing import Any, Callable

USER_AGENT = "pacman-repo-release-checker"
VERSION_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
ASSIGNMENT = re.compile(r"^(pkgver|pkgrel)=([^\n]*)$", re.MULTILINE)


class UpdateError(RuntimeError):
    """An upstream or recipe condition prevents a safe update."""


class PackageAdapter:
    def __init__(
        self,
        pkgname: str,
        api_url: str,
        include_prereleases: bool,
        asset_pattern: re.Pattern[str],
        assets_for_version: Callable[[str], set[str]],
    ) -> None:
        self.pkgname = pkgname
        self.api_url = api_url
        self.include_prereleases = include_prereleases
        self.asset_pattern = asset_pattern
        self.assets_for_version = assets_for_version


ADAPTERS: dict[str, PackageAdapter] = {
    "hermes-decomp": PackageAdapter(
        pkgname="hermes-decomp",
        api_url="https://api.github.com/repos/SymbioticSec/hermes-decomp/releases?per_page=100",
        include_prereleases=False,
        asset_pattern=re.compile(r".*"),
        assets_for_version=lambda _version: set(),
    ),
    "openpencil-bin": PackageAdapter(
        pkgname="openpencil-bin",
        api_url="https://api.github.com/repos/ZSeven-W/openpencil/releases?per_page=100",
        include_prereleases=True,
        asset_pattern=re.compile(r"^openpencil-desktop-linux-(x86_64|aarch64)\.tar\.gz$"),
        assets_for_version=lambda _version: {
            "openpencil-desktop-linux-x86_64.tar.gz",
            "openpencil-desktop-linux-aarch64.tar.gz",
        },
    ),
}


def _request_releases(api_url: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        api_url,
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


def _release_assets(release: dict[str, Any], expected: set[str]) -> set[str]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("GitHub release has malformed assets")
    result = set()
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise UpdateError("GitHub release has malformed asset entry")
        if asset["name"] in expected and asset.get("state") == "uploaded":
            result.add(asset["name"])
    return result


def update_package(
    recipe: Path, adapter: PackageAdapter, releases: list[dict[str, Any]]
) -> tuple[str, str] | None:
    text = recipe.read_text(encoding="utf-8")
    matches = list(ASSIGNMENT.finditer(text))
    versions = [match for match in matches if match.group(1) == "pkgver"]
    rels = [match for match in matches if match.group(1) == "pkgrel"]
    if len(versions) != 1 or len(rels) != 1:
        raise UpdateError(
            f"{adapter.pkgname}: PKGBUILD must contain exactly one standalone pkgver= and pkgrel="
        )
    current = versions[0].group(2)
    if not re.fullmatch(r"\d+\.\d+\.\d+", current):
        raise UpdateError(f"{adapter.pkgname}: unsupported current pkgver: {current}")

    published = []
    for release in releases:
        if not isinstance(release.get("draft"), bool):
            raise UpdateError("GitHub release has malformed draft field")
        if release["draft"]:
            continue
        prerelease = release.get("prerelease", False)
        if not isinstance(prerelease, bool):
            raise UpdateError("GitHub release has malformed prerelease field")
        if prerelease and not adapter.include_prereleases:
            continue
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
        if any(adapter.asset_pattern.fullmatch(name) for name in names):
            if _version(release.get("tag_name")) is None:
                raise UpdateError(
                    f"{adapter.pkgname}: newest asset-bearing release has unsupported tag "
                    f"{release.get('tag_name')!r}"
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

    expected_assets = adapter.assets_for_version(selected_version)
    missing = sorted(expected_assets - _release_assets(selected_release, expected_assets))
    if missing:
        raise UpdateError(
            f"{adapter.pkgname}: release v{selected_version} is missing uploaded assets: "
            f"{', '.join(missing)}"
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
        raise UpdateError(f"{adapter.pkgname}: checksum generation failed: {exc}") from exc
    return f"{adapter.pkgname} to {selected_version}-1", text


def update_recipes(
    repo: Path, releases_by_pkg: dict[str, list[dict[str, Any]]] | None = None
) -> str | None:
    package_dirs = sorted(path.parent for path in (repo / "pkgs").glob("*/PKGBUILD"))
    if not package_dirs:
        raise UpdateError("no packages found under pkgs/")

    unsupported = [path.name for path in package_dirs if path.name not in ADAPTERS]
    if unsupported:
        raise UpdateError(
            f"unsupported package set ({', '.join(unsupported)}); add an explicit release adapter"
        )

    updates: list[str] = []
    originals: list[tuple[Path, str]] = []
    try:
        for pkg_dir in package_dirs:
            adapter = ADAPTERS[pkg_dir.name]
            releases = (
                _request_releases(adapter.api_url)
                if releases_by_pkg is None
                else releases_by_pkg[pkg_dir.name]
            )
            result = update_package(pkg_dir / "PKGBUILD", adapter, releases)
            if result is not None:
                summary, original_text = result
                updates.append(summary)
                originals.append((pkg_dir / "PKGBUILD", original_text))
    except Exception:
        for recipe_path, original_text in originals:
            recipe_path.write_text(original_text, encoding="utf-8")
        raise

    return ", ".join(updates) if updates else None


def main(
    repo: Path | None = None, releases_by_pkg: dict[str, list[dict[str, Any]]] | None = None
) -> int:
    if repo is None:
        repo = Path(__file__).resolve().parent.parent
    try:
        summary = update_recipes(repo, releases_by_pkg)
    except (UpdateError, OSError) as exc:
        print(f"check-updates: {exc}", file=sys.stderr)
        return 1
    if summary:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
