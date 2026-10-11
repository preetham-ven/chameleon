"""
THIS IS THE FILE YOU IMPLEMENT.

Everything else in this repo (input loading, output writing, rendering,
the Dockerfile) is plumbing so you can focus on exactly one function:
`resize()`. See RULES.md and the design schema for the full contract.
"""

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from math import cos, radians, sin
from pathlib import Path
from typing import Any


def _proportional(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
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
            and el.get("group_id") is None
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


# Layout units retain input indices so output order and arbitrary IDs survive.
@dataclass
class _Unit:
    indices: list[int]
    bounds: tuple[float, float, float, float]
    image: bool


def _bounds(elements):
    """Axis-aligned envelope including rotation about each element's center."""
    boxes = []
    for el in elements:
        angle = radians(el.get("rotation", 0))
        w, h = el["width"], el["height"]
        rw = abs(w * cos(angle)) + abs(h * sin(angle))
        rh = abs(w * sin(angle)) + abs(h * cos(angle))
        cx, cy = el["x"] + w / 2, el["y"] + h / 2
        boxes.append((cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2))
    x, y = min(b[0] for b in boxes), min(b[1] for b in boxes)
    return x, y, max(b[2] for b in boxes) - x, max(b[3] for b in boxes) - y


def _background(el, canvas):
    return (el["type"] in ("image", "shape") and el["x"] == el["y"] == 0
            and el["width"] == canvas["width"] and el["height"] == canvas["height"])


def _composition(source):
    backgrounds, decorations, buckets = [], [], {}
    foreground_z = [e.get("z_index", 0) for e in source["elements"]
                    if e["type"] in ("image", "text") and not _background(e, source["canvas"])]
    for i, el in enumerate(source["elements"]):
        if _background(el, source["canvas"]) and el.get("group_id") is None:
            backgrounds.append(i)
        elif (el["type"] == "shape" and el.get("group_id") is None
              and el.get("opacity", 1) <= 0.25 and foreground_z
              and el.get("z_index", 0) < max(foreground_z)):
            decorations.append(i)
        else:
            key = ("group", el["group_id"]) if el.get("group_id") is not None else ("single", i)
            buckets.setdefault(key, []).append(i)
    units = []
    for indices in buckets.values():
        members = [source["elements"][i] for i in indices]
        units.append(_Unit(indices, _bounds(members), all(e["type"] == "image" for e in members)))
    units.sort(key=lambda u: (u.bounds[1], u.bounds[0], u.indices[0]))
    return backgrounds, decorations, units


@lru_cache(maxsize=1)
def _font_manager():
    from renderer.converter.brand_fonts import load_brand_font_manager
    return load_brand_font_manager(str(Path(__file__).resolve().parents[1] / "brand_kit" / "fonts"))


@lru_cache(maxsize=512)
def _advances(family, weight, style, content):
    from renderer.converter.wrap import char_widths
    return tuple(char_widths(_font_manager(), family, weight, style, 1.0, content))


def _text_widths(el, size):
    bold = el.get("font_weight", "regular") == "bold"
    italic = el.get("font_style", "normal") == "italic"
    style = "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"
    return [a * size for a in _advances(el["font_family"], el.get("font_weight", "regular"), style, el["content"])]


def _text_fits(el, size):
    """Use the same glyph advances and wrapping as the official converter."""
    from renderer.converter.wrap import wrap_text
    content = el["content"]
    if not content:
        return True
    widths = _text_widths(el, size)
    # The converter wraps using advances only; also check rendered spacing.
    wrapped = wrap_text(content, widths, el["width"])
    lines = wrapped.split("\n")
    if el.get("max_lines") is not None and len(lines) > el["max_lines"]:
        return False
    if len(lines) * size * el.get("line_height", 1.2) > el["height"] + 1e-6:
        return False
    start = 0
    for line in lines:
        width = sum(widths[start:start + len(line)])
        width += max(0, len(line) - 1) * el.get("letter_spacing", 0)
        if width > el["width"] + 1e-6:
            return False
        start += len(line) + 1
    return True


def _fit_font(el, maximum):
    low, high = 1.0, max(1.0, maximum)
    for _ in range(18):
        mid = (low + high) / 2
        if _text_fits(el, mid):
            low = mid
        else:
            high = mid
    el["font_size"] = low


def _scale_member(el, scale, dx, dy):
    el["x"], el["y"] = el["x"] * scale + dx, el["y"] * scale + dy
    el["width"] *= scale
    el["height"] *= scale
    for field in ("font_size", "corner_radius", "stroke_width", "letter_spacing"):
        if field in el:
            el[field] *= scale
    if el["type"] == "text":
        el["font_size"] = max(1.0, el["font_size"])


def _place(unit, elements, region, type_scale):
    x, y, w, h = region
    ux, uy, uw, uh = unit.bounds
    if len(unit.indices) == 1:
        el = elements[unit.indices[0]]
        if el["type"] == "text" and el.get("rotation", 0) == 0:
            original_size = el["font_size"]
            el.update(x=x, y=y, width=w, height=h)
            if "letter_spacing" in el:
                el["letter_spacing"] *= type_scale
            _fit_font(el, original_size * type_scale)
            return
    scale = min(w / max(uw, 1e-9), h / max(uh, 1e-9))
    dx, dy = x + (w - uw * scale) / 2 - ux * scale, y + (h - uh * scale) / 2 - uy * scale
    for i in unit.indices:
        _scale_member(elements[i], scale, dx, dy)
        if elements[i]["type"] == "text":
            _fit_font(elements[i], elements[i]["font_size"])


def _stack(units, elements, region, gap, type_scale):
    if not units:
        return
    x, y, w, h = region
    available = h - gap * (len(units) - 1)
    if available <= 0:
        return
    # Natural heights favor large imagery, headings, and complete button groups.
    weights = []
    for unit in units:
        members = [elements[i] for i in unit.indices]
        if len(members) == 1 and members[0]["type"] == "text":
            el = members[0]
            from renderer.converter.wrap import wrap_text
            preferred_size = el["font_size"] * type_scale
            widths = _text_widths(el, preferred_size)
            lines = wrap_text(el["content"], widths, w).count("\n") + 1
            weights.append(max(1, lines * preferred_size * el.get("line_height", 1.2)))
        else:
            weights.append(max(1, unit.bounds[3] * min(w / max(unit.bounds[2], 1), type_scale)))
    for unit, weight in zip(units, weights):
        height = available * weight / sum(weights)
        _place(unit, elements, (x, y, w, height), type_scale)
        y += height + gap


def _clamp_unit(indices, elements, canvas):
    x, y, w, h = _bounds([elements[i] for i in indices])
    scale = min(1.0, canvas["width"] / max(w, 1e-9), canvas["height"] / max(h, 1e-9))
    dx = max(0, min(x, canvas["width"] - w * scale)) - x * scale
    dy = max(0, min(y, canvas["height"] - h * scale)) - y * scale
    for i in indices:
        _scale_member(elements[i], scale, dx, dy)


def _finish(source, target, elements, backgrounds, decorations):
    for i in backgrounds:
        el = elements[i]
        el.update(x=0, y=0, width=target["width"], height=target["height"])
        if el["type"] == "image":
            el["fit"] = "cover"
    scale = min(target["width"] / source["canvas"]["width"], target["height"] / source["canvas"]["height"])
    for i in decorations:
        original = source["elements"][i]
        el = deepcopy(original)
        _scale_member(el, scale, 0, 0)
        el["x"] = (original["x"] + original["width"] / 2) / source["canvas"]["width"] * target["width"] - el["width"] / 2
        el["y"] = (original["y"] + original["height"] / 2) / source["canvas"]["height"] * target["height"] - el["height"] / 2
        elements[i] = el
        _clamp_unit([i], elements, target)
    return {"canvas": dict(target), "elements": elements}


def _overlap(a, b):
    return (min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > 1e-5
            and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > 1e-5)


def _inside(el, canvas):
    x, y, w, h = _bounds([el])
    return (x >= -1e-5 and y >= -1e-5 and x + w <= canvas["width"] + 1e-5
            and y + h <= canvas["height"] + 1e-5)


def _valid(source, output, units):
    elements, canvas = output["elements"], output["canvas"]
    if sorted(e["id"] for e in elements) != sorted(e["id"] for e in source["elements"]):
        return False
    for original, el in zip(source["elements"], elements):
        if not _inside(el, canvas):
            return False
        if el["type"] == "text" and not _text_fits(el, el["font_size"]):
            return False
        if el["type"] == "image" and not _background(original, source["canvas"]) and original["height"] and el["height"]:
            if abs(el["width"] / el["height"] - original["width"] / original["height"]) > 1e-5:
                return False
    boxes = [_bounds([elements[i] for i in u.indices]) for u in units]
    return not any(_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])


