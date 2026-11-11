"""Settings: perspective rooms and outdoor scenes drawn behind the action.

Every indoor setting shares one room shell - back wall, side walls, ceiling
and a floor whose boards converge on a vanishing point - then adds its own
furniture. project() maps a floor position (x, depth) to the screen, so a
figure can walk towards or away from the camera and shrink or grow the
right amount. That shared geometry is what gives the scenes depth.

This is 2.5D, not a 3D engine: furniture is drawn as flat front views
against the back wall, and the figure is always drawn front-on or turned
slightly to walk.

Backgrounds use muted colours and soft outlines on purpose, so the figure,
prop and captions stay the clearest things on screen.
"""

import math
import random

from . import config, props
from .easing import lerp

# --- shared room geometry (logical px) ------------------------------------
VP = (540, 640)                         # vanishing point
WALL = (110, 150, 970, 1010)            # back wall: left, top, right, bottom
FRONT_Y = 1215                          # floor line where depth = 0 (closest to camera)
BACK_Y = WALL[3] + 30                   # floor line where depth = 1 (against the wall)

SETTINGS = ["plain", "bedroom", "desk", "living_room", "classroom", "library", "park"]
TIMES = ["day", "night"]


def project(x, depth=0.0):
    """Floor position -> (screen_x, ground_y, scale).

    x      position across the room, in px as measured at the front (depth 0)
    depth  0 = front of the room, 1 = against the back wall
    """
    ground_y = lerp(FRONT_Y, BACK_Y, depth)
    k = (ground_y - VP[1]) / (FRONT_Y - VP[1])
    return (VP[0] + (x - VP[0]) * k, ground_y, k)


def _shade(color, k):
    return tuple(int(min(255, max(0, v * k))) for v in color)


def _soft(color):
    """Outline colour for a filled shape: a darker tone of the fill, not black."""
    return _shade(color, 0.72)


def _ray_to(corner, x_edge):
    """Where the ray from the vanishing point through `corner` reaches x = x_edge."""
    t = (x_edge - VP[0]) / (corner[0] - VP[0])
    return (x_edge, VP[1] + (corner[1] - VP[1]) * t)


# ---------------------------------------------------------------------------
# room shell
# ---------------------------------------------------------------------------
def _shell(c, wall, floor, boards=True):
    left, top, right, bottom = WALL
    tl, tr = _ray_to((left, top), 0), _ray_to((right, top), c.w)
    bl, br = _ray_to((left, bottom), 0), _ray_to((right, bottom), c.w)
    c.rect((0, 0, c.w, c.h), fill=floor)
    c.polygon([(0, 0), (c.w, 0), tr, (right, top), (left, top), tl], fill=_shade(wall, 1.05))   # ceiling
    c.polygon([tl, (left, top), (left, bottom), bl], fill=_shade(wall, 0.92))                   # left wall
    c.polygon([tr, (right, top), (right, bottom), br], fill=_shade(wall, 0.92))                 # right wall
    c.rect((left, top, right, bottom), fill=wall)                                               # back wall

    if boards:                                   # floorboards converging on the vanishing point
        line = _shade(floor, 0.955)
        for i in range(-6, 17):
            x0 = left + (right - left) * i / 10
            dx, dy = x0 - VP[0], bottom - VP[1]
            k = (c.h - VP[1]) / dy
            c.line((x0, bottom), (VP[0] + dx * k, c.h), line, 4)
        # Redraw the side walls' lower edge so boards don't show through them.
        c.polygon([tl, (left, top), (left, bottom), bl], fill=_shade(wall, 0.92))
        c.polygon([tr, (right, top), (right, bottom), br], fill=_shade(wall, 0.92))

    trim = _shade(wall, 0.8)
    c.polyline([bl, (left, bottom), (right, bottom), br], trim, 12)       # skirting board
    for x in (left, right):
        c.line((x, top), (x, bottom), _shade(wall, 0.86), 4)              # wall corners
    c.polyline([tl, (left, top), (right, top), tr], _shade(wall, 0.86), 4)


