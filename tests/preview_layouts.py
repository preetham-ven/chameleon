"""Render the Level 2 sample and independent cases for manual review.

Run: python -m tests.preview_layouts
An optional --before-dir adds existing <case>_<format>.png baseline previews.
"""

import argparse
from html import escape
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from engine.resize import resize
from renderer.converter.convert import render_design_to_png
from tests.layout_cases import layout_cases


ROOT = Path(__file__).resolve().parents[1]
FORMATS = [("wide", 1600, 400), ("square", 1080, 1080), ("portrait", 1080, 1920)]


def review_cases():
    sample = json.loads((ROOT / "input/chameleon_sample_level2_core.json").read_text())["source"]
    return {"sample": sample, **layout_cases()}


def make_sheet(rows, path):
    cell_w, cell_h = 500, 390
    sheet = Image.new("RGB", (cell_w * 3, cell_h * len(rows)), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for row_no, row in enumerate(rows):
        for col, (label, png) in enumerate(row):
            x, y = col * cell_w, row_no * cell_h
            draw.text((x + 12, y + 10), label, fill="black")
            with Image.open(png) as image:
                preview = ImageOps.contain(image.convert("RGB"), (cell_w - 24, cell_h - 44))
                sheet.paste(preview, (x + (cell_w - preview.width) // 2, y + 36 + (cell_h - 44 - preview.height) // 2))
    sheet.save(path)
    make_gallery(rows, path.with_suffix(".html"))


def make_gallery(rows, path):
    """Use a scrollable page so small outputs are not reduced to thumbnails."""
    sections = []
    for row in rows:
        figures = []
        for col, (label, png) in enumerate(row):
            with Image.open(png) as image:
                width, height = image.size
            url = escape(Path(os.path.relpath(png, path.parent)).as_posix(), quote=True)
            kind = "source" if col == 0 else "result"
            figures.append(
                f'<figure class="{kind}"><figcaption>{escape(label)} · {width}×{height}</figcaption>'
                f'<div class="preview"><a href="{url}"><img src="{url}" '
                f'width="{width}" height="{height}" loading="lazy" alt="{escape(label, quote=True)}"></a></div>'
                '</figure>')
        sections.append('<section>' + ''.join(figures) + '</section>')
    path.write_text('''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Layout review at actual size</title>
<style>
body { margin:24px; background:#eee; color:#222; font:15px system-ui,sans-serif; }
section { display:flex; gap:20px; border-top:1px solid #bbb; padding:24px 0; align-items:flex-start; }
figure { margin:0; min-width:0; }
figcaption { margin-bottom:12px; }
.source { flex:0 0 200px; }
.source img { width:auto; height:auto; max-width:200px; max-height:260px; }
.result { flex:1; }
.preview { overflow:auto; padding-bottom:12px; }
.result img { display:block; max-width:none; }
@media(max-width:700px) { section { display:block; } figure { margin-bottom:24px; } }
</style>
<h1>Layout review at actual size</h1>
<p>Outputs are shown at 100% size with browser zoom at 100%. Scroll sideways for wide designs.
Only source thumbnails are reduced. Click any image to open the original PNG.</p>
''' + '\n'.join(sections) + '</html>', encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-dir", type=Path)
    args = parser.parse_args()
    output = ROOT / "output/review"
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, source in review_cases().items():
        source_png = output / f"{name}_source.png"
        render_design_to_png(source, ROOT / "brand_kit/assets", source_png)
        for format_name, w, h in FORMATS:
            resized = resize(source, dict(width=w, height=h))
            stem = output / f"{name}_{format_name}"
            stem.with_suffix(".json").write_text(json.dumps(resized, indent=2))
            png = stem.with_suffix(".png")
            warnings = render_design_to_png(resized, ROOT / "brand_kit/assets", png)
            row = [(f"{name}: source", source_png)]
            before = args.before_dir / png.name if args.before_dir else None
            if before and before.is_file():
                row.append((f"{format_name}: before", before))
            row.append((f"{format_name}: output ({w}x{h})", png))
            rows.append(row)
            print(f"{name}/{format_name}: {png}" + (f"; warnings: {warnings}" if warnings else ""))
    sheet = output / "level2_comparison.png"
    make_sheet(rows, sheet)
    print(f"Comparison sheet: {sheet}")
    print(f"Actual-size previews: {sheet.with_suffix('.html')}")


if __name__ == "__main__":
    main()
