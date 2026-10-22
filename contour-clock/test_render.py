import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import render


class ContrastTests(unittest.TestCase):
    def test_live_entry_disables_adaptive_position(self):
        entry = Path(__file__).with_name("clock.luau").read_text()
        self.assertIn("local adaptive = false", entry)
        self.assertIn('if not current.adaptive then table.insert(args, "--pinned") end', entry)

    def test_time_always_uses_soft_shadow_even_with_legacy_outline_flag(self):
        style = {"light": False, "outline": True, "color": "#101a20", "outline_color": "#b9bdd6"}
        with patch.object(render, "magick") as draw:
            render.text_image("17:11", 135, style, Path("unused.png"), 2, True)
        args = draw.call_args.args[0]
        self.assertNotIn("-morphology", args)
        self.assertNotIn("-border", args)
        self.assertIn("-shadow", args)
        self.assertNotIn("#b9bdd6", args)
        self.assertEqual(args[args.index("-stroke") + 1], "none")

    def test_date_always_uses_soft_shadow_even_with_legacy_outline_flag(self):
        style = {"light": False, "outline": True, "color": "#101a20", "outline_color": "#b9bdd6"}
        with patch.object(render, "magick") as draw:
            render.text_image("Monday, 14 September", 22, style, Path("unused.png"), 2, False)
        args = draw.call_args.args[0]
        self.assertNotIn("-morphology", args)
        self.assertNotIn("-border", args)
        self.assertIn("-shadow", args)
        self.assertEqual(args[args.index("-stroke") + 1], "none")

    def test_luminance_endpoints(self):
        self.assertEqual(render.luminance((0, 0, 0)), 0)
        self.assertAlmostEqual(render.luminance((255, 255, 255)), 1)

    def test_contrast(self):
        self.assertAlmostEqual(render.contrast(0, 1), 21)
        self.assertEqual(render.contrast(.2, .2), 1)

    def test_bright_wallpaper_uses_dark_text(self):
        result = render.treatment([.8] * 100)
        self.assertFalse(result["light"])
        self.assertFalse(result["outline"])
        self.assertGreater(result["contrast_p20"], 4.5)

    def test_dark_wallpaper_uses_light_text(self):
        result = render.treatment([.01] * 100)
        self.assertTrue(result["light"])
        self.assertGreater(result["contrast_p20"], 4.5)

    def test_busy_wallpaper_keeps_uniform_fill_without_outline(self):
        result = render.treatment([0, 1] * 100)
        self.assertFalse(result["outline"])

    def test_impossible_contrast_is_reported_without_adding_outline(self):
        result = render.treatment([.01, .9] * 100)
        self.assertFalse(result["outline"])
        self.assertFalse(result["contrast_met"])

    def test_different_regions_share_one_tone_and_keep_separate_contrast_scores(self):
        samples = {"samples": [{"center_x": 960, "offset": 0,
                                "time": [.097, .257, .389] * 100,
                                "date": [.215, .248, .309] * 100}],
                   "wallpaper": "mixed.jpg", "analysis_key": "sample"}
        with patch.object(render, "sample_wallpaper", return_value=samples):
            result = render.analyse("mixed.jpg", 1920, 1080, Path("unused"), True,
                                    {"primary": "#A6C8FF"})
        self.assertEqual(result["time"]["color"], result["date"]["color"])
        self.assertFalse(result["time"]["light"])
        self.assertFalse(result["time"]["outline"])
        self.assertFalse(result["date"]["outline"])
        self.assertNotEqual(result["time"]["contrast_p10"], result["date"]["contrast_p10"])

    def test_readable_accent_is_preserved_for_both_labels(self):
        styles = render.treatments({"time": ([.01] * 100, 3),
                                    "date": ([.03] * 100, 4.5)}, {"primary": "#81d5ce"})
        for style in styles.values():
            self.assertEqual(style["color"], "#81d5ce")
            self.assertEqual(style["tone_adjustment"], 0)
            self.assertTrue(style["contrast_met"])

    def test_shared_tone_meets_both_targets_when_possible(self):
        styles = render.treatments({"time": ([.3] * 100, 3),
                                    "date": ([.8] * 100, 4.5)}, {"primary": "#a6c8ff"})
        self.assertEqual(styles["time"]["color"], styles["date"]["color"])
        for style in styles.values():
            self.assertGreaterEqual(style["contrast_p10"], style["contrast_target"])
            self.assertTrue(style["contrast_met"])

    def test_readable_native_accent_is_kept(self):
        result = render.treatment([.9] * 100, {"primary": "#904b3b"})
        self.assertEqual(result["color"], "#904b3b")
        self.assertEqual(result["source"], "noctalia.primary")

    def test_bright_wallpaper_darkens_a_dark_mode_pastel(self):
        result = render.treatment([.8] * 100, {"primary": "#ffb4a3"})
        self.assertFalse(result["light"])
        self.assertGreaterEqual(result["contrast_p10"], 4.5)
        r, g, b = render.rgb(result["color"])
        self.assertGreater(r, g)
        self.assertGreater(g, b)

    def test_palette_change_reuses_samples_but_recolours_text(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            wall = cache / "sample.png"
            wall.touch()
            with patch.object(render, "magick", return_value=bytes([240] * (480 * 270 * 3))) as decode:
                warm = render.analyse(str(wall), 1920, 1080, cache, True, {"primary": "#904b3b"})
                cool = render.analyse(str(wall), 1920, 1080, cache, True, {"primary": "#4b5b90"})
            self.assertEqual(decode.call_count, 1)
            self.assertEqual(warm["analysis_key"], cool["analysis_key"])
            self.assertNotEqual(warm["time"]["color"], cool["time"]["color"])
            self.assertNotEqual(warm["date"]["shadow_color"], cool["date"]["shadow_color"])

    def test_region_clamps_outside_screen(self):
        values = render.region(bytes([255] * 12), 2, 2, 100, 100, (-10, -10, 110, 110))
        self.assertEqual(len(values), 4)

    def test_cached_analysis_avoids_decoding(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            wall = cache / "wall with ' quotes.jpg"
            wall.touch()
            raw = bytes([230] * (480 * 270 * 3))
            with patch.object(render, "magick", return_value=raw) as decode:
                a = render.analyse(str(wall), 1920, 1080, cache)
                b = render.analyse(str(wall), 1920, 1080, cache)
                self.assertEqual(a, b)
                self.assertEqual(decode.call_count, 1)
                self.assertEqual(a["center_x"], 960)

    def test_pinned_position(self):
        with tempfile.TemporaryDirectory() as folder:
            wall = Path(folder) / "sample.png"
            wall.touch()
            with patch.object(render, "magick", return_value=bytes([0] * (480 * 270 * 3))):
                a = render.analyse(str(wall), 1920, 1080, Path(folder), True)
            self.assertEqual(a["center_x"], 960)


if __name__ == "__main__":
    unittest.main()