# ---------------------------------------------------------------------------
# furniture (flat front views standing against the back wall)
# ---------------------------------------------------------------------------
FLOOR_LINE = WALL[3]


def _window(c, x, y, w, h, night=False, curtain=None):
    frame = (246, 243, 236)
    sky = (38, 46, 88) if night else (188, 224, 248)
    c.rect((x - 10, y - 10, x + w + 10, y + h + 10), fill=frame, outline=_soft(frame), width=4, radius=6)
    c.rect((x, y, x + w, y + h), fill=sky)
    if night:
        c.circle((x + w * 0.72, y + h * 0.28), w * 0.11, fill=(244, 240, 214))
        c.circle((x + w * 0.67, y + h * 0.25), w * 0.10, fill=sky)                     # crescent
        for sx, sy in ((0.2, 0.2), (0.38, 0.5), (0.15, 0.7), (0.55, 0.15), (0.8, 0.62)):
            c.circle((x + w * sx, y + h * sy), 3, fill=(230, 232, 250))
    else:
        view = c.sub(w, h)                        # own layer, so the hills are clipped to the pane
        view.rect((0, 0, w, h), fill=sky)
        view.ellipse((-w * 0.2, h * 0.68, w * 0.7, h * 1.3), fill=(170, 208, 160))
        view.ellipse((w * 0.4, h * 0.78, w * 1.3, h * 1.4), fill=(150, 196, 146))
        view.ellipse((w * 0.12, h * 0.16, w * 0.46, h * 0.32), fill=(250, 252, 255))
        view.ellipse((w * 0.3, h * 0.1, w * 0.6, h * 0.3), fill=(250, 252, 255))
        c.paste(view, (x + w / 2, y + h / 2))
    c.rect((x - 10, y + h, x + w + 10, y + h + 18), fill=frame, outline=_soft(frame), width=4, radius=4)
    c.line((x + w / 2, y), (x + w / 2, y + h), frame, 8)
    c.line((x, y + h / 2), (x + w, y + h / 2), frame, 8)
    if curtain:
        for sx in (x - 26, x + w - 30):
            c.polygon([(sx, y - 24), (sx + 56, y - 24), (sx + 44, y + h + 30), (sx + 6, y + h + 30)],
                      fill=curtain, outline=_soft(curtain), width=4)
        c.line((x - 40, y - 26), (x + w + 40, y - 26), _soft(curtain), 8)


def _door(c, x, w=190, h=520, color=(214, 190, 160)):
    top = FLOOR_LINE - h
    c.rect((x - 12, top - 12, x + w + 12, FLOOR_LINE), fill=_shade(color, 1.12), outline=_soft(color), width=4)
    c.rect((x, top, x + w, FLOOR_LINE), fill=color, outline=_soft(color), width=4)
    for py in (top + 36, top + h * 0.54):
        c.rect((x + 26, py, x + w - 26, py + h * 0.36), outline=_soft(color), width=4, radius=4)
    c.circle((x + w - 30, top + h * 0.52), 9, fill=(236, 204, 110), outline=_soft((236, 204, 110)), width=3)


def _bookshelf(c, x, top, w, h, rows=4, seed=1, wood=(196, 160, 122)):
    rng = random.Random(seed)                     # same books every frame
    c.rect((x, top, x + w, top + h), fill=_shade(wood, 0.82), outline=_soft(wood), width=5)
    row_h = h / rows
    spines = [(206, 104, 96), (104, 140, 196), (120, 172, 130), (226, 186, 104),
              (150, 122, 182), (222, 150, 110), (110, 168, 176), (232, 226, 210)]
    for r in range(rows):
        base = top + row_h * (r + 1) - 8
        bx = x + 12
        while bx < x + w - 26:
            bw = rng.randint(14, 28)
            bh = row_h * rng.uniform(0.55, 0.84)
            if rng.random() < 0.12:               # a gap, as if a book is missing
                bx += bw
                continue
            color = rng.choice(spines)
            c.rect((bx, base - bh, min(bx + bw, x + w - 12), base), fill=color, outline=_soft(color), width=3)
            bx += bw + 2
        c.rect((x, base, x + w, base + 8), fill=wood)                                   # shelf board


