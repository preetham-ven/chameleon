"""Behavior tests run with: python -m unittest discover -s tests -v."""
from copy import deepcopy
from collections import Counter
import json
from math import ceil, cos, isfinite, radians, sin
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from engine.resize import _background, _bounds, _composition, _valid, resize
from tests.layout_cases import TARGETS, layout_cases


ROOT = Path(__file__).resolve().parents[1]


def task(level):
    path = next((ROOT / "input").glob(f"*level{level}_*.json"))
    return json.loads(path.read_text())


class ResizeTests(unittest.TestCase):
    def assert_contract(self, source, output):
        self.assertEqual(len(source["elements"]), len(output["elements"]))
        self.assertEqual([e["id"] for e in source["elements"]], [e["id"] for e in output["elements"]])
        mutable = {"x", "y", "width", "height", "font_size", "corner_radius", "stroke_width", "letter_spacing", "fit"}
        for original, result in zip(source["elements"], output["elements"]):
            for field in original.keys() - mutable:
                self.assertEqual(original[field], result[field], field)
            if original["type"] == "image" and not _background(original, source["canvas"]):
                self.assertAlmostEqual(original["width"] / original["height"], result["width"] / result["height"])
                self.assertEqual(original.get("fit"), result.get("fit"))
        # Calculate bounds independently rather than trusting engine._valid().
        self.assertEqual(Counter(e["id"] for e in source["elements"]), Counter(e["id"] for e in output["elements"]))
        for el in output["elements"]:
            for field in ("x", "y", "width", "height"):
                self.assertTrue(isfinite(el[field]), (el["id"], field))
            self.assertGreaterEqual(el["width"], 0)
            self.assertGreaterEqual(el["height"], 0)
            angle = radians(el.get("rotation", 0))
            half_w = (abs(el["width"] * cos(angle)) + abs(el["height"] * sin(angle))) / 2
            half_h = (abs(el["width"] * sin(angle)) + abs(el["height"] * cos(angle))) / 2
            cx, cy = el["x"] + el["width"] / 2, el["y"] + el["height"] / 2
            self.assertGreaterEqual(cx - half_w, -1e-6, el["id"])
            self.assertGreaterEqual(cy - half_h, -1e-6, el["id"])
            self.assertLessEqual(cx + half_w, output["canvas"]["width"] + 1e-6, el["id"])
            self.assertLessEqual(cy + half_h, output["canvas"]["height"] + 1e-6, el["id"])
            if el["type"] == "text":
                self.assertGreaterEqual(el["font_size"], 1)
        self.assertTrue(_valid(source, output, _composition(source)[2]))

    def test_level1_exact_geometry(self):
        t = task(1)
        original = deepcopy(t)
        result = resize(t["source"], t["target_canvas"])
        sw, sh = t["source"]["canvas"].values()
        tw, th = t["target_canvas"].values()
        scale = min(tw / sw, th / sh)
        for el, out in zip(t["source"]["elements"], result["elements"]):
            if el["x"] == el["y"] == 0 and el["width"] == sw and el["height"] == sh:
                self.assertEqual((out["x"], out["y"], out["width"], out["height"]), (0, 0, tw, th))
            else:
                self.assertEqual(out["x"], el["x"] * scale + (tw - sw * scale) / 2)
                self.assertEqual(out["y"], el["y"] * scale + (th - sh * scale) / 2)
                self.assertEqual(out["width"], el["width"] * scale)
                self.assertEqual(out["height"], el["height"] * scale)
            if el["type"] == "text":
                self.assertEqual(out["font_size"], max(1, el["font_size"] * scale))
        self.assertEqual(original, t)

    def test_core_layouts_and_groups(self):
        t = task(2)
        source = t["source"]
        original = deepcopy(source)
        for target in ({"width": 1600, "height": 400}, {"width": 1080, "height": 1080},
                       {"width": 1080, "height": 1920}, {"width": 1200, "height": 628}):
            with self.subTest(target=target):
                result = resize(source, target)
                self.assert_contract(source, result)
                self.assertEqual(result, resize(source, target))
                self.assertGreaterEqual(min(e["font_size"] for e in result["elements"] if e["type"] == "text"), 12)
                for unit in _composition(source)[2]:
                    if len(unit.indices) < 2:
                        continue
                    members = [result["elements"][i] for i in unit.indices]
                    if {m["type"] for m in members} == {"shape", "text"}:
                        bg = next(m for m in members if m["type"] == "shape")
                        label = next(m for m in members if m["type"] == "text")
                        self.assertGreaterEqual(label["x"], bg["x"])
                        self.assertGreaterEqual(label["y"], bg["y"])
                        self.assertLessEqual(label["x"] + label["width"], bg["x"] + bg["width"] + 1e-6)
                        self.assertLessEqual(label["y"] + label["height"], bg["y"] + bg["height"] + 1e-6)
                        continue
                    a = source["elements"][unit.indices[0]]
                    b = result["elements"][unit.indices[0]]
                    scale = b["width"] / a["width"]
                    for i in unit.indices:
                        member, out = source["elements"][i], result["elements"][i]
                        self.assertAlmostEqual(out["width"], member["width"] * scale)
                        self.assertAlmostEqual(out["height"], member["height"] * scale)
                        self.assertAlmostEqual(out["x"] - b["x"], (member["x"] - a["x"]) * scale)
                        self.assertAlmostEqual(out["y"] - b["y"], (member["y"] - a["y"]) * scale)
        self.assertEqual(source, original)

    def test_ids_notes_and_input_order_do_not_drive_layout(self):
        t = task(2)
        expected = resize(t["source"], t["target_canvas"])
        source = deepcopy(t["source"])
        for i, el in enumerate(source["elements"]):
            el["id"] = f"arbitrary-{i}"
            el.pop("_note", None)
        source["elements"].reverse()
        actual = resize(source, t["target_canvas"])
        for original, changed in zip(expected["elements"], reversed(actual["elements"])):
            for field in ("x", "y", "width", "height", "font_size"):
                self.assertEqual(original.get(field), changed.get(field))

    def test_wrap_newlines_long_words_and_line_cap(self):
        t = task(2)
        source = t["source"]
        texts = [e for e in source["elements"] if e["type"] == "text" and e.get("group_id") is None]
        texts[0].update(content="Golden\nhour", max_lines=2)
        texts[1].update(content="Supercalifragilisticexpialidocious botanical infusions", max_lines=2)
        for e in texts:
            e.pop("style_runs", None)
        result = resize(source, t["target_canvas"])
        self.assert_contract(source, result)

    def test_rotated_image_and_group_envelopes(self):
        t = task(2)
        source = t["source"]
        for el in source["elements"]:
            if el["type"] == "image" and el["x"] != 0:
                el["rotation"] = 25
            elif el.get("group_id") == "badge":
                el["rotation"] = -10
        result = resize(source, t["target_canvas"])
        self.assert_contract(source, result)
        original_group = [e for e in source["elements"] if e.get("group_id") == "badge"]
        actual_group = [e for e in result["elements"] if e.get("group_id") == "badge"]
        scale = actual_group[0]["width"] / original_group[0]["width"]
        for a, b in zip(original_group, actual_group):
            self.assertAlmostEqual(b["width"], a["width"] * scale)
            self.assertAlmostEqual(b["height"], a["height"] * scale)
            self.assertAlmostEqual(b["y"] - actual_group[0]["y"], (a["y"] - original_group[0]["y"]) * scale)

    def test_styled_text_and_additional_units(self):
        t = task(2)
        source = t["source"]
        extra = deepcopy(source["elements"][4])
        extra.update(id="extra-image", x=50, y=500, width=150, height=150, fit="fill")
        source["elements"].append(extra)
        group = deepcopy(source["elements"][-3:-1])
        for i, el in enumerate(group):
            el.update(id=f"extra-group-{i}", group_id="extra", x=50, y=600 + i * 25)
        source["elements"].extend(group)
        for el in source["elements"]:
            if el["type"] == "text":
                el.update(font_style="italic", letter_spacing=0.5, line_height=1.4)
        result = resize(source, {"width": 1920, "height": 1080})
        self.assert_contract(source, result)

    def test_real_rendering_without_network(self):
        from renderer.converter.convert import render_design_to_png
        t = task(2)
        with TemporaryDirectory() as directory:
            with patch.object(socket.socket, "connect", side_effect=AssertionError("network access")), \
                    patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network access")):
                result = resize(t["source"], t["target_canvas"])
                png = Path(directory) / "preview.png"
                warnings = render_design_to_png(result, ROOT / "brand_kit" / "assets", png)
                self.assertEqual(warnings, [])
                self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_tiny_target_retains_elements_and_bounds(self):
        source = task(2)["source"]
        with self.assertLogs("engine.resize", level="WARNING"):
            result = resize(source, {"width": 8, "height": 4})
        self.assertEqual([e["id"] for e in source["elements"]], [e["id"] for e in result["elements"]])
        for el in result["elements"]:
            x, y, w, h = _bounds([el])
            self.assertGreaterEqual(x, -1e-6)
            self.assertGreaterEqual(y, -1e-6)
            self.assertLessEqual(x + w, 8 + 1e-6)
            self.assertLessEqual(y + h, 4 + 1e-6)

    def rendered_ink(self, element, directory):
        """Read actual rendered pixels, independently of layout measurements."""
        from PIL import Image, ImageChops
        from renderer.converter.convert import render_design_to_png
        el = deepcopy(element)
        el.update(x=40, y=40, rotation=0, color="rgba(0,0,0,1)", opacity=1)
        for run in el.get("style_runs") or []:
            run["color"] = "rgba(0,0,0,1)"
        canvas = dict(width=ceil(el["width"]) + 80, height=ceil(el["height"]) + 80)
        png = Path(directory) / "text.png"
        render_design_to_png(dict(canvas=canvas, elements=[el]), ROOT / "brand_kit/assets", png,
                             max_size=max(canvas.values()))
        with Image.open(png) as image:
            pixels = image.convert("RGB")
            box = ImageChops.difference(pixels, Image.new("RGB", pixels.size, "white")).getbbox()
        if box is None:
            self.assertFalse(el["content"].strip())
            return (0, 0, 0, 0)
        box = tuple(value - 40 for value in box)
        self.assertGreaterEqual(box[0], -1, element["id"])
        self.assertGreaterEqual(box[1], -1, element["id"])
        self.assertLessEqual(box[2], el["width"] + 1, element["id"])
        self.assertLessEqual(box[3], el["height"] + 1, element["id"])
        return box

    def assert_no_foreground_collisions(self, source, output):
        groups = {}
        for i, (original, el) in enumerate(zip(source["elements"], output["elements"])):
            if _background(original, source["canvas"]):
                continue
            if el["type"] == "shape" and el.get("group_id") is None:
                continue  # These fixtures' ungrouped shapes are decorations.
            key = ("group", el["group_id"]) if el.get("group_id") else ("single", i)
            # Independent corner calculation for these fixtures' rotated images.
            angle = radians(el.get("rotation", 0))
            w, h = el["width"], el["height"]
            dw = abs(w * cos(angle)) + abs(h * sin(angle))
            dh = abs(w * sin(angle)) + abs(h * cos(angle))
            cx, cy = el["x"] + w / 2, el["y"] + h / 2
            groups.setdefault(key, []).append((cx - dw / 2, cy - dh / 2, cx + dw / 2, cy + dh / 2))
        envelopes = [(min(b[0] for b in boxes), min(b[1] for b in boxes),
                      max(b[2] for b in boxes), max(b[3] for b in boxes)) for boxes in groups.values()]
        for i, a in enumerate(envelopes):
            for b in envelopes[i + 1:]:
                self.assertFalse(min(a[2], b[2]) - max(a[0], b[0]) > 1e-5
                                 and min(a[3], b[3]) - max(a[1], b[1]) > 1e-5)

    def test_independent_designs_across_formats(self):
        for name, source in layout_cases().items():
            untouched = deepcopy(source)
            for w, h in TARGETS:
                with self.subTest(design=name, target=(w, h)):
                    target = dict(width=w, height=h)
                    out = resize(source, target)
                    self.assertEqual(out["canvas"], target)
                    self.assert_contract(source, out)
                    self.assert_no_foreground_collisions(source, out)
                    self.assertEqual(source, untouched)

    def test_rendered_text_and_button_centering(self):
        with TemporaryDirectory() as directory:
            for source in [task(2)["source"], *layout_cases().values()]:
                for w, h in [(1600, 400), (1080, 1920)]:
                    out = resize(source, dict(width=w, height=h))
                    for el in out["elements"]:
                        if el["type"] != "text":
                            continue
                        box = self.rendered_ink(el, directory)
                        group = [e for e in out["elements"] if el.get("group_id")
                                 and e.get("group_id") == el["group_id"]]
                        bg = next((e for e in group if e["type"] == "shape"), None)
                        if bg and not bg.get("rotation", 0):
                            ink_center = el["y"] + (box[1] + box[3]) / 2
                            self.assertAlmostEqual(ink_center, bg["y"] + bg["height"] / 2, delta=1.5)

    def test_style_run_end_is_exclusive(self):
        from renderer.converter.convert import convert_chameleon_to_crello
        from engine.resize import _font_manager
        el = next(e for e in task(2)["source"]["elements"] if e["id"] == "headline")
        el.update(content="ABC", font_weight="regular", style_runs=[dict(start=0, end=1, font_weight="bold")])
        converted, _ = convert_chameleon_to_crello(dict(canvas=dict(width=300, height=100), elements=[el]), _font_manager())
        self.assertEqual(converted["font_bold"][0], [True, False, False])
        el["style_runs"] = [dict(start=1, end=1, font_weight="bold")]
        converted, _ = convert_chameleon_to_crello(dict(canvas=dict(width=300, height=100), elements=[el]), _font_manager())
        self.assertEqual(converted["font_bold"][0], [False, False, False])

    def test_comparable_images_share_a_panel(self):
        source = layout_cases()["products"]
        for w, h in [(1600, 400), (1500, 500), (1920, 600)]:
            with self.subTest(target=(w, h)):
                out = resize(source, dict(width=w, height=h))
                images = [e for e in out["elements"] if e["type"] == "image"]
                centers = [(e["x"] + e["width"] / 2, e["y"] + e["height"] / 2) for e in images]
                self.assertLess(centers[0][0], centers[1][0])
                self.assertAlmostEqual(centers[0][1], centers[1][1], delta=h * 0.05)
                self.assertGreater(min(e["height"] for e in images), h * 0.6)
                heading = next(e for e in out["elements"] if e["id"] == "message")
                body = next(e for e in out["elements"] if e["id"] == "description")
                # Related copy should stay adjacent rather than split by imagery.
                self.assertLess(body["y"] - heading["y"] - heading["height"], h * 0.12)

    def test_padded_images_keep_their_relative_prominence(self):
        source = task(2)["source"]
        out = resize(source, dict(width=1600, height=400))
        scales = [b["width"] / a["width"] for a, b in zip(source["elements"], out["elements"])
                  if a["type"] == "image" and not _background(a, source["canvas"])]
        # A small logo must not be inflated to match the product's prominence.
        self.assertGreater(min(scales) / max(scales), 0.8)

    def test_nearby_valid_composition_keeps_its_columns(self):
        source = layout_cases()["editorial"]
        out = resize(source, dict(width=1080, height=1080))
        scale, offset_y = 1.08, 108
        for original, actual in zip(source["elements"], out["elements"]):
            if original["type"] not in ("text", "image") or original.get("group_id"):
                continue
            self.assertAlmostEqual(actual["x"], original["x"] * scale)
            self.assertAlmostEqual(actual["y"], original["y"] * scale + offset_y)
            self.assertAlmostEqual(actual["width"], original["width"] * scale)

    def test_styled_long_word_fits_both_converter_versions(self):
        from renderer.converter.textlayout import measure_text, text_styles
        source = task(2)["source"]
        headline = next(e for e in source["elements"] if e["id"] == "headline")
        headline.update(content="i" * 90, font_weight="regular",
                        style_runs=[dict(start=0, end=90, font_weight="bold")])
        out = resize(source, dict(width=1600, height=400))
        self.assert_contract(source, out)
        with TemporaryDirectory() as directory:
            for el in out["elements"]:
                if el["type"] == "text":
                    self.rendered_ink(el, directory)
                    with patch("renderer.converter.convert.measure_text", side_effect=lambda e, m: measure_text(e, m, legacy=True)), \
                            patch("renderer.converter.convert.text_styles", side_effect=lambda e: text_styles(e, inclusive_end=True)):
                        self.rendered_ink(el, directory)

    def test_visible_image_bounds_match_real_asset_fitting(self):
        from engine.resize import _visible_bounds
        from renderer.converter.assets import load_asset_image
        for asset in ("solstice_bottle.png", "solstice_logo_lockup.png"):
            for fit in ("contain", "cover", "fill"):
                with self.subTest(asset=asset, fit=fit):
                    el = dict(id="any", type="image", asset_id=asset, fit=fit,
                              x=0, y=0, width=350, height=170)
                    # Ignore the almost transparent halo introduced by Lanczos.
                    alpha = load_asset_image(str(ROOT / "brand_kit/assets"), asset, 350, 170, fit).getchannel("A")
                    actual = alpha.point(lambda value: 255 if value >= 8 else 0).getbbox()
                    x, y, w, h = _visible_bounds(el)
                    for measured, rendered in zip((x, y, x + w, y + h), actual):
                        self.assertAlmostEqual(measured, rendered, delta=2)

    def test_missing_assets_and_small_text_are_reported(self):
        from engine.main import render_to_png, self_check
        from engine.resize import layout_warnings
        source = task(2)["source"]
        out = resize(source, dict(width=728, height=90))
        self.assertTrue(any("small" in warning for warning in layout_warnings(source, out)))
        el = next(e for e in out["elements"] if e["type"] == "image")
        el["asset_id"] = "missing-test-asset.png"
        with TemporaryDirectory() as directory:
            warnings = render_to_png(out, ROOT / "brand_kit/assets", Path(directory) / "preview.png")
            self.assertTrue(any("missing-test-asset.png" in warning for warning in warnings))
        duplicate = deepcopy(out)
        duplicate["elements"].append(deepcopy(out["elements"][0]))
        self.assertTrue(any("counts differ" in warning for warning in self_check(source, duplicate)))

    def test_background_only_and_empty_text(self):
        source = dict(canvas=dict(width=500, height=500), elements=[
            dict(id="background", type="shape", shape_type="rectangle", x=0, y=0,
                 width=500, height=500, fill_color="rgba(0,0,0,1)")])
        self.assert_contract(source, resize(source, dict(width=1200, height=300)))
        source["elements"].append(dict(id="empty", type="text", x=50, y=50, width=100, height=50,
                                       font_family="Solstice Sans", font_size=24, content="", color="rgba(0,0,0,1)"))
        self.assert_contract(source, resize(source, dict(width=1200, height=300)))


if __name__ == "__main__":
    unittest.main()
