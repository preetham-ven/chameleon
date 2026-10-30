from PIL import Image, ImageDraw

from .colorutil import parse_rgba


def _color(value, default):
    r, g, b, alpha = parse_rgba(value, default=default)
    return r, g, b, round(255 * alpha)


def render_shape(element: dict) -> Image.Image:
    """Rasterize a `shape` element to an RGBA PIL image.

    Crello's schema has no notion of vector shapes (only text/image
    elements), so shapes are pre-rendered to a PNG here and handed to
    cr-renderer as a regular image element. The element's own `opacity` is
    NOT baked in here - cr-renderer applies that separately as paint alpha
    when it composites the image, so baking it in too would double it up.
    """
    width = max(1, round(element.get("width", 1)))
    height = max(1, round(element.get("height", 1)))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    fill = _color(element.get("fill_color"), (200, 200, 200, 1.0))
    stroke = (_color(element["stroke_color"], (0, 0, 0, 1.0))
              if element.get("stroke_color") else None)
    stroke_width = max(0, round(element.get("stroke_width", 0)))
    if not stroke_width:
        stroke = None
    bounds = [0, 0, width - 1, height - 1]

    shape_type = element.get("shape_type", "rectangle")
    if shape_type == "ellipse":
        draw.ellipse(bounds, fill=fill, outline=stroke, width=stroke_width)
    elif shape_type == "line":
        stroke = _color(element.get("stroke_color") or element.get("fill_color"), (0, 0, 0, 1.0))
        draw.line([0, height // 2, width - 1, height // 2], fill=stroke, width=max(1, stroke_width))
    else:
        radius = max(0, min(element.get("corner_radius", 0), width / 2, height / 2))
        if radius > 0:
            draw.rounded_rectangle(bounds, radius=radius, fill=fill, outline=stroke, width=stroke_width)
        else:
            draw.rectangle(bounds, fill=fill, outline=stroke, width=stroke_width)

    return image
