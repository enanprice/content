"""Props: simple drawable objects.

Every prop is a function `prop(canvas, x, y, ...)` working in logical
pixels, with (x, y) at the prop's centre unless noted. Animated props take
a 0..1 parameter (open, level, pop, grow, progress, ...) that you drive
from easing functions - the props themselves hold no state.
"""

import math

from . import config
from .easing import clamp, lerp

INK = config.INK


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _shade(color, k):
    """Darken (k < 1) or lighten (k > 1) an RGB colour."""
    return tuple(int(clamp(v * k, 0, 255)) for v in color)


def _mix(a, b, t):
    return tuple(int(lerp(x, y, t)) for x, y in zip(a, b))


def _arc(cx, cy, r, a0, a1, n=14):
    """Points along a circular arc; angles in degrees, clockwise from 3 o'clock."""
    return [(cx + r * math.cos(math.radians(lerp(a0, a1, i / n))),
             cy + r * math.sin(math.radians(lerp(a0, a1, i / n)))) for i in range(n + 1)]


def _partial(pts, fraction):
    """The first `fraction` (0..1) of a polyline, measured by length."""
    fraction = clamp(fraction)
    lengths = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
    remaining = sum(lengths) * fraction
    out = [pts[0]]
    for (a, b), seg in zip(zip(pts, pts[1:]), lengths):
        if seg <= remaining:
            out.append(b)
            remaining -= seg
        else:
            if seg > 0 and remaining > 0:
                k = remaining / seg
                out.append((lerp(a[0], b[0], k), lerp(a[1], b[1], k)))
            break
    return out


def backdrop(c, ground_y, floor=config.FLOOR):
    """Floor band from ground_y to the bottom of the frame.

    Pure background, so it is allowed to run into the unsafe bottom strip.
    """
    c.rect((0, ground_y, c.w, c.h), fill=floor)
    c.line((0, ground_y), (c.w, ground_y), _shade(floor, 0.9), 6)


# ---------------------------------------------------------------------------
# phone
# ---------------------------------------------------------------------------
_FEED_COLORS = [config.BLUE, config.ORANGE, config.PINK, config.GREEN, config.PURPLE]


def phone(c, x, y, h=220, angle=0.0, scroll=0.0, screen_on=True):
    """Smartphone showing a social feed.

    angle   clockwise rotation in degrees
    scroll  feed position in "posts"; increase it over time to scroll
    """
    w = h * 0.52
    pad = 10
    tile = c.sub(w + 2 * pad, h + 2 * pad)        # drawn upright, rotated on paste
    tile.rect((pad, pad, pad + w, pad + h), fill=(52, 54, 66), outline=INK, width=5, radius=w * 0.17)

    m = w * 0.09
    sw, sh = w - 2 * m, h - 2 * m
    screen = c.sub(sw, sh)                        # its own tile, so the feed is clipped
    if screen_on:
        screen.rect((0, 0, sw, sh), fill=(244, 246, 251), radius=w * 0.09)
        card = sh * 0.46
        first = math.floor(scroll)
        for i in range(-1, 4):
            top = (i - (scroll - first)) * card + card * 0.08
            color = _FEED_COLORS[(i + first) % len(_FEED_COLORS)]
            screen.circle((sw * 0.16, top + card * 0.11), sw * 0.08, fill=color)
            screen.line((sw * 0.32, top + card * 0.11), (sw * 0.72, top + card * 0.11), config.GREY, sw * 0.06)
            screen.rect((sw * 0.08, top + card * 0.26, sw * 0.92, top + card * 0.84),
                        fill=_mix(color, config.WHITE, 0.35), radius=sw * 0.06)
    else:
        screen.rect((0, 0, sw, sh), fill=(24, 25, 32), radius=w * 0.09)
        screen.line((sw * 0.2, sh * 0.12), (sw * 0.5, sh * 0.06), (60, 62, 76), sw * 0.04)
    tile.paste(screen, (pad + w / 2, pad + h / 2))
    c.paste(tile, (x, y), angle)


