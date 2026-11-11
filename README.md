# stickvid

Vertical stick-figure videos (1080x1920, 30 fps) in plain Python. Pillow draws
the frames, ffmpeg (called through `subprocess`) assembles the MP4.

![poses and expressions](docs/showcase_figure.png)
![props](docs/showcase_props.png)

## Install

You need Python 3.9+ and ffmpeg.

**1. ffmpeg**

```bash
# macOS (Homebrew)
brew install ffmpeg
```

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg
```

```bash
# Windows (PowerShell) - then open a new terminal
winget install Gyan.FFmpeg
```

Check it is on your PATH:

```bash
ffmpeg -version
```

**2. Python dependencies** (from the repository root)

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

That installs Pillow (drawing) and edge-tts (narration). edge-tts calls
Microsoft's online speech service, so rendering a narrated video needs an
internet connection; `--no-tts` works offline.

## Videos from JSON

Each video is one JSON file: a list of scenes, each with narration, a pose, an
expression, a prop and a keyword.

```bash
python render_video.py videos/pomodoro.json
```

Writes `output/pomodoro.mp4` (about 40 seconds; rendering takes about 100
seconds). What happens:

1. The JSON is validated. Every problem is reported at once, with its location.
2. edge-tts speaks each scene's narration in a UK English voice. The length of
   the speech sets the length of the scene.
3. Frames are drawn with word-by-word captions burned in, timed to the voice,
   the current word highlighted.
4. Narration, a soft whoosh on each transition and optional background music
   are mixed and attached.

| Flag | Effect |
| --- | --- |
| `--check` | validate the JSON and stop |
| `--no-tts` | no voice, timings estimated from the text; for quick offline previews |
| `--guides` | tint everything outside the safe zone red |
| `--fast` | supersampling off, about 3x faster, slightly jagged |
| `--out PATH` | output file |

### Format

```json
{
  "title": "Why the Pomodoro technique really works",
  "voice": "en-GB-RyanNeural",
  "rate": "+0%",
  "transition": "slide_left",
  "whoosh": true,
  "music": { "path": "music/track.mp3", "volume": 0.08 },
  "captions": { "max_words": 3, "uppercase": true, "highlight": "#FFDD00" },
  "scenes": [
    {
      "narration": "This study trick works... but not for the reason you think.",
      "pose": "pointing",
      "expression": "smug",
      "prop": "tomato",
      "keyword": "STUDY TRICK",
      "camera": "zoom_in"
    }
  ]
}
```

Only `scenes` and each scene's `narration` are required.

**Top level**

| Field | Values | Default |
| --- | --- | --- |
| `voice` | any edge-tts voice; UK ones: `en-GB-RyanNeural`, `en-GB-SoniaNeural`, `en-GB-LibbyNeural`, `en-GB-ThomasNeural`, `en-GB-MaisieNeural` | `en-GB-RyanNeural` |
| `rate` | speaking speed, e.g. `"+10%"`, `"-5%"` | `"+0%"` |
| `transition` | `slide_left`, `slide_right`, `slide_up`, `slide_down`, `cut` | `slide_left` |
| `whoosh` | `true` / `false`: sound on each slide | `true` |
| `music` | `{"path", "volume"}` or `null`. Path is relative to the JSON file. The track is looped, faded in and out. Volume 0-1 | none, volume `0.08` |
| `captions` | `enabled`, `max_words` (1-5), `uppercase`, `highlight` (hex colour) | on, 3, true, yellow |

**Scene**

| Field | Values | Default |
| --- | --- | --- |
| `narration` | the spoken text, up to 400 characters | required |
| `pose` | `idle`, `talking`, `pointing`, `facepalm`, `shrug`, `sleeping`, `walking` (+ `scrolling`, `hold_book`, `read_book`) | `talking` |
| `expression` | `neutral`, `happy`, `stressed`, `smug`, `tired`, `guilty`, `asleep` | `neutral` |
| `prop` | a name, an object with options (below), or `null` | none |
| `keyword` | on-screen text, up to 24 characters. Pops in when its first word is spoken | none |
| `camera` | `none`, `zoom_in` (slow push), `shake` (when the keyword lands) | `none` |
| `background` | hex colour | rotates through a palette |

**Props and their options**

| Prop | Options |
| --- | --- |
| `phone`, `brain`, `tomato` | none |
| `book` | `open` (true/false) |
| `clock` | `time` (hours, 0-24), `spin` (hours per second) |
| `battery` | `from`, `level` (0-1): charges from one to the other during the scene |
| `thought_bubble` | `text` (up to 6 characters) |
| `checklist` | `items` (1-5 texts, up to 12 characters each), `checked` (how many get ticked) |
| `bar_chart` | `values` (2-5 numbers, 0-1), `labels` |
| `arrow` | `direction` (`up`, `down`, `left`, `right`), `color` |

### Hitting a target length

Scene length comes from the audio, so you tune length by editing the script.
The render prints a timeline first:

```
  scene 1:   0.0s ->   3.8s ( 3.8s)  This study trick works... but not for the reason
  ...
  total: 39.4s
