# stickvid

Vertical stick-figure videos (1080x1920, 30 fps) from JSON files. Pillow draws
the frames, edge-tts speaks the narration, ffmpeg assembles the MP4.

![poses and expressions](docs/showcase_figure.png)

## Workflow

1. **Install** once (below).
2. **Write** a JSON file per video in `videos/`. Copy one of the examples.
3. **Check** it: `python make.py videos/my-video.json --check`
4. **Preview** it fast and small: `python make.py videos/my-video.json --preview`
5. Watch `out/my-video.mp4`. Edit the JSON and repeat step 4 until it is right.
6. **Render** the real thing: `python make.py videos/my-video.json`
7. **Upload** `out/my-video.mp4`, use `out/my-video.png` as the thumbnail, and
   paste the title, description and hashtags from `out/my-video.txt`.

## 3D episodes

`make.py` also builds the Blender episodes. A JSON file with `"shots"` instead
of `"scenes"` is a shot list for the blocky 3D town:

```bash
python make.py episodes/ep01.json --preview
```

```bash
python make.py episodes/ep01.json
```

This needs Blender 4.2 or newer as well as ffmpeg. `make.py` looks for it on
your PATH, in the standard install folders, or where you point it:

```bash
python make.py episodes/ep01.json --blender "/path/to/blender"
```

What happens:

1. **Narration.** edge-tts reads each shot's `narration` in a UK English voice
   and reports when every word starts. The line's length sets the shot's
   length (a `duration` on the same shot acts as a minimum).
2. **Picture.** Blender renders the shots to PNG frames.
3. **Captions.** Large white capitals with a black outline, three words at a
   time, the current word in yellow, centred at y = 1385: inside the safe area
   (below the top 250px, above the bottom 400px).
4. **Sound.** Narration, sound effects and optional music. The music drops
   automatically while the voice is speaking and comes back up in the gaps.
5. **Export.** `out/ep01.mp4` (H.264, 30 fps, 1080x1920) and `out/ep01.png`,
   a thumbnail from the middle of the first shot.

`--preview` renders at half size and half the frames, then scales the picture
up smoothly to 1080x1920, so a preview looks soft rather than blocky and its
captions stay sharp. It is for checking timing, not for judging picture
quality. Blender's frames are kept in `out/ep01_work/`.

```bash
python make.py episodes/ep01.json --fps 60
```

`--fps` sets the frame rate (24, 30, 50 or 60; default 30). 60 is visibly
smoother on camera moves and walking, and takes twice as long to render.

### Episode log

Every episode carries a `log` block describing what kind of episode it is:

```json
"log": {
  "structure": "mystery",
  "lead_character": "the man in the yellow hoodie",
  "lead_building": "clock_tower",
  "ending": "open question"
}
```

| Field | Values |
| --- | --- |
| `structure` | `journey`, `mystery`, `countdown`, `debate`, `myth-correction` |
| `ending` | `twist`, `reversal`, `callback`, `open question` |
| `lead_character` | free text |
| `lead_building` | `bakery`, `clock_tower`, `house`, `bus_depot`, `school` |
| `camera_opener`, `lighting_mood` | read from the first shot. You may write them, but they must match it |

When a full render finishes, the episode is added to `episodes/episode_log.json`
(previews are not logged). Before any render, `make.py`:

- **refuses** the episode if its structure and its ending both match either of
  the last two logged episodes, and says which one;
- prints a **variation report** comparing all six fields with the last five.

```
  variation report: ep07 against the last 5 episode(s)
    Structure:      mystery        used in 1 of 5 (ep05)    recent: journey, countdown, debate, mystery, journey
    Ending:         open question  used in 1 of 5 (ep05)    recent: twist, reversal, callback, open question, twist
    ...
ep07 will not be rendered: it has the same structure ("mystery") and the same
ending ("open question") as ep05, one of the last two episodes.
```

