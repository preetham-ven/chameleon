"""
THIS IS THE FILE YOU IMPLEMENT.

Everything else in this repo (input loading, output writing, rendering,
the Dockerfile) is plumbing so you can focus on exactly one function:
`resize()`. See RULES.md and the design schema for the full contract.
"""

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import logging
from math import cos, radians, sin, sqrt
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)
# All five scores are normalized. Readability must not drown out imagery.
SCORE_WEIGHTS = (0.30, 0.20, 0.20, 0.15, 0.15)
READABLE_FONT = 12.0


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


@lru_cache(maxsize=256)
def _asset_bounds(path, modified):
    """Read alpha bounds once per asset revision; never crop or replace it."""
    from PIL import Image
    try:
        with Image.open(path) as image:
            alpha = image.convert("RGBA").getchannel("A")
            box = alpha.getbbox() or (0, 0, image.width, image.height)
            return image.size, box
    except (OSError, ValueError):
        return None


def _visible_bounds(el):
    """Envelope of visible pixels, separate from the full on-canvas box."""
    w, h = el["width"], el["height"]
    left, top, right, bottom = 0, 0, w, h
    if el["type"] == "image":
        path = ROOT / "brand_kit" / "assets" / el["asset_id"]
        info = _asset_bounds(str(path), path.stat().st_mtime_ns) if path.is_file() else None
        if info:
            (iw, ih), (l, t, r, b) = info
            fit = el.get("fit", "contain")
            if fit == "fill":
                left, top, right, bottom = l * w / iw, t * h / ih, r * w / iw, b * h / ih
            else:
                scale = (max if fit == "cover" else min)(w / iw, h / ih)
                dx, dy = (w - iw * scale) / 2, (h - ih * scale) / 2
                left, top = max(0, l * scale + dx), max(0, t * scale + dy)
                right, bottom = min(w, r * scale + dx), min(h, b * scale + dy)
    elif el["type"] == "text":
        left, top, right, bottom = _measure(el).ink
    angle = radians(el.get("rotation", 0))
    corners = [(el["x"] + w / 2 + (x - w / 2) * cos(angle) - (y - h / 2) * sin(angle),
                el["y"] + h / 2 + (x - w / 2) * sin(angle) + (y - h / 2) * cos(angle))
               for x, y in ((left, top), (right, top), (left, bottom), (right, bottom))]
    x, y = min(p[0] for p in corners), min(p[1] for p in corners)
    return x, y, max(p[0] for p in corners) - x, max(p[1] for p in corners) - y


def _image_area(el):
    # Rotation increases an axis-aligned envelope, not the amount of artwork.
    if not (ROOT / "brand_kit" / "assets" / el["asset_id"]).is_file():
        return 0  # A missing asset must survive, but cannot earn image prominence.
    _, _, w, h = _visible_bounds({**el, "rotation": 0})
    return w * h


def _button_members(unit, elements):
    """Only refine an unambiguous, unrotated rectangle-and-label group."""
    if len(unit.indices) != 2:
        return None
    shape = next((i for i in unit.indices if elements[i]["type"] == "shape"), None)
    label = next((i for i in unit.indices if elements[i]["type"] == "text"), None)
    if shape is None or label is None:
        return None
    bg, text = elements[shape], elements[label]
    if bg.get("shape_type") != "rectangle" or bg.get("rotation", 0) or text.get("rotation", 0):
        return None
    if (text["x"] >= bg["x"] and text["y"] >= bg["y"]
            and text["x"] + text["width"] <= bg["x"] + bg["width"] + 1e-6
            and text["y"] + text["height"] <= bg["y"] + bg["height"] + 1e-6):
        return shape, label
    return None


