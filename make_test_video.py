#!/usr/bin/env python3
"""Render the 10-second test video.

Story:  0.0-3.3s  figure doom-scrolls on a phone while the clock races
        3.3-5.8s  a thought of the unread book pops up -> guilt (zoom-in)
        5.8-7.0s  drops the phone (camera shake on impact)
        7.0-7.5s  slide transition
        7.5-10s   opens the book, brain battery recharges

Usage:  python make_test_video.py                 # -> output/test_video.mp4
        python make_test_video.py --guides        # tint the unsafe zones red
        python make_test_video.py --fast          # no anti-aliasing, quick preview
"""

import argparse
import math
import sys
import time

from stickvid import Canvas, CameraRig, Pose, StickFigure, VideoWriter, config, props
from stickvid import draw_safe_guides, slide_transition
from stickvid.easing import (ease_in_cubic, ease_in_out_cubic, ease_out_back,
                             ease_out_cubic, progress)

DURATION = 10.0
GROUND = 1470                 # floor line; feet stand well above the unsafe bottom 400px

T_BUBBLE = 2.9                # thought bubble pops in
T_GUILT = 3.3                 # face changes
T_RELEASE = 6.0               # phone leaves the hand
T_SLIDE = 7.0                 # slide transition starts
SLIDE_LEN = 0.5

PHONE_H = 220


class PhoneDrop:
    """Ballistic fall with one small bounce, then the phone rests on the floor."""

    GRAVITY = 3400.0          # px/s^2 - heavier than real life so it reads as a snappy drop

    def __init__(self, pos, angle, t0, floor_y, velocity=(150.0, -260.0)):
        self.x0, self.y0 = pos
        self.a0, self.t0, self.floor = angle, t0, floor_y
        self.vx, self.vy = velocity
        g = self.GRAVITY
        # Solve y0 + vy*t + g/2*t^2 = floor for the time of first impact.
        self.fall = (-self.vy + math.sqrt(self.vy ** 2 + 2 * g * (floor_y - self.y0))) / g
        self.bounce_v = -0.28 * (self.vy + g * self.fall)     # rebound speed (upwards)
        self.bounce = -2 * self.bounce_v / g                   # air time of the bounce
        self.t_impact = t0 + self.fall

    def at(self, t):
        """-> (x, y, angle, landed)"""
        tau = t - self.t0
        if tau < self.fall:
            p = tau / self.fall
            return (self.x0 + self.vx * tau,
                    self.y0 + self.vy * tau + 0.5 * self.GRAVITY * tau * tau,
                    self.a0 + (270 - self.a0) * ease_in_cubic(p), False)   # spins to lie flat
        tb = min(tau - self.fall, self.bounce)
        x = self.x0 + self.vx * self.fall + self.vx * 0.4 * tb
        y = self.floor + self.bounce_v * tb + 0.5 * self.GRAVITY * tb * tb
        return (x, y, 270.0, True)


class ScrollScene:
    """Scene A: scrolling -> guilt -> dropping the phone."""

    WALL = (226, 228, 247)
    FLOOR = (200, 204, 232)

    def __init__(self):
        fig = self.fig = StickFigure(x=470, ground_y=GROUND, pose="scrolling", expression="tired")
        scrolling = fig.pose
        fig.look_to((0.85, 0.3), at=0, duration=0)                 # eyes glued to the phone

        # Each swipe: the forearm flicks up a touch and the feed advances one post.
        self.swipes = [0.35, 1.05, 1.7, 2.3]
        flick = Pose(**{**scrolling.__dict__, "r_fore": 142, "head_tilt": 9})
        for ts in self.swipes:
            fig.pose_to(flick, at=ts, duration=0.1, ease=ease_out_cubic)
            fig.pose_to("scrolling", at=ts + 0.1, duration=0.25)

        # Guilt: glance at the thought bubble, back at the phone, then at us.
        fig.look_to((0.6, -0.8), at=T_BUBBLE + 0.25)
        fig.expression_to("guilty", at=T_GUILT, duration=0.35)
        fig.pose_to(Pose(head_tilt=-2, shoulder_raise=0.8, r_upper=34, r_fore=128),
                    at=T_GUILT, duration=0.5)
        fig.look_to((0.85, 0.35), at=4.15)
        fig.look_to((-0.6, 0.1), at=4.65)
        fig.expression_to("stressed", at=4.6, duration=0.3)
        fig.look_to((0.0, 0.0), at=5.15)

        # Decision: fling the arm open and let go.
        fig.expression_to("neutral", at=5.75, duration=0.2)
        fig.pose_to(Pose(lean=-3, shoulder_raise=0.3, l_upper=-32, l_fore=-22, r_upper=72, r_fore=62),
                    at=T_RELEASE - 0.15, duration=0.3, ease=ease_out_back)
        fig.look_to((0.7, 0.9), at=T_RELEASE + 0.15)               # watch it fall
        fig.pose_to("idle", at=6.6, duration=0.35)

        # Work out where the phone is at the moment of release, then hand it to physics.
        fig.update(T_RELEASE)
        x, y, angle = self._held_phone()
        self.drop = PhoneDrop((x, y), angle, T_RELEASE, floor_y=GROUND - PHONE_H * 0.52 / 2 - 4)

        self.cam = CameraRig()
        self.cam.zoom_to(1.4, center=(545, 800), at=3.5, duration=0.7)   # push in on the guilty face
        self.cam.reset(at=5.3, duration=0.5)
        self.cam.shake(at=self.drop.t_impact, duration=0.45, amplitude=24)

    def _held_phone(self):
        """Phone position/tilt while gripped: it sits above the hand and follows the forearm."""
        hx, hy = self.fig.joints["r_hand"]
        return hx + 6, hy - PHONE_H * 0.28, 8 + (self.fig.pose.r_fore - 135) * 0.6

    def render(self, t):
        fig = self.fig.update(t)
        c = Canvas(bg=self.WALL)
        props.backdrop(c, GROUND, self.FLOOR)

        # Clock races from 11pm to 2am while the scrolling goes on.
        props.clock(c, 270, 440, r=105, time=23 + 3 * ease_in_out_cubic(progress(t, 0.2, 3.2)))

        # Thought bubble: pops in, shrinks away once the decision is made.
        pop = ease_out_back(progress(t, T_BUBBLE, T_BUBBLE + 0.4)) * (1 - ease_in_cubic(progress(t, 5.55, 5.8)))
        head = fig.joints["head"]
        props.thought_bubble(c, 730, 470, w=300, h=230, pop=pop,
                             tail_to=(head[0] + 85, head[1] - 95))
        if pop > 0.3:
            props.book(c, 730 - 42 * pop, 470, w=84 * pop, h=112 * pop)

        fig.draw_shadow(c, _darker(self.FLOOR))
        fig.draw(c)

        scroll = sum(ease_out_cubic(progress(t, ts, ts + 0.35)) for ts in self.swipes)
        if t < T_RELEASE:
            x, y, angle = self._held_phone()
            props.phone(c, x, y, PHONE_H, angle, scroll)
            fig.draw_hands(c)                                     # thumb over the phone
        else:
            x, y, angle, landed = self.drop.at(t)
            props.phone(c, x, y, PHONE_H, angle, scroll, screen_on=not landed)

        return c.to_frame(self.cam.at(t))


