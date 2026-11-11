"""Keyframe tracks.

A Track holds one animated value (a number, a tuple of numbers, or any
object with a .lerp(other, t) method such as Pose / Face). You schedule
transitions with .to(); .at(t) returns the value at time t.

Tracks are pure functions of time, so frames can be rendered in any order
and a transition that interrupts an unfinished one starts from wherever
the value actually was - no popping.
"""

from dataclasses import dataclass
from typing import Any, Callable

from .easing import ease_in_out_cubic


def blend(a, b, t):
    """Interpolate numbers, tuples of numbers, or objects exposing .lerp()."""
    if hasattr(a, "lerp"):
        return a.lerp(b, t)
    if isinstance(a, (tuple, list)):
        return tuple(x + (y - x) * t for x, y in zip(a, b))
    return a + (b - a) * t


@dataclass
class _Key:
    start: float
    duration: float
    value: Any
    ease: Callable[[float], float]


class Track:
    def __init__(self, initial):
        self.initial = initial
        self.keys = []

    def to(self, value, at, duration=0.4, ease=ease_in_out_cubic):
        """Start moving towards `value` at time `at`, arriving `duration` later."""
        self.keys.append(_Key(at, max(duration, 0.0), value, ease))
        self.keys.sort(key=lambda k: k.start)
        return self

    def at(self, t):
        return self._eval(len(self.keys), t)

    def _eval(self, n, t):
        """Value at time t considering only the first n keyframes."""
        while n > 0 and self.keys[n - 1].start > t:
            n -= 1
        if n == 0:
            return self.initial
        key = self.keys[n - 1]
        if t >= key.start + key.duration:
            return key.value
        # Mid-transition: blend from wherever the earlier keys had us at
        # the moment this transition began.
        base = self._eval(n - 1, key.start)
        return blend(base, key.value, key.ease((t - key.start) / key.duration))
