"""Behavior tests run with: python -m unittest discover -s tests -v."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from engine.resize import _background, _bounds, _composition, _valid, resize


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
        result = resize(source, {"width": 8, "height": 4})
        self.assertEqual([e["id"] for e in source["elements"]], [e["id"] for e in result["elements"]])
        for el in result["elements"]:
            x, y, w, h = _bounds([el])
            self.assertGreaterEqual(x, -1e-6)
            self.assertGreaterEqual(y, -1e-6)
            self.assertLessEqual(x + w, 8 + 1e-6)
            self.assertLessEqual(y + h, 4 + 1e-6)


if __name__ == "__main__":
    unittest.main()