class BookScene:
    """Scene B: opening the book while the brain battery recharges."""

    WALL = (255, 243, 214)
    FLOOR = (240, 219, 178)
    T_OPEN = 7.8

    def __init__(self):
        fig = self.fig = StickFigure(x=540, ground_y=GROUND, pose="hold_book", expression="neutral")
        fig.look_to((0.0, 0.9), at=0, duration=0)                  # looking down at the book
        fig.pose_to("read_book", at=self.T_OPEN, duration=0.7)
        fig.expression_to("happy", at=8.3, duration=0.4)
        fig.look_to((0.0, 0.0), at=9.45, duration=0.25)            # final look to camera

    def render(self, t):
        fig = self.fig.update(t)
        c = Canvas(bg=self.WALL)
        props.backdrop(c, GROUND, self.FLOOR)

        # Brain -> battery: focus recharging as the reading starts.
        charge = ease_in_out_cubic(progress(t, 8.1, 9.5))
        props.brain(c, 310, 480, size=190 * (1 + 0.03 * math.sin(t * 6)))
        props.arrow(c, (440, 480), (560, 480), width=13, progress=ease_out_cubic(progress(t, 7.7, 8.1)))
        props.battery(c, 730, 480, w=270, h=124, level=0.1 + 0.9 * charge, charging=0 < charge < 1)

        fig.draw_shadow(c, _darker(self.FLOOR))
        fig.draw(c)

        # The book sits between the hands; its spine slides to the middle as it opens.
        opened = ease_in_out_cubic(progress(t, self.T_OPEN, self.T_OPEN + 0.7))
        (lx, ly), (rx, ry) = fig.joints["l_hand"], fig.joints["r_hand"]
        w, h = 150, 196
        props.book(c, (lx + rx) / 2 - w / 2 * (1 - opened), (ly + ry) / 2 - h / 2 + 34, w, h, open=opened)
        fig.draw_hands(c)

        return c.to_frame()


def _darker(color, k=0.9):
    return tuple(int(v * k) for v in color)


def make_renderer():
    """Returns frame(t) -> final 1080x1920 Pillow image."""
    scroll, book = ScrollScene(), BookScene()

    def frame(t):
        if t < T_SLIDE:
            return scroll.render(t)
        if t < T_SLIDE + SLIDE_LEN:
            return slide_transition(scroll.render(t), book.render(t), t, T_SLIDE, SLIDE_LEN, "left")
        return book.render(t)

    return frame


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="output/test_video.mp4")
    ap.add_argument("--guides", action="store_true", help="overlay the unsafe zones in red")
    ap.add_argument("--fast", action="store_true", help="disable supersampling (quick preview)")
    args = ap.parse_args()
    if args.fast:
        config.SSAA = 1

    frame = make_renderer()
    total = round(DURATION * config.FPS)
    started = time.time()
    with VideoWriter(args.out) as video:
        for i in range(total):
            img = frame(i / config.FPS)
            video.write(draw_safe_guides(img) if args.guides else img)
            if (i + 1) % config.FPS == 0 or i + 1 == total:
                sys.stdout.write(f"\rrendered {i + 1}/{total} frames")
                sys.stdout.flush()
    print(f"\nwrote {args.out} ({total / config.FPS:.1f}s, {time.time() - started:.0f}s to render)")


if __name__ == "__main__":
    main()