def _desk(c, x, w=380, height=200, wood=(206, 170, 130)):
    top = FLOOR_LINE + 34 - height
    for lx in (x + 18, x + w - 34):
        c.rect((lx, top, lx + 16, FLOOR_LINE + 34), fill=_shade(wood, 0.85), outline=_soft(wood), width=3)
    c.rect((x, top - 18, x + w, top + 6), fill=wood, outline=_soft(wood), width=4, radius=4)
    return top - 18                               # y of the desk surface


def _lamp(c, x, surface, color=(232, 190, 96)):
    c.rect((x - 26, surface - 10, x + 26, surface), fill=(120, 124, 138), radius=4)
    c.polyline([(x, surface - 10), (x - 8, surface - 78), (x + 30, surface - 120)], (120, 124, 138), 7)
    c.polygon([(x + 6, surface - 140), (x + 62, surface - 118), (x + 44, surface - 84), (x + 2, surface - 104)],
              fill=color, outline=_soft(color), width=4)


def _laptop(c, x, surface):
    body = (200, 204, 214)
    c.rect((x, surface - 92, x + 138, surface - 8), fill=(70, 76, 96), outline=_soft(body), width=5, radius=6)
    c.rect((x + 10, surface - 82, x + 128, surface - 18), fill=(178, 208, 236))
    c.rect((x - 14, surface - 10, x + 152, surface), fill=body, outline=_soft(body), width=3, radius=4)


def _book_stack(c, x, surface, n=3):
    for i, color in enumerate([(206, 104, 96), (104, 140, 196), (226, 186, 104)][:n]):
        c.rect((x + i * 5, surface - 18 * (i + 1), x + 104 - i * 4, surface - 18 * i),
               fill=color, outline=_soft(color), width=3, radius=3)


def _frame(c, x, y, w, h, color):
    """A poster or picture with a simple abstract design."""
    c.rect((x, y, x + w, y + h), fill=(248, 244, 234), outline=_soft((230, 220, 200)), width=5)
    c.rect((x + 12, y + 12, x + w - 12, y + h - 12), fill=_shade(color, 1.1))
    c.circle((x + w * 0.64, y + h * 0.36), min(w, h) * 0.16, fill=(250, 236, 190))
    c.polygon([(x + 12, y + h - 12), (x + w * 0.4, y + h * 0.5), (x + w * 0.7, y + h - 12)], fill=_shade(color, 0.8))


def _plant(c, x, pot=(206, 132, 104)):
    base = FLOOR_LINE + 30
    leaf = (120, 172, 126)
    for a, length in ((-50, 120), (-20, 160), (8, 175), (34, 150), (58, 110)):
        r = math.radians(a)
        tip = (x + math.sin(r) * length, base - 70 - math.cos(r) * length)
        mid = (x + math.sin(r) * length * 0.5 + math.cos(r) * 16, base - 70 - math.cos(r) * length * 0.5 + math.sin(r) * 16)
        c.polygon([(x, base - 66), mid, tip, (x + math.sin(r) * length * 0.5 - math.cos(r) * 16,
                                              base - 70 - math.cos(r) * length * 0.5 - math.sin(r) * 16)],
                  fill=leaf, outline=_soft(leaf), width=3)
    c.polygon([(x - 44, base - 72), (x + 44, base - 72), (x + 32, base), (x - 32, base)],
              fill=pot, outline=_soft(pot), width=4)


