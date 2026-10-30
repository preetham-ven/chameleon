"""Check exported dimensions and compositing against actual PNG pixels."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image, ImageChops

from renderer.converter.convert import render_design_to_png


ROOT = Path(__file__).resolve().parents[1]


class RenderingTests(unittest.TestCase):
    def render(self, elements, size=(100, 60), max_size=None, assets=None):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "test.png"
            render_design_to_png(
                dict(canvas=dict(width=size[0], height=size[1]), elements=elements),
                assets or ROOT / "brand_kit/assets", path,
                fonts_dir=ROOT / "brand_kit/fonts", max_size=max_size)
            with Image.open(path) as image:
                return image.convert("RGB")

    def test_export_keeps_requested_resolution(self):
        for size in [(2560, 100), (100, 2560)]:
            with self.subTest(size=size):
                self.assertEqual(self.render([], size).size, size)
                self.assertEqual(self.render([], size, max_size=1280).size,
                                 tuple(n // 2 for n in size))

    def test_contained_image_keeps_transparency_and_color(self):
        with TemporaryDirectory() as directory:
            Image.new("RGBA", (10, 10), (255, 0, 0, 128)).save(Path(directory) / "alpha.png")
            element = dict(id="image", type="image", x=0, y=0, width=100, height=60,
                           asset_id="alpha.png", fit="contain", opacity=0.5)
            result = self.render([element], assets=Path(directory))
            self.assertEqual(result.getpixel((0, 30)), (255, 255, 255))
            for actual, expected in zip(result.getpixel((50, 30)), (255, 191, 191)):
                self.assertAlmostEqual(actual, expected, delta=1)

    def test_text_opacity_applies_to_default_and_styled_colors(self):
        element = dict(id="label", type="text", x=5, y=5, width=90, height=50,
                       content="Hi", font_family="Solstice Sans", font_size=30,
                       color="rgba(0,0,0,1)",
                       style_runs=[dict(start=1, end=2, color="rgba(255,0,0,1)")])
        invisible = self.render([{**element, "opacity": 0}])
        self.assertIsNone(ImageChops.difference(invisible, Image.new("RGB", invisible.size, "white")).getbbox())
        faded = self.render([{**element, "opacity": 0.5}])
        green_min = faded.getchannel("G").getextrema()[0]
        self.assertGreaterEqual(green_min, 126)
        self.assertLess(green_min, 140)

    def test_shapes_keep_separate_fill_stroke_and_element_alpha(self):
        for shape in ("rectangle", "ellipse"):
            with self.subTest(shape=shape):
                element = dict(id="outline", type="shape", shape_type=shape,
                               x=0, y=0, width=100, height=60, fill_color="rgba(255,0,0,0)",
                               stroke_color="rgba(0,0,0,0.5)", stroke_width=4, opacity=0.5)
                result = self.render([element])
                self.assertEqual(result.getpixel((50, 30)), (255, 255, 255))
                for value in result.getpixel((50, 1)):
                    self.assertAlmostEqual(value, 191, delta=1)

    def test_line_uses_stroke_alpha_instead_of_fill_alpha(self):
        element = dict(id="line", type="shape", shape_type="line", x=0, y=0,
                       width=100, height=60, fill_color="rgba(0,0,0,0)",
                       stroke_color="rgba(255,0,0,1)", stroke_width=4)
        self.assertEqual(self.render([element]).getpixel((50, 30)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
