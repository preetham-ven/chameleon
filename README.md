# CHAMELEON — offline layout engine

Stage-one submission: a deterministic engine that rearranges existing design
elements for a requested canvas. It runs offline without a model, API key, or
external service. It preserves copy, font families, element IDs, and image assets.
See [SUBMISSION.md](SUBMISSION.md) for the validation record and handoff instructions.

This repo handles input loading, output writing, rendering, and Docker packaging.
The layout engine lives in **`engine/resize.py`**, with small packing helpers in
`engine/packing.py` and shared font measurements in the renderer converter.

```
input:  a task JSON (source design + target canvas)
              |
              v
        engine/resize.py   (layout selection and fitting)
              |
              v
output: <task>_output.json  (schema-valid resized design)
        <task>_output.png   (rendered preview)
```

Both the JSON and the PNG are what get evaluated — see `RULES.md`.



## Repo layout

```
engine/
  resize.py        <- layout selection, placement, and font fitting
  packing.py       <- rectangle packing, label rows, and balanced columns
  quality.py       <- native-size readability and visible-artwork diagnostics
  main.py           <- orchestrator (input -> resize() -> output). Don't need to edit this.
renderer/           <- the real renderer (transformer-convertor + cr-renderer), already vendored
brand_kit/
  assets/           <- image files referenced by asset_id in the sample designs
  fonts/            <- font files matching the schema's font_family values
input/               <- drop task JSON files here for local testing (3 samples included)
output/              <- results land here
chameleon_design_schema_v0.9.json   <- full field-by-field spec for the design format
Dockerfile
RULES.md
```

