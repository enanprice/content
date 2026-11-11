"""Canvas: a thin wrapper around a Pillow image.

All drawing calls take *logical* coordinates (the 1080x1920 frame). The
canvas multiplies them by the supersampling factor internally, so no other
module has to care about anti-aliasing.
"""

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import config

# Bold sans fonts commonly present on Linux / macOS / Windows. The first one
# that loads wins; otherwise Pillow's built-in font is used.
_FONT_CANDIDATES = [
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "arialbd.ttf",
    "Arial Bold.ttf",
]


@lru_cache(maxsize=64)
def _font(px):
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(size=px)


class Canvas:
    def __init__(self, width=config.WIDTH, height=config.HEIGHT, bg=config.BG,
                 ss=None, transparent=False):
        self.w, self.h = width, height
        self.ss = config.SSAA if ss is None else ss
        self.bg = bg
        size = (max(1, round(width * self.ss)), max(1, round(height * self.ss)))
        if transparent:
            self.img = Image.new("RGBA", size, (0, 0, 0, 0))
        else:
            self.img = Image.new("RGB", size, bg)
        self.d = ImageDraw.Draw(self.img)

    # -- coordinate helpers ---------------------------------------------------
    def _p(self, pt):
        return (pt[0] * self.ss, pt[1] * self.ss)

    def _box(self, box):
        return tuple(v * self.ss for v in box)

    def _w(self, width):
        return max(1, int(round(width * self.ss)))

    # -- primitives -----------------------------------------------------------
    def polyline(self, pts, color, width, closed=False):
        """Thick line through pts with round caps and round joints."""
        pts = [self._p(p) for p in pts]
        if closed:
            pts.append(pts[0])
        w = self._w(width)
        self.d.line(pts, fill=color, width=w, joint="curve")
        r = w / 2
        # Round every vertex on short paths; on long sampled curves the
        # segments are short enough that only the ends need caps.
        for x, y in (pts if len(pts) <= 64 else (pts[0], pts[-1])):
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def line(self, a, b, color, width):
        self.polyline([a, b], color, width)

    def circle(self, center, r, fill=None, outline=None, width=0):
        x, y = center
        self.ellipse((x - r, y - r, x + r, y + r), fill, outline, width)

    def ellipse(self, box, fill=None, outline=None, width=0):
        if box[2] <= box[0] or box[3] <= box[1]:
            return
        self.d.ellipse(self._box(box), fill=fill, outline=outline,
                       width=self._w(width) if outline else 0)

    def polygon(self, pts, fill=None, outline=None, width=0):
        if fill is not None:
            self.d.polygon([self._p(p) for p in pts], fill=fill)
        if outline is not None:
            self.polyline(pts, outline, width, closed=True)

    def rect(self, box, fill=None, outline=None, width=0, radius=0):
        """Axis-aligned rectangle, optionally rounded."""
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            return
        radius = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
        self.d.rounded_rectangle(self._box(box), radius=radius * self.ss, fill=fill,
                                 outline=outline, width=self._w(width) if outline else 0)

    def text(self, pos, s, size, color=config.INK, anchor="mm"):
        """Draw text. `anchor` is a Pillow anchor ('mm' = centred on pos)."""
        self.d.text(self._p(pos), s, font=_font(max(1, round(size * self.ss))),
                    fill=color, anchor=anchor)

    # -- layers ---------------------------------------------------------------
    def sub(self, width, height):
        """Transparent scratch canvas at the same supersampling factor."""
        return Canvas(width, height, ss=self.ss, transparent=True)

    def paste(self, sub, center, angle=0.0):
        """Composite a sub-canvas centred on `center`, rotated clockwise by angle (deg)."""
        tile = sub.img
        if angle % 360:
            tile = tile.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
        x = round(center[0] * self.ss - tile.width / 2)
        y = round(center[1] * self.ss - tile.height / 2)
        self.img.paste(tile, (x, y), tile)

    # -- output ---------------------------------------------------------------
    def to_frame(self, camera=None):
        """Apply the camera (if any) and scale down to the final frame size."""
        img = self.img
        if camera is not None and not camera.is_identity():
            img = camera.apply(img, self.ss, self.bg)
        if self.ss == 1:
            return img.copy()
        if float(self.ss).is_integer():
            return img.reduce(int(self.ss))          # fast box filter
        return img.resize((self.w, self.h), Image.Resampling.LANCZOS)


def draw_safe_guides(frame):
    """Debug overlay: tint the areas outside the safe zone red.

    Works on a final (1x) frame and returns a new image.
    """
    left, top, right, bottom = config.SAFE_BOX
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    tint = (255, 0, 0, 70)
    d.rectangle((0, 0, frame.width, top), fill=tint)
    d.rectangle((0, bottom, frame.width, frame.height), fill=tint)
    d.rectangle((0, top, left, bottom), fill=tint)
    d.rectangle((right, top, frame.width, bottom), fill=tint)
    d.rectangle((left, top, right, bottom), outline=(255, 0, 0, 200), width=3)
    return Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")