```

`en-GB-RyanNeural` speaks roughly 2.5 words per second including pauses. Speech
is cached in `.cache/tts`, so only scenes whose narration changed are fetched
again.

### Music

No music is bundled. Point `music.path` at any audio file you have the rights
to use. `0.08` sits well under a voice; go above `0.15` and it starts to fight
the narration.

### Behind a corporate proxy

If your network inspects TLS, set `SSL_CERT_FILE` to the proxy's CA bundle and
`HTTPS_PROXY` to the proxy address; the narration step picks both up.

## Hand-built test video

```bash
python make_test_video.py
```

Writes `output/test_video.mp4`: 10 seconds, figure scrolls on a phone, feels
guilty, drops the phone and opens a book. Takes about 25 seconds.

| Flag | Effect |
| --- | --- |
| `--guides` | tints everything outside the safe zone red, to check your layout |
| `--fast` | turns supersampling off for a quick, slightly jagged preview |
| `--out PATH` | output file |

```bash
python make_showcase.py
```

Regenerates the two reference sheets above (every pose, expression and prop).

## Layout

```
stickvid/
  config.py    frame size, fps, safe zone, colours
  easing.py    easing curves (cubic, back, bounce, elastic...) and lerp helpers
  timeline.py  Track: keyframed values with eased transitions
  canvas.py    Canvas: supersampled drawing surface in logical 1080x1920 coords
  figure.py    StickFigure, Pose, Face, POSES, EXPRESSIONS, walk_cycle
  props.py     phone, book, clock, brain, battery, thought_bubble, checklist,
               bar_chart, arrow (+ zzz, backdrop)
  camera.py    Camera, CameraRig (zoom-in, shake), slide_transition
  video.py     VideoWriter: pipes raw frames into ffmpeg
  spec.py      JSON video format: loading and validation
  tts.py       edge-tts narration with per-word timings (cached)
  captions.py  word-by-word burned-in captions
  audio.py     whoosh synthesis, narration + music mix
  director.py  spec -> scenes -> timeline -> finished MP4
render_video.py      render a video from a JSON file
videos/pomodoro.json example: 40 seconds on the Pomodoro technique
make_test_video.py   the hand-built 10-second demo of the Python API
make_showcase.py     reference sheets
```

## Safe zone

App UI covers the top 250px and bottom 400px. `config.SAFE_BOX` is
`(60, 250, 1020, 1520)`. Backgrounds fill the whole frame; anything the viewer
has to see goes inside the box. Two things help you stay there:

- `--guides` (or `draw_safe_guides(frame)`) shows the covered areas.
- The camera zooms around the centre of the safe zone, not the frame, so the
  thing you zoom in on lands where it is visible.

Zooming enlarges everything, so objects near the edge of the safe zone will
drift out of it during a zoom. In the demo the clock does this while the
camera is on the face. Check with `--guides` when you add a zoom.

## Writing a scene in Python

The JSON format covers the common case. For custom animation (like the phone
drop in the test video), use the Python API directly.

Everything is a function of time `t` in seconds. You schedule transitions
once, then ask for the state at each frame.

```python
from stickvid import Canvas, CameraRig, StickFigure, VideoWriter, config, props
from stickvid.easing import ease_out_back, progress

fig = StickFigure(x=540, ground_y=1470, pose="idle", expression="neutral")
fig.pose_to("pointing", at=1.0, duration=0.4, ease=ease_out_back)  # eased pose change
fig.expression_to("smug", at=1.0)
fig.look_to((0.8, 0.0), at=1.0)       # gaze: x and y in -1..1
fig.talk(1.5, 3.0)                    # flap the mouth
fig.walk_to(300, start=3.0, end=4.5)  # walk cycle + movement

cam = CameraRig()
cam.zoom_to(1.4, center=(540, 800), at=1.0, duration=0.6)
cam.reset(at=2.5)
cam.shake(at=3.0, amplitude=20)

with VideoWriter("output/my_video.mp4") as video:
    for i in range(5 * config.FPS):
        t = i / config.FPS
        fig.update(t)
        c = Canvas()
        props.backdrop(c, 1470)
        props.bar_chart(c, 780, 600, grow=progress(t, 1.0, 2.0))
        fig.draw(c)
        video.write(c.to_frame(cam.at(t)))
```

**Poses:** `idle`, `talking`, `pointing`, `facepalm`, `shrug`, `sleeping`,
`walking`, plus `scrolling`, `hold_book`, `read_book` for the demo. A pose is a
`Pose` dataclass of joint angles; add your own to `POSES` or pass a `Pose`
straight to `pose_to`. The angle convention is at the top of `figure.py`.

**Expressions:** `neutral`, `happy`, `stressed`, `smug`, `tired`, plus `guilty`
and `asleep`. Same idea: a `Face` dataclass (lids, brows, pupils, mouth curve,
sweat...) that blends smoothly between any two expressions.

**Holding props:** joint positions are in `fig.joints` after `update()`
(`r_hand`, `l_hand`, `head`, ...). Draw the prop there, then call
`fig.draw_hands(c)` so the hand sits on top. See `ScrollScene._held_phone`.

**Slide transition:** render both scenes and combine them:
`slide_transition(frame_a, frame_b, t, start, duration, "left")`.

## Notes

- Frames are drawn at 2x and scaled down for anti-aliasing (`config.SSAA`).
- Output is H.264 / yuv420p / faststart, with AAC audio for JSON videos. The
  hand-built test video is silent.
- Text uses DejaVu Sans Bold or Arial Bold if found, otherwise Pillow's
  built-in font. Add your own font path to `_FONT_CANDIDATES` in `canvas.py`.
