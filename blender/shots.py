"""Shot-list runner: JSON -> scene -> animation -> PNG frames.

    blender -b -P shots.py -- episodes/episode1.json

Options (after the "--"):

    --preview        540x960, every second frame (about 8x less work)
    --stills         one frame from the middle of each shot: a quick storyboard
    --shot N         only shot N (1 = first); repeat for several
    --check          validate the JSON and print the timeline, render nothing
    --engine NAME    eevee (default), workbench or cycles
    --samples N      render quality (default 24; 8 in preview)
    --out DIR        output folder (default: shots_out/<json name>/ next to this script)

Output
    frames/frame_0001.png ...   numbered by position in the whole episode
    stills/shot_01.png ...      with --stills
    scene.blend                 the built, animated scene

The frames carry no sound. Join them into a video with ffmpeg; the exact
command is printed when the render finishes.

How it works
    The town (buildings.py) and the character (build_character.py) are built
    once. Each shot then gets its own camera and a stretch of the timeline.
    Movement is keyframed (camera, character, bus). Things that are simply
    different from shot to shot (lighting, clock time, what is hidden, which
    camera is live) are switched just before that shot's frames render.
"""

import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_character as bc      # noqa: E402
import buildings as town_kit      # noqa: E402
import shotlist                   # noqa: E402

FPS = 30
VIEWPOINT = Vector((1.9, -9.5, 2.0))        # default camera spot: the near end of the street
PARKED = 0.42                               # where the bus waits on its default path
OFFSTAGE_Z = -500.0                         # where the character goes when a shot leaves him out


# ---------------------------------------------------------------------------
# looking things up by name
# ---------------------------------------------------------------------------
def group(town, name):
    """Root objects for a prop name from the shot list."""
    if name in shotlist.BUILDINGS or name == "bus":
        return [town[name]]
    if name == "moon":
        return [bpy.data.objects["Moon"]]
    prefix = {"streetlamps": "Streetlamp", "trees": "Tree", "fences": "Fence", "loaves": "Loaf"}[name]
    return [o for o in bpy.data.objects if o.name.startswith(prefix) and o.type == "EMPTY"]


def set_hidden(roots, hidden):
    for root in roots:
        for obj in [root, *town_kit.descendants(root)]:
            obj.hide_render = obj.hide_viewport = hidden


def bounds_centre(root):
    """Middle of everything parented under `root`, in world space."""
    points = [obj.matrix_world @ Vector(corner) for obj in town_kit.descendants(root)
              if obj.type == "MESH" for corner in obj.bound_box]
    lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return (lo + hi) / 2


def resolve(target, town, frame=None):
    """A target from the shot list -> a world position (at `frame`, for moving things)."""
    if not isinstance(target, str):
        return Vector(target)
    if frame is not None:
        bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    if target == "street":
        return Vector((0.0, 20.0, 2.0))
    if target == "clock":
        return bpy.data.objects["clock_0"].matrix_world.translation.copy()
    if target == "character":
        return bc.ARM.matrix_world @ bc.ARM.pose.bones["head"].head
    if target == "bus":
        return town["bus"].matrix_world.translation + Vector((0, 0, 1.6))
    return bounds_centre(town[target])


# ---------------------------------------------------------------------------
# camera moves
# ---------------------------------------------------------------------------
def _key(obj, frame, location, interpolation="BEZIER"):
    with bc._interpolation(interpolation):
        obj.location = location
        bc._insert_key(obj, "location", frame)


def _wobble(t, seed):
    """Smooth pseudo-random value in about -1..1 (a few detuned sines; repeatable)."""
    return (math.sin(t * 5.1 + seed) + 0.6 * math.sin(t * 11.3 + seed * 2.3) + 0.3 * math.sin(t * 19.7 + seed * 4.1)) / 1.9


