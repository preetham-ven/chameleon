"""Readability diagnostics, separate from structural validity and scoring."""

from math import sqrt

from engine.resize import READABLE_FONT, _background, _image_area, _visible_bounds


def assess_quality(source, output):
    """Report native pixel sizes; fitting text is not automatically readable.

    Below 8 px is a serious readability warning, 8–11 px still needs visual
    review, and 12 px meets our soft font floor. These are local checks, not
    the challenge evaluator or a guarantee of design quality.
    """
    originals = {el["id"]: el for el in source["elements"]}
    text = [el for el in output["elements"] if el["type"] == "text" and el["content"].strip()]
    sizes = {el["id"]: int(el["font_size"]) for el in text}
    minimum = min(sizes.values(), default=None)
    largest_source = max((originals[el["id"]]["font_size"] for el in text), default=0)
    primary = [el for el in text if originals[el["id"]]["font_size"] == largest_source]
    if minimum is None:
        readability = "no_text"
    elif minimum < 8:
        readability = "too_small"
    elif minimum < READABLE_FONT:
        readability = "small_text"
    else:
        readability = "meets_font_floor"

    images = []
    desired = min(48, min(output["canvas"].values()) * 0.5)
    for el in output["elements"]:
        if el["type"] != "image" or _background(originals[el["id"]], source["canvas"]):
            continue
        available = _image_area(el) > 0
        _, _, width, height = _visible_bounds(el)
        images.append(dict(id=el["id"], asset_available=available,
                           visible_width=round(width, 1), visible_height=round(height, 1),
                           small_artwork=available and sqrt(_image_area(el)) < desired))
    return dict(readability=readability, minimum_rendered_font=minimum,
                primary_text_font=min((int(el["font_size"]) for el in primary), default=None),
                text_sizes=sizes, text_below_8px=[key for key, size in sizes.items() if size < 8],
                text_below_12px=[key for key, size in sizes.items() if size < READABLE_FONT],
                images=images)