def _composition(source):
    from renderer.converter.colorutil import parse_rgba
    backgrounds, decorations, buckets = [], [], {}
    foreground_z = [e.get("z_index", 0) for e in source["elements"]
                    if e["type"] in ("image", "text") and not _background(e, source["canvas"])]
    for i, el in enumerate(source["elements"]):
        if _background(el, source["canvas"]) and el.get("group_id") is None:
            backgrounds.append(i)
        elif (el["type"] == "shape" and el.get("group_id") is None
              and el.get("opacity", 1) * parse_rgba(el.get("fill_color"))[3] <= 0.25 and foreground_z
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
    return load_brand_font_manager(str(ROOT / "brand_kit" / "fonts"))


def _measure(el, size=None, legacy=False):
    from renderer.converter.textlayout import measure_text
    return measure_text(el, _font_manager(), size, legacy)


def _text_fits(el, size):
    """Fit both the corrected preview and the original converter's text."""
    for legacy in (False, True):
        layout = _measure(el, size, legacy)
        if el.get("max_lines") is not None and layout.wrapped.count("\n") + 1 > el["max_lines"]:
            return False
        if max(layout.width, layout.ink[2] - layout.ink[0]) > el["width"] + 1e-6:
            return False
        if layout.height > el["height"] + 1e-6:
            return False
    return True


def _fit_font(el, maximum, integer_search=False):
    if integer_search:
        # Wrap changes and glyph overhang can make a smaller size fail even
        # when a larger size fits. Scan actual rendered sizes for compact text.
        for size in [max(1.0, maximum), *range(int(maximum), 0, -1)]:
            if _text_fits(el, size):
                el["font_size"] = size
                return
        el["font_size"] = 1.0
        return
    low, high = 1.0, max(1.0, maximum)
    for _ in range(12):
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


def _place(unit, elements, region, type_scale, integer_search=False):
    x, y, w, h = region
    ux, uy, uw, uh = unit.bounds
    button = _button_members(unit, elements)
    if button:
        _place_button(button, elements, region, type_scale, integer_search)
        return
    if len(unit.indices) == 1:
        el = elements[unit.indices[0]]
        if el["type"] == "text" and el.get("rotation", 0) == 0:
            original_size = el["font_size"]
            el.update(x=x, y=y, width=w, height=h)
            if "letter_spacing" in el:
                el["letter_spacing"] *= type_scale
            _fit_font(el, original_size * type_scale, integer_search)
            layout = _measure(el)
            el["height"] = min(h, max(layout.height, _measure(el, legacy=True).height))
            # Center the ink when there is room, while retaining the full box.
            centered = y + h / 2 - (layout.ink[1] + layout.ink[3]) / 2
            el["y"] = max(y, min(centered, y + h - el["height"]))
            return
    scale = min(w / max(uw, 1e-9), h / max(uh, 1e-9))
    dx, dy = x + (w - uw * scale) / 2 - ux * scale, y + (h - uh * scale) / 2 - uy * scale
    for i in unit.indices:
        _scale_member(elements[i], scale, dx, dy)
        if elements[i]["type"] == "text":
            _fit_font(elements[i], elements[i]["font_size"], integer_search)


def _place_button(members, elements, region, type_scale, integer_search=False):
    x, y, w, h = region
    bg, label = (elements[i] for i in members)
    radius_ratio = bg.get("corner_radius", 0) / max(1, min(bg["width"], bg["height"]))
    original_size = label["font_size"]
    natural = _measure(label).width
    pad_ratio = max(0.6, min(1.5, (bg["width"] - natural) / (2 * original_size)))
    preferred = original_size * type_scale
    # Reduce padding with the font so a narrow cell can still hold its label.
    preferred = min(preferred, w / (2 * pad_ratio + 1), h / 2.1)
    pad_x, pad_y = preferred * pad_ratio, preferred * 0.45
    label.update(width=max(0, w - 2 * pad_x), height=max(0, h - 2 * pad_y))
    if "letter_spacing" in label:
        label["letter_spacing"] *= type_scale
    _fit_font(label, preferred, integer_search)
    layouts = [_measure(label, legacy=legacy) for legacy in (False, True)]
    text_width = max(max(m.width, m.ink[2] - m.ink[0]) for m in layouts)
    text_height = max(m.height for m in layouts)
    bw = min(w, text_width + 2 * pad_x + 1)
    if integer_search:
        label["width"] = max(0, bw - 2 * pad_x)
        compact_layouts = [_measure(label, legacy=legacy) for legacy in (False, True)]
        # The original greedy wrapper may move an earlier space when a box
        # becomes narrower. Retain the measured width if shrinking adds lines.
        if any(new.wrapped.count("\n") > old.wrapped.count("\n")
               or max(new.width, new.ink[2] - new.ink[0]) > label["width"] + 1e-6
               for old, new in zip(layouts, compact_layouts)):
            bw = w
            label["width"] = max(0, w - 2 * pad_x)
            compact_layouts = [_measure(label, legacy=legacy) for legacy in (False, True)]
        text_height = max(m.height for m in compact_layouts)
    bh = min(h, text_height + 2 * pad_y)
    bx, by = x + (w - bw) / 2, y + (h - bh) / 2
    bg.update(x=bx, y=by, width=bw, height=bh)
    if "corner_radius" in bg:
        bg["corner_radius"] = radius_ratio * min(bw, bh)
    if "stroke_width" in bg:
        bg["stroke_width"] *= type_scale
    label.update(x=bx + pad_x, width=max(0, bw - 2 * pad_x), height=text_height)
    ink = _measure(label).ink
    label["y"] = max(by, min(by + bh / 2 - (ink[1] + ink[3]) / 2, by + bh - text_height))


def _natural_height(unit, elements, width, type_scale):
    button = _button_members(unit, elements)
    if button:
        label = deepcopy(elements[button[1]])
        size = label["font_size"] * type_scale
        label.update(width=max(1, width - 3 * size), font_size=size)
        return max(_measure(label, legacy=legacy).height for legacy in (False, True)) + 0.9 * size
    if len(unit.indices) == 1 and elements[unit.indices[0]]["type"] == "text":
        label = deepcopy(elements[unit.indices[0]])
        label.update(width=width, font_size=label["font_size"] * type_scale)
        if "letter_spacing" in label:
            label["letter_spacing"] *= type_scale
        return max(1, *(_measure(label, legacy=legacy).height for legacy in (False, True)))
    return max(1, unit.bounds[3] * min(width / max(unit.bounds[2], 1), type_scale))


def _stack(units, elements, region, gap, type_scale):
    if not units:
        return
    x, y, w, h = region
    available = h - gap * (len(units) - 1)
    if available <= 0:
        return
    heights = [_natural_height(unit, elements, w, type_scale) for unit in units]
    scale = min(1, available / sum(heights))
    y += max(0, (available - sum(heights) * scale) / 2)
    for unit, natural in zip(units, heights):
        height = natural * scale
        _place(unit, elements, (x, y, w, height), type_scale)
        y += height + gap


def _content_column(units, dominant, elements, region, gap, type_scale):
    """Small images and early compact groups can share a header row."""
    x, y, w, h = region
    header = [u for u in units if (u.image or _button_members(u, elements))
              and u.bounds[1] + u.bounds[3] / 2 < dominant.bounds[1] + dominant.bounds[3] / 2]
    body = [u for u in units if u not in header]
    if not header or not body:
        _stack(units, elements, region, gap, type_scale)
        return
    cell_width = (w - gap * (len(header) - 1)) / len(header)
    if cell_width <= 0:
        return
    header_height = min(h * 0.24, max(_natural_height(u, elements, cell_width, type_scale) for u in header))
    for i, unit in enumerate(header):
        _place(unit, elements, (x + i * (cell_width + gap), y, cell_width, header_height), type_scale)
    _stack(body, elements, (x, y + header_height + gap, w, h - header_height - gap), gap, type_scale)


def _grid(units, elements, region, gap, type_scale, columns):
    x, y, w, h = region
    rows = [units[i:i + columns] for i in range(0, len(units), columns)]
    cell_width = (w - gap * (columns - 1)) / columns
    available = h - gap * (len(rows) - 1)
    if not rows or cell_width <= 0 or available <= 0:
        return
    heights = [max(_natural_height(u, elements, cell_width, type_scale) for u in row) for row in rows]
    scale = min(1, available / sum(heights))
    y += max(0, (available - sum(heights) * scale) / 2)
    for row, natural in zip(rows, heights):
        height = natural * scale
        for col, unit in enumerate(row):
            _place(unit, elements, (x + col * (cell_width + gap), y, cell_width, height), type_scale)
        y += height + gap


def _image_panel(units, elements, region, gap, type_scale):
    """Keep comparable images together, filling a regular row or grid."""
    x, y, w, h = region
    columns = min(len(units), max(1, round(sqrt(len(units) * w / max(h, 1)))))
    rows = (len(units) + columns - 1) // columns
    if rows == 1:
        units = sorted(units, key=lambda unit: unit.bounds[0])
    cw, ch = (w - gap * (columns - 1)) / columns, (h - gap * (rows - 1)) / rows
    if cw <= 0 or ch <= 0:
        return
    for index, unit in enumerate(units):
        row, col = divmod(index, columns)
        # Center a short last row instead of leaving it pinned to one side.
        count = min(columns, len(units) - row * columns)
        offset = (columns - count) * (cw + gap) / 2
        _place(unit, elements, (x + offset + col * (cw + gap), y + row * (ch + gap), cw, ch), type_scale)


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
        if el.get("rotation", 0):
            _clamp_unit([i], elements, target)
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
        if el["type"] == "text":
            x, y, w, h = _visible_bounds(el)
            if x < -1 or y < -1 or x + w > canvas["width"] + 1 or y + h > canvas["height"] + 1:
                return False
        if el["type"] == "image" and not _background(original, source["canvas"]) and original["height"] and el["height"]:
            if abs(el["width"] / el["height"] - original["width"] / original["height"]) > 1e-5:
                return False
    boxes = [_bounds([elements[i] for i in u.indices]) for u in units]
    return not any(_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])


