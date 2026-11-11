"""VideoWriter: streams Pillow frames into ffmpeg over a pipe.

Frames go straight to ffmpeg's stdin as raw RGB, so nothing is written to
disk except the finished MP4 (H.264, yuv420p, faststart - the combination
every social platform accepts).
"""

import os
import shutil
import subprocess
import tempfile

from . import config


class VideoWriter:
    def __init__(self, path, width=config.WIDTH, height=config.HEIGHT, fps=config.FPS,
                 crf=18, preset="medium", frames_dir=None):
        """
        crf         quality: lower = better/larger (18 is visually lossless)
        frames_dir  if set, also save every frame there as a PNG (debugging)
        """
        self.path = str(path)
        self.size = (width, height)
        self.fps = fps
        self.crf = crf
        self.preset = preset
        self.frames_dir = frames_dir
        self.count = 0
        self._proc = None
        self._log = None

    def __enter__(self):
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg not found on PATH - see the install steps in README.md")
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        if self.frames_dir:
            os.makedirs(self.frames_dir, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            # input: raw RGB frames on stdin
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{self.size[0]}x{self.size[1]}", "-r", str(self.fps), "-i", "-",
            # output: H.264 in MP4
            "-an", "-c:v", "libx264", "-preset", self.preset, "-crf", str(self.crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            self.path,
        ]
        # ffmpeg's messages go to a temp file: a pipe nobody reads could fill up and stall it.
        self._log = tempfile.TemporaryFile()
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self._log)
        return self

    def write(self, frame):
        """Append one frame (a Pillow image of exactly the output size)."""
        if frame.size != self.size:
            raise ValueError(f"frame is {frame.size}, expected {self.size}")
        if self.frames_dir:
            frame.save(os.path.join(self.frames_dir, f"frame_{self.count:05d}.png"))
        try:
            self._proc.stdin.write(frame.convert("RGB").tobytes())
        except BrokenPipeError:
            raise RuntimeError(f"ffmpeg exited early:\n{self._finish()}") from None
        self.count += 1

    def _finish(self):
        """Close the pipe, wait for ffmpeg, and return whatever it logged."""
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        self._proc.wait()
        self._log.seek(0)
        log = self._log.read().decode(errors="replace")
        self._log.close()
        return log

    def __exit__(self, exc_type, exc, tb):
        log = self._finish()
        if exc_type is None and self._proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {self._proc.returncode}):\n{log}")
        return False
