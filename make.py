#!/usr/bin/env python3
"""Build videos from JSON specs.

    python make.py videos/*.json          2D stick-figure videos ("scenes")
    python make.py episodes/ep01.json     3D Blender episodes ("shots")

For every spec this writes three files to out/ (change with --out):

    out/<name>.mp4   the video, with narration, captions and sound
    out/<name>.png   a thumbnail: a still from the first scene
    out/<name>.txt   title, description, hashtags and sources, ready to
                     paste into the upload form

Options:
    --preview    fast, low-resolution render (540x960, 15 fps) for checking
                 pacing and layout; the thumbnail and text are still full quality
    --check      validate the JSON files and stop
    --no-tts     no voice; timings estimated from the text (works offline)
    --guides     tint the areas app UI covers, to check the safe zone
    --jobs N     render N videos at once (default 1)

All specs are validated before anything is rendered, so a typo in the last
file is reported straight away rather than after the others have rendered.
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from stickvid import config
from stickvid.director import Video
from stickvid.spec import SpecError, load

PREVIEW_SIZE = (540, 960)
PREVIEW_FPS = 15


# ---------------------------------------------------------------------------
# upload text
# ---------------------------------------------------------------------------
def _first_sentence(text):
    match = re.match(r"(.+?[.?!…]+)(\s|$)", text)
    return match.group(1) if match else text


def _default_hashtags(name):
    """Fallback when a spec lists no hashtags: built from the file name."""
    words = [w.capitalize() for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    tags = ["#" + "".join(words)] if words else []
    tags += ["#" + w for w in words if len(w) > 3 and "#" + w not in tags]
    return (tags + ["#Shorts"])[:3]


def upload_text(spec, name, duration):
    """The text file: everything you paste when uploading, plus the sources."""
    scenes = spec["scenes"]
    title = spec["title"] or name.replace("-", " ").replace("_", " ").capitalize()
    source = spec["source"]

    if spec["description"]:
        description = spec["description"]
    else:
        # The hook, then the action the video ends on, then how far to trust it.
        parts = [_first_sentence(scenes[0]["narration"]), "", "Try this: " + scenes[-1]["narration"]]
        if source and source["evidence"]:
            verdict = {"strong": "well supported by research",
                       "moderate": "supported by research, but by few or small studies",
                       "mixed": "based on research with mixed results"}[source["evidence"]]
            parts += ["", f"How solid is this? It is {verdict}. Details and sources below."]
        description = "\n".join(parts)

    hashtags = spec["hashtags"] or _default_hashtags(name)

    lines = ["TITLE", title, "",
             "DESCRIPTION", description, "",
             "HASHTAGS", " ".join(hashtags), "",
             "SOURCES"]
    if source:
        lines.append(source["citation"])
        if source["link"]:
            lines.append(source["link"])
        if source["finding"]:
            lines += ["", "What it found: " + source["finding"]]
        if source["evidence"]:
            lines.append("Evidence: " + source["evidence"])
        if source["caveat"]:
            lines.append("Caveat: " + source["caveat"])
    else:
        lines.append('None listed. Add a "source" block to the JSON if the video makes factual claims.')
    lines += ["", "-" * 60,
              f"Video length: {duration:.1f}s",
              "Script:"]
    lines += [f"  {i + 1}. {scene['narration']}" for i, scene in enumerate(scenes)]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# building one video
# ---------------------------------------------------------------------------
def is_episode(path):
    """True for a 3D shot list ("shots"), False for a 2D stick-figure video ("scenes")."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return isinstance(data, dict) and "shots" in data
    except (OSError, ValueError):
        return False                                 # let the normal loader report the problem