def layout_warnings(source, output):
    """Report best-effort limitations without changing the design schema."""
    warnings = []
    for el in output["elements"]:
        if el["type"] == "text":
            if not _text_fits(el, el["font_size"]):
                warnings.append(f"text '{el['id']}' does not fit its box or line limit")
            if int(el["font_size"]) < READABLE_FONT:
                warnings.append(f"text '{el['id']}' is small ({int(el['font_size'])}px rendered)")
    units = _composition(source)[2]
    boxes = [_bounds([output["elements"][i] for i in u.indices]) for u in units]
    if any(_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:]):
        warnings.append("foreground units overlap in the best-effort layout")
    return warnings


def _rank(source, output, units):
    elements = output["elements"]
    canvas = output["canvas"]
    area_scale = canvas["width"] * canvas["height"] / (source["canvas"]["width"] * source["canvas"]["height"])
    text = [(a, b) for a, b in zip(source["elements"], elements) if a["type"] == "text"]
    scales = [b["font_size"] / a["font_size"] for a, b in text]
    readability = sum(0.5 * min(1, b["font_size"] / READABLE_FONT)
                      + 0.5 * min(1, b["font_size"] / max(1, a["font_size"] * sqrt(area_scale)))
                      for a, b in text) / max(1, len(text)) if text else 1
    text_hierarchy = min(scales) / max(scales) if scales else 1
    images = [(a, b) for a, b in zip(source["elements"], elements)
              if a["type"] == "image" and not _background(a, source["canvas"])]
    prominence, total_weight, image_scales = 0, 0, []
    for original, result in images:
        source_area, target_area = _image_area(original), _image_area(result)
        weight = sqrt(source_area)
        prominence += weight * min(1, target_area / max(1, source_area * area_scale))
        total_weight += weight
        if source_area > 0 and target_area > 0:
            image_scales.append(sqrt(target_area / source_area))
    prominence = prominence / total_weight if total_weight else 1
    image_hierarchy = min(image_scales) / max(image_scales) if image_scales else 1
    hierarchy = ((text_hierarchy + image_hierarchy) / 2 if text and images
                 else text_hierarchy if text else image_hierarchy)
    boxes = [_visible_bounds(elements[i]) for u in units for i in u.indices]
    if boxes:
        left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
        right, bottom = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
        coverage = (right - left) * (bottom - top) / (canvas["width"] * canvas["height"])
        center_error = abs((left + right) / 2 / canvas["width"] - 0.5) + abs((top + bottom) / 2 / canvas["height"] - 0.5)
        balance = 0.5 * min(1, coverage) + 0.5 * max(0, 1 - 2 * center_error)
    else:
        balance = 1
    movement = sum(abs(a["x"] / source["canvas"]["width"] - b["x"] / output["canvas"]["width"])
                   + abs(a["y"] / source["canvas"]["height"] - b["y"] / output["canvas"]["height"])
                   for a, b in zip(source["elements"], elements))
    fidelity = max(0, 1 - movement / max(1, 2 * len(elements)))
    score = sum(weight * value for weight, value in zip(SCORE_WEIGHTS,
                (readability, hierarchy, prominence, balance, fidelity)))
    return score, -movement


