"""StickFigure: a jointed figure with an expressive face.

Angle convention (degrees) - the one rule to remember:

    0 means the segment hangs straight down (limbs) or stands straight up
    (torso / head). A POSITIVE angle swings the free end towards
    SCREEN-RIGHT, a negative angle towards screen-left.

Limb angles are absolute (relative to the body, not to the parent segment),
which makes poses easy to author: r_fore=90 is always "forearm pointing
right". "l_" / "r_" mean screen-left / screen-right, not the character's own
left and right.

The figure plants itself on `ground_y` automatically: whatever the pose,
its lowest point touches the ground. That is what gives the walk cycle its
bob and lets the sleeping pose lie on the floor without special cases.
"""

import math
from dataclasses import dataclass, fields

from . import config
from .easing import clamp, ease_in_out_cubic, linear, progress
from .timeline import Track


# ---------------------------------------------------------------------------
# Pose & Face: plain bags of numbers that can be blended
# ---------------------------------------------------------------------------
class _Blendable:
    def lerp(self, other, t):
        return type(self)(**{
            f.name: getattr(self, f.name) + (getattr(other, f.name) - getattr(self, f.name)) * t
            for f in fields(self)
        })


@dataclass
class Pose(_Blendable):
    lean: float = 0.0            # torso tilt
    head_tilt: float = 0.0       # extra head tilt on top of the lean
    body_rot: float = 0.0        # rotate the whole body about the hip (-90 = lying, head left)
    shoulder_raise: float = 0.0  # 0..1, lifts the shoulders (shrug)
    l_upper: float = -14.0       # upper arms
    r_upper: float = 14.0
    l_fore: float = -8.0         # forearms
    r_fore: float = 8.0
    l_thigh: float = -9.0
    r_thigh: float = 9.0
    l_shin: float = -9.0
    r_shin: float = 9.0
    y_offset: float = 0.0        # vertical nudge in px (negative = up, e.g. a hop)

    def mirrored(self):
        """Left-right flipped copy of this pose."""
        return Pose(
            lean=-self.lean, head_tilt=-self.head_tilt, body_rot=-self.body_rot,
            shoulder_raise=self.shoulder_raise,
            l_upper=-self.r_upper, r_upper=-self.l_upper,
            l_fore=-self.r_fore, r_fore=-self.l_fore,
            l_thigh=-self.r_thigh, r_thigh=-self.l_thigh,
            l_shin=-self.r_shin, r_shin=-self.l_shin,
            y_offset=self.y_offset,
        )


@dataclass
class Face(_Blendable):
    eye_open: float = 1.0      # 1 = wide open, 0 = closed (upper lid)
    eye_scale: float = 1.0     # eye size multiplier
    pupil_scale: float = 1.0
    cheek: float = 0.0         # 0..1 lower lid pushed up (smiling eyes)
    brow_angle: float = 0.0    # +1 worried (inner ends up), -1 angry
    brow_raise: float = 0.0    # +1 raised, -1 lowered
    brow_skew: float = 0.0     # raises only the screen-right brow (smug)
    bags: float = 0.0          # 0..1 under-eye bags
    sweat: float = 0.0         # 0..1 size of the sweat drop
    mouth_curve: float = 0.15  # +1 smile, -1 frown
    mouth_open: float = 0.0    # 0..1
    mouth_width: float = 1.0
    mouth_skew: float = 0.0    # lifts the screen-right corner (smirk)
    mouth_wavy: float = 0.0    # 0..1 wobbly line


