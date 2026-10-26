"""Small, deterministic packing helpers. All returned regions are disjoint."""


def pack_rectangles(sizes, region, gap, vertical_first=True):
    """Pack large rectangles first, splitting each remaining cell in two."""
    free = [region]
    placed = [None] * len(sizes)
    order = sorted(range(len(sizes)), key=lambda i: sizes[i][0] * sizes[i][1], reverse=True)
    for i in order:
        w, h = sizes[i]
        fitting = [(fw * fh - w * h, index) for index, (_, _, fw, fh) in enumerate(free)
                   if w <= fw + 1e-6 and h <= fh + 1e-6]
        if not fitting:
            return None
        _, index = min(fitting)
        x, y, fw, fh = free.pop(index)
        placed[i] = (x, y, w, h)
        if vertical_first:
            remaining = [(x + w + gap, y, fw - w - gap, fh),
                         (x, y + h + gap, w, fh - h - gap)]
        else:
            remaining = [(x + w + gap, y, fw - w - gap, h),
                         (x, y + h + gap, fw, fh - h - gap)]
        free.extend(box for box in remaining if box[2] > 0 and box[3] > 0)
    return placed


def flow_rows(sizes, width, gap):
    """Break an ordered sequence into rows with the smallest total height.

    Try every row ending at each item. Keeping the cheapest prefix gives the
    best row breaks without enumerating every possible combination.
    """
    costs, previous = [0] + [float("inf")] * len(sizes), [0] * (len(sizes) + 1)
    for end in range(1, len(sizes) + 1):
        row_w, row_h = 0, 0
        for start in range(end - 1, -1, -1):
            w, h = sizes[start]
            row_w += w + (gap if start < end - 1 else 0)
            row_h = max(row_h, h)
            if row_w > width + 1e-6:
                break
            cost = costs[start] + row_h + (gap if start else 0)
            if cost < costs[end]:
                costs[end], previous[end] = cost, start
    if costs[-1] == float("inf"):
        return None
    rows, end = [], len(sizes)
    while end:
        start = previous[end]
        rows.append((start, end))
        end = start
    placed, y = [None] * len(sizes), 0
    for start, end in reversed(rows):
        row_w = sum(sizes[i][0] for i in range(start, end)) + gap * (end - start - 1)
        row_h = max(sizes[i][1] for i in range(start, end))
        x = (width - row_w) / 2
        for i in range(start, end):
            w, h = sizes[i]
            placed[i] = (x, y + (row_h - h) / 2, w, h)
            x += w + gap
        y += row_h + gap
    return placed, costs[-1]


def balanced_columns(heights, columns, gap):
    """Split ordered blocks into columns, minimizing the tallest column."""
    n = len(heights)
    prefix = [0]
    for height in heights:
        prefix.append(prefix[-1] + height)
    costs = [[float("inf")] * (n + 1) for _ in range(columns + 1)]
    previous = [[0] * (n + 1) for _ in range(columns + 1)]
    costs[0][0] = 0
    for count in range(1, columns + 1):
        for end in range(count, n + 1):
            for start in range(count - 1, end):
                height = prefix[end] - prefix[start] + gap * (end - start - 1)
                cost = max(costs[count - 1][start], height)
                if cost < costs[count][end]:
                    costs[count][end], previous[count][end] = cost, start
    ranges, end = [], n
    for count in range(columns, 0, -1):
        start = previous[count][end]
        ranges.append((start, end))
        end = start
    return list(reversed(ranges)), costs[columns][n]