def _candidate_elements(source, target, units):
    """A bounded search of simple arrangements, independent of IDs and copy."""
    images = [u for u in units if u.image]
    other = [u for u in units if not u.image]
    short = min(target.values())
    area_scale = sqrt(target["width"] * target["height"] /
                      (source["canvas"]["width"] * source["canvas"]["height"]))
    image_sizes = sorted(((sum(_image_area(source["elements"][i]) for i in u.indices), u)
                          for u in images), key=lambda item: item[0], reverse=True)
    dominant = image_sizes[0][1] if image_sizes else None
    if len(image_sizes) > 1 and image_sizes[0][0] < image_sizes[1][0] * 1.8:
        dominant = None
    for spacing in (1.0, 0.5):
        margin, gap = short * 0.05 * spacing, short * 0.03 * spacing
        w, h = target["width"] - 2 * margin, target["height"] - 2 * margin
        for type_scale in (area_scale, area_scale * 1.4, area_scale * 2.0):
            for mode in ("horizontal", "vertical", "balanced", "feature", "gallery"):
                if mode == "feature" and dominant is None:
                    continue
                if mode == "gallery" and len(images) < 2:
                    continue
                for first in (True, False):
                    left, right = (images, other) if first else (other, images)
                    if mode == "balanced":
                        middle = (len(units) + 1) // 2
                        left, right = units[:middle], units[middle:]
                        if not first:
                            left, right = right, left
                    elif mode == "feature":
                        remaining = [u for u in units if u is not dominant]
                        left, right = ([dominant], remaining) if first else (remaining, [dominant])
                    for fraction in ((0.5,) if mode == "balanced" else (0.35, 0.5, 0.65)):
                        elements = deepcopy(source["elements"])
                        if not left or not right:
                            _stack(left or right, elements, (margin, margin, w, h), gap, type_scale)
                        else:
                            vertical = mode == "vertical" or (mode in ("feature", "gallery") and h > w)
                            split = ((h if vertical else w) - gap) * fraction
                            if vertical:
                                regions = ((margin, margin, w, split),
                                           (margin, margin + split + gap, w, h - split - gap))
                            else:
                                regions = ((margin, margin, split, h),
                                           (margin + split + gap, margin, w - split - gap, h))
                            for group, region in zip((left, right), regions):
                                if mode == "feature" and group != [dominant]:
                                    _content_column(group, dominant, elements, region, gap, type_scale)
                                elif mode == "gallery" and group == images:
                                    _image_panel(group, elements, region, gap, type_scale)
                                else:
                                    _stack(group, elements, region, gap, type_scale)
                        yield elements
            for columns in (2, 3):
                if len(units) >= columns:
                    elements = deepcopy(source["elements"])
                    _grid(units, elements, (margin, margin, w, h), gap, type_scale, columns)
                    yield elements
            if images and not other:
                elements = deepcopy(source["elements"])
                _image_panel(images, elements, (margin, margin, w, h), gap, type_scale)
                yield elements