# ---------------------------------------------------------------------------
# book
# ---------------------------------------------------------------------------
def book(c, x, y, w=150, h=200, open=0.0, color=config.RED):
    """Book whose SPINE is centred on (x, y).

    open=0 is closed (occupying x..x+w); open=1 lies flat (x-w..x+w). In
    between, the front cover swings from the right side over to the left.
    """
    top, bot = y - h / 2, y + h / 2
    o = clamp(open)
    edge = max(3.0, h * 0.025)

    # Back cover and the page block resting on it.
    c.rect((x, top, x + w, bot), fill=_shade(color, 0.8), outline=INK, width=edge, radius=h * 0.03)
    c.rect((x + edge, top + h * 0.045, x + w - h * 0.045, bot - h * 0.045), fill=config.PAPER)
    for i in range(6):
        ly = top + h * (0.2 + 0.11 * i)
        c.line((x + w * 0.16, ly), (x + w * (0.8 if i < 5 else 0.5), ly), config.GREY, h * 0.02)

    # Front cover as a parallelogram: its free edge swings through 180 deg
    # and lifts slightly mid-swing for a hint of perspective.
    theta = o * math.pi
    ext = w * math.cos(theta)
    lift = h * 0.1 * math.sin(theta)

    def pt(u, v):
        """Point on the cover: u = 0 at the spine .. 1 at the free edge, v = 0 top .. 1 bottom."""
        return (x + ext * u, top + h * v - lift * u)

    cover = [pt(0, 0), pt(1, 0), pt(1, 1), pt(0, 1)]
    if theta < math.pi / 2:
        # Still facing us: we see the outside of the cover.
        c.polygon(cover, fill=color, outline=INK, width=edge)
        if ext > w * 0.45:
            c.polygon([pt(0.2, 0.18), pt(0.8, 0.18), pt(0.8, 0.42), pt(0.2, 0.42)],
                      fill=_mix(color, config.WHITE, 0.75))
            c.line(pt(0.3, 0.30), pt(0.7, 0.30), _shade(color, 0.7), h * 0.022)
    else:
        # Swung past vertical: we see the inside, i.e. the left-hand page.
        c.polygon(cover, fill=_shade(color, 0.9), outline=INK, width=edge)
        if abs(ext) > w * 0.15:
            c.polygon([pt(0.02, 0.045), pt(0.93, 0.045), pt(0.93, 0.955), pt(0.02, 0.955)], fill=config.PAPER)
            for i in range(6):
                v = 0.2 + 0.11 * i
                c.line(pt(0.84 if i else 0.6, v), pt(0.2, v), config.GREY, h * 0.02)
    c.line((x, top), (x, bot), INK, edge)        # spine


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------
def clock(c, x, y, r=100, time=10.17, face=config.WHITE):
    """Analogue clock. `time` is in hours (10.5 = half past ten); animate it to spin the hands."""
    c.circle((x, y), r, fill=face, outline=INK, width=r * 0.09)
    for i in range(12):
        a = math.radians(i * 30)
        inner = r * (0.70 if i % 3 == 0 else 0.78)
        c.line((x + math.sin(a) * inner, y - math.cos(a) * inner),
               (x + math.sin(a) * r * 0.84, y - math.cos(a) * r * 0.84), INK, r * 0.045)
    hour_a = math.radians((time % 12) / 12 * 360)
    min_a = math.radians((time % 1) * 360)
    c.line((x, y), (x + math.sin(hour_a) * r * 0.45, y - math.cos(hour_a) * r * 0.45), INK, r * 0.10)
    c.line((x, y), (x + math.sin(min_a) * r * 0.68, y - math.cos(min_a) * r * 0.68), config.RED, r * 0.065)
    c.circle((x, y), r * 0.075, fill=INK)


# ---------------------------------------------------------------------------
# brain
# ---------------------------------------------------------------------------
# Lobes as (x, y, radius) in units of half the brain width.
_BRAIN_LOBES = [(-0.52, -0.18, 0.40), (-0.18, -0.42, 0.42), (0.26, -0.40, 0.42), (0.60, -0.10, 0.38),
                (0.44, 0.22, 0.36), (0.02, 0.24, 0.42), (-0.40, 0.20, 0.38), (0.0, -0.08, 0.5)]


def brain(c, x, y, size=200, color=config.PINK):
    """Cartoon brain, `size` px wide."""
    u = size / 2
    edge = max(3.0, size * 0.03)
    # Stem first, then every lobe in ink slightly oversized, then again in
    # colour: the union of circles gets one clean outline.
    c.rect((x + u * 0.12, y + u * 0.38, x + u * 0.40, y + u * 0.82),
           fill=_shade(color, 0.85), outline=INK, width=edge, radius=u * 0.1)
    for lx, ly, lr in _BRAIN_LOBES:
        c.circle((x + lx * u, y + ly * u), lr * u + edge, fill=INK)
    for lx, ly, lr in _BRAIN_LOBES:
        c.circle((x + lx * u, y + ly * u), lr * u, fill=color)
    fold = _shade(color, 0.72)
    for cx, cy, r, a0, a1 in [(-0.50, -0.20, 0.22, 200, 400), (-0.10, -0.42, 0.24, 160, 350),
                              (0.34, -0.36, 0.22, 190, 380), (0.52, 0.10, 0.2, 250, 450),
                              (0.02, 0.20, 0.24, 20, 200), (-0.42, 0.22, 0.18, 60, 250),
                              (0.05, -0.08, 0.16, 280, 470)]:
        c.polyline(_arc(x + cx * u, y + cy * u, r * u, a0, a1), fold, edge * 0.9)


