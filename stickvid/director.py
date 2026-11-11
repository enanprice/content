"""Director: turns a validated spec into a finished video.

Pipeline
    1. narration  each scene's text -> speech; the speech length sets the
                  scene length
    2. timeline   scenes are laid end to end; captions get absolute times
    3. frames     every frame is drawn, transitions blended, captions burned in
    4. sound      narration + whooshes + music are mixed and attached

Every scene uses the same layout, all inside the safe zone:

    y  330-460    keyword, as a handwritten note taped to the wall
    y  640-1000   figure on the left, prop on a pale card on the right
    y 1215        front of the floor, where the figure stands
    y 1340-1430   captions

When two neighbouring scenes are in different settings, the figure walks
out of the first and into the second, so a slide reads as moving between
rooms.
"""

import math
import os
import re
from dataclasses import replace

from . import config, props, rooms, tts
from .audio import Clip, make_whoosh, mux
from .camera import CameraRig, slide_transition
from .canvas import Canvas, _font, draw_safe_guides
from .captions import Captions
from .easing import (ease_in_out_cubic, ease_in_out_sine, ease_out_back, ease_out_cubic,
                     progress)
from .figure import StickFigure
from .timeline import Track
from .video import VideoWriter

LEAD = 0.30            # silence before a scene's narration (covers the slide-in)
TAIL = 0.35            # breathing room after it
TRANSITION = 0.40      # slide length, centred on the scene boundary
WHOOSH_VOLUME = 0.30

FIG_X, FIG_SCALE = 330, 0.78
PROP_X, PROP_Y = 765, 830
KEYWORD_Y = 395
KEYWORD_SIZE = 72
ACCENTS = [config.RED, config.BLUE, config.GREEN, config.ORANGE, config.PURPLE]
WIDE_PROPS = ("checklist", "bar_chart")


# ---------------------------------------------------------------------------
# props as scenes use them: s = pop-in scale, p = 0..1 through the narration
# ---------------------------------------------------------------------------
def _draw_prop(c, prop, s, p, t, fig):
    kind, x, y = prop["type"], PROP_X, PROP_Y
    grow = ease_in_out_cubic(p)
    if kind == "phone":
        props.phone(c, x, y, h=360 * s, angle=8, scroll=t * 0.8)
    elif kind == "book":
        opened = ease_in_out_cubic(progress(p, 0.15, 0.5)) if prop.get("open", True) else 0.0
        w = 170 * s
        props.book(c, x - w / 2 * (1 - opened), y, w, 230 * s, open=opened)
    elif kind == "clock":
        props.clock(c, x, y, r=155 * s, time=prop.get("time", 12.0) + t * prop.get("spin", 0.07))
    elif kind == "brain":
        props.brain(c, x, y, size=310 * s * (1 + 0.03 * math.sin(t * 6)))
    elif kind == "battery":
        start, end = prop.get("from", 0.1), prop.get("level", 1.0)
        props.battery(c, x, y, w=330 * s, h=150 * s, level=start + (end - start) * grow,
                      charging=end > start and 0 < p < 1)
    elif kind == "thought_bubble":
        head = fig.joints["head"]
        props.thought_bubble(c, x, y - 60, w=340, h=260, pop=s, tail_to=(head[0] + 95, head[1] - 60))
        if prop.get("text") and s > 0.3:
            c.text((x, y - 60), prop["text"], 120 * s, config.INK)
    elif kind == "checklist":
        items = prop.get("items", 3)
        count = len(items) if isinstance(items, list) else items
        props.checklist(c, x - 10, y, w=410 * s, h=420 * s, items=items,
                        checked=prop.get("checked", count) * progress(p, 0.1, 0.9))
    elif kind == "bar_chart":
        props.bar_chart(c, x, y, w=340 * s, h=320 * s, values=prop.get("values", (0.3, 0.55, 0.9)),
                        labels=prop.get("labels"), grow=grow)
    elif kind == "arrow":
        dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[prop.get("direction", "up")]
        reach = 150 * s
        props.arrow(c, (x - dx * reach, y - dy * reach), (x + dx * reach, y + dy * reach),
                    color=prop.get("color", config.GREEN), width=30 * s, progress=ease_out_cubic(progress(p, 0, 0.4)))
    elif kind == "tomato":
        props.tomato(c, x, y + 8 * math.sin(t * 2.2), size=300 * s)


