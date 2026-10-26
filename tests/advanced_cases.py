"""Independent dense designs for extreme-aspect and variable-count testing."""

from tests.layout_cases import button, image, text


def advanced_design(badges=5, images=2):
    elements = [dict(id="canvas-art", type="shape", shape_type="rectangle",
                     x=0, y=0, width=1200, height=1600, z_index=0,
                     fill_color="rgba(40,25,47,1)"),
                text("announcement", "A weekend of fresh ideas, seasonal discoveries, and unexpected connections",
                     100, 500, 1000, 180, 48, font_weight="bold"),
                text("invitation", "Meet the makers, try something new, and enjoy a carefully curated selection of botanical blends. "
                     "Join us for conversations, tastings, and bright moments to share with friends.",
                     100, 720, 1000, 230, 25),
                text("conditions", "Reservations are required. Dates and availability may change. "
                     "Visit the event page for accessibility information and complete terms.",
                     60, 1490, 1080, 80, 12)]
    for i in range(images):
        asset = "solstice_logo_lockup.png" if i == 0 else "solstice_bottle.png"
        elements.append(image(f"picture-{i}", asset, 80 + i * 220, 100, 200, 200,
                              rotation=10 if i > 1 else 0))
    for i in range(badges):
        elements.extend(button(f"session-{i}", f"Session {i + 1}: Discover more",
                               50 + (i % 3) * 370, 1000 + (i // 3) * 95, 340, 72, 18))
    ribbon = button("ribbon", "EARLY ACCESS", 750, 50, 350, 74, 22)
    for el in ribbon:
        el["rotation"] = -16
    elements.extend(ribbon)
    return dict(canvas=dict(width=1200, height=1600), elements=elements)


def awkward_design():
    source = advanced_design(badges=3, images=1)
    headline = next(e for e in source["elements"] if e["id"] == "announcement")
    headline.update(content="Antidisestablishmentarianism" * 3, max_lines=1,
                    letter_spacing=0.1, style_runs=[dict(start=0, end=40, font_style="italic")])
    paragraph = next(e for e in source["elements"] if e["id"] == "invitation")
    paragraph.update(content="A new idea.\nA different perspective.\nA moment worth sharing.", max_lines=3)
    return source


def image_collection(count=16):
    source = dict(canvas=dict(width=1200, height=1200), elements=[
        dict(id="backdrop", type="shape", shape_type="rectangle", x=0, y=0,
             width=1200, height=1200, fill_color="rgba(40,25,47,1)", z_index=0)])
    for i in range(count):
        source["elements"].append(image(f"photo-{i}", "solstice_bottle.png",
                                        40 + (i % 4) * 290, 40 + (i // 4) * 290, 250, 250))
    return source


EXTREME_TARGETS = [(728, 90), (970, 90), (320, 50), (160, 600), (90, 728), (300, 250)]
