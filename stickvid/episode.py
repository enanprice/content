"""Episode pipeline: a 3D shot list -> narrated, captioned MP4.

    1. narration  edge-tts speaks each shot's line and reports when every
                  word starts; the line's length sets the shot's length
    2. picture    Blender (blender/shots.py) renders the shots to PNG frames
    3. captions   each frame gets word-by-word captions burned in
    4. sound      narration + sound effects + music (ducked under the voice)
    5. export     H.264 MP4 at 30 fps, 1080x1920, plus a thumbnail PNG

make.py calls build() for any JSON file that contains "shots".
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace

from PIL import Image

from . import config, tts
from .audio import SFX, Clip, mux
from .captions import Captions
from .video import VideoWriter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "blender"))
import shotlist  # noqa: E402  (the shot-list validator; plain Python, no Blender needed)

FPS = 30
LEAD = 0.30        # silence before a shot's narration
TAIL = 0.45        # and after it, before the cut
MUSIC_DEFAULT = 0.12


class EpisodeError(RuntimeError):
    pass


def find_blender(explicit=None):
    """Path to the Blender program: --blender, then $BLENDER, then the PATH,
    then the usual install locations."""
    candidates = [explicit, os.environ.get("BLENDER"), shutil.which("blender"),
                  "/Applications/Blender.app/Contents/MacOS/Blender",
                  *sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True)]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    raise EpisodeError(
        "Blender was not found. Install Blender 4.2 or newer, then either put it on your PATH, "
        "set the BLENDER environment variable to the program's full path, or pass --blender PATH.")


def plan_timing(spec, use_tts, cache_dir, log):
    """Narrate each shot and fix every shot's length.

    Returns (durations, narrations): seconds per shot (whole frames), and
    the tts.Narration for each shot or None.
    """
    durations, narrations = [], []
    for i, shot in enumerate(spec["shots"]):
        narration = None
        if shot["narration"]:
            if use_tts:
                log(f"  narration {i + 1}/{len(spec['shots'])}...")
                narration = tts.synthesize(shot["narration"], spec["voice"], spec["rate"],
                                           os.path.join(cache_dir, "tts"))
            else:
                narration = tts.estimate(shot["narration"])
        if shot["duration"] == "auto":
            seconds = tts.audio_duration(shot["audio"])
        else:
            seconds = shot["duration"] or 0.0
        if narration:
            # As long as the speech (measured to the end of the last word:
            # edge-tts pads its files with silence), or longer if a duration asks for it.
            spoken = min(narration.duration, narration.words[-1].end + 0.1)
            seconds = max(seconds, LEAD + spoken + TAIL)
        durations.append(max(1, round(seconds * FPS)) / FPS)        # whole frames, as the renderer counts them
        narrations.append(narration)
    return durations, narrations


def run_blender(blender, resolved_path, frames_root, preview, log):
    """Render the shot list to PNG frames with blender/shots.py."""
    cmd = [blender, "-b", "-P", os.path.join(ROOT, "blender", "shots.py"), "--",
           resolved_path, "--out", frames_root]
    if preview:
        cmd.append("--preview")
    log("  rendering in Blender (this is the slow part)...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    tail = []
    for line in proc.stdout:
        line = line.rstrip()
        tail = (tail + [line])[-25:]
        if re.match(r"(shot \d+:|rendered shot|timeline:|  note:)", line):
            log("  " + line.strip())
    if proc.wait() != 0:
        raise EpisodeError("Blender failed. Its last lines were:\n  " + "\n  ".join(tail))
    frames = sorted(glob.glob(os.path.join(frames_root, "frames", "frame_*.png")))
    if not frames:
        raise EpisodeError("Blender finished but wrote no frames. Its last lines were:\n  " + "\n  ".join(tail))
    return frames


def build(path, out_dir, preview=False, use_tts=True, blender=None, log=print, cache_dir=".cache"):
    """Build one episode. Returns (name, duration_seconds)."""
    name = os.path.splitext(os.path.basename(path))[0]
    spec = shotlist.load(path)
    blender = find_blender(blender)
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, name + "_work")
    shutil.rmtree(os.path.join(work, "frames"), ignore_errors=True)   # never mix frames from an older run
    os.makedirs(work, exist_ok=True)

    # 1. narration and timing
    durations, narrations = plan_timing(spec, use_tts, cache_dir, log)
    starts = [sum(durations[:i]) for i in range(len(durations))]
    total = sum(durations)
    for i, (shot, start, seconds) in enumerate(zip(spec["shots"], starts, durations)):
        log(f"  shot {i + 1}: {start:5.1f}s -> {start + seconds:5.1f}s ({seconds:4.1f}s)  {shot['name']}")
    log(f"  total: {total:.1f}s")

    # 2. picture: hand Blender the same shot list with every duration filled in
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    for shot, seconds in zip(raw["shots"], durations):
        shot["duration"] = seconds
        shot.pop("audio", None)
    raw.pop("music", None)                                            # sound is mixed here, not in Blender
    resolved = os.path.join(work, name + ".resolved.json")
    with open(resolved, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    frames = run_blender(blender, resolved, work, preview, log)
    numbered = [(int(re.search(r"frame_(\d+)\.png$", f).group(1)), f) for f in frames]

    # thumbnail: the middle of the first shot, before captions go on
    first_shot_last = round(durations[0] * FPS)
    middle = [f for n, f in numbered if n <= first_shot_last]
    shutil.copyfile(middle[len(middle) // 2], os.path.join(out_dir, name + ".png"))

    # 3. captions, drawn in full-size coordinates so they sit in the same place in a preview
    words = [replace(w, start=w.start + start + LEAD, end=w.end + start + LEAD)
             for narration, start in zip(narrations, starts) if narration for w in narration.words]
    captions = Captions(words, max_words=3, uppercase=True, highlight=(255, 221, 0),
                        max_chars=18, style="bold") if words else None

    out_fps = FPS // 2 if preview else FPS
    size = (config.WIDTH // 2, config.HEIGHT // 2) if preview else (config.WIDTH, config.HEIGHT)
    silent = os.path.join(work, name + ".silent.mp4")
    log("  burning captions and encoding...")
    with VideoWriter(silent, size[0], size[1], out_fps, crf=26 if preview else 18,
                     preset="veryfast" if preview else "medium") as video:
        cursor = 0
        for k in range(round(total * out_fps)):
            t = k / out_fps
            # The latest rendered frame at or before this moment (a preview has only every second frame).
            wanted = 1 + round(t * FPS)
            while cursor + 1 < len(numbered) and numbered[cursor + 1][0] <= wanted:
                cursor += 1
            img = Image.open(numbered[cursor][1]).convert("RGB")
            if captions:
                if img.size != (config.WIDTH, config.HEIGHT):
                    img = img.resize((config.WIDTH, config.HEIGHT), Image.Resampling.BILINEAR)
                captions.draw(img, t)
            if img.size != size:
                img = img.resize(size, Image.Resampling.BILINEAR)
            video.write(img)

    # 4. sound
    speech = [Clip(n.path, start + LEAD) for n, start in zip(narrations, starts) if n and n.path]
    effects = []
    for shot, start, seconds in zip(spec["shots"], starts, durations):
        for fx in shot["sfx"]:
            maker, volume = SFX[fx["tag"]]
            if fx["tag"] == "bus_engine":                              # runs for the rest of its shot
                length = max(1.0, seconds - fx["at"])
                wav = maker(os.path.join(cache_dir, "sfx", f"bus_engine_{length:.2f}.wav"), duration=length)
            else:
                wav = maker(os.path.join(cache_dir, "sfx", fx["tag"] + ".wav"))
            effects.append(Clip(wav, start + fx["at"], fx["volume"] if fx["volume"] is not None else volume))

    # 5. export
    final = os.path.join(out_dir, name + ".mp4")
    mux(silent, final, total, clips=effects, music=spec["music"], speech=speech, duck=True)
    os.remove(silent)
    return name, total