def _rug(c, x, y, rx, ry, color):
    c.ellipse((x - rx, y - ry, x + rx, y + ry), fill=color, outline=_soft(color), width=5)
    c.ellipse((x - rx * 0.8, y - ry * 0.74, x + rx * 0.8, y + ry * 0.74), outline=_shade(color, 1.12), width=5)


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------
def _bedroom(c, wall, floor, night):
    _shell(c, wall, floor)
    _window(c, 610, 430, 250, 250, night, curtain=(226, 170, 150))
    _frame(c, 150, 470, 150, 190, (150, 176, 214))
    # Bed along the back wall: headboard, mattress, pillow, duvet.
    wood, sheet, duvet = (196, 160, 122), (244, 240, 232), (134, 164, 206)
    base = FLOOR_LINE + 40
    c.rect((140, base - 250, 172, base), fill=wood, outline=_soft(wood), width=4, radius=8)
    c.rect((160, base - 120, 600, base - 20), fill=sheet, outline=_soft(sheet), width=4, radius=14)
    c.rect((180, base - 168, 300, base - 112), fill=(252, 250, 246), outline=_soft(sheet), width=4, radius=22)
    c.rect((300, base - 138, 604, base - 26), fill=duvet, outline=_soft(duvet), width=4, radius=18)
    c.rect((160, base - 30, 600, base), fill=wood, outline=_soft(wood), width=4, radius=4)
    # Bedside table with a lamp.
    c.rect((640, base - 130, 760, base), fill=wood, outline=_soft(wood), width=4, radius=4)
    c.line((656, base - 70), (744, base - 70), _soft(wood), 4)
    _lamp(c, 690, base - 130)
    _rug(c, 520, 1330, 360, 90, (214, 190, 204))


def _desk_room(c, wall, floor, night):
    _shell(c, wall, floor)
    _window(c, 150, 420, 230, 240, night)
    _bookshelf(c, 690, 440, 240, 250, rows=3, seed=4)
    # Pinboard with notes.
    cork = (214, 180, 140)
    c.rect((440, 450, 640, 600), fill=cork, outline=_soft(cork), width=5)
    for nx, ny, col in ((456, 466, (250, 240, 170)), (540, 474, (190, 226, 200)), (478, 532, (246, 200, 196)), (566, 528, (250, 250, 250))):
        c.rect((nx, ny, nx + 60, ny + 52), fill=col)
    surface = _desk(c, 420, 440)
    _laptop(c, 540, surface)
    _lamp(c, 470, surface)
    _book_stack(c, 730, surface)
    # Chair pushed back from the desk.
    seat = (120, 150, 178)
    c.rect((270, FLOOR_LINE - 150, 290, FLOOR_LINE + 70), fill=_shade(seat, 0.8), radius=6)
    c.rect((270, FLOOR_LINE - 60, 400, FLOOR_LINE - 36), fill=seat, outline=_soft(seat), width=4, radius=8)
    c.rect((380, FLOOR_LINE - 40, 396, FLOOR_LINE + 70), fill=_shade(seat, 0.8), radius=6)
    c.rect((262, FLOOR_LINE - 250, 298, FLOOR_LINE - 110), fill=seat, outline=_soft(seat), width=4, radius=10)


def _living_room(c, wall, floor, night):
    _shell(c, wall, floor)
    _window(c, 150, 420, 260, 250, night, curtain=(206, 190, 150))
    _frame(c, 500, 450, 130, 160, (226, 170, 150))
    _door(c, 730, w=180, h=500)
    # Sofa.
    sofa, base = (136, 170, 164), FLOOR_LINE + 44
    c.rect((150, base - 260, 640, base - 60), fill=sofa, outline=_soft(sofa), width=5, radius=36)
    c.rect((130, base - 190, 210, base - 10), fill=_shade(sofa, 0.94), outline=_soft(sofa), width=5, radius=28)
    c.rect((580, base - 190, 660, base - 10), fill=_shade(sofa, 0.94), outline=_soft(sofa), width=5, radius=28)
    c.rect((200, base - 140, 590, base - 30), fill=_shade(sofa, 1.08), outline=_soft(sofa), width=5, radius=22)
    c.line((395, base - 136), (395, base - 34), _soft(sofa), 4)
    c.rect((250, base - 230, 350, base - 138), fill=(232, 196, 120), outline=_soft((232, 196, 120)), width=4, radius=16)
    _rug(c, 540, 1340, 380, 92, (226, 206, 176))


