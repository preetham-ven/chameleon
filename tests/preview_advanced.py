"""Render Level 3 examples and a comparison sheet: python -m tests.preview_advanced."""

import argparse
import json
from pathlib import Path

from engine.resize import _minimum_font, layout_warnings, resize
from engine.quality import assess_quality
from renderer.converter.convert import render_design_to_png
from tests.advanced_cases import advanced_design, awkward_design
from tests.preview_layouts import ROOT, make_sheet


FORMATS = [("leaderboard", 728, 90), ("wide", 970, 90), ("mobile", 320, 50),
           ("skyscraper", 160, 600), ("portrait", 90, 728), ("card", 300, 250)]


def review_cases():
    sample = json.loads((ROOT / "input/chameleon_sample_level3_advanced.json").read_text())["source"]
    return {"sample": sample, "dense": advanced_design(),
            "many_badges": advanced_design(badges=11), "awkward": awkward_design()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-dir", type=Path)
    args = parser.parse_args()
    output = ROOT / "output/level3_review"
    output.mkdir(parents=True, exist_ok=True)
    rows, report = [], []
    for name, source in review_cases().items():
        source_png = output / f"{name}_source.png"
        render_design_to_png(source, ROOT / "brand_kit/assets", source_png)
        for label, w, h in FORMATS:
            out = resize(source, dict(width=w, height=h))
            stem = output / f"{name}_{label}"
            stem.with_suffix(".json").write_text(json.dumps(out, indent=2))
            warnings = render_design_to_png(out, ROOT / "brand_kit/assets", stem.with_suffix(".png"))
            warnings += layout_warnings(source, out)
            quality = assess_quality(source, out)
            row = [(f"{name}: source", source_png)]
            before = args.before_dir / stem.with_suffix(".png").name if args.before_dir else None
            if before and before.is_file():
                row.append((f"{label}: before", before))
            row.append((f"{label}: {quality['readability']} ({w}x{h}, min {_minimum_font(out)}px)", stem.with_suffix(".png")))
            rows.append(row)
            report.append(dict(design=name, width=w, height=h, elements=len(out["elements"]),
                               minimum_rendered_font=_minimum_font(out), quality=quality, warnings=warnings))
            print(f"{name}/{label}: {quality['readability']}, min {_minimum_font(out)}px, {len(warnings)} warning(s)", flush=True)
    make_sheet(rows, output / "level3_comparison.png")
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print(f"Previews and report: {output}")
    print(f"Actual-size previews: {output / 'level3_comparison.html'}")


if __name__ == "__main__":
    main()