# ---------------------------------------------------------------------------
# one scene
# ---------------------------------------------------------------------------
class SceneClip:
    def __init__(self, scene, index, narration, enters=False, exits=False):
        """
        enters  the previous scene was somewhere else: walk in from the left
        exits   the next scene is somewhere else: walk off to the right
        """
        self.scene = scene
        self.index = index
        self.narration = narration
        # Word timings relative to the start of this scene.
        self.words = [replace(w, start=w.start + LEAD, end=w.end + LEAD) for w in narration.words]
        self.speech_start = self.words[0].start
        self.speech_end = self.words[-1].end
        # The scene lasts as long as the speech does. edge-tts pads its files
        # with close to a second of silence, so the last word's end is used
        # rather than the raw file length (the silent tail just overlaps the
        # next scene).
        self.duration = min(LEAD + narration.duration, self.speech_end + 0.1) + TAIL
        self.keyword_at = self._keyword_time()
        self._background = None                       # drawn once, on first use

        pose, expression, move = scene["pose"], scene["expression"], scene["move"]
        lying = pose == "sleeping"
        walks_in = enters and not lying and move != "approach"
        home_x = FIG_X + (150 if lying else 0)        # a lying figure is wide: keep its head in the safe zone

        # Start idle and settle into the pose as the scene arrives. Sleeping
        # starts lying down (blending from standing would look like a fall).
        fig = self.fig = StickFigure(-170 if walks_in else home_x, rooms.FRONT_Y, FIG_SCALE,
                                     pose=pose if lying else "idle")
        # Depth in the room: 0 = front, 1 = back wall. The stage hook turns
        # (x, depth) into a screen position and size every frame.
        self.depth = Track(0.0)
        fig.stage = self._stage

        settle = 0.15
        if walks_in:
            fig.walk_to(home_x, -TRANSITION / 2, 0.85)
            settle = 0.7
        if move == "approach" and not lying:
            self.depth = Track(0.9).to(0.0, at=0.0, duration=1.6, ease=ease_in_out_sine)
            fig.march(0.0, 1.6)
            settle = 1.3
        elif move == "pace" and not lying and self.duration > 4.2:
            fig.walk_to(home_x + 170, settle + 0.6, settle + 1.7)
            fig.walk_to(home_x, self.duration - 2.0, self.duration - 0.9)

        if pose == "walking":
            fig.walk_to(home_x, settle, self.duration + 1.0)       # walk on the spot
        elif not lying:
            fig.pose_to(pose, at=settle, duration=0.45, ease=ease_out_cubic)
        fig.expression_to(expression, at=0.15, duration=0.3)
        if pose not in ("sleeping", "facepalm") and expression != "asleep":
            fig.talk(self.speech_start, self.speech_end)          # mouth moves with the voice
        if scene["prop"]:
            fig.look_to((0.8, -0.1), at=settle + 0.3)             # glance at the prop...
            fig.look_to((0.0, 0.0), at=settle + 1.15)             # ...then back to the viewer
        if exits and not lying:
            fig.walk_to(home_x + 430, self.speech_end + 0.12, self.duration + TRANSITION / 2 + 0.1)

        self.cam = CameraRig()
        if scene["camera"] == "zoom_in":
            self.cam.zoom_to(1.1, at=0.2, duration=max(self.duration - 0.2, 0.5), ease=ease_in_out_sine)
        elif scene["camera"] == "shake":
            self.cam.shake(at=self.keyword_at, duration=0.4, amplitude=14)

    def _stage(self, x, t):
        sx, ground_y, k = rooms.project(x, self.depth.at(t))
        return sx, ground_y, FIG_SCALE * k

    def _keyword_time(self):
        """The keyword appears when its first word is spoken (or as speech starts)."""
        keyword = self.scene["keyword"]
        if keyword:
            first = tts._norm(keyword.split()[0])
            for w in self.words:
                if first and tts._norm(w.text) == first:
                    return max(w.start - 0.05, 0.1)
        return self.speech_start

    def _draw_keyword(self, c, t):
        """The keyword as a handwritten note taped to the wall."""
        text = self.scene["keyword"]
        pop = ease_out_back(progress(t, self.keyword_at, self.keyword_at + 0.3))
        if not text or pop <= 0.05:
            return
        size = KEYWORD_SIZE
        width = _font(size, "hand").getlength(text)
        if width > 760:
            size, width = size * 760 / width, 760
        size, width = size * pop, width * pop
        w, h = width + 90 * pop, size * 1.6
        tile = c.sub(w + 40, h + 60)
        cx, cy = (w + 40) / 2, (h + 60) / 2 + 6
        tile.rect((cx - w / 2 + 6, cy - h / 2 + 8, cx + w / 2 + 6, cy + h / 2 + 8), fill=(0, 0, 0, 40), radius=6)
        tile.rect((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), fill=(255, 250, 226),
                  outline=(226, 214, 176), width=3, radius=6)
        tile.text((cx, cy - size * 0.1), text, size, (52, 54, 66), font="hand")
        # A slightly wobbly pen underline.
        line = [(cx + width * 0.42 * u, cy + size * 0.52 + 2.5 * pop * math.sin(u * 5 + self.index))
                for u in (i / 10 - 1 for i in range(21))]
        tile.polyline(line, ACCENTS[self.index % len(ACCENTS)], 5 * pop)
        tile.rect((cx - 44 * pop, cy - h / 2 - 15 * pop, cx + 44 * pop, cy - h / 2 + 13 * pop),
                  fill=(232, 222, 188, 215))                                       # tape
        c.paste(tile, (config.WIDTH / 2, KEYWORD_Y), angle=-2.5)

    def _backdrop(self):
        """The setting, drawn once and copied for every frame."""
        if self._background is None:
            scene = self.scene
            canvas = Canvas(bg=rooms.colors(scene["setting"], self.index, scene["background"], scene["time"])[0])
            _, self.floor = rooms.draw(canvas, scene["setting"], self.index, scene["background"], scene["time"])
            self._background = canvas
        return self._background.copy()

    def render(self, t):
        """Final frame for scene-local time t (may run slightly outside 0..duration)."""
        fig = self.fig.update(t)
        c = self._backdrop()
        self._draw_keyword(c, t)

        prop = self.scene["prop"]
        if prop:
            pop = ease_out_back(progress(t, 0.25, 0.65))
            if pop > 0.05:
                if self.scene["setting"] != "plain" and prop["type"] != "thought_bubble":
                    # A pale card lifts the prop off the room's furniture.
                    half = (240 if prop["type"] in WIDE_PROPS else 205) * pop
                    card = c.sub(half * 2, half * 2)
                    card.rect((0, 0, half * 2, half * 2), fill=(255, 255, 255, 175), radius=56 * pop)
                    c.paste(card, (PROP_X, PROP_Y))
                p = progress(t, self.speech_start, self.speech_end)
                _draw_prop(c, prop, pop, p, t, fig)

        fig.draw_shadow(c, tuple(int(v * 0.88) for v in self.floor))
        fig.draw(c)
        if self.scene["pose"] == "sleeping":
            head = fig.joints["head"]
            props.zzz(c, head[0] + 40, head[1] - 90, t, size=44)
        return c.to_frame(self.cam.at(t))


