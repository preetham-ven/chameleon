"""The submission checker must catch bad artifacts, not only successful runs."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from scripts.validate_outputs import check_design, validate_directory


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.png = Path(self.directory.name) / "result.png"
        Image.new("RGB", (100, 100), "white").save(self.png)
        self.design = dict(canvas=dict(width=100, height=100), elements=[
            dict(id="copy", type="text", x=20, y=20, width=60, height=30,
                 font_family="Solstice Sans", font_size=18, content="Hello", color="rgba(0,0,0,1)")])
        self.task = dict(source=deepcopy(self.design), target_canvas=dict(width=100, height=100))

    def test_valid_artifacts_pass_and_small_text_is_a_warning(self):
        self.assertEqual(check_design(self.task, self.design, self.png), ([], []))
        self.design["elements"][0]["font_size"] = 5
        errors, warnings = check_design(self.task, self.design, self.png)
        self.assertEqual(errors, [])
        self.assertTrue(any("small text" in warning for warning in warnings))

    def test_rewritten_copy_and_duplicate_ids_fail(self):
        self.design["elements"][0]["content"] = "Changed"
        self.design["elements"].append(deepcopy(self.design["elements"][0]))
        errors, _ = check_design(self.task, self.design, self.png)
        self.assertTrue(any("content" in error for error in errors))
        self.assertTrue(any("IDs/counts" in error for error in errors))

    def test_rotated_overflow_and_wrong_resolution_fail(self):
        self.task["source"]["elements"][0]["rotation"] = 45
        self.design["elements"][0].update(x=0, y=0, rotation=45)
        Image.new("RGB", (50, 50), "white").save(self.png)
        errors, _ = check_design(self.task, self.design, self.png)
        self.assertTrue(any("off-canvas" in error for error in errors))
        self.assertTrue(any("dimensions" in error for error in errors))

    def test_invalid_schema_and_empty_input_fail(self):
        del self.design["elements"][0]["font_family"]
        errors, _ = check_design(self.task, self.design, self.png)
        self.assertTrue(any("schema" in error for error in errors))
        self.assertFalse(validate_directory(Path(self.directory.name), Path(self.directory.name))["passed"])


if __name__ == "__main__":
    unittest.main()
