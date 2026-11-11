"""Director: turns a validated spec into a finished video.

Pipeline
    1. narration  each scene's text -> speech; the audio length sets the
                  scene length
    2. timeline   scenes are laid end to end; captions get absolute times
    3. frames     every frame is drawn, transitions blended, captions burned in
    4. sound      narration + whooshes + music are mixed and attached

Every scene uses the same layout, all inside the safe zone:

    y  300-520    keyword text
    y  640-1000   figure on the left, prop on the right
    y 1215        floor line
    y 1280-1410   captions
"""

import math
import os
import re
from dataclasses import replace

from . import config, props, tts
from .audio import Clip, make_whoosh, mux
from .camera import CameraRig, slide_transition
from .canvas import Canvas, _font, draw_safe_guides
from .captions import Captions
from .easing import (ease_in_out_cubic, ease_in_out_sine, ease_out_back, ease_out_cubic,
                     progress)
from .figure import StickFigure
from .video import VideoWriter

LEAD = 0.30            # silence before a scene's narration (covers the slide-in)
TAIL = 0.35            # breathing room after it
TRANSITION = 0.40      # slide length, centred on the scene boundary
WHOOSH_VOLUME = 0.30

FIG_X, GROUND, FIG_SCALE = 330, 1215, 0.78
PROP_X, PROP_Y = 765, 830
KEYWORD_Y = 410
KEYWORD_SIZE = 116

# (wall, floor) pairs used in rotation when a scene sets no background.
PALETTE = [((226, 228, 247), (200, 204, 232)), ((255, 243, 214), (240, 219, 178)),
           ((222, 242, 230), (190, 220, 202)), ((252, 228, 226), (236, 200, 198)),
           ((224, 240, 250), (192, 216, 234))]
ACCENTS = [config.RED, config.BLUE, config.GREEN, config.ORANGE, config.PURPLE]


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
    def __init__(self, scene, index, narration):
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
        self.wall, self.floor = PALETTE[index % len(PALETTE)]
        if scene["background"]:
            self.wall = scene["background"]
            self.floor = tuple(int(v * 0.9) for v in self.wall)
        self.keyword_at = self._keyword_time()

        pose, expression = scene["pose"], scene["expression"]
        # Start idle and snap into the pose as the scene arrives. Sleeping
        # starts lying down (blending from standing would look like a fall).
        # A lying figure is wide, so it moves right to keep its head in the safe zone.
        fig = self.fig = StickFigure(FIG_X + (150 if pose == "sleeping" else 0), GROUND, FIG_SCALE,
                                     pose=pose if pose == "sleeping" else "idle")
        if pose == "walking":
            fig.walk_to(FIG_X, 0.0, self.duration + 1.0)          # walk on the spot
        elif pose != "sleeping":
            fig.pose_to(pose, at=0.15, duration=0.45, ease=ease_out_cubic)
        fig.expression_to(expression, at=0.15, duration=0.3)
        if pose not in ("sleeping", "facepalm") and expression != "asleep":
            fig.talk(self.speech_start, self.speech_end)          # mouth moves with the voice
        if scene["prop"]:
            fig.look_to((0.8, -0.1), at=0.45)                     # glance at the prop...
            fig.look_to((0.0, 0.0), at=1.3)                       # ...then back to the viewer

        self.cam = CameraRig()
        if scene["camera"] == "zoom_in":
            self.cam.zoom_to(1.1, at=0.2, duration=max(self.duration - 0.2, 0.5), ease=ease_in_out_sine)
        elif scene["camera"] == "shake":
            self.cam.shake(at=self.keyword_at, duration=0.4, amplitude=14)

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
        text = self.scene["keyword"]
        pop = ease_out_back(progress(t, self.keyword_at, self.keyword_at + 0.3))
        if not text or pop <= 0.02:
            return
        max_width = config.SAFE_BOX[2] - config.SAFE_BOX[0] - 60
        width = _font(KEYWORD_SIZE).getlength(text)
        size = KEYWORD_SIZE * min(1.0, max_width / width) * pop
        width = min(width, max_width) * pop
        c.text((config.WIDTH / 2, KEYWORD_Y), text, size, config.INK)
        bar_y = KEYWORD_Y + size * 0.62
        c.line((config.WIDTH / 2 - width * 0.3, bar_y), (config.WIDTH / 2 + width * 0.3, bar_y),
               ACCENTS[self.index % len(ACCENTS)], 14 * pop)

    def render(self, t):
        """Final frame for scene-local time t (may run slightly outside 0..duration)."""
        fig = self.fig.update(t)
        c = Canvas(bg=self.wall)
        props.backdrop(c, GROUND, self.floor)
        self._draw_keyword(c, t)

        if self.scene["prop"]:
            pop = ease_out_back(progress(t, 0.25, 0.65))
            if pop > 0.02:
                p = progress(t, self.speech_start, self.speech_end)
                _draw_prop(c, self.scene["prop"], pop, p, t, fig)

        fig.draw_shadow(c, tuple(int(v * 0.9) for v in self.floor))
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
        for i, scene in enumerate(spec["scenes"]):
            if use_tts:
                log(f"  narration {i + 1}/{len(spec['scenes'])}...")
                narration = tts.synthesize(scene["narration"], spec["voice"], spec["rate"],
                                           os.path.join(cache_dir, "tts"))
            else:
                narration = tts.estimate(scene["narration"])
            clip = SceneClip(scene, i, narration)
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
                         f"({clip.duration:4.1f}s)  {clip.scene['narration'][:48]}")
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
