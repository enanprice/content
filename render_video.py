#!/usr/bin/env python3
"""Render a video from a JSON spec.

Usage:  python render_video.py videos/pomodoro.json
        python render_video.py videos/pomodoro.json --check     # validate only
        python render_video.py videos/pomodoro.json --no-tts    # silent preview, no network
        python render_video.py videos/pomodoro.json --guides    # tint unsafe zones red
        python render_video.py videos/pomodoro.json --fast      # no anti-aliasing

The output goes to output/<spec name>.mp4 unless --out is given.
The spec format is documented in README.md and stickvid/spec.py.
"""

import argparse
import os
import sys
import time

from stickvid import config
from stickvid.director import Video
from stickvid.spec import SpecError, load
from stickvid.tts import TTSError


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="path to the video's JSON file")
    ap.add_argument("--out", help="output MP4 path")
    ap.add_argument("--check", action="store_true", help="validate the JSON and exit")
    ap.add_argument("--no-tts", action="store_true",
                    help="skip narration: estimated timings, no voice (works offline)")
    ap.add_argument("--guides", action="store_true", help="overlay the unsafe zones in red")
    ap.add_argument("--fast", action="store_true", help="disable supersampling (quick preview)")
    args = ap.parse_args()

    try:
        spec = load(args.spec)
    except SpecError as e:
        sys.exit(str(e))
    if args.check:
        print(f"{args.spec}: OK ({len(spec['scenes'])} scenes)")
        return

    if args.fast:
        config.SSAA = 1
    out = args.out or os.path.join("output", os.path.splitext(os.path.basename(args.spec))[0] + ".mp4")
    started = time.time()
    try:
        print("narration:" if not args.no_tts else "narration: skipped (--no-tts)")
        video = Video(spec, use_tts=not args.no_tts)
        print("timeline:")
        print(video.summary())
        print("rendering:")
        video.render(out, guides=args.guides)
    except (TTSError, RuntimeError) as e:
        sys.exit(f"error: {e}")
    print(f"wrote {out} ({video.duration:.1f}s, {time.time() - started:.0f}s to render)")


if __name__ == "__main__":
    main()
