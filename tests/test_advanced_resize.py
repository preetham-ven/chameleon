from copy import deepcopy
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from engine.packing import balanced_columns, flow_rows, pack_rectangles
from engine.quality import assess_quality
from engine.resize import _minimum_font, layout_warnings, resize
from tests import test_resize as checks
from tests.advanced_cases import EXTREME_TARGETS, advanced_design, awkward_design, image_collection


ROOT = Path(__file__).resolve().parents[1]


class PackingTests(unittest.TestCase):
    def assert_disjoint(self, boxes, region):
        rx, ry, rw, rh = region
        for i, (x, y, w, h) in enumerate(boxes):
            self.assertGreaterEqual(x, rx)
            self.assertGreaterEqual(y, ry)
            self.assertLessEqual(x + w, rx + rw + 1e-6)
            self.assertLessEqual(y + h, ry + rh + 1e-6)
            for xx, yy, ww, hh in boxes[i + 1:]:
                self.assertFalse(min(x + w, xx + ww) > max(x, xx) + 1e-6
                                 and min(y + h, yy + hh) > max(y, yy) + 1e-6)

    def test_supporting_rectangles_fit_without_overlap(self):
        sizes = [(70, 70), (90, 35), (70, 20), (25, 10)]
        region = (3, 4, 190, 86)
        for vertical in (True, False):
            boxes = pack_rectangles(sizes, region, 2, vertical)
            self.assertIsNotNone(boxes)
            self.assert_disjoint(boxes, region)
        self.assertIsNone(pack_rectangles([(200, 30)], region, 2))

    def test_row_breaks_avoid_two_tall_rows(self):
        boxes, height = flow_rows([(65, 10), (30, 30), (30, 30)], 100, 2)
        self.assertEqual(height, 42)
        self.assert_disjoint(boxes, (0, 0, 100, height))
        self.assertIsNone(flow_rows([(101, 10)], 100, 2))

    def test_ordered_columns_balance_their_heights(self):
        ranges, height = balanced_columns([50, 10, 10, 50], 2, 2)
        self.assertEqual(ranges, [(0, 2), (2, 4)])
        self.assertEqual(height, 62)


