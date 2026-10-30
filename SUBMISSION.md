# Stage-one submission

This package contains the CHAMELEON resizing engine, its renderer integration,
the supplied brand assets/fonts, sample inputs, Dockerfile, and run instructions.
It follows sections 5.1 and 7.3 of the final challenge brief: the full Express
add-on, pitch, and demo video belong to the finale, not this initial submission.
The older starter FAQ's viewer requirement differs from that final brief.

## Run the engine

From the extracted `chameleon` directory, with Docker running:

```bash
docker build --platform linux/amd64 -t chameleon-submission:stage1 .
docker run --rm --platform linux/amd64 --network none \
  -v "$(pwd)/input:/app/input:ro" \
  -v "$(pwd)/output:/app/output" \
  chameleon-submission:stage1
```

Place task JSON files in `input/`. Each task produces
`output/<task>_output.json` and `output/<task>_output.png` at the requested
canvas dimensions. No network access, API keys, model weights, or GPU are
needed at runtime. The build downloads dependencies; the run is offline.

## Approach

The engine treats groups as layout units and measures text with the supplied
brand fonts. It compares proportional, column, row, image-panel, and grid
arrangements. For dense designs, it considers tighter badges, variable column
widths, full-width small print, and image sizes based on visible alpha bounds.
The source's larger text gets priority when spending spare space. The engine
preserves every element ID, text string, font family, and asset reference.
It does not regenerate or replace imagery. Image files remain unchanged.

The Python base image is pinned by digest; the renderer Git revision and Python
dependency versions are pinned in `requirements.txt` and `constraints.txt`.

## Verification record

The archive's `examples/` folder contains the outputs produced inside the
Linux/AMD64 container, the build/run logs, test log, and JSON validation report.
`examples/environment.json` records the image ID, test count, network setting,
and SHA-256 hashes of the verified source files. `MANIFEST.sha256.json` lists
the hashes of the packaged files.

The checks cover the official JSON schema, requested PNG dimensions, element
IDs/counts, unchanged copy/fonts/assets, rotated bounds, image aspect ratios,
rendered text fitting, groups, transparency, offline rendering, and independent
designs at multiple target sizes. These are local regression checks, not the
official hidden evaluator or a prediction of its visual score.

To reproduce all checks and build a fresh archive (Python 3.11 recommended):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/verify_submission.py
python scripts/package_submission.py
```

The verifier builds a separate test image so test-only tools are not needed in
the production image. Both the sample run and the regression tests execute with
`--network none`. Packaging refuses a failed verification or changed source.

## Known limitations

- Dense Level 3 designs can still require small text, especially in tiny banners
  or when long words cannot wrap. Readability warnings are intentionally kept.
- The Level 3 sample deliberately references the absent
  `solstice_holiday_badge_2025.png`. It remains a labeled placeholder; no substitute
  asset is generated.
- The supplied font set has no Solstice Serif bold-italic face. The renderer
  reports its fallback to the available bold face when that style is requested.
- Linux Skia may emit a non-fatal Fontconfig configuration warning. Brand fonts
  are loaded explicitly from the supplied files; rendered-pixel tests check them.
- Layout choices can differ slightly across operating systems due to font
  rasterization. The packaged verification uses the target Linux container.

The source ZIP excludes virtual environments, Git history, personal configuration,
caches, and intermediate layout experiments. Upload `chameleon-stage1.zip` through
the organizers' submission channel when requested; no submission has been sent
automatically.