## Quick start (no Docker needed for iterating on `resize()`)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m engine.main
```

This processes every `*.json` file in `input/` (the 3 sample designs are
already there — one per difficulty level) and writes an `_output.json` and
`_output.png` for each into `output/`.

The engine preserves the **Level 1 proportional layout** for simple designs
resized to nearby aspect ratios: foreground elements scale uniformly and
remain centered, while backgrounds fill the canvas. Complex nearby resizes
also retain their composition when it remains readable and collision-free;
simple label groups can still be compacted and centered.

For **Level 2**, it compares proportional, horizontal, vertical, grid,
featured-image, and image-panel layouts. A featured-image layout requires a
clearly dominant source image; comparable images can share a row or grid.
The engine reads transparent image bounds to judge visible prominence while
keeping the full image boxes on-canvas. It never crops away transparent padding
or modifies asset pixels.

The standard search keeps complex and rotated groups together through uniform
scaling. Simple unrotated
rectangle-and-label groups can become more compact, with their lettering
centered vertically using real glyph bounds. Text uses local brand fonts,
style runs, letter spacing, wrapping, and line limits. The engine checks text
against both the corrected local converter and the original converter's
wrapping/style-range behavior. The shared measurements live in
`renderer/converter/textlayout.py`.

Low-opacity decorative shapes retain their layering and are brought inside
the target. Candidate selection balances readability, source hierarchy,
visible image prominence, spacing, and source ordering. It uses no network
or model at runtime and never changes copy, font families, or image assets.

The layout rules use geometry and grouping, rather than sample IDs or target
resolutions. Extremely small targets use a best-effort proportional fallback;
text may be tiny or unable to fit, and foreground collisions may remain.

For **Level 3**, layouts whose text is still below the readability floor try
a measured compact search. Long copy flows into ordered, balanced columns;
variable-count badges wrap into rows; images and rigid groups pack into a side
or top rail. Simple rotated rectangle-and-label groups can lose excess padding
while keeping their original angle. Complex groups still scale uniformly.
Image-only designs can use an adaptive row/grid rather than a fixed column count.

Column widths also follow copy length and source font prominence. Small final
paragraphs can span a full-width footer instead of consuming a reading column.
Spare text space goes to the most prominent source copy first, instead of
enlarging every paragraph together. Dense buttons use tighter padding.
Image sizing tries both the full source box
and the visible alpha bounds, so transparent padding does not automatically
make branding tiny; the complete asset remains uncropped and on-canvas.

The compact search checks integer readability floors from 12 px down to 1 px.
When the best floor is above 8 px, it also compares one lower floor, allowing
at most a 1 px trade for clearer primary text and larger visible artwork.
It never makes that trade below 8 px. If no layout reaches 8 px, it keeps the
largest floor it found and reports the readability limit. Primary text is
inferred from source font sizes, not element IDs. Missing image references survive
and render through the existing placeholder behavior, but receive no image-
prominence reward. No text, elements, or assets are dropped or rewritten.
Very small canvases with long copy still require small text; warnings report
these limitations rather than claiming that every layout is comfortably readable.

Run the local regression suite with the installed renderer dependencies.
These are our regression tests, not the challenge's official evaluator:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The suite includes independently constructed image-heavy and text-heavy
designs across six target sizes, rendered-pixel text-fit and button-centering
checks, complex groups, rotations, styled copy, and offline rendering.
Pixel tests also check native export resolution, image transparency,
text opacity, and independent shape fill/stroke colors and opacity.

Generate previews of the Level 2 sample and the independent designs for
manual visual review:

```bash
python -m tests.preview_layouts
open output/review/level2_comparison.html
```

The page shows outputs at their actual pixel size with scrollbars for wide
designs, alongside reduced source thumbnails. A PNG contact sheet, individual
previews, and JSONs also appear in `output/review/`. The contact sheet reduces
images to fit; use the HTML page or individual PNGs to judge readability.

For Level 3, generate the supplied sample plus independent dense/awkward designs
at six extreme formats, including wide banners and narrow portrait canvases:

```bash
python -m tests.preview_advanced
open output/level3_review/level3_comparison.html
```

`output/level3_review/report.json` records element counts, minimum rendered font
sizes, and warnings. Its `quality` field distinguishes `too_small` (below 8 px),
`small_text` (8–11 px), and `meets_font_floor` (12 px or larger). It also records
primary text size and visible artwork dimensions. These are local diagnostics:
meeting a font floor is not a guarantee of visual quality. The regression suite
also covers variable badge counts,
larger image collections, unchanged copy, rigid groups, and actual rendered text
under both the corrected and original converter behavior.

## What the self-check does (and doesn't do)

`main.py` runs a quick structural check after every task — same element
`id`s as the source, required fields present, nothing off-canvas. **This
is not the official scorer.** It exists to catch obvious mistakes before
you waste a submission on them. See `RULES.md` for what's actually
checked and graded.

A warning does not fail the run — your JSON and PNG are still written either
way. Warnings now include text that cannot fit, fonts below the soft 12 px
readability floor, foreground collisions, and missing renderer assets. Read
any warning before accepting an output. The Level 2
engine brings the sample's intentionally corner-bleeding decorative circle
inside the target, so its resized output should not produce that warning.

## The renderer

`main.py` calls `renderer/converter/convert.py`'s `render_design_to_png()`
(a vendored copy of `transformer-convertor`, wrapping `cr-renderer`) to
produce each task's PNG — already wired in, no setup needed. It reads
fonts/assets from `brand_kit/` and writes a real rendered preview, not a
placeholder. Exports use the requested canvas dimensions, including sizes
above 2,048 pixels; callers can explicitly request a smaller `max_size` for
thumbnails. If you ever see plain labeled boxes instead of real text and
images in `output/*.png`, that means the import in `main.py` failed (e.g.
`cr-renderer` didn't install — check `requirements.txt` installed cleanly)
and it fell back to the box-and-label placeholder with a warning; don't judge
your layout quality by that fallback.

## Docker (how you'll actually be run)

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .
docker run --rm --platform linux/amd64 --network none \
  -v "$(pwd)/input:/app/input:ro" \
  -v "$(pwd)/output:/app/output" \
  my-chameleon-engine
```

`--network none` matches how stage-one scoring runs: everything your
engine needs must be installed at **build** time (add it to
`requirements.txt`), not fetched at run time. If you're using a locally
hosted model, bake its weights into the image during the build step.

The base image, Pillow, Skia, and the renderer Git revision are pinned.
`constraints.txt` records the tested Linux dependency versions.
The final challenge PDF places the full Express add-on, pitch, and demo video
in the finale. This package is for stage one; the older viewer requirement in
the starter `FAQ.md` differs from the final brief.

To validate an existing run independently:

```bash
python scripts/validate_outputs.py --input input --output output
```

The validator checks the official design schema plus content, aspect ratios,
rotated bounds, and the PNG dimensions. Install `requirements-dev.txt` to use it.
Readability warnings remain visible even when those structural checks pass.

To build and test the Docker image, then package the verified source:

```bash
python scripts/verify_submission.py
python scripts/package_submission.py
```

The archive is written to `dist/chameleon-stage1.zip` with sample outputs and
verification logs. Packaging requires a successful verification of the current
source files.

## See also

- `chameleon_design_schema_v0.9.json` — full input/output field spec
- `RULES.md` — what's checked, what's graded, and what disqualifies a submission
- FAQ — for anything not covered above