def walk_cycle(phase):
    """Pose for a rightward walk. `phase` runs 0..1 over one full stride."""
    a = 2 * math.pi * phase
    swing, lift = math.sin(a), math.cos(a)
    r_thigh, l_thigh = 26 * swing, -26 * swing
    # A leg bends at the knee while it travels forward.
    r_bend = 8 + 30 * max(0.0, lift)
    l_bend = 8 + 30 * max(0.0, -lift)
    return Pose(
        lean=4,
        r_thigh=r_thigh, r_shin=r_thigh - r_bend,
        l_thigh=l_thigh, l_shin=l_thigh - l_bend,
        # Arms swing opposite to the legs, elbows slightly bent forward.
        r_upper=-24 * swing, r_fore=-24 * swing + 20,
        l_upper=24 * swing, l_fore=24 * swing + 20,
    )


POSES = {
    "idle": Pose(),
    "talking": Pose(head_tilt=4, r_upper=35, r_fore=140),
    "pointing": Pose(lean=-3, r_upper=98, r_fore=98, l_upper=-40, l_fore=30),
    "facepalm": Pose(lean=3, head_tilt=10, r_upper=115, r_fore=229),
    "shrug": Pose(head_tilt=8, shoulder_raise=1.0,
                  l_upper=-45, l_fore=-125, r_upper=45, r_fore=125),
    "sleeping": Pose(body_rot=-90, r_upper=32, r_fore=-28, l_upper=0, l_fore=0,
                     r_thigh=28, r_shin=-38, l_thigh=-10, l_shin=-10),
    "walking": walk_cycle(0.12),
    # Extras used by the test video
    "scrolling": Pose(head_tilt=7, r_upper=40, r_fore=135),
    "hold_book": Pose(l_upper=-60, l_fore=25, r_upper=60, r_fore=-25),
    "read_book": Pose(head_tilt=0, l_upper=-60, l_fore=-20, r_upper=60, r_fore=20),
}

EXPRESSIONS = {
    "neutral": Face(),
    "happy": Face(cheek=0.4, brow_raise=0.5, mouth_curve=1.0, mouth_open=0.45, mouth_width=1.15),
    "stressed": Face(eye_scale=1.2, pupil_scale=0.6, brow_angle=1.0, brow_raise=0.5,
                     sweat=1.0, mouth_curve=-0.45, mouth_wavy=1.0, mouth_width=1.1),
    "smug": Face(eye_open=0.55, brow_angle=-0.35, brow_skew=1.0,
                 mouth_curve=0.6, mouth_skew=1.0, mouth_width=0.9),
    "tired": Face(eye_open=0.42, brow_angle=0.5, brow_raise=-0.3, bags=1.0,
                  mouth_curve=-0.35, mouth_width=0.8),
    # Extras
    "guilty": Face(pupil_scale=0.85, brow_angle=0.9, brow_raise=0.25, sweat=0.6,
                   mouth_curve=-0.45, mouth_skew=0.45, mouth_width=0.7),
    "asleep": Face(eye_open=0.0, mouth_curve=0.1, mouth_open=0.3, mouth_width=0.45),
}


def _pose(p):
    return POSES[p] if isinstance(p, str) else p


def _face(f):
    return EXPRESSIONS[f] if isinstance(f, str) else f