def build(path, out_dir, preview=False, use_tts=True, guides=False, quiet=False, blender=None, fps=30,
          draft=False, resume=False):
    """Render one spec. Returns (name, duration, seconds_taken)."""
    started = time.time()
    name = os.path.splitext(os.path.basename(path))[0]
    log = (lambda *a: None) if quiet else print
    if is_episode(path):
        from stickvid import episode
        name, duration = episode.build(path, out_dir, preview=preview, use_tts=use_tts, blender=blender,
                                       log=print, fps=fps, draft=draft, resume=resume)     # always print: the variation report matters
        return name, duration, time.time() - started
    spec = load(path)
    os.makedirs(out_dir, exist_ok=True)

    # Thumbnail first, at full quality, before any preview settings apply.
    video = Video(spec, use_tts=use_tts, log=log)
    video.thumbnail().save(os.path.join(out_dir, name + ".png"))
    with open(os.path.join(out_dir, name + ".txt"), "w", encoding="utf-8") as f:
        f.write(upload_text(spec, name, video.duration))

    if preview:
        # Fewer pixels and fewer frames: no supersampling, half size, half frame rate.
        full = (config.SSAA, config.FPS)
        config.SSAA, config.FPS = 1, PREVIEW_FPS
        try:
            video = Video(spec, use_tts=use_tts, log=lambda *a: None)   # rebuilt for the new frame rate
            video.render(os.path.join(out_dir, name + ".mp4"), guides=guides, log=log,
                         size=PREVIEW_SIZE, crf=28, preset="veryfast")
        finally:
            config.SSAA, config.FPS = full                              # the next video's thumbnail needs them
    else:
        log(video.summary())
        video.render(os.path.join(out_dir, name + ".mp4"), guides=guides, log=log)
    return name, video.duration, time.time() - started


def _build_job(args):
    """Wrapper for worker processes: never raises, returns (path, result, error)."""
    path, kwargs = args
    try:
        return path, build(path, **kwargs), None
    except Exception as e:                       # one bad video must not stop the batch
        return path, None, f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("specs", nargs="+", help="one or more JSON files, e.g. videos/*.json")
    ap.add_argument("--out", default="out", help="output folder (default: out)")
    ap.add_argument("--preview", action="store_true", help="fast low-resolution render")
    ap.add_argument("--check", action="store_true", help="validate the JSON files and stop")
    ap.add_argument("--no-tts", action="store_true", help="no voice; estimated timings (offline)")
    ap.add_argument("--guides", action="store_true", help="overlay the unsafe zones in red")
    ap.add_argument("--jobs", type=int, default=1, help="videos to render at once (default 1)")
    ap.add_argument("--draft", action="store_true",
                    help="3D episodes: render at half size but every frame, scaled up (4x faster than full)")
    ap.add_argument("--resume", action="store_true",
                    help="3D episodes: keep frames from an interrupted run and render only the missing ones "
                         "(only if the JSON and the size/fps flags are unchanged)")
    ap.add_argument("--blender", default=None, help="path to the Blender program (3D episodes only)")
    ap.add_argument("--fps", type=int, default=30, choices=[24, 30, 50, 60],
                    help="frame rate of 3D episodes (default 30; 60 is smoother and twice the render time)")
    args = ap.parse_args()

    # Validate everything up front.
    problems = 0
    for path in args.specs:
        try:
            if is_episode(path):
                from stickvid import episode
                spec = episode.shotlist.load(path)
                _, refusal, report = episode.variation(path, spec)
                if args.check:
                    print(f"{path}: OK ({len(spec['shots'])} shots, 3D episode)")
                    print(report)
                if refusal:
                    raise ValueError(refusal)
                continue
            spec = load(path)
            if args.check:
                print(f"{path}: OK ({len(spec['scenes'])} scenes)")
        except (SpecError, ValueError, RuntimeError) as e:
            print(e, file=sys.stderr)
            problems += 1
    if problems:
        sys.exit(f"\n{problems} of {len(args.specs)} file(s) have problems. Nothing was rendered.")
    if args.check:
        return

    kwargs = dict(out_dir=args.out, preview=args.preview, use_tts=not args.no_tts, guides=args.guides,
                  blender=args.blender, fps=args.fps, draft=args.draft, resume=args.resume)
    jobs = [(path, dict(kwargs, quiet=args.jobs > 1)) for path in args.specs]
    failed = []
    started = time.time()

    def report(path, result, error):
        if error:
            failed.append(path)
            print(f"FAILED {path}\n  {error}", file=sys.stderr)
        else:
            name, duration, took = result
            print(f"done   {os.path.join(args.out, name)}.mp4  ({duration:.1f}s video, {took:.0f}s to render)")

    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for outcome in pool.map(_build_job, jobs):
                report(*outcome)
    else:
        for job in jobs:
            print(f"\n== {job[0]}")
            report(*_build_job(job))

    made = len(jobs) - len(failed)
    print(f"\n{made} of {len(jobs)} video(s) written to {args.out}/ in {time.time() - started:.0f}s"
          + (" (preview quality)" if args.preview else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
