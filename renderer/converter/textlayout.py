"""Text styles and measurements shared by layout and preview rendering.

The renderer draws at integer font sizes and positions glyphs from the font's
ascent. Measuring those same glyphs lets us center visible lettering rather
than its (often much taller) text box.
"""

from dataclasses import dataclass
from functools import lru_cache
from itertools import groupby

import skia

from .wrap import wrap_text


@dataclass(frozen=True)
class TextLayout:
    wrapped: str
    width: float
    height: float
    ink: tuple[float, float, float, float]


def text_styles(element, inclusive_end=False):
    """Return per-character (bold, italic, color), with schema-exclusive ends.

    inclusive_end is only for checking compatibility with the old converter.
    """
    content = element["content"]
    default = (element.get("font_weight", "regular") == "bold",
               element.get("font_style", "normal") == "italic",
               element.get("color", "rgba(0,0,0,1)"))
    styles = [default] * len(content)
    for run in element.get("style_runs") or []:
        start = max(0, run["start"])
        end = min(len(content), run["end"] + int(inclusive_end))
        for i in range(start, end):
            bold, italic, color = styles[i]
            styles[i] = (run.get("font_weight", "bold" if bold else "regular") == "bold",
                         run.get("font_style", "italic" if italic else "normal") == "italic",
                         run.get("color", color))
    return styles


@lru_cache(maxsize=64)
def _typeface(manager, family, bold, italic):
    style = "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"
    data = manager.lookup(family, "bold" if bold else "regular", style)
    return skia.Typeface.MakeFromData(data)


@lru_cache(maxsize=4096)
def _glyphs(manager, family, bold, italic, size, content):
    font = skia.Font(_typeface(manager, family, bold, italic), size)
    glyphs = font.textToGlyphs(content)
    widths = tuple(font.getWidths(glyphs))
    ascent = -font.getMetrics().fAscent
    boxes = tuple((b.left(), b.top() + ascent, b.right(), b.bottom() + ascent)
                  for b in font.getBounds(glyphs))
    return widths, boxes


def _character_data(element, manager, size, styles):
    widths, boxes = [], []
    for style, indices in groupby(range(len(styles)), key=styles.__getitem__):
        indices = list(indices)
        content = element["content"][indices[0]:indices[-1] + 1]
        advances, bounds = _glyphs(manager, element["font_family"], *style[:2], size, content)
        widths.extend(advances)
        boxes.extend(bounds)
    return widths, boxes


def measure_text(element, manager, size=None, legacy=False):
    """Measure wrapped advances, line height and actual glyph ink bounds.

    legacy=True models the supplied converter's base-font wrapping and its
    inclusive style-run ends. The engine checks both interpretations.
    """
    content = element["content"]
    if not content:
        return TextLayout("", 0, 0, (0, 0, 0, 0))
    size = element["font_size"] if size is None else size
    styles = text_styles(element, inclusive_end=legacy)
    widths, boxes = _character_data(element, manager, max(1, int(size)), styles)
    spacing = element.get("letter_spacing", 0)
    if legacy:
        bold = element.get("font_weight", "regular") == "bold"
        italic = element.get("font_style", "normal") == "italic"
        # char_widths uses the float size, just as the original converter did.
        wrap_widths = _glyphs(manager, element["font_family"], bold, italic, size, content)[0]
    else:
        wrap_widths = [w + (spacing if i + 1 < len(content) and styles[i] == styles[i + 1]
                            and content[i + 1] != "\n" else 0)
                       for i, w in enumerate(widths)]
    wrapped = wrap_text(content, wrap_widths, element["width"])
    ink, line_widths, start = [], [], 0
    lines = wrapped.split("\n")
    for line_no, line in enumerate(lines):
        cursor = 0
        line_boxes = []
        for i in range(start, start + len(line)):
            left, top, right, bottom = boxes[i]
            if right > left and bottom > top:
                line_boxes.append((cursor + left, top, cursor + right, bottom))
            cursor += widths[i]
            if i + 1 < start + len(line) and styles[i] == styles[i + 1]:
                cursor += spacing
        offset = {"left": 0, "center": (element["width"] - cursor) / 2,
                  "right": element["width"] - cursor}.get(element.get("text_align", "left"), 0)
        y = line_no * size * element.get("line_height", 1.2)
        ink.extend((l + offset, t + y, r + offset, b + y) for l, t, r, b in line_boxes)
        # Keep enough width for both wrapping (float size in the legacy
        # converter) and drawing (integer size in cr-renderer).
        line_widths.append(max(cursor, sum(wrap_widths[start:start + len(line)])))
        start += len(line) + 1
    bounds = ((min(b[0] for b in ink), min(b[1] for b in ink),
               max(b[2] for b in ink), max(b[3] for b in ink)) if ink else (0, 0, 0, 0))
    height = max(len(lines) * size * element.get("line_height", 1.2), bounds[3])
    return TextLayout(wrapped, max(line_widths, default=0), height, bounds)
