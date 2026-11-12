# Blocky 3D character (Blender)

`build_character.py` builds an original blocky character in Blender from
primitives, rigs it, animates a 5-second test clip and renders a 540x960
preview. It is separate from the 2D `stickvid` pipeline in the rest of this
repository: nothing here is wired into `make.py` yet.

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
