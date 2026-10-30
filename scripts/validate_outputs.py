"""Validate engine artifacts independently: python scripts/validate_outputs.py."""

import argparse
from collections import Counter
import json
from math import cos, isfinite, radians, sin
from pathlib import Path

from jsonschema import Draft202012Validator
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "chameleon_design_schema_v0.9.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)
MUTABLE = {"x", "y", "width", "height", "font_size", "letter_spacing",
           "corner_radius", "stroke_width", "fit"}


def check_design(task, output, png_path):
    """Return hard failures and separate readability/missing-asset warnings."""
    errors = [f"schema {list(e.path)}: {e.message}" for e in VALIDATOR.iter_errors(output)]
    warnings = []
    if errors:
        return errors, warnings
    source, target = task["source"], task["target_canvas"]
    if output["canvas"] != target:
        errors.append("output canvas does not match the requested target")
    originals = {el["id"]: el for el in source["elements"]}
    if Counter(el["id"] for el in source["elements"]) != Counter(el["id"] for el in output["elements"]):
        errors.append("element IDs/counts differ from the source")

    for el in output["elements"]:
        original = originals.get(el["id"])
        if original is None:
            continue
        for field in original.keys() - MUTABLE:
            if el.get(field) != original[field]:
                errors.append(f"{el['id']}: changed source field {field}")
        numbers = [el[key] for key in ("x", "y", "width", "height")] + [el.get("rotation", 0)]
        if not all(isfinite(n) for n in numbers):
            errors.append(f"{el['id']}: non-finite geometry")
            continue
        x, y, width, height, angle = numbers
        angle = radians(angle)
        half_w = (abs(width * cos(angle)) + abs(height * sin(angle))) / 2
        half_h = (abs(width * sin(angle)) + abs(height * cos(angle))) / 2
        cx, cy = x + width / 2, y + height / 2
        if (cx - half_w < -1e-5 or cy - half_h < -1e-5
                or cx + half_w > target["width"] + 1e-5 or cy + half_h > target["height"] + 1e-5):
            errors.append(f"{el['id']}: rotated bounds extend off-canvas")
        if el["type"] == "image":
            background = (original["x"] == original["y"] == 0
                          and original["width"] == source["canvas"]["width"]
                          and original["height"] == source["canvas"]["height"])
            if not background:
                if original["height"] > 0 and height > 0:
                    old_ratio, new_ratio = original["width"] / original["height"], width / height
                    if abs(new_ratio - old_ratio) > max(1e-5, abs(old_ratio) * 0.05):
                        errors.append(f"{el['id']}: image aspect ratio changed by more than 5%")
                if original.get("fit", "contain") != el.get("fit", "contain"):
                    errors.append(f"{el['id']}: foreground image fit changed")
            if not (ROOT / "brand_kit/assets" / el["asset_id"]).is_file():
                warnings.append(f"{el['id']}: missing asset {el['asset_id']}")
        if el["type"] == "text":
            if not isfinite(el["font_size"]):
                errors.append(f"{el['id']}: non-finite font size")
            elif el["content"].strip() and int(el["font_size"]) < 12:
                warnings.append(f"{el['id']}: small text ({int(el['font_size'])}px rendered)")
    try:
        with Image.open(png_path) as image:
            if image.format != "PNG" or image.size != (target["width"], target["height"]):
                errors.append("PNG format/dimensions do not match the requested target")
            image.verify()
    except (OSError, ValueError) as error:
        errors.append(f"PNG could not be verified: {error}")
    return errors, warnings


def validate_directory(input_dir, output_dir):
    cases = []
    for task_path in sorted(input_dir.glob("*.json")):
        try:
            task = json.loads(task_path.read_text())
            design_path = output_dir / f"{task_path.stem}_output.json"
            output = json.loads(design_path.read_text())
            errors, warnings = check_design(task, output, design_path.with_suffix(".png"))
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors, warnings = [str(error)], []
        cases.append(dict(task=task_path.name, passed=not errors, errors=errors, warnings=warnings))
    return dict(passed=bool(cases) and all(case["passed"] for case in cases), cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("input"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate_directory(args.input, args.output)
    for case in report["cases"]:
        print(f"{case['task']}: {'PASS' if case['passed'] else 'FAIL'}, {len(case['warnings'])} warning(s)")
        for error in case["errors"]:
            print(f"  ERROR: {error}")
        for warning in case["warnings"]:
            print(f"  WARNING: {warning}")
    if not report["cases"]:
        print("FAIL: no input tasks found")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