def _classroom(c, wall, floor, night):
    _shell(c, wall, floor, boards=False)
    # Tiled floor: lines to the vanishing point plus cross lines that bunch up with distance.
    line = _shade(floor, 0.93)
    for i in range(-8, 19):
        x0 = WALL[0] + (WALL[2] - WALL[0]) * i / 10
        k = (c.h - VP[1]) / (FLOOR_LINE - VP[1])
        c.line((x0, FLOOR_LINE), (VP[0] + (x0 - VP[0]) * k, c.h), line, 4)
    y, step = FLOOR_LINE + 26, 34
    while y < c.h:
        c.line((0, y), (c.w, y), line, 4)
        step *= 1.34
        y += step
    _shell_sides(c, wall)
    # Whiteboard with faint writing.
    board = (250, 251, 248)
    c.rect((220, 440, 800, 760), fill=board, outline=(176, 180, 190), width=10, radius=6)
    ink = (150, 170, 200)
    for i, (x0, x1) in enumerate(((260, 560), (260, 640), (260, 500), (260, 600))):
        c.line((x0, 500 + i * 52), (x1, 500 + i * 52), ink, 6)
    c.circle((700, 580), 46, outline=(214, 150, 140), width=6)
    c.rect((440, 762, 580, 776), fill=(176, 180, 190), radius=4)
    props.clock(c, 880, 420, r=46, time=10.2 if not night else 8.6)
    # Teacher's desk.
    surface = _desk(c, 560, 340, height=190, wood=(200, 176, 146))
    _book_stack(c, 600, surface, n=2)
    c.circle((820, surface - 30), 30, fill=(214, 104, 96), outline=_soft((214, 104, 96)), width=4)   # apple
    c.line((820, surface - 58), (826, surface - 72), (110, 90, 70), 5)


def _shell_sides(c, wall):
    """Repaint the side walls and skirting (used after custom floor patterns)."""
    left, top, right, bottom = WALL
    tl, tr = _ray_to((left, top), 0), _ray_to((right, top), c.w)
    bl, br = _ray_to((left, bottom), 0), _ray_to((right, bottom), c.w)
    c.polygon([tl, (left, top), (left, bottom), bl], fill=_shade(wall, 0.92))
    c.polygon([tr, (right, top), (right, bottom), br], fill=_shade(wall, 0.92))
    c.polyline([bl, (left, bottom), (right, bottom), br], _shade(wall, 0.8), 12)


def _library(c, wall, floor, night):
    _shell(c, wall, floor)
    for i, x in enumerate((130, 420, 710)):
        _bookshelf(c, x, 300, 250, FLOOR_LINE + 20 - 300, rows=5, seed=10 + i, wood=(176, 140, 108))
    # Reading table with a lamp and an open book.
    surface = _desk(c, 560, 360, height=170, wood=(190, 152, 116))
    _lamp(c, 610, surface, color=(120, 176, 140))
    c.polygon([(700, surface - 6), (760, surface - 22), (820, surface - 6), (760, surface)],
              fill=(250, 248, 240), outline=_soft((230, 224, 206)), width=3)
    _rug(c, 520, 1340, 380, 92, (176, 110, 104))


