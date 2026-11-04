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


BASE_RECIPE = """pkgname=openpencil-bin
pkgver=0.8.5
pkgrel=7
arch=('x86_64' 'aarch64')
source_x86_64=(\"binary-${pkgver}.tar.gz\" \"icon.png\")
source_aarch64=(\"binary-${pkgver}.tar.gz\" \"icon.png\")
sha256sums_x86_64=('old-binary-x' 'old-icon-x')
sha256sums_aarch64=('old-binary-a' 'old-icon-a')
"""


def release(version="0.8.6", assets=None, tag=None):
    if assets is None:
        assets = checker.ASSET_NAMES
    return {
        "draft": False,
        "prerelease": True,
        "published_at": "2026-01-01T00:00:00Z",
        "tag_name": tag or f"v{version}",
        "assets": [{"name": name, "state": "uploaded"} for name in assets],
    }


class UpdateRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.package = self.repo / "pkgs" / "openpencil-bin"
        self.package.mkdir(parents=True)
        self.recipe = self.package / "PKGBUILD"
        self.recipe.write_text(BASE_RECIPE)

    def tearDown(self):
        self.temp.cleanup()

    def test_prerelease_refreshes_version_both_architectures_and_checksums(self):
        def run(command, **kwargs):
            if command[0] == "vercmp":
                return type("Result", (), {"stdout": "1"})()
            self.assertEqual(command, ["updpkgsums", "PKGBUILD"])
            recipe_text = self.recipe.read_text()
            self.assertIn("pkgver=0.8.6", recipe_text)
            self.assertIn("pkgrel=1", recipe_text)
            self.recipe.write_text(
                recipe_text.replace("'old-binary-x' 'old-icon-x'", "'new-binary-x' 'new-icon-x'")
                .replace("'old-binary-a' 'old-icon-a'", "'new-binary-a' 'new-icon-a'")
            )

        output = io.StringIO()
        with patch.object(checker.subprocess, "run", side_effect=run):
            with contextlib.redirect_stdout(output):
                status = checker.main(self.repo, [release()])
        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "openpencil-bin to 0.8.6-1\n")
        text = self.recipe.read_text()
        self.assertIn("pkgver=0.8.6", text)
        self.assertIn("pkgrel=1", text)
        self.assertIn("'new-binary-x' 'new-icon-x'", text)
        self.assertIn("'new-binary-a' 'new-icon-a'", text)

    def test_equal_or_older_release_leaves_recipe_unchanged(self):
        original = self.recipe.read_text()
        def cmp(command, **kwargs):
            return type("Result", (), {"stdout": "0" if command[1] == "0.8.5" else "-1"})()
        with patch.object(checker.subprocess, "run", side_effect=cmp):
            self.assertIsNone(checker.update_recipe(self.repo, [release("0.8.5"), release("0.8.4")]))
        self.assertEqual(self.recipe.read_text(), original)

    def test_missing_asset_fails_without_recipe_change(self):
        original = self.recipe.read_text()
        with patch.object(checker.subprocess, "run", return_value=type("Result", (), {"stdout": "1"})()):
            with self.assertRaisesRegex(checker.UpdateError, "missing uploaded assets"):
                checker.update_recipe(self.repo, [release(assets={"openpencil-desktop-linux-x86_64.tar.gz"})])
        self.assertEqual(self.recipe.read_text(), original)

    def test_checksum_failure_restores_original_recipe(self):
        original = self.recipe.read_text()
        def fail_checksum(command, **kwargs):
            if command[0] == "vercmp":
                return type("Result", (), {"stdout": "1"})()
            raise __import__("subprocess").CalledProcessError(1, "updpkgsums")
        with patch.object(checker.subprocess, "run", side_effect=fail_checksum):
            with self.assertRaisesRegex(checker.UpdateError, "checksum generation failed"):
                checker.update_recipe(self.repo, [release()])
        self.assertEqual(self.recipe.read_text(), original)

    def test_additional_package_is_rejected(self):
        (self.repo / "pkgs" / "other").mkdir()
        (self.repo / "pkgs" / "other" / "PKGBUILD").write_text("pkgname=other")
        with self.assertRaisesRegex(checker.UpdateError, "explicit release adapter"):
            checker.update_recipe(self.repo, [])

    def test_http_failure_is_reported(self):
        with patch.object(checker.urllib.request, "urlopen", side_effect=__import__("urllib.error").error.HTTPError("url", 503, "error", {}, None)):
            with self.assertRaisesRegex(checker.UpdateError, "GitHub release request failed"):
                checker._request_releases()


if __name__ == "__main__":
    unittest.main()
