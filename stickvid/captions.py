"""Burned-in captions: a few words at a time, current word highlighted.

Captions are drawn on the FINAL frame (after camera and transitions), so
they stay rock-steady while the scene behind them zooms, shakes or slides.

Style: heavy white text with a thick black outline (readable on any
background), the word being spoken in the highlight colour with a small
pop. They sit in the middle-lower part of the frame, above the bottom
400px that app UI covers.
"""

import bisect
from dataclasses import dataclass

from PIL import ImageDraw

from . import config
from .canvas import _font
from .easing import ease_out_back, progress

CAPTION_Y = 1345                 # vertical centre of the caption line
CAPTION_SIZE = 96                # px; shrinks automatically for long chunks
MAX_WIDTH = config.SAFE_BOX[2] - config.SAFE_BOX[0] - 40
LINGER = 0.35                    # seconds a chunk stays after its last word
_BREAK_AFTER = ".?!…,;:"         # punctuation that ends a chunk early


@dataclass
class _Chunk:
    words: list                  # [tts.Word] with absolute times
    start: float
    end: float


class Captions:
    def __init__(self, words, max_words=3, uppercase=True, highlight=(255, 221, 0),
                 color=config.WHITE, outline=(0, 0, 0), max_chars=18):
        """words: every spoken word of the video, in order, with absolute times."""
        self.uppercase = uppercase
        self.highlight = highlight
        self.color = color
        self.outline = outline
        self.chunks = self._chunk(words, max_words, max_chars)
        self._starts = [c.start for c in self.chunks]

    @staticmethod
    def _chunk(words, max_words, max_chars):
        """Group words into short on-screen phrases."""
        groups, current = [], []
        for i, word in enumerate(words):
            too_long = current and sum(len(w.text) + 1 for w in current) + len(word.text) > max_chars
            paused = current and word.start - current[-1].end > 0.45     # audible gap
            if current and (len(current) >= max_words or too_long or paused):
                groups.append(current)
                current = []
            current.append(word)
            if word.text[-1] in _BREAK_AFTER:
                groups.append(current)
                current = []
        if current:
            groups.append(current)

        chunks = []
        for i, group in enumerate(groups):
            end = group[-1].end + LINGER
            if i + 1 < len(groups):
                end = min(end, groups[i + 1][0].start)     # never overlap the next chunk
            chunks.append(_Chunk(group, group[0].start - 0.04, end))
        return chunks

    def draw(self, frame, t):
        """Draw the caption for time t onto a final frame (in place)."""
        i = bisect.bisect_right(self._starts, t) - 1
        if i < 0 or t >= self.chunks[i].end:
            return frame
        chunk = self.chunks[i]
        texts = [w.text.upper() if self.uppercase else w.text for w in chunk.words]

        # Fit the line to the safe width.
        def measure(size):
            font = _font(size)
            # The outline eats into the gap between words, so widen it by the stroke.
            space = font.getlength(" ") + 2 * size * 0.11
            widths = [font.getlength(s) for s in texts]
            return font, space, widths, sum(widths) + space * (len(texts) - 1)

        size = CAPTION_SIZE
        font, space, widths, total = measure(size)
        if total > MAX_WIDTH:
            size = int(size * MAX_WIDTH / total)
            font, space, widths, total = measure(size)

        # The active word is the last one whose start time has passed.
        active = max((k for k, w in enumerate(chunk.words) if w.start <= t + 0.02), default=0)

        d = ImageDraw.Draw(frame)
        stroke = max(4, round(size * 0.11))
        x = config.WIDTH / 2 - total / 2
        centres = []
        for s, w in zip(texts, widths):
            centres.append(x + w / 2)
            x += w + space
        # Inactive words first so the popped active word overlaps its neighbours cleanly.
        for k, s in enumerate(texts):
            if k != active:
                d.text((centres[k], CAPTION_Y), s, font=font, fill=self.color, anchor="mm",
                       stroke_width=stroke, stroke_fill=self.outline)
        pop = 1.0 + 0.09 * ease_out_back(progress(t, chunk.words[active].start, chunk.words[active].start + 0.12))
        big = _font(round(size * pop))
        d.text((centres[active], CAPTION_Y), texts[active], font=big, fill=self.highlight, anchor="mm",
               stroke_width=max(4, round(size * pop * 0.11)), stroke_fill=self.outline)
        return frame