def make_camera(index, cam, town, f0, f1):
    """Create shot `index`'s camera and keyframe its move over frames f0..f1.

    The camera always looks at an invisible "aim" object (a Track To
    constraint); moves animate the camera, the aim, or both.
    """
    scene = bpy.context.scene
    data = bpy.data.cameras.new(f"cam_{index:02d}")
    data.lens = cam["lens"]
    data.clip_end = 500
    camera = bpy.data.objects.new(f"cam_{index:02d}", data)
    aim = bpy.data.objects.new(f"aim_{index:02d}", None)
    for obj in (camera, aim):
        scene.collection.objects.link(obj)
    track = camera.constraints.new("TRACK_TO")
    track.target, track.track_axis, track.up_axis = aim, "TRACK_NEGATIVE_Z", "UP_Y"

    target = resolve(cam["target"], town, f0)
    if cam["position"]:
        start = Vector(cam["position"])
    else:
        # No position given: stand 10 m from the target, towards the near end of the street.
        away = (VIEWPOINT - target).to_2d()
        away = away.normalized() if away.length > 0.01 else Vector((0, -1))
        start = Vector((target.x + away.x * 10, target.y + away.y * 10, 1.8))

    move = cam["move"]
    _key(aim, f0, target)
    if move == "static":
        _key(camera, f0, start)
    elif move in ("push_in", "pull_back"):
        near = start + (target - start) * cam["amount"]
        a, b = (start, near) if move == "push_in" else (near, start)
        _key(camera, f0, a)
        _key(camera, f1, b)
    elif move == "orbit":
        # Circle the target at constant height and distance.
        offset = start - target
        steps = max(2, (f1 - f0) // 3)
        for i in range(steps + 1):
            angle = math.radians(cam["degrees"]) * i / steps
            x = offset.x * math.cos(angle) - offset.y * math.sin(angle)
            y = offset.x * math.sin(angle) + offset.y * math.cos(angle)
            _key(camera, round(f0 + (f1 - f0) * i / steps), target + Vector((x, y, offset.z)), "LINEAR")
    elif move == "follow":
        # Keep the same offset from the subject as it moves.
        offset = start - target
        for frame in sorted({*range(f0, f1 + 1, 3), f1}):
            subject = resolve(cam["target"], town, frame)
            _key(aim, frame, subject, "LINEAR")
            _key(camera, frame, subject + offset, "LINEAR")
    elif move == "handheld_shake":
        # Small drifting offsets on camera and aim, sampled every other frame.
        for frame in sorted({*range(f0, f1 + 1, 2), f1}):
            t = (frame - f0) / FPS
            _key(camera, frame, start + Vector((_wobble(t, 1), _wobble(t, 2), _wobble(t, 3))) * 0.045, "LINEAR")
            _key(aim, frame, target + Vector((_wobble(t, 4), _wobble(t, 5), _wobble(t, 6))) * 0.11, "LINEAR")
    return camera


def make_text(index, text, camera):
    """On-screen caption: white text with a dark outline, fixed in front of the camera,
    in the lower-middle of the frame (clear of the areas app UI covers)."""
    def material(name, colour, glow):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        bsdf = town_kit._principled(m)
        bsdf.inputs["Base Color"].default_value = colour
        bsdf.inputs["Emission Color"].default_value = colour
        bsdf.inputs["Emission Strength"].default_value = glow
        return m

    made = []
    for layer, (colour, glow, thicken, depth) in enumerate((((0.01, 0.01, 0.012, 1), 0.0, 0.012, -2.004),
                                                            ((1, 1, 1, 1), 1.0, 0.0, -2.0))):
        data = bpy.data.curves.new(f"text_{index:02d}_{layer}", "FONT")
        data.body = text
        data.align_x, data.align_y = "CENTER", "CENTER"
        data.size = 0.085
        data.offset = thicken                       # the back copy is fattened: it reads as an outline
        data.text_boxes[0].width = 1.15             # wrap long lines inside the frame
        data.text_boxes[0].x = -1.15 / 2
        obj = bpy.data.objects.new(data.name, data)
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = camera
        obj.location = (0, -0.42, depth)
        data.materials.append(material(data.name, colour, glow))
        obj.hide_render = obj.hide_viewport = True  # switched on only for its own shot
        made.append(obj)
    return made


# ---------------------------------------------------------------------------
# character
# ---------------------------------------------------------------------------
def animate_character(ch, town, f0, f1):
    """Key the character for one shot: stand and pose, or walk a path and then pose."""
    bc.set_face(ch["eyes"], ch["mouth"], frame=f0)

    def pose_and_look(frame):
        bc.set_pose(ch["pose"], frame)
        if ch["look_at"] is not None:
            bc.look_at(resolve(ch["look_at"], town, frame), frame)

    if not ch["path"]:
        for frame in (f0, f1):
            bc.set_root(frame, ch["position"], ch["heading"], "LINEAR")
            pose_and_look(frame)
        return

    # Walk each leg of the path in a straight line at the given speed. Walk
    # poses are keyed by DISTANCE (one pose per eighth of a stride) so the
    # feet keep pace with the ground whatever the speed.
    eighth = bc.STRIDE_PER_LOOP / 8
    frame, travelled = float(f0), 0.0
    pts = ch["path"]
    for a, b in zip(pts, pts[1:]):
        leg = math.dist(a, b)
        heading = math.degrees(math.atan2(b[0] - a[0], -(b[1] - a[1])))
        leg_frames = leg / ch["speed"] * FPS
        end = min(frame + leg_frames, f1)
        share = (end - frame) / leg_frames if leg_frames else 1.0
        stop = (a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share)
        bc.set_root(round(frame), a, heading, "LINEAR")
        bc.set_root(round(end), stop, heading, "LINEAR")
        frame, travelled = end, travelled + leg * share
        if frame >= f1:
            break
    arrive = round(frame)
    with bc._interpolation("BEZIER"):
        for i in range(int(travelled / eighth) + 1):
            bc._apply_pose(bc.walk_pose(i), round(f0 + i * eighth / ch["speed"] * FPS))
    if arrive + 10 <= f1:                             # time left: settle into the pose
        pose_and_look(arrive + 10)
        pose_and_look(f1)
    else:
        print(f"  note: the walk needs longer than this shot, so he is still walking at the cut")


# ---------------------------------------------------------------------------
# building the whole episode
# ---------------------------------------------------------------------------
def audio_seconds(path):
    import aud                                        # Blender's own audio library
    sound = aud.Sound.file(path)
    return sound.length / sound.specs[0]


def build_episode(spec, engine, samples):
    """Build town + character, key every shot. Returns (town, plan); plan has one
    dict per shot with its frame range, camera and per-shot switches."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = town_kit.setup_render(engine, samples, 100)
    scene.render.fps = FPS
    town = town_kit.street_layout()
    bc.build_character()
    default_path = town["bus_path"]

    plan, frame = [], 1
    for i, shot in enumerate(spec["shots"], start=1):
        if shot["duration"] == "auto":
            seconds = audio_seconds(shot["audio"])
        elif shot["duration"] is None:
            # Narrated shot run without make.py: guess from the word count (about 2.5 words a second).
            seconds = len(shot["narration"].split()) / 2.5 + 0.8
            print(f"  note: shot {i} has no duration; estimating {seconds:.1f}s from its narration. "
                  f"Run it through make.py for exact timing.")
        else:
            seconds = shot["duration"]
        f0, f1 = frame, frame + max(1, round(seconds * FPS)) - 1
        frame = f1 + 1
        print(f"shot {i}: frames {f0}-{f1} ({seconds:.1f}s) {shot['name']}")

        # Bus first, then the character, then the camera: a "follow" camera
        # has to read where its subject is on each frame.
        if shot["vehicle"]:
            path = town_kit.make_path(shot["vehicle"]["path"], name=f"bus_path_{i:02d}")
            length = path.data.splines[0].calc_length()
            travel = round(length / shot["vehicle"]["speed"] * FPS)
            end = min(f0 + travel, f1)
            town_kit.drive_bus(town["bus"], path, f0, end, 0.0, (end - f0) / travel if travel else 1.0)
            if end < f1:                              # arrived early: wait at the end of the path
                town_kit.drive_bus(town["bus"], path, end, f1, 1.0, 1.0)
        else:
            path = default_path
            town_kit.drive_bus(town["bus"], path, f0, f1, PARKED, PARKED)
        town["bus"].constraints["Follow Path"].target = path     # so "follow" cameras see this shot's path

        if shot["character"]:
            bc.ARM.location.z = 0.0
            animate_character(shot["character"], town, f0, f1)

        camera = make_camera(i, shot["camera"], town, f0, f1)
        text = make_text(i, shot["text"], camera) if shot["text"] else []
        plan.append(dict(index=i, shot=shot, f0=f0, f1=f1, camera=camera, text=text, bus_path=path))

    scene.frame_start, scene.frame_end = 1, frame - 1
    return town, plan


def enter_shot(entry, town, plan, hidden):
    """Switch everything that is simply different in this shot (not animated)."""
    shot, scene = entry["shot"], bpy.context.scene
    scene.camera = entry["camera"]
    town["bus"].constraints["Follow Path"].target = entry["bus_path"]
    bc.ARM.location.z = 0.0 if shot["character"] else OFFSTAGE_Z

    hidden.update(shot["hide"])
    hidden.difference_update(shot["show"])
    for name in shotlist.PROPS:
        if name != "moon":
            set_hidden(group(town, name), name in hidden)
    town_kit.set_lighting(shot["lighting"], town)       # also decides whether the moon is out
    if "moon" in hidden:
        set_hidden(group(town, "moon"), True)
    if shot["clock"]:
        town_kit.set_clock(town["clock_tower"], *shot["clock"])
    for other in plan:
        for obj in other["text"]:
            obj.hide_render = obj.hide_viewport = other is not entry


def add_glow(scene):
    """Soft halo around bright things (lit windows, lamps, the moon).

    Eevee 4.2 has no bloom setting, so this is a Glare node in the
    compositor. If this Blender version's compositor works differently, the
    glow is skipped and the render carries on without it.
    """
    try:
        scene.use_nodes = True
        tree = scene.node_tree
        tree.nodes.clear()
        layers = tree.nodes.new("CompositorNodeRLayers")
        glare = tree.nodes.new("CompositorNodeGlare")
        glare.glare_type = "FOG_GLOW"
        glare.quality = "HIGH"
        glare.threshold = 1.0                        # only what is brighter than white glows
        glare.size = 7
        glare.mix = -0.55                            # mostly the original picture, a little halo
        out = tree.nodes.new("CompositorNodeComposite")
        tree.links.new(layers.outputs["Image"], glare.inputs["Image"])
        tree.links.new(glare.outputs["Image"], out.inputs["Image"])
    except Exception as e:                           # cosmetic only: never fail a render over it
        scene.use_nodes = False
        print(f"  note: glow pass skipped ({type(e).__name__}: {e})")


def parse_args():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="blender -b -P shots.py --")
    ap.add_argument("spec", help="the shot-list JSON file")
    ap.add_argument("--preview", action="store_true", help="540x960, every second frame")
    ap.add_argument("--half", action="store_true", help="540x960 but every frame (a draft at full frame rate)")
    ap.add_argument("--stills", action="store_true", help="one middle frame per shot")
    ap.add_argument("--shot", type=int, action="append", help="only this shot number; repeatable")
    ap.add_argument("--check", action="store_true", help="validate and print the timeline only")
    ap.add_argument("--engine", choices=["eevee", "workbench", "cycles"], default="eevee")
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--fps", type=int, default=30, help="frames per second (default 30; 60 is smoother and twice the work)")
    ap.add_argument("--out", default=None)
    return ap.parse_args(argv)


def main():
    global FPS
    args = parse_args()
    if not 12 <= args.fps <= 120:
        sys.exit("--fps must be between 12 and 120.")
    FPS = args.fps
    try:
        spec = shotlist.load(args.spec)
    except shotlist.ShotListError as e:
        sys.exit(str(e))
    # The validator keeps its own lists so it can run without Blender; make sure they still match.
    assert set(shotlist.POSES) == set(bc.POSES) and set(shotlist.LIGHTING) == set(town_kit.LIGHTING), \
        "shotlist.py's pose or lighting names have drifted from the Blender scripts"
    wanted = args.shot or list(range(1, len(spec["shots"]) + 1))
    bad = [n for n in wanted if not 1 <= n <= len(spec["shots"])]
    if bad:
        sys.exit(f"--shot {bad[0]}: this shot list has shots 1 to {len(spec['shots'])}.")

    name = os.path.splitext(os.path.basename(args.spec))[0]
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(HERE, "shots_out", name)
    samples = args.samples or (12 if args.preview or args.half else 32)

    town, plan = build_episode(spec, args.engine, samples)
    scene = bpy.context.scene
    if args.engine != "workbench":
        add_glow(scene)
    total = scene.frame_end
    print(f"timeline: {len(plan)} shots, {total} frames, {total / FPS:.1f}s at {FPS} fps")
    if args.check:
        return

    os.makedirs(out_dir, exist_ok=True)
    scene.render.resolution_x, scene.render.resolution_y = 1080, 1920
    scene.render.resolution_percentage = 50 if args.preview or args.half else 100
    scene.render.image_settings.file_format = "PNG"
    step = 2 if args.preview else 1

    hidden = set()
    for entry in plan:
        enter_shot(entry, town, plan, hidden)           # every shot, in order: hide/show carries forward
        if entry["index"] not in wanted:
            continue
        if args.stills:
            scene.frame_set((entry["f0"] + entry["f1"]) // 2)
            scene.render.filepath = os.path.join(out_dir, "stills", f"shot_{entry['index']:02d}.png")
            bpy.ops.render.render(write_still=True)
        else:
            scene.frame_start, scene.frame_end, scene.frame_step = entry["f0"], entry["f1"], step
            scene.render.filepath = os.path.join(out_dir, "frames", "frame_")
            bpy.ops.render.render(animation=True)
        print(f"rendered shot {entry['index']}")

    scene.frame_start, scene.frame_end, scene.frame_step = 1, total, 1
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "scene.blend"))
    if args.stills:
        print(f"stills in {os.path.join(out_dir, 'stills')}")
    else:
        frames = os.path.join(out_dir, "frames")
        print(f"frames in {frames}\nto make a video:\n  ffmpeg -framerate {FPS // step} -pattern_type glob "
              f"-i '{frames}/frame_*.png' -c:v libx264 -pix_fmt yuv420p {os.path.join(out_dir, name)}.mp4")


if __name__ == "__main__":
    main()
