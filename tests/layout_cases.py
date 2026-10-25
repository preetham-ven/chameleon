"""Independent compositions for generalization tests and visual review."""

from copy import deepcopy


def text(identity, content, x, y, width, height, size, **extra):
    return dict(id=identity, type="text", content=content, x=x, y=y, width=width,
                height=height, font_size=size, font_family="Solstice Sans",
                color="rgba(255,255,255,1)", z_index=4, **extra)


def image(identity, asset, x, y, width, height, **extra):
    return dict(id=identity, type="image", asset_id=asset, x=x, y=y, width=width,
                height=height, fit="contain", z_index=2, **extra)


def button(identity, content, x, y, width, height, size):
    return [dict(id=identity + "-surface", type="shape", shape_type="rectangle",
                 x=x, y=y, width=width, height=height, fill_color="rgba(232,106,58,1)",
                 corner_radius=height / 2, z_index=3, group_id=identity),
            text(identity + "-words", content, x + 12, y + 12, width - 24, height - 24,
                 size, group_id=identity, text_align="center")]


def layout_cases():
    background = dict(id="paper", type="shape", shape_type="rectangle", x=0, y=0,
                      width=1000, height=800, fill_color="rgba(45,26,47,1)", z_index=0)
    editorial = dict(canvas=dict(width=1000, height=800), elements=[
        background,
        image("mark", "solstice_logo_lockup.png", 50, 30, 240, 80),
        image("art", "solstice_bottle.png", 30, 170, 440, 440),
        text("intro", "A different kind of afternoon", 500, 160, 440, 150, 46,
             font_weight="bold", max_lines=3),
        text("details", "Small batches. Bright ingredients.\nMade to share with good company.",
             500, 345, 440, 160, 25, max_lines=4),
        *button("action", "Explore the collection", 530, 590, 350, 76, 22),
        dict(id="accent", type="shape", shape_type="ellipse", x=-40, y=570,
             width=260, height=260, fill_color="rgba(255,255,255,0.14)", z_index=1),
    ])
    text_heavy = dict(canvas=dict(width=1000, height=800), elements=[
        deepcopy(background),
        text("a", "Gather, taste, celebrate", 70, 60, 850, 110, 54, font_weight="bold"),
        text("b", "An evening of fresh ideas", 70, 210, 850, 80, 32),
        text("c", "Discover seasonal flavors with the people who make them.\nBring a friend and stay awhile.",
             70, 340, 850, 150, 25),
        *button("reservation", "Reserve your place", 70, 570, 350, 80, 24),
        *button("schedule", "See the schedule", 550, 570, 350, 80, 24),
    ])
    products = dict(canvas=dict(width=1000, height=800), elements=[
        deepcopy(background),
        text("message", "Find your favorite", 100, 40, 800, 100, 50, font_weight="bold"),
        image("first", "solstice_bottle.png", 40, 180, 390, 390),
        image("second", "solstice_bottle.png", 550, 180, 390, 390, rotation=12),
        text("description", "Two bright blends. One golden moment.", 80, 590, 840, 80, 26),
        *button("collection", "Meet the blends", 310, 690, 380, 70, 22),
    ])
    return {"editorial": editorial, "text_heavy": text_heavy, "products": products}


TARGETS = [(1600, 400), (1080, 1080), (1080, 1920), (1200, 628), (1920, 1080), (820, 312)]
