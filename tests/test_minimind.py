"""Static tutorial mount regressions. No network or live database access."""

import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import render


class TestMiniMindMount(unittest.TestCase):
    def test_build_resources_are_scoped_to_minimind(self):
        index = (render.MINIMIND / "index.html").read_text(encoding="utf-8")
        resources = re.findall(r'(?:src|href)="([^"]+)"', index)
        self.assertGreaterEqual(len(resources), 3)
        for url in resources:
            self.assertTrue(url.startswith("/minimind/"), url)
            self.assertTrue((render.MINIMIND / url.removeprefix("/minimind/")).is_file(), url)
        for css in (render.MINIMIND / "assets").glob("*.css"):
            for url in re.findall(r'url\([\'"]?([^\)\'\"]+)', css.read_text()):
                self.assertTrue(url.startswith("/minimind/"), url)
                self.assertTrue((render.MINIMIND / url.removeprefix("/minimind/")).is_file(), url)

    def test_render_preserves_main_site_and_remounts_tutorial(self):
        with TemporaryDirectory() as td:
            out = Path(td)
            (out / "img").mkdir()
            (out / "img" / "existing.png").write_bytes(b"existing cover")
            for _ in range(2):
                render.render_site([], out_dir=out)
                home = (out / "index.html").read_text(encoding="utf-8")
                self.assertIn("AI Radar", home)
                self.assertIn('href="/minimind/">互动教程</a>', home)
                self.assertEqual((out / "img" / "existing.png").read_bytes(), b"existing cover")
                for source in render.MINIMIND.rglob("*"):
                    if source.is_file():
                        self.assertEqual((out / "minimind" / source.relative_to(render.MINIMIND)).read_bytes(), source.read_bytes())
                self.assertIn("/minimind/assets/*", (out / "_headers").read_text())
                # Re-render must restore an absent entry, not rely on a one-off dist copy.
                (out / "minimind" / "index.html").unlink()

    def test_missing_build_fails_before_changing_existing_site(self):
        with TemporaryDirectory() as td:
            out = Path(td)
            (out / "index.html").write_text("existing home")
            with mock.patch.object(render, "MINIMIND", out / "missing"):
                with self.assertRaises(FileNotFoundError):
                    render.render_site([], out_dir=out)
            self.assertEqual((out / "index.html").read_text(), "existing home")


if __name__ == "__main__":
    unittest.main()