@dataclass
class _SizedUnit:
    unit: _Unit
    width: float
    height: float
    type_scale: float
    members: list[dict] | None = None


def _minimum_font(output):
    """Use the actual integer size drawn by cr-renderer, ignoring empty copy."""
    return min((int(e["font_size"]) for e in output["elements"]
                if e["type"] == "text" and e["content"].strip()), default=int(READABLE_FONT))


def _compact_scale(unit, elements, floor, reference):
    fonts = [elements[i]["font_size"] for i in unit.indices
             if elements[i]["type"] == "text" and elements[i]["content"].strip()]
    if not fonts:
        return 1.0
    smallest = min(fonts)
    # Compress the hierarchy on dense canvases while keeping larger text larger.
    # A small epsilon survives binary fitting without rounding a 6px goal to 5px.
    preferred = floor * min(3, sqrt(smallest / reference)) + 0.02
    return preferred / smallest


def _compact_item(unit, source, floor, reference, region, image_scale):
    elements = source["elements"]
    _, _, max_w, max_h = region
    short = min(max_w, max_h)
    type_scale = _compact_scale(unit, elements, floor, reference)
    members = None
    angle = elements[unit.indices[0]].get("rotation", 0)
    common_rotation = angle and all(elements[i].get("rotation", 0) == angle for i in unit.indices)
    trial = list(elements)
    for i in unit.indices:
        trial[i] = deepcopy(elements[i])
        if common_rotation:
            trial[i]["rotation"] = 0
    button = _button_members(unit, trial)
    if button:
        # A rotated pill can lose excess padding while retaining its angle.
        # Other rotated/complex groups remain rigid, uniformly scaled units.
        factor = abs(cos(radians(angle))) + abs(sin(radians(angle)))
        _place_button(button, trial, (0, 0, max_w / factor, max_h / factor), type_scale, integer_search=True)
        bg = trial[button[0]]
        cx, cy = bg["x"] + bg["width"] / 2, bg["y"] + bg["height"] / 2
        for i in unit.indices:
            el = trial[i]
            dx, dy = el["x"] + el["width"] / 2 - cx, el["y"] + el["height"] / 2 - cy
            el["x"] = cx + dx * cos(radians(angle)) - dy * sin(radians(angle)) - el["width"] / 2
            el["y"] = cy + dx * sin(radians(angle)) + dy * cos(radians(angle)) - el["height"] / 2
            el["rotation"] = elements[i].get("rotation", 0)
            if "rotation" not in elements[i]:
                el.pop("rotation", None)
        x, y, w, h = _bounds([trial[i] for i in unit.indices])
        members = [trial[i] for i in unit.indices]
        for el in members:
            el["x"] -= x
            el["y"] -= y
    else:
        _, _, w, h = unit.bounds
        fonts = [elements[i]["font_size"] for i in unit.indices if elements[i]["type"] == "text"]
        if fonts:
            scale = type_scale
        else:
            missing = unit.image and not any(_image_area(elements[i]) for i in unit.indices)
            edge = short * (0.30 if missing else image_scale)
            scale = min(edge / max(w, h, 1), max_w / max(w, 1), max_h / max(h, 1))
        w, h = w * scale, h * scale
    return _SizedUnit(unit, max(1, w), max(1, h), type_scale, members)


