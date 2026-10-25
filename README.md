# CHAMELEON — starter repo

This is the scaffolding for your engine. It handles input loading, output
writing, rendering, and Docker packaging — so the only file you need to
edit is **`engine/resize.py`**.

```
input:  a task JSON (source design + target canvas)
              |
              v
        engine/resize.py   <-- YOU IMPLEMENT THIS
              |
              v
output: <task>_output.json  (schema-valid resized design)
        <task>_output.png   (rendered preview)
```

Both the JSON and the PNG are what get evaluated — see `RULES.md`.



## Repo layout

```
engine/
  resize.py        <- implement your approach here
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
pip install -r requirements.txt
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

Complex and rotated groups retain their internal geometry. Simple unrotated
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
Level 3 optimization is not included.

Run the local regression suite with the installed renderer dependencies.
These are our regression tests, not the challenge's official evaluator:

```bash
python -m unittest discover -s tests -v
```

The suite includes independently constructed image-heavy and text-heavy
designs across six target sizes, rendered-pixel text-fit and button-centering
checks, complex groups, rotations, styled copy, and offline rendering.

Generate previews of the Level 2 sample and the independent designs for
manual visual review:

```bash
python -m tests.preview_layouts
open output/review/level2_comparison.png
```

The sheet shows each source alongside its wide, square, and portrait results.
Individual previews and JSONs also appear in `output/review/`.

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
placeholder. If you ever see plain labeled boxes instead of real text and
images in `output/*.png`, that means the import in `main.py` failed (e.g.
`cr-renderer` didn't install — check `requirements.txt` installed cleanly)
and it fell back to the box-and-label placeholder with a warning; don't judge
your layout quality by that fallback.

## Docker (how you'll actually be run)

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .
docker run --rm --network none \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  my-chameleon-engine
```

`--network none` matches how stage-one scoring runs: everything your
engine needs must be installed at **build** time (add it to
`requirements.txt`), not fetched at run time. If you're using a locally
hosted model, bake its weights into the image during the build step.

## See also

- `chameleon_design_schema_v0.9.json` — full input/output field spec
- `RULES.md` — what's checked, what's graded, and what disqualifies a submission
- FAQ — for anything not covered above