# ---------------------------------------------------------------------------
# The figure
# ---------------------------------------------------------------------------
class StickFigure:
    # Body proportions in px at scale=1 (standing height is about 740px).
    HEAD_R = 88
    NECK = 18
    TORSO = 250
    UPPER_ARM = 125
    FOREARM = 120
    THIGH = 150
    SHIN = 150
    LINE = 20

    def __init__(self, x=config.WIDTH / 2, ground_y=1470, scale=1.0,
                 pose="idle", expression="neutral",
                 color=config.INK, skin=config.WHITE, alive=True):
        self.ground_y = ground_y
        self.scale = scale
        self.color = color
        self.skin = skin
        self.alive = alive            # automatic blinking + breathing

        self._pose = Track(_pose(pose))
        self._face = Track(_face(expression))
        self._look = Track((0.0, 0.0))
        self._x = Track(float(x))
        self._walks = []              # (start, end, direction, strides_per_sec)
        self._talks = []              # (start, end)

        self.update(0.0)

    # -- scheduling (all times in seconds) ----------------------------------
    def pose_to(self, pose, at, duration=0.4, ease=ease_in_out_cubic):
        """Ease into `pose` (a name from POSES or a Pose) starting at time `at`."""
        self._pose.to(_pose(pose), at, duration, ease)
        return self

    def expression_to(self, expression, at, duration=0.25, ease=ease_in_out_cubic):
        self._face.to(_face(expression), at, duration, ease)
        return self

    def look_to(self, direction, at, duration=0.2, ease=ease_in_out_cubic):
        """Move the gaze. direction=(x, y), each -1..1; (0, 0) looks at the viewer."""
        self._look.to(tuple(direction), at, duration, ease)
        return self

    def move_to(self, x, at, duration=0.5, ease=ease_in_out_cubic):
        self._x.to(float(x), at, duration, ease)
        return self

    def walk_to(self, x, start, end, strides_per_sec=1.6):
        """Walk to x between `start` and `end`, playing the walk cycle."""
        direction = 1 if x >= self._x.at(start) else -1
        self._x.to(float(x), start, end - start, linear)
        self._walks.append((start, end, direction, strides_per_sec))
        return self

    def talk(self, start, end):
        """Flap the mouth between `start` and `end` (combine with any pose)."""
        self._talks.append((start, end))
        return self

    # -- per-frame state ------------------------------------------------------
    def update(self, t):
        """Resolve every track at time t and compute joint positions."""
        self.t = t
        self.x = self._x.at(t)
        pose = self._pose.at(t)
        face = self._face.at(t)
        self.look = self._look.at(t)

        # Blend the walk cycle in and out over 0.2s at each end of a walk.
        for start, end, direction, rate in self._walks:
            w = min(progress(t, start, start + 0.2), 1 - progress(t, end - 0.2, end))
            if w > 0:
                cycle = walk_cycle((t - start) * rate)
                pose = pose.lerp(cycle if direction > 0 else cycle.mirrored(), w)

        if self.alive:
            # Breathing: shoulders drift up and down a couple of pixels.
            pose = pose.lerp(Pose(**{**pose.__dict__,
                                     "shoulder_raise": pose.shoulder_raise + 0.12}),
                             0.5 + 0.5 * math.sin(t * 2.1))
            # Blink every ~3.1s: lids close and reopen within 0.14s.
            phase = (t + 1.3) % 3.1
            if phase < 0.14:
                face = face.lerp(Face(**{**face.__dict__, "eye_open": 0.0}),
                                 1 - abs(phase / 0.07 - 1))

        for start, end in self._talks:
            w = min(progress(t, start, start + 0.1), 1 - progress(t, end - 0.1, end))
            if w > 0:
                flap = 0.15 + 0.6 * abs(math.sin((t - start) * 17)) * (0.6 + 0.4 * math.sin(t * 7.3))
                face = face.lerp(Face(**{**face.__dict__, "mouth_open": max(face.mouth_open, flap)}), w)

        self.pose, self.face = pose, face
        self.joints = self._solve(pose)
        return self

    def _solve(self, p):
        """Forward kinematics: pose angles -> joint positions on the canvas."""
        s = self.scale

        def up(deg, length):
            a = math.radians(deg)
            return (math.sin(a) * length, -math.cos(a) * length)

        def down(deg, length):
            a = math.radians(deg)
            return (math.sin(a) * length, math.cos(a) * length)

        def add(a, b):
            return (a[0] + b[0], a[1] + b[1])

        j = {"hip": (0.0, 0.0)}
        j["neck"] = up(p.lean, self.TORSO * s)
        j["shoulder"] = add(up(p.lean, (self.TORSO - 18) * s), (0, -p.shoulder_raise * 16 * s))
        j["head"] = add(j["neck"], up(p.lean + p.head_tilt, (self.NECK + self.HEAD_R) * s))
        for side in ("l", "r"):
            elbow = add(j["shoulder"], down(getattr(p, side + "_upper"), self.UPPER_ARM * s))
            j[side + "_elbow"] = elbow
            j[side + "_hand"] = add(elbow, down(getattr(p, side + "_fore"), self.FOREARM * s))
            knee = down(getattr(p, side + "_thigh"), self.THIGH * s)
            j[side + "_knee"] = knee
            j[side + "_foot"] = add(knee, down(getattr(p, side + "_shin"), self.SHIN * s))

        # Whole-body rotation about the hip (clockwise for positive angles).
        if p.body_rot:
            a = math.radians(p.body_rot)
            ca, sa = math.cos(a), math.sin(a)
            j = {k: (x * ca - y * sa, x * sa + y * ca) for k, (x, y) in j.items()}

        # Plant the lowest body point on the ground.
        half_line = self.LINE * s / 2
        lowest = max(
            j["head"][1] + self.HEAD_R * s,
            *(j[k][1] + half_line for k in ("hip", "neck", "l_knee", "r_knee", "l_foot", "r_foot")),
        )
        dx, dy = self.x, self.ground_y - lowest + p.y_offset
        return {k: (x + dx, y + dy) for k, (x, y) in j.items()}

    # -- drawing --------------------------------------------------------------
    def draw_shadow(self, canvas, color):
        """Soft ground shadow. Draw it before the figure."""
        j, s = self.joints, self.scale
        xs = [j[k][0] for k in ("l_foot", "r_foot", "hip", "head")]
        cx, half = (min(xs) + max(xs)) / 2, (max(xs) - min(xs)) / 2 + 70 * s
        canvas.ellipse((cx - half, self.ground_y - 14 * s, cx + half, self.ground_y + 16 * s), fill=color)

    def draw(self, canvas):
        j, s, col = self.joints, self.scale, self.color
        lw = self.LINE * s
        canvas.polyline([j["hip"], j["l_knee"], j["l_foot"]], col, lw)
        canvas.polyline([j["hip"], j["r_knee"], j["r_foot"]], col, lw)
        canvas.line(j["hip"], j["neck"], col, lw)
        canvas.circle(j["head"], self.HEAD_R * s, fill=self.skin, outline=col, width=lw * 0.8)
        self._draw_face(canvas)
        # Arms go last so a hand can pass in front of the face (facepalm).
        canvas.polyline([j["shoulder"], j["l_elbow"], j["l_hand"]], col, lw)
        canvas.polyline([j["shoulder"], j["r_elbow"], j["r_hand"]], col, lw)
        self.draw_hands(canvas)

    def draw_hands(self, canvas):
        """Hands only - call again after drawing a held prop so they grip it."""
        r = self.LINE * self.scale * 0.72
        canvas.circle(self.joints["l_hand"], r, fill=self.color)
        canvas.circle(self.joints["r_hand"], r, fill=self.color)

    def _draw_face(self, c):
        f, p, ink = self.face, self.pose, self.color
        R = self.HEAD_R * self.scale
        hx, hy = self.joints["head"]
        lx, ly = (clamp(v, -1, 1) for v in self.look)

        # Face features are laid out in head-local coordinates and rotated
        # with the head, so tilting or lying down just works.
        a = math.radians(p.lean + p.head_tilt + p.body_rot)
        ca, sa = math.cos(a), math.sin(a)

        def W(x, y):
            return (hx + x * ca - y * sa, hy + x * sa + y * ca)

        # The whole face drifts a little in the gaze direction, which reads
        # as the head turning.
        ox, oy = lx * R * 0.10, ly * R * 0.07
        thin = max(1.5, R * 0.055)

        # --- eyes + brows ---
        rx, ry = R * 0.2, R * 0.25 * f.eye_scale
        for side in (-1, 1):
            ex, ey = side * R * 0.36 + ox, -R * 0.12 + oy
            lid = ey - ry + 2 * ry * (1 - clamp(f.eye_open))    # upper lid line
            cheek = ey + ry - ry * clamp(f.cheek)                # lower lid line
            if cheek - lid < ry * 0.3:
                # Closed: a single downward-curved lash line.
                ym = clamp((lid + cheek) / 2, ey - ry * 0.3, ey + ry * 0.5)
                pts = [(ex + rx * u, ym + ry * 0.3 * (1 - u * u)) for u in _steps(-1, 1, 8)]
                c.polyline([W(*q) for q in pts], ink, thin)
            else:
                # Open: the eye ellipse with its y clamped between the lids.
                ring = [(ex + rx * math.cos(q), clamp(ey + ry * math.sin(q), lid, cheek))
                        for q in _steps(0, 2 * math.pi, 28)]
                c.polygon([W(*q) for q in ring], fill=config.WHITE)
                pr = R * 0.095 * f.pupil_scale
                px = ex + lx * (rx - pr - thin * 0.5)
                py = ey + ly * (ry - pr - thin * 0.5)
                pupil = [(px + pr * math.cos(q), clamp(py + pr * math.sin(q), lid, cheek))
                         for q in _steps(0, 2 * math.pi, 16)]
                c.polygon([W(*q) for q in pupil], fill=ink)
                if py - pr * 0.4 > lid + pr * 0.2:               # catch-light
                    c.circle(W(px - pr * 0.35, py - pr * 0.4), pr * 0.3, fill=config.WHITE)
                c.polyline([W(*q) for q in ring], ink, thin, closed=True)

            if f.bags > 0.3:
                bag = [(ex + rx * 0.85 * u, ey + ry + R * 0.05 + R * 0.05 * (1 - u * u))
                       for u in _steps(-1, 1, 6)]
                c.polyline([W(*q) for q in bag], config.GREY, thin * 0.8)

            by = ey - ry - R * 0.13 - f.brow_raise * R * 0.08
            if side > 0:
                by -= f.brow_skew * R * 0.11
            tilt = f.brow_angle * R * 0.09
            inner = (ex - side * R * 0.2, by - tilt)
            outer = (ex + side * R * 0.2, by + tilt)
            c.line(W(*inner), W(*outer), ink, thin * 1.3)

        # --- mouth ---
        mw = R * 0.32 * f.mouth_width
        mx, my = ox * 0.8, R * 0.45 + oy
        curve = f.mouth_curve * R * 0.2
        us = _steps(-1, 1, 16)

        def upper(u):
            y = curve * (0.6 - u * u)                      # smile / frown
            y -= f.mouth_skew * R * 0.1 * u                # smirk
            y += f.mouth_wavy * R * 0.045 * math.sin(u * 7.5)
            return (mx + mw * u, my + y)

        if f.mouth_open > 0.08:
            gap = f.mouth_open * R * 0.34
            lower = [(upper(u)[0], upper(u)[1] + gap * (1 - u * u)) for u in reversed(us)]
            shape = [W(*upper(u)) for u in us] + [W(*q) for q in lower]
            c.polygon(shape, fill=(120, 40, 52), outline=ink, width=thin)
        else:
            c.polyline([W(*upper(u)) for u in us], ink, thin * 1.2)

        # --- sweat drop on the temple ---
        if f.sweat > 0.05:
            r = R * 0.13 * clamp(f.sweat)
            dx, dy = R * 0.66, -R * 0.42 + (self.t * 30 % 12) * self.scale * 0.5
            drop = [(dx, dy - r * 2.1)] + [
                (dx + r * math.cos(q), dy + r * math.sin(q))
                for q in _steps(math.radians(-40), math.radians(220), 12)
            ]
            c.polygon([W(*q) for q in drop], fill=config.SWEAT, outline=ink, width=thin * 0.6)


def _steps(a, b, n):
    """n+1 evenly spaced values from a to b inclusive."""
    return [a + (b - a) * i / n for i in range(n + 1)]