def _place_sized(items, regions, elements, dx=0, dy=0):
    for item, (x, y, w, h) in zip(items, regions):
        if item.members is None:
            _place(item.unit, elements, (x + dx, y + dy, w, h), item.type_scale, integer_search=True)
        else:
            for index, member in zip(item.unit.indices, item.members):
                elements[index] = {**member, "x": member["x"] + x + dx,
                                   "y": member["y"] + y + dy}


def _compact_paragraphs(units, source, region, gap, floor, reference, columns):
    """Measure blocks before balancing their ordered sequence into columns."""
    from engine.packing import balanced_columns
    x, y, w, h = region
    cw = (w - gap * (columns - 1)) / columns
    if cw <= 0 or h <= 0:
        return None
    def measure(unit, boost):
        original = source["elements"][unit.indices[0]]
        el = {**original, "width": cw, "height": h}
        preferred = original["font_size"] * _compact_scale(unit, source["elements"], floor, reference)
        size = floor + 0.02 + boost * (preferred - floor - 0.02)
        if "letter_spacing" in el:
            el["letter_spacing"] *= size / original["font_size"]
        _fit_font(el, size, integer_search=True)
        if int(el["font_size"]) < floor or not _text_fits(el, el["font_size"]):
            return None
        height = max(_measure(el, legacy=legacy).height for legacy in (False, True))
        return _SizedUnit(unit, cw, height, el["font_size"] / original["font_size"])

    minimum = [measure(unit, 0) for unit in units]
    if any(item is None for item in minimum):
        return None
    ranges, height = balanced_columns([item.height for item in minimum], columns, gap)
    if height > h + 1e-6:
        return None
    items, regions = [], []
    for col, (start, end) in enumerate(ranges):
        chosen, low, high = minimum[start:end], 0, 1
        for _ in range(8):
            boost = (low + high) / 2
            trial = [measure(unit, boost) for unit in units[start:end]]
            if (all(item is not None for item in trial)
                    and sum(item.height for item in trial) + gap * (end - start - 1) <= h + 1e-6):
                chosen, low = trial, boost
            else:
                high = boost
        items.extend(chosen)
        column_h = sum(item.height for item in chosen) + gap * (end - start - 1)
        cy = y + (h - column_h) / 2
        for item in chosen:
            regions.append((x + col * (cw + gap), cy, cw, item.height))
            cy += item.height + gap
    return items, regions


