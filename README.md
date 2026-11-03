# My personal pacman repository

A pacman binary repository served via **GitHub Pages**. Packages are built
locally with `makepkg` and committed; the site publishes the `x86_64/`
directory as a repo pacman can consume.

## Packages

| Package | Version | Description | Upstream |
|---------|---------|-------------|----------|
| openpencil-bin | 0.8.5-1 | Open-source AI-native vector design tool (prebuilt binary) | https://github.com/ZSeven-W/openpencil |

## Client setup

Append to `/etc/pacman.conf`:

```ini
[personal]
SigLevel = PackageRequired
Server = https://<your-github-user>.github.io/my-pacman-repo/x86_64
```

> Replace `<your-github-user>` and `my-pacman-repo` with your actual
> GitHub username and repo name. The URL must be the *Pages* URL, not the
> repo URL.

Then:

```bash
sudo pacman -Sy
pacman -Sl personal          # list packages
sudo pacman -S openpencil-bin
```

> **Unsigned repo:** because this repo is not GPG-signed, `SigLevel =
> PackageRequired` means pacman checks the package's *internal* md5/sha256
> (recorded in the built package) but not a publisher signature. This is the
> minimum-safe setting for a personal repo over HTTPS.

## Repo layout

```
pkgs/<pkgname>/PKGBUILD   # one directory per package, named after the package
x86_64/                   # built packages + personal.db / personal.files
.github/workflows/        # publishes x86_64/ to GitHub Pages
scripts/                  # build.sh, rebuild-db.sh
```

`pkgs/` is the source of truth (PKGBUILDs are committed). `x86_64/` is
generated — never edit packages there by hand; rebuild and recommit.

## Adding / updating a package

From the repo root:

```bash
# one-time: create the package dir
mkdir -p pkgs/<pkgname> && $EDITOR pkgs/<pkgname>/PKGBUILD

# build (sources are downloaded into the pkgs dir, then cleaned)
./scripts/build.sh <pkgname>

# regenerate the database after adding or removing any package
./scripts/rebuild-db.sh
```

`scripts/build.sh` moves the built `.pkg.tar.zst` into `x86_64/`, removes
old versions of the same package, regenerates `personal.db`, and cleans
build artifacts. Commit and push the result:

```bash
git add -A
git commit -m "openpencil-bin: add 0.8.5-1"
git push
```

GitHub Actions publishes on push to `main` (see
`.github/workflows/publish.yml`). The first push needs Pages enabled once:
**Settings → Pages → Source: GitHub Actions**.

## Removing a package

```bash
rm x86_64/<pkgname>-*.pkg.tar.zst
./scripts/rebuild-db.sh
git add -A && git commit -m "<pkgname>: remove" && git push
```
