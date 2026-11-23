import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-updates.py"
SPEC = importlib.util.spec_from_file_location("check_updates", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


OPENPENCIL_RECIPE = """pkgname=openpencil-bin
pkgver=0.8.5
pkgrel=7
arch=('x86_64' 'aarch64')
source_x86_64=("binary-${pkgver}.tar.gz" "icon.png")
source_aarch64=("binary-${pkgver}.tar.gz" "icon.png")
sha256sums_x86_64=('old-binary-x' 'old-icon-x')
sha256sums_aarch64=('old-binary-a' 'old-icon-a')
"""

HERMES_RECIPE = """pkgname=hermes-decomp
pkgver=0.2.4
pkgrel=3
arch=('x86_64' 'aarch64')
source=("hermes-decomp-LICENSE-${pkgver}")
source_x86_64=("hermes-decomp-${pkgver}-x86_64.tar.gz")
source_aarch64=("hermes-decomp-${pkgver}-aarch64.tar.gz")
sha256sums=('old-license')
sha256sums_x86_64=('old-hermes-x')
sha256sums_aarch64=('old-hermes-a')
"""


def openpencil_release(version="0.8.6", assets=None, tag=None, prerelease=True):
    if assets is None:
        assets = checker.ADAPTERS["openpencil-bin"].assets_for_version(version)
    return {
        "draft": False,
        "prerelease": prerelease,
        "published_at": "2026-01-01T00:00:00Z",
        "tag_name": tag or f"v{version}",
        "assets": [{"name": name, "state": "uploaded"} for name in assets],
    }


def hermes_release(version="0.2.5", assets=None, tag=None, prerelease=False):
    if assets is None:
        assets = checker.ADAPTERS["hermes-decomp"].assets_for_version(version)
    return {
        "draft": False,
        "prerelease": prerelease,
        "published_at": "2026-10-15T00:00:00Z",
        "tag_name": tag or f"v{version}",
        "assets": [{"name": name, "state": "uploaded"} for name in assets],
    }


class UpdateRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.openpencil_pkg = self.repo / "pkgs" / "openpencil-bin"
        self.openpencil_pkg.mkdir(parents=True)
        self.openpencil_recipe = self.openpencil_pkg / "PKGBUILD"
        self.openpencil_recipe.write_text(OPENPENCIL_RECIPE)

    def tearDown(self):
        self.temp.cleanup()

    def _add_hermes(self):
        self.hermes_pkg = self.repo / "pkgs" / "hermes-decomp"
        self.hermes_pkg.mkdir(parents=True)
        self.hermes_recipe = self.hermes_pkg / "PKGBUILD"
        self.hermes_recipe.write_text(HERMES_RECIPE)

    def test_prerelease_refreshes_openpencil_version_and_checksums(self):
        def run(command, **kwargs):
            if command[0] == "vercmp":
                return type("Result", (), {"stdout": "1"})()
            self.assertEqual(command, ["updpkgsums", "PKGBUILD"])
            recipe_text = self.openpencil_recipe.read_text()
            self.assertIn("pkgver=0.8.6", recipe_text)
            self.assertIn("pkgrel=1", recipe_text)
            self.openpencil_recipe.write_text(
                recipe_text.replace("'old-binary-x' 'old-icon-x'", "'new-binary-x' 'new-icon-x'")
                .replace("'old-binary-a' 'old-icon-a'", "'new-binary-a' 'new-icon-a'")
            )

        output = io.StringIO()
        with patch.object(checker.subprocess, "run", side_effect=run):
            with contextlib.redirect_stdout(output):
                status = checker.main(self.repo, {"openpencil-bin": [openpencil_release()]})
        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "openpencil-bin to 0.8.6-1\n")
        text = self.openpencil_recipe.read_text()
        self.assertIn("pkgver=0.8.6", text)
        self.assertIn("pkgrel=1", text)
        self.assertIn("'new-binary-x' 'new-icon-x'", text)
        self.assertIn("'new-binary-a' 'new-icon-a'", text)

    def test_hermes_skips_prereleases_and_updates_stable_release(self):
        self._add_hermes()

        def run(command, cwd=None, **kwargs):
            if command[0] == "vercmp":
                return type("Result", (), {"stdout": "1" if command[1] == "0.2.5" else "0"})()
            self.assertEqual(command, ["updpkgsums", "PKGBUILD"])
            self.assertEqual(cwd, self.hermes_pkg)
            recipe_text = self.hermes_recipe.read_text()
            self.assertIn("pkgver=0.2.5", recipe_text)
            self.assertIn("pkgrel=1", recipe_text)
            self.hermes_recipe.write_text(
                recipe_text.replace("'old-license'", "'new-license'")
                .replace("'old-hermes-x'", "'new-hermes-x'")
                .replace("'old-hermes-a'", "'new-hermes-a'")
            )

        output = io.StringIO()
        with patch.object(checker.subprocess, "run", side_effect=run):
            with contextlib.redirect_stdout(output):
                status = checker.main(
                    self.repo,
                    {
                        "openpencil-bin": [openpencil_release("0.8.5")],
                        "hermes-decomp": [
                            hermes_release("0.3.0", prerelease=True),
                            hermes_release("0.2.5", prerelease=False),
                        ],
                    },
                )
        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "hermes-decomp to 0.2.5-1\n")
        text = self.hermes_recipe.read_text()
        self.assertIn("pkgver=0.2.5", text)
        self.assertIn("pkgrel=1", text)
        self.assertIn("'new-hermes-x'", text)
        self.assertIn("'new-hermes-a'", text)

    def test_multi_package_update_outputs_single_line_summary(self):
        self._add_hermes()

        def run(command, cwd=None, **kwargs):
            if command[0] == "vercmp":
                return type("Result", (), {"stdout": "1"})()
            return None

        output = io.StringIO()
        with patch.object(checker.subprocess, "run", side_effect=run):
            with contextlib.redirect_stdout(output):
                status = checker.main(
                    self.repo,
                    {
                        "hermes-decomp": [hermes_release("0.2.5")],
                        "openpencil-bin": [openpencil_release("0.8.6")],
                    },
                )
        self.assertEqual(status, 0)
        self.assertEqual(
            output.getvalue(),
            "hermes-decomp to 0.2.5-1, openpencil-bin to 0.8.6-1\n",
        )

    def test_equal_or_older_release_leaves_recipe_unchanged(self):
        original = self.openpencil_recipe.read_text()

        def cmp(command, **kwargs):
            return type("Result", (), {"stdout": "0" if command[1] == "0.8.5" else "-1"})()

        with patch.object(checker.subprocess, "run", side_effect=cmp):
            self.assertIsNone(
                checker.update_recipes(
                    self.repo,
                    {"openpencil-bin": [openpencil_release("0.8.5"), openpencil_release("0.8.4")]},
                )
            )
        self.assertEqual(self.openpencil_recipe.read_text(), original)

    def test_missing_asset_fails_without_recipe_change(self):
        original = self.openpencil_recipe.read_text()
        with patch.object(checker.subprocess, "run", return_value=type("Result", (), {"stdout": "1"})()):
            with self.assertRaisesRegex(checker.UpdateError, "missing uploaded assets"):
                checker.update_recipes(
                    self.repo,
                    {
                        "openpencil-bin": [
                            openpencil_release(assets={"openpencil-desktop-linux-x86_64.tar.gz"})
                        ]
                    },
                )
        self.assertEqual(self.openpencil_recipe.read_text(), original)

    def test_checksum_failure_restores_all_modified_recipes(self):
        self._add_hermes()
        orig_hermes = self.hermes_recipe.read_text()
        orig_openpencil = self.openpencil_recipe.read_text()

        def fail_second(command, cwd=None, **kwargs):
            if command[0] == "vercmp":
                return type("Result", (), {"stdout": "1"})()
            if cwd == self.openpencil_pkg:
                raise __import__("subprocess").CalledProcessError(1, "updpkgsums")
            return None

        with patch.object(checker.subprocess, "run", side_effect=fail_second):
            with self.assertRaisesRegex(checker.UpdateError, "checksum generation failed"):
                checker.update_recipes(
                    self.repo,
                    {
                        "hermes-decomp": [hermes_release("0.2.5")],
                        "openpencil-bin": [openpencil_release("0.8.6")],
                    },
                )
        self.assertEqual(self.hermes_recipe.read_text(), orig_hermes)
        self.assertEqual(self.openpencil_recipe.read_text(), orig_openpencil)

    def test_additional_package_is_rejected(self):
        (self.repo / "pkgs" / "other").mkdir()
        (self.repo / "pkgs" / "other" / "PKGBUILD").write_text("pkgname=other")
        with self.assertRaisesRegex(checker.UpdateError, "explicit release adapter"):
            checker.update_recipes(self.repo, {})

    def test_http_failure_is_reported(self):
        with patch.object(
            checker.urllib.request,
            "urlopen",
            side_effect=__import__("urllib.error").error.HTTPError("url", 503, "error", {}, None),
        ):
            with self.assertRaisesRegex(checker.UpdateError, "GitHub release request failed"):
                checker._request_releases("https://example.invalid/releases")


if __name__ == "__main__":
    unittest.main()