class AdvancedResizeTests(unittest.TestCase):
    def assert_contract(self, source, output):
        checks.ResizeTests.assert_contract(self, source, output)
        checks.ResizeTests.assert_no_foreground_collisions(self, source, output)

    def test_level3_sample_preserves_copy_and_improves_smallest_text(self):
        task = checks.task(3)
        original = deepcopy(task)
        out = resize(task["source"], task["target_canvas"])
        self.assert_contract(task["source"], out)
        self.assertGreaterEqual(_minimum_font(out), 7)
        self.assertEqual(task, original)
        self.assertEqual(out, resize(task["source"], task["target_canvas"]))
        ribbon = [e for e in out["elements"] if e.get("group_id") == "ribbon"]
        self.assertTrue(all(e["rotation"] == -12 for e in ribbon))
        missing = next(e for e in out["elements"] if e["id"] == "holiday_watermark")
        self.assertEqual(missing["asset_id"], "solstice_holiday_badge_2025.png")

    def test_sample_keeps_hierarchy_and_visible_branding(self):
        from renderer.converter.assets import load_asset_image
        task = checks.task(3)
        out = resize(task["source"], task["target_canvas"])
        quality = assess_quality(task["source"], out)
        self.assertGreaterEqual(quality["minimum_rendered_font"], 8)
        self.assertGreaterEqual(quality["primary_text_font"], 12)
        self.assertEqual(quality["readability"], "small_text")
        # Measure rasterized alpha independently of engine visibility scores.
        for identifier, min_width, min_height in [("logo", 50, 28), ("product", 32, 53)]:
            el = next(e for e in out["elements"] if e["id"] == identifier)
            pixels = load_asset_image(str(ROOT / "brand_kit/assets"), el["asset_id"],
                                      el["width"], el["height"], el.get("fit", "contain"))
            left, top, right, bottom = pixels.getchannel("A").point(lambda a: 255 if a >= 8 else 0).getbbox()
            self.assertGreaterEqual(right - left, min_width, identifier)
            self.assertGreaterEqual(bottom - top, min_height, identifier)

    def test_tiny_copy_is_flagged_as_a_quality_failure_even_when_it_fits(self):
        source = awkward_design()
        out = resize(source, dict(width=90, height=728))
        self.assert_contract(source, out)
        quality = assess_quality(source, out)
        self.assertEqual(quality["readability"], "too_small")
        self.assertTrue(quality["text_below_8px"])
        self.assertTrue(any("readability limited" in warning for warning in layout_warnings(source, out)))

    def test_independent_dense_copy_keeps_a_prominent_heading(self):
        source = advanced_design()
        for width, height in [(970, 90), (300, 250)]:
            with self.subTest(target=(width, height)):
                out = resize(source, dict(width=width, height=height))
                self.assert_contract(source, out)
                quality = assess_quality(source, out)
                self.assertGreaterEqual(quality["minimum_rendered_font"], 8)
                self.assertGreaterEqual(quality["primary_text_font"], 12)

    def test_readability_status_is_distinct_from_missing_assets(self):
        source = checks.task(1)["source"]
        out = resize(source, dict(width=1080, height=1350))
        quality = assess_quality(source, out)
        self.assertEqual(quality["readability"], "meets_font_floor")
        self.assertEqual(quality["text_below_12px"], [])
        image = next(e for e in out["elements"] if e["type"] == "image" and e["id"] != "bg")
        image["asset_id"] = "absent-quality-test.png"
        quality = assess_quality(source, out)
        self.assertFalse(next(i for i in quality["images"] if i["id"] == image["id"])["asset_available"])

    def test_narrow_sample_does_not_shrink_already_fitting_text(self):
        task = checks.task(3)
        for w, h in [(90, 728), (160, 600)]:
            with self.subTest(target=(w, h)):
                out = resize(task["source"], dict(width=w, height=h))
                self.assert_contract(task["source"], out)
                self.assertGreaterEqual(_minimum_font(out), 7)

    def test_independent_dense_design_across_extreme_formats(self):
        source = advanced_design()
        original = deepcopy(source)
        for w, h in EXTREME_TARGETS:
            with self.subTest(target=(w, h)):
                out = resize(source, dict(width=w, height=h))
                self.assert_contract(source, out)
                self.assertGreaterEqual(_minimum_font(out), 2)
        self.assertEqual(source, original)

    def test_badge_counts_are_not_fixed(self):
        for count in (1, 5, 11, 23):
            source = advanced_design(badges=count)
            for w, h in [(970, 90), (300, 600)]:
                with self.subTest(badges=count, target=(w, h)):
                    out = resize(source, dict(width=w, height=h))
                    self.assert_contract(source, out)
                    self.assertGreaterEqual(_minimum_font(out), 3)

    def test_long_unbreakable_words_and_explicit_line_limits(self):
        source = awkward_design()
        for w, h in [(970, 90), (160, 600), (300, 250)]:
            with self.subTest(target=(w, h)):
                out = resize(source, dict(width=w, height=h))
                self.assert_contract(source, out)
                self.assertEqual(next(e for e in out["elements"] if e["id"] == "announcement")["content"],
                                 next(e for e in source["elements"] if e["id"] == "announcement")["content"])

    def test_larger_image_collections_use_canvas_height(self):
        source = image_collection()
        out = resize(source, dict(width=1000, height=120))
        self.assert_contract(source, out)
        self.assertGreater(min(e["height"] for e in out["elements"] if e["type"] == "image"), 30)

    def test_level3_ids_and_input_order_do_not_select_the_layout(self):
        task = checks.task(3)
        source, target = task["source"], task["target_canvas"]
        expected = resize(source, target)
        changed = deepcopy(source)
        for i, el in enumerate(changed["elements"]):
            el["id"] = f"different-{i}"
            el.pop("_adversarial_note", None)
        changed["elements"].reverse()
        actual = resize(changed, target)
        for a, b in zip(expected["elements"], reversed(actual["elements"])):
            for field in ("x", "y", "width", "height", "font_size"):
                self.assertAlmostEqual(a.get(field, 0), b.get(field, 0), places=6)

    def test_actual_pixels_fit_in_both_renderers_without_network(self):
        from renderer.converter.convert import render_design_to_png
        from renderer.converter.textlayout import measure_text, text_styles
        task = checks.task(3)
        with TemporaryDirectory() as directory:
            with patch.object(socket.socket, "connect", side_effect=AssertionError("network access")), \
                    patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network access")):
                out = resize(task["source"], task["target_canvas"])
                warnings = render_design_to_png(out, ROOT / "brand_kit/assets", Path(directory) / "all.png")
                self.assertEqual(len(warnings), 1)
                self.assertIn("solstice_holiday_badge_2025.png", warnings[0])
                for el in out["elements"]:
                    if el["type"] == "text":
                        checks.ResizeTests.rendered_ink(self, el, directory)
                        with patch("renderer.converter.convert.measure_text", side_effect=lambda e, m: measure_text(e, m, legacy=True)), \
                                patch("renderer.converter.convert.text_styles", side_effect=lambda e: text_styles(e, inclusive_end=True)):
                            checks.ResizeTests.rendered_ink(self, el, directory)

    def test_awkward_text_pixels_fit(self):
        source = awkward_design()
        with TemporaryDirectory() as directory:
            for w, h in [(970, 90), (160, 600), (300, 250)]:
                out = resize(source, dict(width=w, height=h))
                for el in out["elements"]:
                    if el["type"] == "text":
                        checks.ResizeTests.rendered_ink(self, el, directory)

    def test_rotated_label_ink_stays_centered(self):
        from math import cos, radians, sin
        task = checks.task(3)
        out = resize(task["source"], task["target_canvas"])
        bg = next(e for e in out["elements"] if e["id"] == "ribbon_bg")
        label = next(e for e in out["elements"] if e["id"] == "ribbon_label")
        with TemporaryDirectory() as directory:
            left, top, right, bottom = checks.ResizeTests.rendered_ink(self, label, directory)
        angle = radians(label["rotation"])
        dx = (left + right - label["width"]) / 2
        dy = (top + bottom - label["height"]) / 2
        ink_x = label["x"] + label["width"] / 2 + dx * cos(angle) - dy * sin(angle)
        ink_y = label["y"] + label["height"] / 2 + dx * sin(angle) + dy * cos(angle)
        self.assertAlmostEqual(ink_x, bg["x"] + bg["width"] / 2, delta=1.5)
        self.assertAlmostEqual(ink_y, bg["y"] + bg["height"] / 2, delta=1.5)

    def test_rotated_background_is_also_contained(self):
        source = dict(canvas=dict(width=600, height=800), elements=[
            dict(id="background", type="image", x=0, y=0, width=600, height=800,
                 asset_id="solstice_bg_gradient.png", rotation=18, fit="cover")])
        self.assert_contract(source, resize(source, dict(width=600, height=90)))

    def test_complex_groups_keep_internal_geometry(self):
        source = advanced_design()
        group = [dict(id="card", type="shape", shape_type="rectangle", x=100, y=300,
                      width=400, height=160, fill_color="rgba(80,40,40,1)", rotation=18,
                      group_id="rigid", z_index=3),
                 dict(id="card-line1", type="text", x=130, y=320, width=340, height=50,
                      content="A special preview", font_family="Solstice Sans", font_size=24,
                      color="rgba(255,255,255,1)", rotation=18, group_id="rigid", z_index=4),
                 dict(id="card-line2", type="text", x=130, y=390, width=340, height=40,
                      content="Find something new", font_family="Solstice Sans", font_size=18,
                      color="rgba(255,255,255,1)", rotation=18, group_id="rigid", z_index=4)]
        source["elements"].extend(group)
        out = resize(source, dict(width=970, height=90))
        self.assert_contract(source, out)
        actual = [e for e in out["elements"] if e.get("group_id") == "rigid"]
        scale = actual[0]["width"] / group[0]["width"]
        for a, b in zip(group, actual):
            self.assertAlmostEqual(b["width"], a["width"] * scale)
            self.assertAlmostEqual(b["height"], a["height"] * scale)
            self.assertAlmostEqual(b["x"] - actual[0]["x"], (a["x"] - group[0]["x"]) * scale)
            self.assertAlmostEqual(b["y"] - actual[0]["y"], (a["y"] - group[0]["y"]) * scale)


if __name__ == "__main__":
    unittest.main()
