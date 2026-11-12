# Blocky 3D character and town (Blender)

Two scripts, each run on its own with `blender -b -P <script>`:

- `build_character.py` builds an original blocky character from primitives,
  rigs it, animates a 5-second test clip and renders a 540x960 preview.
- `buildings.py` generates a modular blocky town (buildings, bus, street
  props, lighting presets) and renders an establishing shot at midnight and
  again at dawn. See [The town](#the-town) below.

- `shots.py` renders a whole episode from a JSON shot list, using the town
  and the character together. See [Shot lists](#shot-lists) at the end.

They are separate from the 2D `stickvid` pipeline in the rest of this
repository: nothing here is wired into `make.py`.

Tested with Blender 4.2.3 LTS on Linux, rendering with Eevee on the CPU
(software OpenGL). It has not been run on Windows, macOS or a GPU.

## Install

You only need Blender 4.2 LTS or newer. The script uses `bpy`, `bmesh`,
`mathutils` and `numpy`, which are all inside Blender already. Do not
`pip install` anything, and do not run the script with your normal Python.

**Windows**

1. Install Blender from <https://www.blender.org/download/lts/4-2/> (or the Microsoft Store, or Steam).
2. In PowerShell, from this folder:

```powershell
& "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" -b -P build_character.py
```

**macOS**

1. Install Blender from the link above and drag it to Applications.
2. In Terminal, from this folder:

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b -P build_character.py
```

**Linux**

1. Download the tarball from the link above and unpack it (or `sudo snap install blender --classic`).
2. From this folder:

```bash
/path/to/blender-4.2.3-linux-x64/blender -b -P build_character.py
```

If `blender` is already on your PATH, the short form works on every system:

```bash
blender -b -P build_character.py
```

`-b` runs Blender without a window; `-P` runs the script.

## What you get

In `character_out/`, next to the script:

| File | What it is |
| --- | --- |
| `character.blend` | the rigged, animated scene. Open it in Blender to look around or keep animating |
| `character_test.mp4` | the test clip: he walks in, stops, goes wide-eyed, shrugs. 540x960, 24 fps, 5 seconds |

## Options

Options go after a lone `--`:

```bash
blender -b -P build_character.py -- --still 82
```

| Option | Effect |
| --- | --- |
| `--engine eevee` | default |
| `--engine workbench` | Blender's simplest renderer: flat lighting, very fast. Use it if Eevee fails |
| `--engine cycles` | path tracer. Works on any CPU with no graphics driver at all, but slow |
| `--samples N` | render quality (default 16, which is preview quality; 64 is clean) |
| `--still FRAME` | render one frame as a PNG instead of the clip |
| `--no-render` | build and save the `.blend` only |
| `--out DIR` | output folder |

## GPU or no GPU

- **With a GPU** (any reasonably modern one): Eevee renders the clip in well
  under a minute.
- **Without a GPU:** Eevee still needs OpenGL. On a desktop PC or Mac with
  integrated graphics that is fine. On a headless Linux server you need
  software OpenGL installed (`sudo apt install libegl1 libgl1-mesa-dri`), and
  then it is slow: the 120-frame clip took several minutes on 4 CPU cores.
  If Eevee prints `Couldn't open libEGL.so.1` or cannot create a context, use
  `-- --engine cycles`, which needs no graphics driver.
- When Eevee renders through software OpenGL it prints
  `EGL Error (0x3009): EGL_BAD_MATCH`. The render still completes; ignore it.

## Things you must do in Blender's UI

Nothing is required: the script builds, animates, saves and renders by itself.
These only matter when you open `character.blend` to work on it by hand:

- **To see colours and the face**, switch the viewport to Material Preview or
  Rendered (the sphere icons at the top right of the 3D viewport, or hold `Z`).
  The default Solid view shows flat colours and a blank face.
- **To pose by hand**, click the armature (the thin lines inside the body),
  press `Ctrl+Tab` for Pose Mode, click a bone and press `R` to rotate. If the
  bones are hard to see, turn on *In Front* under Object Data (green stick-man
  tab) > Viewport Display.
- **To swap a face by hand**, each expression is its own object (`eyes_open`,
  `eyes_wide`, `mouth_smile`, ...) parented to the head. In the Outliner, show
  one and hide the others using the eye and camera icons. The camera icon is
  the one that affects renders; if you don't see it, enable it in the
  Outliner's filter drop-down (funnel icon).
- **To edit how a face looks**, open its material (`eyes_wide`, ...) in the
  Shading workspace. The textures are packed inside the `.blend`; re-running
  the script regenerates them and overwrites any hand edits.
- **Re-running the script overwrites `character.blend`.** Save your own work
  under another name.
- If you paste the script into Blender's Text Editor instead of using the
  command line, save the text block to disk first: the script uses its own
  file location to decide where `character_out/` goes.

## The character

About 1.8 units tall, standing on Z=0, facing -Y (Blender's front view).
`.L` is his own left, which is +X.

- Bevelled-cube head with a flat front, hair cap, box neck
- Yellow hoodie: torso, hood, pocket, drawstrings, upper and lower arms
- Dark trousers: pelvis, upper and lower legs; box hands and feet
- Round glasses: two thin torus rings, a bridge, and arms back to the ears

**Rig.** Forward kinematics only. Every mesh is parented to exactly one bone
(bone parenting, not an Armature modifier), so nothing bends or stretches.

```
root
└── hips
    ├── spine
    │   ├── neck ── head
    │   ├── shoulder.L ── elbow.L        (upper arm, forearm + hand)
    │   └── shoulder.R ── elbow.R
    ├── hip.L ── knee.L                  (thigh, shin + foot)
    └── hip.R ── knee.R
```

`root` moves the whole character around the scene. Poses never touch it.

## Animating from Python

Add your own animation by editing `animate_test_clip()` at the bottom of the
script, or by importing the file from another script run with `blender -b -P`.

```python
set_pose("shrug", frame=82)                    # key the whole body, Bezier-eased
set_face("wide", "small_o", frame=60)          # eyes, mouth; swaps on that exact frame
set_root(49, (0, 0), heading=22)               # position on the ground + facing
end_frame, end_xy = walk(1, start=(-2.2, 0), heading=90, loops=1.5)
look_at(CAMERA_POSITION, frame=82, tilt=9)     # head and neck aim at a point
```

**Poses:** `idle`, `talking`, `point`, `shrug`, `panic`, `sleepy`,
`sit_driving`. They live in the `POSES` dict as `(fwd, side, twist)` degrees
per bone:

- `fwd` > 0 swings the bone's free end forward. A knee bends with a negative `fwd`.
- `side` > 0 swings a limb outward; for spine, neck and head it leans to his left.
- `twist` > 0 turns to his left.

Angles are relative to the parent bone. Bones a pose leaves out go back to
rest. A bone can also be moved: `{"rot": (...), "loc": (x, y, z)}`, which is
how `shrug` lifts the shoulders and `sit_driving` lowers the hips.

**Easing.** `set_pose` writes Bezier keyframes with auto-clamped handles, so
motion eases out of one pose and into the next without overshooting. To hold
a pose, key it at both ends of the hold.

**Faces.** Eyes: `open`, `wide`, `half_closed`, `squint`. Mouth: `neutral`,
`open`, `small_o`, `smile`, `flat`. Each is a separate quad on the front of
the head with its own material, drawn in code (no image files). `set_face`
shows one and hides the rest, keyframed with stepped interpolation.

**Walk.** The cycle is 8 poses (`walk_pose(0)` to `walk_pose(7)`). `walk()`
spaces them `frames_per_pose` apart: the default 3 gives a 24-frame loop, one
second per two steps, which is a natural pace. `frames_per_pose=1` plays the
loop in literally 8 frames, which at 24 fps is a sprint. Forward speed is
matched to the stride so the feet don't slide.

**look_at.** Call it after `set_pose` for the same frame: it reads where the
chest is at that frame, then keys the neck and head, overriding whatever the
pose set for them. The turn is clamped to 75 degrees and the nod to 40.

## Known limits

- FK only: hands and feet can't be pinned to a point. In `sit_driving` the
  hands are placed by eye, and there is no seat or steering wheel in the scene.
- No wrist, ankle or finger bones: hands and feet ride on the forearm and shin.
- The walk plants its feet reasonably well in a straight line. Turning while
  walking will slide.
- Rigid boxes intersect at elbows, knees and shoulders in strong poses. That
  is the blocky look, but it is visible in `panic` and `sit_driving`.

---

# The town

```bash
blender -b -P buildings.py
```

Writes to `town_out/`, next to the script:

| File | What it is |
| --- | --- |
| `town.blend` | the whole street, lit for midnight |
| `establishing_midnight.png` | the street at midnight, clock at 12:00, 1080x1920 |
| `establishing_dawn.png` | the same shot at dawn, clock at 5:40 |

Both stills together took 40 seconds on 4 CPU cores with no GPU. The street is
about 12,000 triangles in 121 mesh objects.

| Option (after `--`) | Effect |
| --- | --- |
| `--preset day` | which lighting to render: `day`, `dawn`, `midnight`. Repeat for several |
| `--scale 50` | percent of 1080x1920 |
| `--samples N` | quality (default 24) |
| `--engine cycles` | or `workbench`, if Eevee can't start |
| `--no-render` | build and save the `.blend` only |

Install, GPU notes and the Blender UI notes above apply here too. One more for
the town: the haze is a large box called `Haze` drawn as a wireframe. Don't
delete it, and don't be alarmed by the box in the viewport.

## No text anywhere

Signs, the bus's destination board and the school flag are blank panels, and
the clock faces have tick marks instead of numerals. `make_building(sign=True)`
adds a blank panel; there is no option to put text on it. If the story later
needs one readable sign, add a text object or an image texture to that
building's `sign` object by hand, so that it stays a deliberate exception.

## make_building

```python
make_building(width, depth, floors, roof_style, wall_colour, door_side,
              name="Building", location=(0, 0, 0), rotation=0.0, ...)
```

| Argument | Meaning |
| --- | --- |
| `width`, `depth` | footprint in metres; width runs along the street |
| `floors` | number of storeys (2.8 m each; change with `floor_height`) |
| `roof_style` | `"flat"`, `"gabled"`, `"clock_tower"` |
| `wall_colour` | `"#RRGGBB"` |
| `door_side` | which wall has the door: `"front"`, `"back"`, `"left"`, `"right"` |
| `door_offset` | -1..1, slides the door along that wall |
| `sign` | blank panel above the door |
| `shopfront` | one large display window on the ground floor |
| `lit_fraction`, `seed` | what share of windows light up at night, and which |

A building's origin is the middle of its front wall at ground level. Its front
faces -Y; `rotation` (degrees) turns it. It returns an Empty that everything
else is parented to: move or rotate that.

**Windows** are recessed: four frame bars stand proud of the wall with the
glass set back between them. All of a building's frames are one mesh and all
of its glass is two (the panes that light up, and the ones that stay dark), so
a building is about ten objects however many windows it has.

**Day and night per building.** Each building owns its window material:

```python
set_windows(town["bakery"], on=True)              # just the bakery
set_windows(town["school"], on=False)
set_windows(town["house"], on=True, frame=48)     # keyframed: a light comes on at frame 48
```

## The buildings

| Function | What you get |
| --- | --- |
| `make_bakery()` | two storeys, gabled roof, shopfront window, striped awning, blank sign, table of loaves outside |
| `make_school()` | 17 m wide, flat roof, double doors, steps, flagpole with a blank flag |
| `make_bus_depot()` | one tall storey, roller garage door, side door, blank sign |
| `make_clock_tower()` | stone hall with a tower; a clock face and a pair of hands on all four sides |

**Clock.** `set_clock(building, hours, minutes, frame=None)` turns the hands on
all four faces. Hours can run past 12 so the hands sweep forwards:

```python
set_clock(tower, 0, 0, frame=1)
set_clock(tower, 3, 0, frame=120)      # minute hand goes round three times
```

## Props

| Function | Notes |
| --- | --- |
| `make_bus()` | blocky single-decker with four separate wheels, headlights, blank destination board |
| `make_path(points)` | a smooth curve through `[(x, y), ...]` for the bus to follow |
| `drive_bus(bus, path, start_frame, end_frame, start=0, end=1)` | moves the bus along the curve, turning with it, and spins the wheels by exactly the distance travelled |
| `set_bus_lights(bus, on)` | interior lights and headlights |
| `make_loaf()` | bread with score marks |
| `make_streetlamp()` | pole, glowing head and a real point light |
| `make_fence(length)` | posts and two rails |
| `make_tree()` | box trunk, cube canopy |
| `make_road(length)` | tarmac, dashed centre line, edge lines, raised pavement and kerb on both sides |

Driving the bus out of the depot and down the street:

```python
drive_bus(town["bus"], town["bus_path"], 1, 97)                       # whole path in 4 seconds
drive_bus(town["bus"], town["bus_path"], 1, 49, start=0.0, end=0.5)   # or stop half way...
drive_bus(town["bus"], town["bus_path"], 73, 121, start=0.5, end=1.0) # ...and carry on later
```

## street_layout()

One street running away from the camera, five buildings:

```
        left side              right side
        Bakery                 House
        Clock tower            Bus depot
                 School across the far end
```

I read "five buildings and the school at the end" as five including the
school. If you meant five plus the school, add one more `make_building(...)`
line to the `town` dict in `street_layout()`.

It returns a dict: `bakery`, `clock_tower`, `house`, `bus_depot`, `school`,
`all_buildings`, `bus`, `bus_path`, `road`.

## Lighting presets

```python
set_lighting("midnight", town)     # or "dawn", "day"
```

| Preset | Light | Windows | Streetlamps | Haze |
| --- | --- | --- | --- | --- |
| `day` | high white sun, blue sky | off | off | none |
| `dawn` | low orange sun, pink-to-blue sky | bakery only | dim | light, warm |
| `midnight` | blue moonlight, dark blue sky, a blocky moon | all on | on | subtle, blue |

A preset changes the sun, sky, haze, windows, streetlamps and bus lights and
rebuilds nothing, so the same camera can render each one. The numbers are in
the `LIGHTING` dict near the bottom of the script.

## Known limits

- Tested on Blender 4.2.3 with Eevee on CPU only, like the character script.
- Window glow is the emissive material alone. Eevee in 4.2 has no bloom
  setting; for a soft halo round the windows add a Glare node in the
  compositor.
- The lit windows clip to near-white in the midnight shot. Lower
  `window_strength` in `LIGHTING["midnight"]` if you want to see more colour.
- `drive_bus` moves at constant speed with no acceleration or braking.
- Building interiors are empty and the glass is opaque: you cannot see in.
- The loaves sit on a table outside the bakery, not in the window, for that reason.

---

# Shot lists

An episode is a JSON file: a list of shots. `shots.py` builds the town and the
character, animates every shot and renders PNG frames.

```bash
python shotlist.py ../episodes/ep01.json
```

checks the file from an ordinary terminal (no Blender needed), and

```bash
blender -b -P shots.py -- ../episodes/ep01.json --stills --preview
```

renders one small frame per shot: a storyboard, about a minute on a CPU. Do
that before any full render.

```bash
blender -b -P shots.py -- ../episodes/ep01.json --preview
```

```bash
blender -b -P shots.py -- ../episodes/ep01.json
```

| Option | Effect |
| --- | --- |
| (none) | 1080x1920, 30 fps, every frame |
| `--preview` | 540x960, every second frame |
| `--stills` | one frame from the middle of each shot |
| `--shot N` | only shot N; repeat for several |
| `--check` | validate and print the timeline (frame range per shot) |
| `--engine`, `--samples`, `--out` | as for the other scripts |

Frames go to `shots_out/<name>/frames/frame_0001.png ...`, numbered through
the whole episode, with `scene.blend` beside them. The frames have no sound.
The ffmpeg command that joins them into a video is printed at the end.

`episodes/ep01.json` (in the repository root) is a **placeholder**: eight shots I made up to
exercise every feature. Replace them with your own.

## A shot

```json
{
  "name": "3. He notices the clock",
  "duration": 3.0,
  "lighting": "midnight",
  "clock": "11:59",
  "camera": { "move": "orbit", "target": "character", "position": [2.6, 1.2, 1.9], "degrees": 35, "lens": 35 },
  "character": { "pose": "idle", "expression": "surprised", "position": [4.8, 4.0], "heading": -70, "look_at": "clock" },
  "props": { "hide": ["bus"] },
  "vehicle": { "path": [[5.1, 23.6], [1.75, 14.0], [1.75, -4.0]], "speed": 6.5 },
  "text": "Twelve."
}
```

Only `duration` is required. For narration, captions, sound and the final MP4,
run the shot list through `python make.py episodes/ep01.json` from the repository
root instead: see the main README.

| Field | Values |
| --- | --- |
| `duration` | seconds, or `"auto"` to use the length of the file named in `audio` |
| `lighting` | `day`, `dawn`, `midnight` |
| `clock` | time on the clock tower, e.g. `"5:40"`. Stays until changed |
| `camera.move` | `static`, `push_in`, `pull_back`, `orbit`, `follow`, `handheld_shake` |
| `camera.target` | what it looks at: `bakery`, `clock_tower`, `house`, `bus_depot`, `school`, `clock`, `bus`, `character`, `street`, or `[x, y, z]` |
| `camera.position` | where it starts, `[x, y, z]`. Left out, it stands 10 m from the target towards the near end of the street |
| `camera.amount` | push_in / pull_back: share of the distance to the target (default 0.35) |
| `camera.degrees` | orbit sweep (default 40) |
| `camera.lens` | focal length in mm (default 28) |
| `character` | leave the block out and he is off screen for that shot |
| `character.pose` | `idle`, `talking`, `point`, `shrug`, `panic`, `sleepy`, `sit_driving` |
| `character.expression` | `neutral`, `surprised`, `shocked`, `worried`, `happy`, `pleased`, `talking`, `sleepy`, `deadpan`, or `{"eyes": ..., "mouth": ...}` |
| `character.position`, `heading` | where he stands, `[x, y]`, and which way he faces (0 = towards -Y, 90 = towards +X) |
| `character.path` | `{"points": [[x, y], ...], "speed": 1.4}`: he walks it, then takes the pose |
| `character.look_at` | a target name or `[x, y, z]` |
| `props.hide`, `props.show` | `bakery`, `clock_tower`, `house`, `bus_depot`, `school`, `bus`, `streetlamps`, `trees`, `fences`, `loaves`, `moon`. Stays in force for later shots |
| `vehicle` | `{"path": [[x, y], ...], "speed": 6}`: the bus drives it. Without this the bus is parked outside the depot |
| `text` | on-screen caption, up to 90 characters, lower-middle of the frame |

**Map.** Metres. The street runs along +Y from y = -6 (near end) to y = 40
(the school). The road is x = -3.5 to 3.5. Pavements run out to x = 6.1 on
each side, where the building fronts are: bakery and clock tower on the left
(negative x) at y = 5 and y = 21, house and bus depot on the right at y = 5
and y = 22.

**`follow`** keeps the camera at a fixed offset from the character or the bus.
**`handheld_shake`** is a fixed camera with a small drifting wobble.

## Limits

- Each shot is one pose and one expression. A change mid-shot is two shots.
- If a walk takes longer than its shot, he is still walking at the cut. The
  runner prints a note when that happens.
- Hands and feet can't be pinned (FK rig), so `sit_driving` does not put him
  in the bus: there is no seat or wheel, and the bus windows are opaque.
- Audio only sets `duration: "auto"`. It is not attached to the frames.
- `scene.blend` holds the animation, but lighting, clock time and hidden
  props are switched per shot at render time, so the file shows the last
  shot's settings.