`python make.py episodes/ep07.json --check` shows the report without rendering.
Re-rendering an episode already in the log is always allowed. "Last" means
order in the log file, which is the order episodes were first rendered. There
is no flag to override the refusal: change the episode, or edit the log file
by hand if it is wrong.

Fields this adds to a shot list (everything else is in `blender/README.md`):

| Field | Meaning |
| --- | --- |
| `voice`, `rate` (top level) | edge-tts voice and speed. Default `en-GB-RyanNeural`, `"+0%"` |
| `music` (top level) | `{"path": "...", "volume": 0.12}`, relative to the JSON file. None is bundled |
| `narration` (per shot) | the line to speak. Shots without one need a `duration` |
| `sfx` (per shot) | list of `"clock_chime"`, `"bus_engine"`, `"whoosh"`, or `{"tag": ..., "at": seconds, "volume": 0-1}` |

The three effects are synthesised in code, so they are simple: a bell, a low
rumble that runs to the end of its shot, and a short swish.

`episodes/ep01.json` is a placeholder: the eight shots and their narration are
invented to exercise the pipeline. Replace them with your own.

**Render time.** Blender is the slow step. With a GPU expect a few minutes for
a 30-second episode. On a machine with no GPU the midnight shots are very
slow because of the haze: a 4.6-second preview took over six minutes on four
CPU cores. Use `--preview` first, and test with one or two shots.

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
Microsoft's online speech service, so a narrated render needs an internet
connection; `--no-tts` works offline.

## make.py

```bash
python make.py videos/*.json
```

For each JSON file this writes three files to `out/`:

| File | What it is |
| --- | --- |
| `out/<name>.mp4` | the video: narration, captions, whooshes, optional music |
| `out/<name>.png` | thumbnail: a 1080x1920 still from the first scene, no captions |
| `out/<name>.txt` | title, description, three hashtags, the sources, and the script |

Every file is validated before anything renders, so a typo in the last one is
reported straight away. If one video fails mid-batch (for example the speech
service drops out), the rest still render and the failures are listed at the end.

| Flag | Effect |
| --- | --- |
| `--preview` | 540x960 at 15 fps, no anti-aliasing. About 17 seconds per 40-second video instead of about 100. Thumbnail and text are still full quality |
| `--check` | validate the JSON and stop |
| `--no-tts` | no voice, timings estimated from the text; works offline |
| `--guides` | tint everything outside the safe zone red |
| `--jobs N` | render N videos at once |
| `--out DIR` | output folder (default `out`) |

Speech is cached in `.cache/tts`, so a preview followed by a full render only
fetches each line once, and editing one scene only re-fetches that scene.

### The text file

```
TITLE
Is your phone distracting you when you're not using it?

DESCRIPTION
Your phone might be distracting you even when you're not touching it.

Try this: Today, for one study session, put your phone on silent in another room. See if you notice.

How solid is this? It is based on research with mixed results. Details and sources below.

HASHTAGS
#StudyTips #Focus #PhoneFree

SOURCES
Ward, A. F., Duke, K., Gneezy, A., & Bos, M. W. (2017). Brain drain: ...
```

- **Title** is the JSON's `title`.
- **Description** is the JSON's `description` if you wrote one. Otherwise it is
  built from the hook (the first sentence), the action the video ends on, and a
  plain statement of how strong the evidence is.
- **Hashtags** are the JSON's `hashtags`. Without them, they are guessed from
  the file name, which is a poor substitute: write your own.
- **Sources** are the JSON's `source` block: citation, link, finding, evidence
  rating and caveat.

The script is appended below a divider for reference; don't paste that part.

## The JSON format

