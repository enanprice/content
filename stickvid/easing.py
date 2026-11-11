"""Easing curves and small interpolation helpers.

Every easing function maps progress p in [0, 1] to an eased value, with
f(0) == 0 and f(1) == 1. Some (back, elastic) deliberately overshoot.
"""

import math


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def progress(t, start, end):
    """Linear 0..1 progress of time t through the window [start, end]."""
    if end <= start:
        return 1.0 if t >= start else 0.0
    return clamp((t - start) / (end - start))


def linear(p):
    return p


def ease_in_quad(p):
    return p * p


def ease_out_quad(p):
    return 1 - (1 - p) ** 2


def ease_in_cubic(p):
    return p ** 3


def ease_out_cubic(p):
    return 1 - (1 - p) ** 3


def ease_in_out_cubic(p):
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_in_out_sine(p):
    return -(math.cos(math.pi * p) - 1) / 2


def ease_out_back(p, overshoot=1.70158):
    """Shoots slightly past the target and settles. Great for snappy poses."""
    c3 = overshoot + 1
    return 1 + c3 * (p - 1) ** 3 + overshoot * (p - 1) ** 2


def ease_out_elastic(p):
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return 2 ** (-10 * p) * math.sin((p * 10 - 0.75) * (2 * math.pi) / 3) + 1


def ease_out_bounce(p):
    n, d = 7.5625, 2.75
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        p -= 1.5 / d
        return n * p * p + 0.75
    if p < 2.5 / d:
        p -= 2.25 / d
        return n * p * p + 0.9375
    p -= 2.625 / d
    return n * p * p + 0.984375


def tween(t, start, duration, a, b, ease=ease_in_out_cubic):
    """Value going from a to b over [start, start+duration], eased."""
    return lerp(a, b, ease(progress(t, start, start + duration)))
