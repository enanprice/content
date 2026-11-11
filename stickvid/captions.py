"""Burned-in captions: a short phrase at a time, the spoken word picked out.

Captions are drawn on the FINAL frame (after camera and transitions), so
they stay steady while the scene behind them zooms, shakes or slides.

Style: sentence-case text on a soft dark strip. Words already spoken are
white, the word being spoken takes the highlight colour, and words still to
come are dimmed - so the eye is led along without anything jumping about.
They sit in the middle-lower part of the frame, above the bottom 400px that
app UI covers.
"""

import bisect
from dataclasses import dataclass

from PIL import Image, ImageDraw

from . import config
from .canvas import _font

CAPTION_Y = 1385                 # vertical centre of the caption strip
CAPTION_SIZE = 56                # px; shrinks automatically for long phrases
PAD_X, PAD_Y = 30, 18            # strip padding around the text
MAX_WIDTH = config.SAFE_BOX[2] - config.SAFE_BOX[0] - 2 * PAD_X - 20
LINGER = 0.35                    # seconds a phrase stays after its last word
STRIP = (16, 18, 28, 150)        # translucent dark background
UPCOMING_ALPHA = 130             # opacity of words not yet spoken
_BREAK_AFTER = ".?!…,;:"         # punctuation that ends a phrase early


@dataclass
class _Chunk:
    words: list                  # [tts.Word] with absolute times
    start: float
    end: float


class Captions:
    def __init__(self, words, max_words=4, uppercase=False, highlight=(255, 221, 120),
                 color=config.WHITE, max_chars=26):
        """words: every spoken word of the video, in order, with absolute times."""
        self.uppercase = uppercase
        self.highlight = highlight
        self.color = color
        self.chunks = self._chunk(words, max_words, max_chars)
        self._starts = [c.start for c in self.chunks]

    @staticmethod
    def _chunk(words, max_words, max_chars):
        """Group words into short on-screen phrases."""
        groups, current = [], []
        for word in words:
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
                end = min(end, groups[i + 1][0].start)     # never overlap the next phrase
            chunks.append(_Chunk(group, group[0].start - 0.04, end))
        return chunks

    def draw(self, frame, t):
        """Draw the caption for time t onto a final frame (in place)."""
        i = bisect.bisect_right(self._starts, t) - 1
        if i < 0 or t >= self.chunks[i].end:
            return frame
        chunk = self.chunks[i]
        texts = [w.text.upper() if self.uppercase else w.text for w in chunk.words]

        def measure(size):
            font = _font(size)
            space = font.getlength(" ")
            widths = [font.getlength(s) for s in texts]
            return font, space, widths, sum(widths) + space * (len(texts) - 1)

        size = CAPTION_SIZE
        font, space, widths, total = measure(size)
        if total > MAX_WIDTH:
            size = int(size * MAX_WIDTH / total)
            font, space, widths, total = measure(size)

        # The active word is the last one whose start time has passed.
        active = max((k for k, w in enumerate(chunk.words) if w.start <= t + 0.02), default=0)

        # Draw strip + text on a transparent layer, then blend it onto the frame.
        w, h = round(total + 2 * PAD_X), round(size * 1.3 + 2 * PAD_Y)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h * 0.3, fill=STRIP)
        x = PAD_X
        for k, (s, word_w) in enumerate(zip(texts, widths)):
            if k < active:
                fill = self.color + (255,)
            elif k == active:
                fill = self.highlight + (255,)
            else:
                fill = self.color + (UPCOMING_ALPHA,)
            d.text((x, h / 2), s, font=font, fill=fill, anchor="lm")
            x += word_w + space
        frame.paste(layer, (round(config.WIDTH / 2 - w / 2), round(CAPTION_Y - h / 2)), layer)
        return frame