```json
{
  "title": "Rereading is not revising",
  "description": "Optional. Written for you if left out.",
  "hashtags": ["#StudyTips", "#Revision", "#ActiveRecall"],
  "voice": "en-GB-RyanNeural",
  "rate": "+0%",
  "transition": "slide_left",
  "whoosh": true,
  "music": { "path": "music/track.mp3", "volume": 0.08 },
  "captions": { "max_words": 4, "uppercase": false, "highlight": "#FFDD78" },
  "source": {
    "citation": "Author, A. (2006). Title. Journal, 1(2), 3-4.",
    "finding": "What the study found, in plain words.",
    "evidence": "moderate",
    "caveat": "What it does not show.",
    "link": "https://doi.org/..."
  },
  "scenes": [
    {
      "narration": "Rereading your notes feels like revision. Mostly, it isn't.",
      "pose": "pointing",
      "expression": "smug",
      "prop": "book",
      "keyword": "Rereading",
      "setting": "bedroom",
      "time": "day",
      "move": "stay",
      "camera": "zoom_in"
    }
  ]
}
```

Only `scenes` and each scene's `narration` are required.

**Top level**

| Field | Values | Default |
| --- | --- | --- |
| `title` | text, up to 100 characters | from the file name |
| `description` | text, up to 1000 characters | built from the script |
| `hashtags` | 1 to 3, letters/digits/underscores | guessed from the file name |
| `voice` | any edge-tts voice; UK ones: `en-GB-RyanNeural`, `en-GB-SoniaNeural`, `en-GB-LibbyNeural`, `en-GB-ThomasNeural`, `en-GB-MaisieNeural` | `en-GB-RyanNeural` |
| `rate` | speaking speed, e.g. `"+10%"`, `"-5%"` | `"+0%"` |
| `transition` | `slide_left`, `slide_right`, `slide_up`, `slide_down`, `cut` | `slide_left` |
| `whoosh` | `true` / `false`: sound on each slide | `true` |
| `music` | `{"path", "volume"}` or `null`. Path is relative to the JSON file. Looped, faded in and out. Volume 0-1 | none, volume `0.08` |
| `captions` | `enabled`, `max_words` (1-5), `uppercase`, `highlight` (hex colour) | on, 4, false, soft yellow |
| `source` | `citation` (required), `finding`, `evidence` (`strong`, `moderate`, `mixed`), `caveat`, `link`. Never shown on screen | none |

**Scene**

| Field | Values | Default |
| --- | --- | --- |
| `narration` | the spoken text, up to 400 characters | required |
| `pose` | `idle`, `talking`, `pointing`, `facepalm`, `shrug`, `sleeping`, `walking` (+ `scrolling`, `hold_book`, `read_book`) | `talking` |
| `expression` | `neutral`, `happy`, `stressed`, `smug`, `tired`, `guilty`, `asleep` | `neutral` |
| `prop` | a name, an object with options (below), or `null` | none |
| `keyword` | up to 24 characters, shown as a handwritten note taped to the wall. Appears when its first word is spoken | none |
| `setting` | `plain`, `bedroom`, `desk`, `living_room`, `classroom`, `library`, `park` | `plain` |
| `time` | `day`, `night` (dark window, dimmer room) | `day` |
| `move` | `stay`, `approach` (walks up from the back of the room), `pace` (walks across and back) | `stay` |
| `camera` | `none`, `zoom_in` (slow push), `shake` (when the keyword lands) | `none` |
| `background` | hex colour: overrides the setting's wall colour | the setting's own |

**Props and their options**

![props](docs/showcase_props.png)

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

A bar chart draws whatever numbers you give it. If the video cites research,
use the study's real figures or pick a different prop.

### Hitting a target length

Scene length comes from the audio, so you tune length by editing the script.
Each render prints a timeline:

```
  scene 1:   0.0s ->   5.3s ( 5.3s)  bedroom     Rereading your notes feels like revision
  ...
  total: 38.2s
```

`en-GB-RyanNeural` speaks roughly 2.5 words per second including pauses, so a
40-second video is about 90 words.

### Rooms and movement