# ---------------------------------------------------------------------------
# battery meter
# ---------------------------------------------------------------------------
def battery(c, x, y, w=260, h=120, level=0.5, charging=False):
    """Battery whose fill goes red -> yellow -> green as `level` goes 0..1."""
    level = clamp(level)
    edge = max(3.0, h * 0.07)
    nub = w * 0.06
    left, top, right, bot = x - w / 2, y - h / 2, x + w / 2 - nub, y + h / 2
    c.rect((right - edge, y - h * 0.2, x + w / 2, y + h * 0.2), fill=INK, radius=h * 0.06)
    c.rect((left, top, right, bot), fill=config.WHITE, outline=INK, width=edge, radius=h * 0.18)

    if level < 0.5:
        color = _mix(config.RED, config.YELLOW, max(0.0, level - 0.15) / 0.35)
    else:
        color = _mix(config.YELLOW, config.GREEN, min(1.0, (level - 0.5) / 0.3))
    gap = edge * 1.9
    fill_w = (right - left - 2 * gap) * level
    if fill_w > 3:
        c.rect((left + gap, top + gap, left + gap + fill_w, bot - gap), fill=color, radius=h * 0.08)

    if charging:
        cx, cy, s = (left + right) / 2, y, h * 0.36
        bolt = [(cx + 0.15 * s, cy - s), (cx - 0.55 * s, cy + 0.15 * s), (cx - 0.05 * s, cy + 0.15 * s),
                (cx - 0.15 * s, cy + s), (cx + 0.55 * s, cy - 0.15 * s), (cx + 0.05 * s, cy - 0.15 * s)]
        c.polygon(bolt, fill=config.YELLOW, outline=INK, width=edge * 0.55)


# ---------------------------------------------------------------------------
# thought bubble
# ---------------------------------------------------------------------------
def thought_bubble(c, x, y, w=300, h=220, tail_to=None, pop=1.0):
    """Cloud-shaped bubble with a trail of dots towards `tail_to`.

    pop scales the bubble (0 = hidden); ease it with ease_out_back for a
    pop-in. Draw the bubble's contents yourself, centred on (x, y).
    """
    if pop <= 0.02:
        return
    w, h = w * pop, h * pop
    edge = max(3.0, 6 * min(pop, 1.0))
    lump = h * 0.27
    lumps = [(x + (w / 2 - lump * 0.85) * math.cos(a), y + (h / 2 - lump * 0.85) * math.sin(a))
             for a in (math.radians(i * 36 + 10) for i in range(10))]
    dots = []
    if tail_to is not None:
        dx, dy = tail_to[0] - x, tail_to[1] - y
        dist = math.hypot(dx, dy) or 1.0
        sx, sy = x + dx / dist * h * 0.5, y + dy / dist * h * 0.5   # leave from the cloud's edge
        dots = [((lerp(sx, tail_to[0], f), lerp(sy, tail_to[1], f)), r * pop)
                for f, r in ((0.28, 24), (0.58, 16), (0.85, 10))]

    core = (x - w / 2 + lump * 0.7, y - h / 2 + lump * 0.7, x + w / 2 - lump * 0.7, y + h / 2 - lump * 0.7)
    for p in lumps:                                  # ink pass (outline)
        c.circle(p, lump + edge, fill=INK)
    for p, r in dots:
        c.circle(p, r + edge, fill=INK)
    for p in lumps:                                  # white pass (fill)
        c.circle(p, lump, fill=config.WHITE)
    for p, r in dots:
        c.circle(p, r, fill=config.WHITE)
    c.ellipse(core, fill=config.WHITE)


# ---------------------------------------------------------------------------
# checklist
# ---------------------------------------------------------------------------
def checklist(c, x, y, w=320, h=420, items=4, checked=0.0):
    """Clipboard-style list.

    items    number of rows, or a list of strings to print as labels
    checked  how many rows are ticked. Fractions draw the next tick
             part-way (2.5 = two ticks and half of the third).
    """
    labels = items if isinstance(items, (list, tuple)) else [None] * items
    n = len(labels)
    left, top = x - w / 2, y - h / 2
    c.rect((left, top, left + w, top + h), fill=config.PAPER, outline=INK, width=6, radius=18)
    c.rect((x - w * 0.2, top - 16, x + w * 0.2, top + 26), fill=config.GREY, outline=INK, width=5, radius=10)

    row_h = (h - 70) / n
    box = min(44.0, row_h * 0.6)
    for i, label in enumerate(labels):
        cy = top + 56 + row_h * (i + 0.5)
        bx = left + 30
        done = clamp(checked - i)
        c.rect((bx, cy - box / 2, bx + box, cy + box / 2), fill=config.WHITE, outline=INK, width=5, radius=6)
        tx = bx + box + 22
        if label:
            c.text((tx, cy), label, box * 0.62, config.GREY if done >= 1 else INK, anchor="lm")
        else:
            c.line((tx, cy), (left + w - 34, cy), config.GREY, 9)
        if done > 0:
            tick = [(bx + box * 0.12, cy + box * 0.02), (bx + box * 0.42, cy + box * 0.30),
                    (bx + box * 1.02, cy - box * 0.42)]
            c.polyline(_partial(tick, done), config.GREEN, 10)