def _compact_candidates(source, target, backgrounds, decorations, units, spacing=1.0):
    """Find the largest common readable size using measured compact layouts.

    Paragraphs occupy reading columns. Labels wrap into rows. Images and rigid
    groups pack into a side/top rail. Search depends on geometry and content
    demand, never task IDs, difficulty labels, or a catalogue of resolutions.
    """
    from engine.packing import flow_rows, pack_rectangles
    texts = [e["font_size"] for e in source["elements"] if e["type"] == "text" and e["content"].strip()]
    if not texts:
        return []
    reference = min(texts)
    paragraphs = [u for u in units if len(u.indices) == 1
                  and source["elements"][u.indices[0]]["type"] == "text"
                  and not source["elements"][u.indices[0]].get("rotation", 0)]
    supporting = [u for u in units if u not in paragraphs]
    images = [u for u in supporting if u.image]
    labels = [u for u in supporting if _button_members(u, source["elements"])]
    rigid = [u for u in supporting if u not in images and u not in labels]
    short = min(target.values())
    margin, gap = min(8, short * 0.025) * spacing, min(6, short * 0.02) * spacing
    w, h = target["width"] - 2 * margin, target["height"] - 2 * margin
    if w <= 0 or h <= 0:
        return []
    orientation = "side" if w >= h else "top"
    paragraph_cache = {}
    for floor in range(int(READABLE_FONT), 0, -1):
        feasible = []
        # Try rigid groups in the rail as well as alongside the label rows.
        for rigid_in_rail in (True, False):
            rail_units = images + (rigid if rigid_in_rail else [])
            row_units = labels + ([] if rigid_in_rail else rigid)
            row_units.sort(key=lambda u: (u.bounds[1], u.bounds[0]))
            fractions = (0.18, 0.28, 0.38) if rail_units else (0,)
            for fraction in fractions:
                for reverse in ((False, True) if rail_units else (False,)):
                    rail, body = (0, 0, w, h), (margin, margin, w, h)
                    if rail_units and orientation == "side":
                        rw = w * fraction
                        rail = (margin + (w - rw if reverse else 0), margin, rw, h)
                        body = (margin + (0 if reverse else rw + gap), margin, w - rw - gap, h)
                    elif rail_units:
                        rh = h * fraction
                        rail = (margin, margin + (h - rh if reverse else 0), w, rh)
                        body = (margin, margin + (0 if reverse else rh + gap), w, h - rh - gap)
                    bx, by, bw, bh = body
                    for image_scale in ((0.9, 0.65) if images else (0.9,)):
                        rail_items = [_compact_item(u, source, floor, reference, rail, image_scale) for u in rail_units]
                        row_items = [_compact_item(u, source, floor, reference, body, image_scale) for u in row_units]
                        rows = flow_rows([(i.width, i.height) for i in row_items], bw, gap)
                        if rows is None:
                            continue
                        row_regions, row_h = rows
                        text_h = bh - row_h - (gap if paragraphs and row_items else 0)
                        if text_h < 0:
                            continue
                        column_counts = range(1, min(3, len(paragraphs)) + 1) if paragraphs else (0,)
                        for columns in column_counts:
                            key = (floor, bw, text_h, columns)
                            if key not in paragraph_cache:
                                paragraph_cache[key] = _compact_paragraphs(
                                    paragraphs, source, (0, 0, bw, text_h), gap, floor,
                                    reference, columns) if paragraphs else ([], [])
                            copy_layout = paragraph_cache[key]
                            if copy_layout is None:
                                continue
                            for vertical_first in ((True, False) if rail_items else (True,)):
                                rail_regions = pack_rectangles([(i.width, i.height) for i in rail_items],
                                                               rail, gap, vertical_first)
                                if rail_regions is None:
                                    continue
                                elements = deepcopy(source["elements"])
                                _place_sized(rail_items, rail_regions, elements)
                                _place_sized(row_items, row_regions, elements, bx, by + bh - row_h)
                                _place_sized(copy_layout[0], copy_layout[1], elements, bx, by)
                                output = _finish(source, target, elements, backgrounds, decorations)
                                if _minimum_font(output) >= floor and _valid(source, output, units):
                                    feasible.append(output)
        if feasible:
            return feasible  # Lower floors cannot beat this floor's minimum size.
    return []


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """Retarget a design offline, preserving assets, content, groups and IDs.

    Simple nearby resizes retain the Level 1 proportional composition.
    Complex designs compete across group-aware horizontal, vertical and
    balanced layouts. Tiny targets may still require very small text.
    """
    backgrounds, decorations, units = _composition(source)
    baseline = _proportional(source, target_canvas)
    ratio_change = (target_canvas["width"] / target_canvas["height"]) / (source["canvas"]["width"] / source["canvas"]["height"])
    # Keep the established Level 1 geometry when the text is already readable.
    if (len(source["elements"]) <= 4 and not decorations and 2 / 3 <= ratio_change <= 1.5
            and all(len(u.indices) == 1 for u in units)):
        boxes = [_bounds([baseline["elements"][i] for i in u.indices]) for u in units]
        if (all(_inside(e, target_canvas) for e in baseline["elements"])
                and all(_text_fits(e, e["font_size"]) for e in baseline["elements"] if e["type"] == "text")
                and not any(_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])):
            return baseline
    baseline = _finish(source, target_canvas, baseline["elements"], backgrounds, decorations)
    # Nearby resizes should not dismantle an already readable composition.
    # Compact simple labels inside their existing regions, keeping all other
    # relationships intact. Invalid source overlaps still go through reflow.
    if 2 / 3 <= ratio_change <= 1.5 and _valid(source, baseline, units):
        nearby = deepcopy(baseline)
        for unit in units:
            button = _button_members(unit, source["elements"])
            if button:
                region = _bounds([nearby["elements"][i] for i in unit.indices])
                _place_button(button, nearby["elements"], region, 1.0)
        if (_valid(source, nearby, units)
                and all(e["font_size"] >= READABLE_FONT for e in nearby["elements"] if e["type"] == "text")):
            return nearby
    candidates = [baseline] if _valid(source, baseline, units) else []
    for elements in _candidate_elements(source, target_canvas, units):
        output = _finish(source, target_canvas, elements, backgrounds, decorations)
        if _valid(source, output, units):
            candidates.append(output)
    best = max(candidates, key=lambda output: _rank(source, output, units)) if candidates else None
    if best is None or _minimum_font(best) < READABLE_FONT:
        compact = []
        for spacing in (1.0, 0.5):
            compact.extend(_compact_candidates(source, target_canvas, backgrounds, decorations, units, spacing))
        if compact:
            best = max(([best] if best else []) + compact,
                       key=lambda output: (_minimum_font(output), _rank(source, output, units)))
    if best is not None:
        return best
    # Best-effort fallback preserves every unit even for infeasible tiny targets.
    for unit in units:
        _clamp_unit(unit.indices, baseline["elements"], target_canvas)
        for i in unit.indices:
            el = baseline["elements"][i]
            if el["type"] == "text":
                _fit_font(el, el["font_size"])
    logger.warning("No collision-free layout with fitting text for %sx%s; using a best-effort layout.",
                   target_canvas["width"], target_canvas["height"])
    return baseline