def _rank(source, output, units):
    elements = output["elements"]
    text = [(a, b) for a, b in zip(source["elements"], elements) if a["type"] == "text"]
    scales = [b["font_size"] / a["font_size"] for a, b in text]
    hierarchy = -(max(scales) - min(scales)) if scales else 0
    image_areas = [sum(elements[i]["width"] * elements[i]["height"] for i in u.indices) for u in units if u.image]
    occupied = sum(_bounds([elements[i] for i in u.indices])[2] * _bounds([elements[i] for i in u.indices])[3] for u in units)
    movement = sum(abs(a["x"] / source["canvas"]["width"] - b["x"] / output["canvas"]["width"])
                   + abs(a["y"] / source["canvas"]["height"] - b["y"] / output["canvas"]["height"])
                   for a, b in zip(source["elements"], elements))
    return (min((b["font_size"] for _, b in text), default=0) / min(output["canvas"].values()),
            hierarchy, max(image_areas, default=0), occupied, -movement)


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """Retarget a design offline, preserving assets, content, groups and IDs.

    Simple nearby resizes retain the Level 1 proportional composition.
    Complex designs compete across group-aware horizontal, vertical and
    balanced layouts. Tiny targets may still require very small text.
    """
    backgrounds, decorations, units = _composition(source)
    baseline = _proportional(source, target_canvas)
    ratio_change = (target_canvas["width"] / target_canvas["height"]) / (source["canvas"]["width"] / source["canvas"]["height"])
    # Keep the established Level 1 behavior without loading renderer fonts.
    if (len(source["elements"]) <= 4 and not decorations and 2 / 3 <= ratio_change <= 1.5
            and all(len(u.indices) == 1 for u in units)):
        boxes = [_bounds([baseline["elements"][i] for i in u.indices]) for u in units]
        if (all(_inside(e, target_canvas) for e in baseline["elements"])
                and not any(_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])):
            return baseline
    baseline = _finish(source, target_canvas, baseline["elements"], backgrounds, decorations)
    candidates = [baseline] if _valid(source, baseline, units) else []
    images = [u for u in units if u.image]
    other = [u for u in units if not u.image]
    short = min(target_canvas.values())
    type_scale = short / min(source["canvas"].values()) * 2.5
    for spacing in (1.0, 0.5):
        margin, gap = short * 0.05 * spacing, short * 0.03 * spacing
        w, h = target_canvas["width"] - 2 * margin, target_canvas["height"] - 2 * margin
        for mode in ("horizontal", "vertical", "balanced"):
            for first in (True, False):
                left, right = (images, other) if first else (other, images)
                if mode == "balanced":
                    middle = (len(units) + 1) // 2
                    left, right = units[:middle], units[middle:]
                    if not first:
                        left, right = right, left
                for fraction in ((0.5,) if mode == "balanced" else (0.35, 0.5, 0.65)):
                    elements = deepcopy(source["elements"])
                    if not left or not right:
                        _stack(left or right, elements, (margin, margin, w, h), gap, type_scale)
                    elif mode == "vertical":
                        split = (h - gap) * fraction
                        _stack(left, elements, (margin, margin, w, split), gap, type_scale)
                        _stack(right, elements, (margin, margin + split + gap, w, h - split - gap), gap, type_scale)
                    else:
                        split = (w - gap) * fraction
                        _stack(left, elements, (margin, margin, split, h), gap, type_scale)
                        _stack(right, elements, (margin + split + gap, margin, w - split - gap, h), gap, type_scale)
                    output = _finish(source, target_canvas, elements, backgrounds, decorations)
                    if _valid(source, output, units):
                        candidates.append(output)
        if candidates:
            return max(candidates, key=lambda output: _rank(source, output, units))
    # Best-effort fallback preserves every unit even for infeasible tiny targets.
    for unit in units:
        _clamp_unit(unit.indices, baseline["elements"], target_canvas)
        for i in unit.indices:
            el = baseline["elements"][i]
            if el["type"] == "text":
                _fit_font(el, el["font_size"])
    return baseline