# ---------------------------------------------------------------------------
# bar chart
# ---------------------------------------------------------------------------
def bar_chart(c, x, y, w=360, h=300, values=(0.3, 0.55, 0.9), colors=None, grow=1.0, labels=None):
    """Bar chart with values in 0..1.

    grow 0..1 raises the bars one after another, left to right.
    """
    colors = colors or [config.BLUE, config.ORANGE, config.GREEN, config.PURPLE, config.RED]
    n = len(values)
    left, right, top, bottom = x - w / 2, x + w / 2, y - h / 2, y + h / 2
    slot = (w - 30) / n
    bar_w = slot * 0.62
    for i, v in enumerate(values):
        # Stagger: each bar starts a little after the previous one.
        g = clamp(grow * (1 + 0.3 * (n - 1)) - 0.3 * i)
        bh = (h - 24) * clamp(v) * g
        bx = left + 22 + slot * i + (slot - bar_w) / 2
        if bh > 6:
            c.rect((bx, bottom - bh, bx + bar_w, bottom), fill=colors[i % len(colors)], outline=INK, width=5)
        if labels:
            c.text((bx + bar_w / 2, bottom + 14), labels[i], 26, INK, anchor="mt")
    c.polyline([(left, top), (left, bottom), (right, bottom)], INK, 8)


# ---------------------------------------------------------------------------
# arrows
# ---------------------------------------------------------------------------
def arrow(c, start, end, color=INK, width=14, head=None, progress=1.0, curve=0.0):
    """Arrow from `start` to `end` (the tip lands exactly on `end`).

    progress  0..1 draws the arrow on progressively
    curve     bends the shaft sideways; 0.3 is a gentle arc, sign picks the side
    """
    if progress <= 0.02:
        return
    head = head or width * 3.2
    (x0, y0), (x1, y1) = start, end
    length = math.hypot(x1 - x0, y1 - y0) or 1.0
    # Quadratic bezier with the control point pushed out perpendicular to the line.
    cx = (x0 + x1) / 2 - (y1 - y0) / length * curve * length
    cy = (y0 + y1) / 2 + (x1 - x0) / length * curve * length
    path = []
    for i in range(25):
        t = i / 24
        path.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1,
                     (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1))
    path = _partial(path, progress)
    if len(path) < 2:
        return
    tip = path[-1]
    # Direction at the tip, measured a head-length back so short final
    # segments don't make the head twitch.
    back = next((p for p in reversed(path) if math.dist(p, tip) >= head * 0.8), path[0])
    d = math.dist(back, tip) or 1.0
    ux, uy = (tip[0] - back[0]) / d, (tip[1] - back[1]) / d
    base = (tip[0] - ux * head, tip[1] - uy * head)
    # Shaft stops at the base of the head so it never pokes through the tip.
    shaft = [p for p in path if math.dist(p, tip) > head] + [base]
    if len(shaft) >= 2:
        c.polyline(shaft, color, width)
    half = head * 0.55
    c.polygon([tip, (base[0] - uy * half, base[1] + ux * half), (base[0] + uy * half, base[1] - ux * half)],
              fill=color, outline=color, width=width * 0.25)


# ---------------------------------------------------------------------------
# extra: floating "Zzz" for the sleeping pose
# ---------------------------------------------------------------------------
def zzz(c, x, y, t, size=44, color=config.BLUE):
    """Three Z's drifting up and to the right from (x, y). `t` is time in seconds."""
    for i in range(3):
        phase = (t * 0.45 + i / 3) % 1.0
        s = size * (0.45 + 0.9 * phase) * min(1.0, (1 - phase) * 6)   # grow, then blink out
        if s < 4:
            continue
        zx = x + 110 * phase + 12 * math.sin(phase * 9)
        zy = y - 170 * phase
        c.polyline([(zx - s / 2, zy - s / 2), (zx + s / 2, zy - s / 2),
                    (zx - s / 2, zy + s / 2), (zx + s / 2, zy + s / 2)], color, max(3.0, s * 0.2))
