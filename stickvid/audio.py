"""Soundtrack: narration clips, optional music bed and transition whooshes.

mux() lays every sound on a timeline with ffmpeg and attaches the mix to
the silent video (the video stream is copied, not re-encoded).

The whoosh is synthesised here - filtered noise with a rising pitch - so
the project needs no sound files of its own.
"""

import math
import os
import random
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass

SAMPLE_RATE = 44100


@dataclass
class Clip:
    path: str
    start: float          # seconds from the start of the video
    volume: float = 1.0


def make_whoosh(path, duration=0.45, volume=0.5):
    """Write a short, soft whoosh to `path` (mono 16-bit WAV)."""
    rng = random.Random(7)                       # fixed seed: identical file every time
    n = int(SAMPLE_RATE * duration)
    low = band = 0.0
    frames = bytearray()
    for i in range(n):
        p = i / n
        # State-variable band-pass over white noise; sweeping the centre
        # frequency upwards is what makes it sound like movement.
        freq = 350 + 2600 * p * p
        f = 2 * math.sin(math.pi * freq / SAMPLE_RATE)
        high = rng.uniform(-1, 1) - low - 0.7 * band
        band += f * high
        low += f * band
        envelope = math.sin(math.pi * p) ** 2    # fade in and out, no clicks
        sample = max(-1.0, min(1.0, band * envelope * volume))
        frames += struct.pack("<h", int(sample * 32767))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(frames))
    return path


def mux(video_path, out_path, duration, clips=(), music=None):
    """Combine the silent video with its soundtrack.

    clips   [Clip] narration and effects, each placed at its start time
    music   {"path": ..., "volume": ...} or None; looped to the video's
            length, faded in and out, and kept quiet under the voice
    """
    clips = list(clips)
    if not clips and not music:
        shutil.copyfile(video_path, out_path)            # nothing to add
        return out_path

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video_path]
    filters, labels = [], []
    fmt = f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
    for i, clip in enumerate(clips, start=1):
        cmd += ["-i", clip.path]
        delay = max(0, round(clip.start * 1000))
        filters.append(f"[{i}:a]{fmt},volume={clip.volume:.3f},adelay={delay}:all=1[a{i}]")
        labels.append(f"[a{i}]")
    if music:
        i = len(clips) + 1
        cmd += ["-stream_loop", "-1", "-i", music["path"]]   # loop short tracks
        fade_out = max(0.0, duration - 1.5)
        filters.append(f"[{i}:a]{fmt},atrim=0:{duration:.3f},volume={music['volume']:.3f},"
                       f"afade=t=in:d=0.8,afade=t=out:st={fade_out:.3f}:d=1.5[a{i}]")
        labels.append(f"[a{i}]")

    # normalize=0 keeps each track at the level set above instead of
    # dividing by the number of inputs; apad+atrim makes the audio exactly
    # as long as the video.
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,"
                   f"alimiter=limit=0.95,apad,atrim=0:{duration:.3f}[mix]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[mix]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed while mixing audio:\n{result.stderr.strip()}")
    return out_path
