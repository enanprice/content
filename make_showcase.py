#!/usr/bin/env python3
"""Render reference sheets of every pose, expression and prop.

Usage:  python make_showcase.py      # -> docs/showcase_figure.png, docs/showcase_props.png

Handy as a visual regression check after editing figure.py or props.py.
"""

import os

from stickvid import Canvas, StickFigure, config, props

SHEET_W, SHEET_H = 1920, 1080
POSE_NAMES = ["idle", "talking", "pointing", "facepalm", "shrug", "sleeping", "walking"]
FACE_NAMES = ["neutral", "happy", "stressed", "smug", "tired", "guilty", "asleep"]


def figure_sheet():
    c = Canvas(SHEET_W, SHEET_H)
    col = SHEET_W / 7
    for i, name in enumerate(POSE_NAMES):
        x, ground = col * (i + 0.5), 470
        asleep = name == "sleeping"
        fig = StickFigure(x, ground, scale=0.5, pose=name, alive=False,
                          expression="asleep" if asleep else "neutral")
        fig.draw_shadow(c, config.FLOOR)
        fig.draw(c)
        if asleep:
            props.zzz(c, x - 60, ground - 120, t=0.6, size=30)
        c.text((x, ground + 50), name, 30)
    for i, name in enumerate(FACE_NAMES):
        x, ground = col * (i + 0.5), 960
        fig = StickFigure(x, ground, scale=0.5, expression=name, alive=False)
        fig.draw_shadow(c, config.FLOOR)
        fig.draw(c)
        c.text((x, ground + 50), name, 30)
    return c.to_frame()


def props_sheet():
    c = Canvas(SHEET_W, SHEET_H)
    cells = [
        ("phone", lambda x, y: props.phone(c, x, y, 260, angle=8, scroll=0.3)),
        ("book", lambda x, y: (props.book(c, x - 150, y, 110, 150), props.book(c, x + 80, y, 110, 150, open=1))),
        ("clock", lambda x, y: props.clock(c, x, y, 120)),
        ("brain", lambda x, y: props.brain(c, x, y, 240)),
        ("battery", lambda x, y: (props.battery(c, x, y - 70, 240, 100, 0.2),
                                  props.battery(c, x, y + 70, 240, 100, 0.85, charging=True))),
        ("thought bubble", lambda x, y: props.thought_bubble(c, x + 20, y - 40, 260, 190, tail_to=(x - 130, y + 140))),
        ("checklist", lambda x, y: props.checklist(c, x, y + 10, 260, 300, ["read", "sleep", "scroll"], checked=1.6)),
        ("bar chart", lambda x, y: props.bar_chart(c, x, y - 10, 280, 240, labels=["Mon", "Tue", "Wed"])),
        ("arrows", lambda x, y: (props.arrow(c, (x - 120, y + 90), (x + 120, y - 90), config.RED, curve=0.3),
                                 props.arrow(c, (x - 120, y - 80), (x + 110, y + 100), progress=0.9))),
        ("zzz (extra)", lambda x, y: props.zzz(c, x - 60, y + 90, t=0.6, size=50)),
    ]
    for i, (name, draw) in enumerate(cells):
        x, y = SHEET_W / 5 * (i % 5 + 0.5), 270 + 520 * (i // 5)
        draw(x, y)
        c.text((x, y + 215), name, 32)
    return c.to_frame()


if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    figure_sheet().save("docs/showcase_figure.png")
    props_sheet().save("docs/showcase_props.png")
    print("wrote docs/showcase_figure.png and docs/showcase_props.png")