# ---------------------------------------------------------------------------
# the whole video
# ---------------------------------------------------------------------------
class Video:
    def __init__(self, spec, use_tts=True, cache_dir=".cache", log=print):
        self.spec = spec
        self.cache_dir = cache_dir
        self.clips, self.starts = [], []
        cursor = 0.0
        scenes = spec["scenes"]
        place = [(sc["setting"], sc["time"]) for sc in scenes]
        for i, scene in enumerate(scenes):
            if use_tts:
                log(f"  narration {i + 1}/{len(spec['scenes'])}...")
                narration = tts.synthesize(scene["narration"], spec["voice"], spec["rate"],
                                           os.path.join(cache_dir, "tts"))
            else:
                narration = tts.estimate(scene["narration"])
            clip = SceneClip(scene, i, narration,
                             enters=i > 0 and place[i - 1] != place[i],
                             exits=i + 1 < len(scenes) and place[i + 1] != place[i])
            self.clips.append(clip)
            self.starts.append(cursor)
            cursor += clip.duration
        self.frames = math.ceil(cursor * config.FPS)
        self.duration = self.frames / config.FPS

        words = [replace(w, start=w.start + s, end=w.end + s)
                 for clip, s in zip(self.clips, self.starts) for w in clip.words]
        cap = spec["captions"]
        self.captions = Captions(words, cap["max_words"], cap["uppercase"], cap["highlight"]) \
            if cap["enabled"] else None

        self.slide = None if spec["transition"] == "cut" else spec["transition"].split("_")[1]

    def summary(self):
        lines = []
        for i, (clip, start) in enumerate(zip(self.clips, self.starts)):
            lines.append(f"  scene {i + 1}: {start:5.1f}s -> {start + clip.duration:5.1f}s "
                         f"({clip.duration:4.1f}s)  {clip.scene['setting']:<12}{clip.scene['narration'][:40]}")
        lines.append(f"  total: {self.duration:.1f}s")
        return "\n".join(lines)

    def frame(self, t):
        """Final frame at time t, captions included."""
        i = max(k for k, s in enumerate(self.starts) if s <= t + 1e-9)
        img = None
        if self.slide:
            # A slide straddles each boundary: half before it, half after.
            for k in (i, i + 1):
                if 1 <= k < len(self.clips) and abs(t - self.starts[k]) < TRANSITION / 2:
                    a, b = self.clips[k - 1], self.clips[k]
                    img = slide_transition(a.render(t - self.starts[k - 1]), b.render(t - self.starts[k]),
                                           t, self.starts[k] - TRANSITION / 2, TRANSITION, self.slide)
                    break
        if img is None:
            img = self.clips[i].render(t - self.starts[i])
        if self.captions:
            self.captions.draw(img, t)
        return img

    def sound(self):
        """Every sound in the video as timeline clips."""
        clips = [Clip(c.narration.path, s + LEAD) for c, s in zip(self.clips, self.starts)
                 if c.narration.path]
        if self.slide and self.spec["whoosh"] and len(self.clips) > 1:
            whoosh = make_whoosh(os.path.join(self.cache_dir, "whoosh.wav"))
            clips += [Clip(whoosh, s - TRANSITION / 2 - 0.05, WHOOSH_VOLUME) for s in self.starts[1:]]
        return clips

    def render(self, out_path, guides=False, log=print):
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        silent = re.sub(r"\.mp4$", "", out_path) + ".silent.mp4"
        with VideoWriter(silent) as video:
            for n in range(self.frames):
                img = self.frame(n / config.FPS)
                video.write(draw_safe_guides(img) if guides else img)
                if (n + 1) % (config.FPS * 5) == 0 or n + 1 == self.frames:
                    log(f"  frame {n + 1}/{self.frames}")
        try:
            mux(silent, out_path, self.duration, self.sound(), self.spec["music"])
        finally:
            os.remove(silent)
        return out_path
