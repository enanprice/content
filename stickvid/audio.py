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


def _write_wav(path, samples):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    frames = bytearray()
    for v in samples:
        frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(frames))
    return path


def make_chime(path, duration=2.6, volume=0.5):
    """A clock-tower bell: a few inharmonic partials, struck hard and left to ring."""
    partials = [(220.0, 1.0, 1.1), (440.5, 0.6, 1.6), (657.0, 0.45, 2.2), (893.0, 0.3, 3.0), (1320.0, 0.18, 4.2)]
    out = []
    for i in range(int(SAMPLE_RATE * duration)):
        t = i / SAMPLE_RATE
        v = sum(amp * math.exp(-decay * t) * math.sin(2 * math.pi * freq * t) for freq, amp, decay in partials)
        out.append(v / 2.5 * volume * min(1.0, t / 0.004) * min(1.0, (duration - t) / 0.2))
    return _write_wav(path, out)


def make_engine(path, duration=4.0, volume=0.5):
    """A bus engine: low rumble with a slow throb, fading in and out."""
    rng = random.Random(11)
    low, out = 0.0, []
    for i in range(int(SAMPLE_RATE * duration)):
        t = i / SAMPLE_RATE
        low += 0.02 * (rng.uniform(-1, 1) - low)                    # heavily low-passed noise
        tone = math.sin(2 * math.pi * 58 * t) + 0.5 * math.sin(2 * math.pi * 116 * t + 0.6)
        throb = 0.75 + 0.25 * math.sin(2 * math.pi * 9 * t)
        fade = min(1.0, t / 0.5) * min(1.0, (duration - t) / 0.7)
        out.append((0.45 * tone + 5.0 * low) * throb * fade * volume * 0.6)
    return _write_wav(path, out)


# name -> (maker, default volume in the mix). "bus_engine" is made to the length of its shot.
SFX = {"clock_chime": (make_chime, 0.6), "bus_engine": (make_engine, 0.5), "whoosh": (make_whoosh, 0.35)}


def mux(video_path, out_path, duration, clips=(), music=None, speech=(), duck=False):
    """Combine the silent video with its soundtrack.

    clips   [Clip] sounds placed at their start times (effects; narration too, if not ducking)
    speech  [Clip] narration, kept separate so music can duck under it
    music   {"path": ..., "volume": ...} or None; looped to the video's
            length, faded in and out, and kept quiet under the voice
    duck    lower the music automatically whenever speech is playing
    """
    clips, speech = list(clips), list(speech)
    if not clips and not speech and not music:
        shutil.copyfile(video_path, out_path)            # nothing to add
        return out_path

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video_path]
    filters, labels = [], []
    fmt = f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
    n = 0

    def place(clip, tag):
        nonlocal n
        n += 1
        cmd.extend(["-i", clip.path])
        delay = max(0, round(clip.start * 1000))
        filters.append(f"[{n}:a]{fmt},volume={clip.volume:.3f},adelay={delay}:all=1[{tag}{n}]")
        return f"[{tag}{n}]"

    speech_labels = [place(c, "s") for c in speech]
    labels += [place(c, "a") for c in clips]

    key = None
    if speech_labels:
        # All narration on one bus, padded to the full length so it can drive the ducking.
        filters.append(f"{''.join(speech_labels)}amix=inputs={len(speech_labels)}:normalize=0:duration=longest,"
                       f"apad,atrim=0:{duration:.3f}[speech]")
        if duck and music:
            filters.append("[speech]asplit=2[speech_mix][speech_key]")
            labels.append("[speech_mix]")
            key = "[speech_key]"
        else:
            labels.append("[speech]")

    if music:
        n += 1
        cmd += ["-stream_loop", "-1", "-i", music["path"]]   # loop short tracks
        fade_out = max(0.0, duration - 1.5)
        filters.append(f"[{n}:a]{fmt},atrim=0:{duration:.3f},volume={music['volume']:.3f},"
                       f"afade=t=in:d=0.8,afade=t=out:st={fade_out:.3f}:d=1.5[music]")
        if key:
            # Sidechain compressor: the voice pushes the music down, and it
            # recovers over about half a second when the voice stops.
            filters.append(f"[music]{key}sidechaincompress=threshold=0.02:ratio=6:attack=20:release=450[ducked]")
            labels.append("[ducked]")
        else:
            labels.append("[music]")

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