def _park(c, wall, floor, night):
    sky = (40, 50, 92) if night else wall
    grass = _shade(floor, 0.62) if night else floor
    horizon = FLOOR_LINE
    c.rect((0, 0, c.w, horizon), fill=sky)
    if night:
        c.circle((820, 420), 60, fill=(244, 240, 214))
        for sx, sy in ((150, 330), (300, 470), (470, 300), (640, 520), (930, 620), (210, 640)):
            c.circle((sx, sy), 4, fill=(230, 232, 250))
    else:
        c.circle((830, 420), 70, fill=(252, 232, 150))
        for cx, cy, s in ((230, 380, 1.0), (640, 560, 0.75)):
            for dx, dy, r in ((0, 0, 46), (52, -20, 56), (112, 0, 44), (56, 14, 50)):
                c.circle((cx + dx * s, cy + dy * s), r * s, fill=(250, 252, 255))
    hill = _shade(grass, 1.08)
    c.ellipse((-260, horizon - 190, 560, horizon + 260), fill=hill)
    c.ellipse((420, horizon - 130, 1340, horizon + 240), fill=_shade(grass, 1.03))
    c.rect((0, horizon, c.w, c.h), fill=grass)
    # Path narrowing into the distance.
    path = _shade((226, 208, 172), 0.62 if night else 1.0)
    c.polygon([(420, c.h), (900, c.h), (640, horizon), (600, horizon)], fill=path)
    # Trees.
    for tx, s in ((170, 1.0), (930, 0.8)):
        trunk, leaf = (150, 116, 90), _shade((126, 180, 128), 0.6 if night else 1.0)
        c.rect((tx - 18 * s, horizon - 230 * s, tx + 18 * s, horizon + 10), fill=trunk, outline=_soft(trunk), width=4)
        for dx, dy, r in ((0, -330, 120), (-80, -260, 90), (84, -250, 96), (0, -220, 100)):
            c.circle((tx + dx * s, horizon + dy * s), r * s, fill=leaf)
    # Bench.
    wood = (196, 160, 122)
    for lx in (560, 800):
        c.rect((lx, horizon - 70, lx + 14, horizon + 24), fill=_shade(wood, 0.8))
    c.rect((540, horizon - 70, 834, horizon - 48), fill=wood, outline=_soft(wood), width=4, radius=6)
    c.rect((540, horizon - 150, 834, horizon - 96), fill=wood, outline=_soft(wood), width=4, radius=6)


# name -> (draw function, wall colour, floor colour)
_SETTINGS = {
    "bedroom": (_bedroom, (212, 222, 240), (224, 200, 166)),
    "desk": (_desk_room, (238, 229, 210), (208, 184, 152)),
    "living_room": (_living_room, (226, 234, 222), (216, 194, 162)),
    "classroom": (_classroom, (238, 234, 220), (208, 212, 216)),
    "library": (_library, (228, 216, 200), (190, 160, 128)),
    "park": (_park, (196, 228, 248), (172, 210, 152)),
}

# (wall, floor) pairs for the "plain" setting, used in rotation.
PLAIN = [((226, 228, 247), (200, 204, 232)), ((255, 243, 214), (240, 219, 178)),
         ((222, 242, 230), (190, 220, 202)), ((252, 228, 226), (236, 200, 198)),
         ((224, 240, 250), (192, 216, 234))]


def colors(setting, index=0, wall=None, time="day"):
    """(wall, floor) colours for a setting; `wall` overrides the wall colour."""
    if setting == "plain":
        base_wall, floor = PLAIN[index % len(PLAIN)]
        if wall:
            floor = _shade(wall, 0.9)
    else:
        _, base_wall, floor = _SETTINGS[setting]
    wall = wall or base_wall
    if time == "night" and setting != "park":
        # Dim, slightly blue light.
        wall = tuple(int(v * k) for v, k in zip(wall, (0.74, 0.76, 0.86)))
        floor = tuple(int(v * k) for v, k in zip(floor, (0.74, 0.76, 0.86)))
    return wall, floor


def draw(c, setting, index=0, wall=None, time="day"):
    """Draw a setting onto canvas `c` and return its (wall, floor) colours."""
    wall, floor = colors(setting, index, wall, time)
    if setting == "plain":
        c.rect((0, 0, c.w, c.h), fill=wall)
        props.backdrop(c, FRONT_Y, floor)
    else:
        _SETTINGS[setting][0](c, wall, floor, time == "night")
    return wall, floor
