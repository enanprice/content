"""Camera effects: zoom-in, shake, and slide transitions.

Camera     a single frame's view (zoom + where it looks + shake offset)
CameraRig  keyframed camera; call .at(t) to get the Camera for a frame
slide_transition  pushes one finished frame out with another

The camera works on the finished drawing, so figures and props never need
to know about it. Zoom is anchored on the centre of the SAFE ZONE (not the
frame), so whatever you zoom in on ends up where app UI can't cover it.
"""

import math
from dataclasses import dataclass

from PIL import Image

from . import config
from .easing import ease_in_out_cubic, progress
from .timeline import Track


@dataclass
class Camera:
    zoom: float = 1.0
    center: tuple = config.SAFE_CENTER    # world point shown at the safe-zone centre
    offset: tuple = (0.0, 0.0)            # screen-space shake offset in px

    def is_identity(self):
        return (abs(self.zoom - 1) < 1e-4 and self.offset == (0.0, 0.0)
                and math.dist(self.center, config.SAFE_CENTER) < 1e-3)

    def apply(self, img, ss=1, fill=config.BG):
        """Return the camera's view of `img` (a canvas image at ss x resolution)."""
        ax, ay = config.SAFE_CENTER
        ox, oy = self.offset
        zoom = max(self.zoom, 0.05)
        # Overscan just enough that a shake never drags blank edges into view.
        zoom *= 1 + max(abs(ox) / min(ax, config.WIDTH - ax), abs(oy) / min(ay, config.HEIGHT - ay))

        cx, cy = self.center
        if zoom >= 1:
            # Keep the view inside the drawn frame.
            cx = min(max(cx, ax / zoom), config.WIDTH - (config.WIDTH - ax) / zoom)
            cy = min(max(cy, ay / zoom), config.HEIGHT - (config.HEIGHT - ay) / zoom)

        # Pillow wants the inverse map: output pixel -> source pixel.
        #   world = center + (screen - anchor - offset) / zoom
        inv = 1 / zoom
        coeffs = (inv, 0, ss * (cx - (ax + ox) * inv),
                  0, inv, ss * (cy - (ay + oy) * inv))
        return img.transform(img.size, Image.Transform.AFFINE, coeffs,
                             resample=Image.Resampling.BILINEAR, fillcolor=fill)


def shake_offset(t, start, duration=0.4, amplitude=20.0, frequency=26.0):
    """Decaying shake offset (dx, dy) in px; (0, 0) outside the window.

    Deterministic (two detuned sines, no RNG) so renders are repeatable.
    """
    if not start <= t < start + duration:
        return (0.0, 0.0)
    tau = t - start
    decay = (1 - tau / duration) ** 2
    return (amplitude * decay * math.sin(2 * math.pi * frequency * tau),
            amplitude * decay * math.sin(2 * math.pi * frequency * 1.31 * tau + 1.7))


class CameraRig:
    """Keyframed camera.

        rig = CameraRig()
        rig.zoom_to(1.5, center=face_xy, at=3.0, duration=0.6)   # zoom-in
        rig.reset(at=5.0)                                        # back out
        rig.shake(at=6.4, amplitude=24)
        frame = canvas.to_frame(rig.at(t))
    """

    def __init__(self):
        self._zoom = Track(1.0)
        self._center = Track(tuple(config.SAFE_CENTER))
        self._shakes = []

    def zoom_to(self, zoom, at, duration=0.6, center=None, ease=ease_in_out_cubic):
        """Ease to `zoom`, optionally re-centring on a world point at the same time."""
        self._zoom.to(float(zoom), at, duration, ease)
        if center is not None:
            self._center.to(tuple(center), at, duration, ease)
        return self

    def reset(self, at, duration=0.5, ease=ease_in_out_cubic):
        return self.zoom_to(1.0, at, duration, config.SAFE_CENTER, ease)

    def shake(self, at, duration=0.4, amplitude=20.0, frequency=26.0):
        self._shakes.append((at, duration, amplitude, frequency))
        return self

    def at(self, t):
        ox = oy = 0.0
        for shake in self._shakes:
            dx, dy = shake_offset(t, *shake)
            ox, oy = ox + dx, oy + dy
        return Camera(self._zoom.at(t), self._center.at(t), (ox, oy))


def slide_transition(frame_a, frame_b, t, start, duration=0.5, direction="left",
                     ease=ease_in_out_cubic):
    """Slide frame_b in while pushing frame_a out.

    direction is the way the content travels: "left" brings the new scene
    in from the right. Both frames must be final (same-size) images.
    """
    p = ease(progress(t, start, start + duration))
    w, h = frame_a.size
    dx, dy = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[direction]
    out = Image.new("RGB", (w, h))
    ax, ay = round(dx * w * p), round(dy * h * p)
    out.paste(frame_a, (ax, ay))
    out.paste(frame_b, (ax - dx * w, ay - dy * h))
    return out