Indoor settings share one perspective room: back wall, side walls and a floor
whose boards run to a vanishing point. The figure has a depth in that room, so
with `"move": "approach"` it walks towards the camera and grows as it comes.
When two neighbouring scenes have different settings, the figure walks out of
one and into the next, so the slide reads as going from room to room.

This is 2.5D, not a 3D engine. Furniture is flat front views against the back
wall and the figure is always drawn facing you, or turned a little to walk.
New settings go in `stickvid/rooms.py`: write a draw function and add it to
`_SETTINGS`.

### Safe zone

App UI covers the top 250px and bottom 400px. `config.SAFE_BOX` is
`(60, 250, 1020, 1520)`. Backgrounds fill the whole frame; the figure, prop,
keyword note and captions sit inside the box. `--guides` shows the covered
areas. A `zoom_in` camera enlarges everything, so check it with `--guides`.

### Music

No music is bundled. Point `music.path` at any audio file you have the rights
to use. `0.08` sits well under a voice; go above `0.15` and it starts to fight
the narration.

### Behind a corporate proxy

If your network inspects TLS, set `SSL_CERT_FILE` to the proxy's CA bundle and
`HTTPS_PROXY` to the proxy address; the narration step picks both up.

## What's in the repository

```
make.py              the command you run: JSON -> MP4 + thumbnail + upload text
videos/*.json        example videos; videos/SOURCES.md lists their sources
stickvid/
  spec.py      JSON format: loading and validation
  director.py  spec -> scenes -> timeline -> finished MP4
  tts.py       edge-tts narration with per-word timings (cached)
  captions.py  burned-in captions with the spoken word picked out
  audio.py     whoosh synthesis, narration + music mix
  rooms.py     settings: perspective rooms, a park, and the depth projection
  figure.py    StickFigure, Pose, Face, POSES, EXPRESSIONS, walk cycles
  props.py     phone, book, clock, brain, battery, thought_bubble, checklist,
               bar_chart, arrow, tomato
  camera.py    Camera, CameraRig (zoom-in, shake), slide_transition
  canvas.py    Canvas: supersampled drawing surface in logical 1080x1920 coords
  timeline.py  Track: keyframed values with eased transitions
  easing.py    easing curves and lerp helpers
  video.py     VideoWriter: pipes raw frames into ffmpeg
  config.py    frame size, fps, safe zone, colours
  fonts/       Poppins and Patrick Hand (SIL Open Font License)
blender/             3D character, town and shot runner (see blender/README.md)
episodes/*.json      3D episodes: shot lists with narration
  episode.py   3D episode pipeline: narration, Blender, captions, sound
make_test_video.py   hand-animated 10-second demo of the Python API
make_showcase.py     regenerates the reference sheets in docs/
```

## Custom animation in Python

The JSON format covers the common case. For anything it can't express (like the
phone drop in `make_test_video.py`), use the Python API directly. Everything is
a function of time `t` in seconds: schedule transitions once, then ask for the
state at each frame.

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

with VideoWriter("out/my_video.mp4") as video:
    for i in range(5 * config.FPS):
        t = i / config.FPS
        fig.update(t)
        c = Canvas()
        props.backdrop(c, 1470)
        props.bar_chart(c, 780, 600, grow=progress(t, 1.0, 2.0))
        fig.draw(c)
        video.write(c.to_frame(cam.at(t)))
```

- A pose is a `Pose` dataclass of joint angles; add your own to `POSES` or pass
  one straight to `pose_to`. The angle convention is at the top of `figure.py`.
- An expression is a `Face` dataclass (lids, brows, pupils, mouth curve, sweat)
  that blends smoothly between any two.
- Joint positions are in `fig.joints` after `update()`. Draw a held prop at
  `fig.joints["r_hand"]`, then call `fig.draw_hands(c)` so the hand sits on top.
- The jumper and hair colours are `StickFigure(shirt=..., hair=...)`; pass
  `None` for either to get the bare stick figure.
