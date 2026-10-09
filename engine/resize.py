"""
THIS IS THE FILE YOU IMPLEMENT.

Everything else in this repo (input loading, output writing, rendering,
the Dockerfile) is plumbing so you can focus on exactly one function:
`resize()`. See RULES.md and the design schema for the full contract.
"""

from copy import deepcopy
from typing import Any


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """
    Args:
        source: {"canvas": {"width": int, "height": int}, "elements": [...]}
                 — the design at its original size. See
                 chameleon_design_schema_v0.9.json for the full element spec
                 (text / image / shape, position, size, rotation, opacity,
                 z_index, group_id, and type-specific fields).
        target_canvas: {"width": int, "height": int} — the shape you're
                 resizing into.

    Returns:
        A design dict with the SAME shape as `source`:
        {"canvas": target_canvas, "elements": [...]}

        Hard requirements (see RULES.md for the full list):
        - Every element `id` in `source` must appear exactly once in your
          output. Do not add, remove, or invent elements.
        - Do not regenerate or redraw any asset's pixel content — you are
          repositioning and resizing the elements you were given, nothing
          more. This is a disqualifying rule, not a style preference.
        - Non-background image elements should be kept in proportion
          (matching the source aspect ratio within ~5%) unless they are a
          full-bleed / `fit: "cover"` element, which is expected to crop.
        - `font_size` may change to help text fit. `font_family` and
          `content` should not, for this stage of scoring (see RULES.md,
          "Adaptive typography and copy").
        - Nothing should end up outside `target_canvas`'s bounds.

    Level 1 approach: scale the source composition proportionally and
    center it on the target canvas, with full-canvas backgrounds filling
    the target. This preserves the layout rather than reflowing it.
    """

    source_width = source["canvas"]["width"]
    source_height = source["canvas"]["height"]
    target_width = target_canvas["width"]
    target_height = target_canvas["height"]
    scale = min(target_width / source_width, target_height / source_height)
    offset_x = (target_width - source_width * scale) / 2
    offset_y = (target_height - source_height * scale) / 2

    out_elements = deepcopy(source["elements"])
    for el in out_elements:
        # Only non-text elements covering the source canvas are backgrounds.
        is_background = (
            el["type"] in ("image", "shape")
            and el["x"] == 0
            and el["y"] == 0
            and el["width"] == source_width
            and el["height"] == source_height
        )
        if is_background:
            el["x"], el["y"] = 0, 0
            el["width"], el["height"] = target_width, target_height
            if el["type"] == "image":
                el["fit"] = "cover"
        else:
            el["x"] = el["x"] * scale + offset_x
            el["y"] = el["y"] * scale + offset_y
            el["width"] *= scale
            el["height"] *= scale

        if el["type"] == "text":
            el["font_size"] = max(1.0, el["font_size"] * scale)
        for field in ("corner_radius", "stroke_width", "letter_spacing"):
            if field in el:
                el[field] *= scale

    return {
        "canvas": {"width": target_width, "height": target_height},
        "elements": out_elements,
    }
