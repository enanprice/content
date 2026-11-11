"""Global settings: frame geometry, safe zone and colour palette.

Everything else in the package works in *logical* pixels on a 1080x1920
canvas. Change values here and the whole pipeline follows.
"""

# --- Output format ---------------------------------------------------------
WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Supersampling factor. Pillow's line drawing is not anti-aliased, so frames
# are drawn at SSAA x resolution and scaled down. 2 looks clean; 1 is ~3x
# faster and fine for previews.
SSAA = 2

# --- Safe zone ---------------------------------------------------------------
# TikTok / Reels / Shorts cover the top and bottom of the frame with UI
# (username, caption, buttons). Backgrounds may bleed into these bands, but
# anything the viewer must see has to stay inside SAFE_BOX.
SAFE_TOP = 250       # px hidden at the top
SAFE_BOTTOM = 400    # px hidden at the bottom
SAFE_SIDE = 60       # small side margin (right-hand button column, rounding)

SAFE_BOX = (SAFE_SIDE, SAFE_TOP, WIDTH - SAFE_SIDE, HEIGHT - SAFE_BOTTOM)
SAFE_CENTER = ((SAFE_BOX[0] + SAFE_BOX[2]) / 2, (SAFE_BOX[1] + SAFE_BOX[3]) / 2)


def in_safe_zone(x, y, margin=0):
    """True if the logical point (x, y) is inside the safe zone."""
    left, top, right, bottom = SAFE_BOX
    return left + margin <= x <= right - margin and top + margin <= y <= bottom - margin


# --- Palette ---------------------------------------------------------------
INK = (34, 34, 42)          # figure lines, outlines
WHITE = (255, 255, 255)
PAPER = (250, 248, 242)     # book pages, checklist paper
GREY = (176, 178, 190)
BG = (255, 244, 222)        # default background
FLOOR = (240, 221, 184)

RED = (235, 87, 87)
ORANGE = (245, 158, 66)
YELLOW = (250, 204, 55)
GREEN = (88, 184, 108)
BLUE = (76, 141, 245)
PURPLE = (150, 110, 220)
PINK = (244, 151, 180)
SWEAT = (120, 190, 255)
