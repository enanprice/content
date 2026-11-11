"""stickvid - tiny toolkit for rendering vertical stick-figure videos.

Modules
-------
config    frame size, fps, safe zone, palette
easing    easing curves + small math helpers
timeline  Track: keyframed values with eased transitions
canvas    Canvas: supersampled Pillow drawing surface (logical 1080x1920 coords)
figure    StickFigure, Pose, Face, POSES, EXPRESSIONS
props     phone, book, clock, brain, battery, thought bubble, checklist, bar chart, arrows
camera    Camera / CameraRig (zoom, shake) and slide_transition
video     VideoWriter: pipes frames into ffmpeg
"""

from . import config, easing, props
from .camera import Camera, CameraRig, slide_transition
from .canvas import Canvas, draw_safe_guides
from .figure import EXPRESSIONS, POSES, Face, Pose, StickFigure, march_cycle, walk_cycle
from .timeline import Track
from .video import VideoWriter

__all__ = [
    "config", "easing", "props",
    "Camera", "CameraRig", "slide_transition",
    "Canvas", "draw_safe_guides",
    "EXPRESSIONS", "POSES", "Face", "Pose", "StickFigure", "march_cycle", "walk_cycle",
    "Track", "VideoWriter",
]
