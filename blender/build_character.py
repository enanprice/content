"""Build a blocky, rigged 3D character and render a 5-second test clip.

Run (no Blender window needed):

    blender -b -P build_character.py

Options go after a lone "--":

    blender -b -P build_character.py -- --engine workbench   # if Eevee can't start
    blender -b -P build_character.py -- --still 80           # one PNG of frame 80
    blender -b -P build_character.py -- --no-render          # only save the .blend
    blender -b -P build_character.py -- --samples 64 --out renders

Writes to ./character_out/ next to this script:

    character.blend        the rigged, animated scene - open it in Blender
    character_test.mp4     540x960 preview of the test clip

Needs Blender 4.2 LTS or newer. Uses only bpy, bmesh, mathutils and numpy,
all of which ship inside Blender.

Layout of this file
    1. settings and colours
    2. mesh helpers
    3. face textures (drawn in code, no image files)
    4. build_character(): body parts, armature, rigid bone parenting
    5. animation API: POSES, set_pose, set_face, walk, look_at, set_root
    6. scene: camera, light, ground
    7. test clip + render

Conventions
    The character stands on Z=0, is 1.8 units tall and faces -Y (towards
    Blender's front view). ".L" is the character's own left, which is +X.
"""

import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

# ---------------------------------------------------------------------------
# 1. settings and colours
# ---------------------------------------------------------------------------
FPS = 24
CLIP_SECONDS = 5
RES_X, RES_Y = 540, 960


def srgb(hex_colour):
    """'#RRGGBB' -> linear RGBA, which is what Blender materials expect."""
    out = []
    for i in (1, 3, 5):
        c = int(hex_colour[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (*out, 1.0)


COLOURS = {
    "hoodie": "#F2C12E",
    "hoodie_dark": "#D9A520",
    "trousers": "#23283A",
    "shoes": "#ECECF0",
    "skin": "#E8B48C",
    "hair": "#3A2A22",
    "glasses": "#1B1B22",
    "string": "#F7F3E8",
    "ground": "#B9C4D6",
    "sky": "#E9EEF7",
}
FACE_INK = "#26202A"
MOUTH_INSIDE = "#7A2C36"


# ---------------------------------------------------------------------------
# 2. mesh helpers
# ---------------------------------------------------------------------------
def material(name, hex_colour, roughness=0.85):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = srgb(hex_colour)
    bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = srgb(hex_colour)          # colour in solid view / Workbench
    return mat


def _object(name, mesh, mat):
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if mat:
        mesh.materials.append(mat)
    return obj


def box(name, size, centre, mat, bevel=0.0):
    """Axis-aligned box. Vertices are stored in world coordinates (the object
    stays at the origin), which keeps the bone parenting below simple."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(centre), verts=bm.verts)
    if bevel:
        bmesh.ops.bevel(bm, geom=bm.edges[:], offset=bevel, segments=3, profile=0.5, affect="EDGES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return _object(name, mesh, mat)


def ring(name, centre, radius, thickness, mat, segments=32, sides=8):
    """Thin torus standing upright, its hole facing along Y (i.e. a glasses lens rim)."""
    verts, faces = [], []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        for j in range(sides):
            b = 2 * math.pi * j / sides
            r = radius + thickness * math.cos(b)
            verts.append((centre[0] + r * math.cos(a), centre[1] + thickness * math.sin(b),
                          centre[2] + r * math.sin(a)))
    for i in range(segments):
        for j in range(sides):
            i2, j2 = (i + 1) % segments, (j + 1) % sides
            faces.append((i * sides + j, i2 * sides + j, i2 * sides + j2, i * sides + j2))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    return _object(name, mesh, mat)


def face_quad(name, width, height, centre, mat):
    """Flat quad facing -Y with a 0..1 UV map, for a face texture."""
    x, y, z = centre
    verts = [(x - width / 2, y, z - height / 2), (x + width / 2, y, z - height / 2),
             (x + width / 2, y, z + height / 2), (x - width / 2, y, z + height / 2)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new(name="UVMap")
    for loop, coord in zip(uv.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop.uv = coord
    return _object(name, mesh, mat)


# ---------------------------------------------------------------------------
# 3. face textures - drawn with numpy as signed-distance shapes, so the
#    script needs no image files. Each expression becomes its own material.
# ---------------------------------------------------------------------------
PX_PER_UNIT = 1400                  # texture resolution: pixels per Blender unit


class Sketch:
    """A tiny raster canvas in Blender units, origin at the centre, y up."""

    def __init__(self, width, height, background_hex):
        self.w, self.h = width, height
        nx, ny = int(width * PX_PER_UNIT), int(height * PX_PER_UNIT)
        xs = (np.arange(nx) + 0.5) / nx * width - width / 2
        ys = (np.arange(ny) + 0.5) / ny * height - height / 2      # row 0 = bottom, as Blender stores images
        self.X, self.Y = np.meshgrid(xs, ys)
        self.aa = 1.0 / PX_PER_UNIT                                 # one pixel, for anti-aliasing
        self.rgb = np.empty((ny, nx, 3), dtype=np.float32)
        self.rgb[:] = self._rgb(background_hex)

    @staticmethod
    def _rgb(hex_colour):
        return [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    def _paint(self, distance, hex_colour):
        """Fill wherever the signed distance is negative, with a soft 1px edge."""
        alpha = np.clip(0.5 - distance / self.aa, 0, 1)[..., None]
        self.rgb = self.rgb * (1 - alpha) + np.array(self._rgb(hex_colour), dtype=np.float32) * alpha

    def ellipse(self, cx, cy, rx, ry, colour):
        k = np.sqrt(((self.X - cx) / rx) ** 2 + ((self.Y - cy) / ry) ** 2)
        self._paint((k - 1) * min(rx, ry), colour)

    def stroke(self, points, thickness, colour):
        """Round-capped polyline through `points`."""
        d = np.full(self.X.shape, 1e9, dtype=np.float32)
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            px, py, vx, vy = self.X - ax, self.Y - ay, bx - ax, by - ay
            t = np.clip((px * vx + py * vy) / (vx * vx + vy * vy + 1e-12), 0, 1)
            d = np.minimum(d, np.hypot(px - t * vx, py - t * vy))
        self._paint(d - thickness / 2, colour)

    def arc(self, cx, cy, half_width, sag, thickness, colour, n=12):
        """Curve from left to right; sag > 0 hangs down in the middle (a smile)."""
        pts = [(cx + half_width * u, cy - sag * (1 - u * u)) for u in np.linspace(-1, 1, n)]
        self.stroke(pts, thickness, colour)

    def cover_above(self, y, colour):
        """Paint everything above height y (used for eyelids)."""
        self._paint(y - self.Y, colour)

    def to_material(self, name):
        ny, nx, _ = self.rgb.shape
        image = bpy.data.images.new(name, width=nx, height=ny, alpha=False)
        rgba = np.concatenate([self.rgb, np.ones((ny, nx, 1), dtype=np.float32)], axis=2)
        image.pixels.foreach_set(rgba.astype(np.float32).ravel())
        image.pack()                                   # store inside the .blend
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Roughness"].default_value = 0.85
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        mat.diffuse_color = srgb(COLOURS["skin"])
        return mat


EYES_SIZE = (0.34, 0.15)            # the eyes quad, in Blender units
MOUTH_SIZE = (0.20, 0.09)
EYE_X = 0.095                       # each eye's distance from the centre line


def eyes_material(style):
    s = Sketch(*EYES_SIZE, COLOURS["skin"])
    skin = COLOURS["skin"]
    for side in (-1, 1):
        x = side * EYE_X
        if style == "open":
            s.ellipse(x, 0.0, 0.021, 0.030, FACE_INK)
            s.ellipse(x - 0.007, 0.011, 0.006, 0.007, "#FFFFFF")
        elif style == "wide":
            s.ellipse(x, 0.0, 0.043, 0.050, FACE_INK)
            s.ellipse(x, 0.0, 0.036, 0.043, "#FFFFFF")
            s.ellipse(x, 0.0, 0.014, 0.016, FACE_INK)
            s.stroke([(x - 0.035, 0.064), (x + 0.035, 0.064)], 0.009, FACE_INK)        # raised brow
        elif style == "half_closed":
            s.ellipse(x, 0.0, 0.022, 0.030, FACE_INK)
            s.cover_above(0.004, skin)                                                 # heavy lid
            s.stroke([(x - 0.030, 0.004), (x + 0.030, 0.004)], 0.008, FACE_INK)
        elif style == "squint":
            s.arc(x, 0.008, 0.028, -0.014, 0.010, FACE_INK)                            # arched line
        else:
            raise ValueError(f"unknown eye style {style!r}")
    return s.to_material("eyes_" + style)


def mouth_material(style):
    s = Sketch(*MOUTH_SIZE, COLOURS["skin"])
    if style == "neutral":
        s.arc(0, 0.004, 0.036, 0.006, 0.009, FACE_INK)
    elif style == "open":
        s.ellipse(0, 0.0, 0.046, 0.032, FACE_INK)
        s.ellipse(0, 0.0, 0.039, 0.025, MOUTH_INSIDE)
    elif style == "small_o":
        s.ellipse(0, 0.0, 0.020, 0.023, FACE_INK)
        s.ellipse(0, 0.0, 0.013, 0.016, MOUTH_INSIDE)
    elif style == "smile":
        s.arc(0, 0.016, 0.062, 0.030, 0.010, FACE_INK)
    elif style == "flat":
        s.stroke([(-0.042, 0.0), (0.042, 0.0)], 0.009, FACE_INK)
    else:
        raise ValueError(f"unknown mouth style {style!r}")
    return s.to_material("mouth_" + style)


EYE_STYLES = ["open", "wide", "half_closed", "squint"]
MOUTH_STYLES = ["neutral", "open", "small_o", "smile", "flat"]


# ---------------------------------------------------------------------------
# 4. the character
# ---------------------------------------------------------------------------
# Bones: name -> (head position, tail position, parent). All FK. Limb bones
# point down from their joint, so "shoulder" is the upper arm, "elbow" the
# forearm, "hip" the thigh and "knee" the shin. "root" moves the whole
# character and is never touched by poses.
BONES = {
    "root":       ((0, 0, 0),         (0, 0.30, 0),       None),
    "hips":       ((0, 0, 0.86),      (0, 0, 0.94),       "root"),
    "spine":      ((0, 0, 0.94),      (0, 0, 1.32),       "hips"),
    "neck":       ((0, 0, 1.32),      (0, 0, 1.38),       "spine"),
    "head":       ((0, 0, 1.38),      (0, 0, 1.78),       "neck"),
    "shoulder.L": ((0.30, 0, 1.29),   (0.30, 0, 1.05),    "spine"),
    "elbow.L":    ((0.30, 0, 1.05),   (0.30, 0, 0.80),    "shoulder.L"),
    "shoulder.R": ((-0.30, 0, 1.29),  (-0.30, 0, 1.05),   "spine"),
    "elbow.R":    ((-0.30, 0, 1.05),  (-0.30, 0, 0.80),   "shoulder.R"),
    "hip.L":      ((0.115, 0, 0.86),  (0.115, 0, 0.46),   "hips"),
    "knee.L":     ((0.115, 0, 0.46),  (0.115, 0, 0.08),   "hip.L"),
    "hip.R":      ((-0.115, 0, 0.86), (-0.115, 0, 0.46),  "hips"),
    "knee.R":     ((-0.115, 0, 0.46), (-0.115, 0, 0.08),  "hip.R"),
}
LEG_LENGTH = 0.86 - 0.08

ARM = None          # the armature object, set by build_character()
FACE = {}           # {"eyes": {style: object}, "mouth": {style: object}}
_last_quat = {}     # bone name -> last keyed quaternion (keeps interpolation the short way round)


def build_character():
    """Create every mesh, the armature, and bone-parent the meshes to it."""
    global ARM
    mats = {name: material(name, colour) for name, colour in COLOURS.items()}
    hoodie, trousers, skin = mats["hoodie"], mats["trousers"], mats["skin"]

    # --- armature -----------------------------------------------------------
    data = bpy.data.armatures.new("CharacterRig")
    ARM = bpy.data.objects.new("Character", data)
    bpy.context.scene.collection.objects.link(ARM)
    bpy.context.view_layer.objects.active = ARM
    bpy.ops.object.mode_set(mode="EDIT")            # bones can only be created in edit mode
    for name, (head, tail, parent) in BONES.items():
        bone = data.edit_bones.new(name)
        bone.head, bone.tail, bone.roll = head, tail, 0.0
        if parent:
            bone.parent = data.edit_bones[parent]   # not "connected": every bone keeps its own pivot
    bpy.ops.object.mode_set(mode="OBJECT")
    for pose_bone in ARM.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
    data.display_type = "STICK"

    # --- body parts: (object, bone it rides on) -----------------------------
    parts = []

    def add(obj, bone):
        parts.append((obj, bone))
        return obj

    head_z = 1.57                                    # head box spans z 1.37 .. 1.77
    add(box("head", (0.44, 0.40, 0.40), (0, 0, head_z), skin, bevel=0.035), "head")
    add(box("hair_top", (0.46, 0.42, 0.07), (0, 0.005, 1.765), mats["hair"], bevel=0.012), "head")
    add(box("hair_back", (0.46, 0.06, 0.24), (0, 0.185, 1.66), mats["hair"], bevel=0.012), "head")
    add(box("hair_fringe", (0.40, 0.03, 0.05), (0.03, -0.195, 1.725), mats["hair"]), "head")
    add(box("neck", (0.14, 0.14, 0.08), (0, 0, 1.35), skin), "neck")

    add(box("torso", (0.46, 0.26, 0.46), (0, 0, 1.11), hoodie, bevel=0.015), "spine")
    add(box("hood", (0.36, 0.12, 0.16), (0, 0.15, 1.30), mats["hoodie_dark"], bevel=0.02), "spine")
    add(box("pocket", (0.26, 0.02, 0.12), (0, -0.135, 0.99), mats["hoodie_dark"]), "spine")
    for sx in (-0.05, 0.05):
        add(box("drawstring", (0.012, 0.012, 0.11), (sx, -0.134, 1.25), mats["string"]), "spine")
    add(box("pelvis", (0.44, 0.24, 0.14), (0, 0, 0.87), trousers), "hips")

    for side, sx in (("L", 1), ("R", -1)):
        x = 0.30 * sx
        add(box("upper_arm." + side, (0.13, 0.13, 0.27), (x, 0, 1.19), hoodie, bevel=0.01), "shoulder." + side)
        add(box("lower_arm." + side, (0.12, 0.12, 0.25), (x, 0, 0.925), hoodie, bevel=0.01), "elbow." + side)
        add(box("hand." + side, (0.11, 0.11, 0.10), (x, 0, 0.75), skin, bevel=0.012), "elbow." + side)
        x = 0.115 * sx
        add(box("upper_leg." + side, (0.18, 0.19, 0.42), (x, 0, 0.67), trousers, bevel=0.01), "hip." + side)
        add(box("lower_leg." + side, (0.17, 0.18, 0.38), (x, 0, 0.27), trousers, bevel=0.01), "knee." + side)
        add(box("foot." + side, (0.18, 0.29, 0.08), (x, -0.045, 0.04), mats["shoes"], bevel=0.012), "knee." + side)

    # --- glasses: two rings, a bridge, and arms back to the ears ------------
    glasses, gy, gz = mats["glasses"], -0.215, head_z + 0.03
    for sx in (-1, 1):
        add(ring("glasses_rim", (EYE_X * sx, gy, gz), 0.074, 0.008, glasses), "head")
        add(box("glasses_hinge", (0.058, 0.014, 0.014), (0.196 * sx, gy, gz), glasses), "head")
        add(box("glasses_arm", (0.012, 0.20, 0.014), (0.226 * sx, gy + 0.10, gz), glasses), "head")
    add(box("glasses_bridge", (0.05, 0.012, 0.012), (0, gy, gz + 0.01), glasses), "head")

    # --- face: one quad per expression, stacked in the same place. Only one
    #     eyes quad and one mouth quad is visible at a time (see set_face). --
    face_y = -0.2012                                 # just in front of the head's flat front
    FACE["eyes"] = {s: add(face_quad("eyes_" + s, *EYES_SIZE, (0, face_y, gz), eyes_material(s)), "head")
                    for s in EYE_STYLES}
    FACE["mouth"] = {s: add(face_quad("mouth_" + s, *MOUTH_SIZE, (0, face_y, head_z - 0.115), mouth_material(s)), "head")
                     for s in MOUTH_STYLES}

    # --- rigid parenting: each mesh follows exactly one bone, no deformation -
    for obj, bone_name in parts:
        bone = data.bones[bone_name]
        obj.parent = ARM
        obj.parent_type = "BONE"
        obj.parent_bone = bone_name
        # A bone-parented object hangs off the bone's TAIL. Cancel that
        # transform so the mesh stays exactly where it was modelled.
        tail_space = ARM.matrix_world @ bone.matrix_local @ Matrix.Translation((0, bone.length, 0))
        obj.matrix_parent_inverse = tail_space.inverted()

    set_face("open", "neutral")
    return ARM


# ---------------------------------------------------------------------------
# 5. animation API
# ---------------------------------------------------------------------------
# A pose lists rotations per bone as (fwd, side, twist) in degrees:
#
#   fwd    > 0 swings the bone's free end FORWARD (the way the character faces).
#          So shoulder fwd=90 points the arm straight ahead, and a knee bends
#          with a NEGATIVE fwd (the shin swings back).
#   side   limbs: > 0 swings the free end OUTWARD, away from the body.
#          spine / neck / head / hips: > 0 leans to the character's left.
#   twist  > 0 turns to the character's left, about the vertical axis.
#
# Rotations are relative to the parent, as in any FK rig: an elbow's angles
# are measured from wherever the upper arm currently points.
#
# Bones a pose doesn't mention return to rest. To also MOVE a bone, give a
# dict instead: {"rot": (fwd, side, twist), "loc": (x, y, z)} with loc in
# units along the character's own right(-)/left(+), back(+)/front(-), up(+).
POSES = {
    "idle": {
        "spine": (2, 0, 0),
        "shoulder.L": (0, 5, 0), "shoulder.R": (0, 5, 0),
        "elbow.L": (10, 0, 0), "elbow.R": (10, 0, 0),
    },
    "talking": {
        "spine": (3, 0, 0), "head": (0, 4, 0),
        "shoulder.R": (38, 12, 0), "elbow.R": (78, 0, 0),
        "shoulder.L": (0, 5, 0), "elbow.L": (12, 0, 0),
    },
    "point": {                                       # points out to his right, other hand on hip
        "spine": (0, -3, -6), "head": (0, 0, -28),
        "shoulder.R": (8, 84, 0), "elbow.R": (0, 4, 0),
        "shoulder.L": (0, 28, 0), "elbow.L": (25, -72, 0),
    },
    "shrug": {
        "spine": (-3, 0, 0), "head": (-4, 9, 0),
        "shoulder.L": {"rot": (8, 16, 0), "loc": (0, 0, 0.05)},      # shoulders lift
        "shoulder.R": {"rot": (8, 16, 0), "loc": (0, 0, 0.05)},
        "elbow.L": (30, 100, 0), "elbow.R": (30, 100, 0),            # forearms out to the sides, hands up
    },
    "panic": {
        "hips": {"rot": (0, 0, 0), "loc": (0, 0, -0.025)},
        "spine": (-7, 0, 0), "head": (-10, 0, 0),
        "shoulder.L": (0, 152, 0), "shoulder.R": (0, 152, 0),
        "elbow.L": (0, -34, 0), "elbow.R": (0, -34, 0),
        "hip.L": (14, 6, 0), "hip.R": (14, 6, 0),
        "knee.L": (-28, 0, 0), "knee.R": (-28, 0, 0),
    },
    "sleepy": {
        "hips": {"rot": (0, 0, 0), "loc": (0, 0, -0.012)},
        "spine": (14, 3, 0), "neck": (12, 0, 0), "head": (16, 8, 0),
        "shoulder.L": (8, 2, 0), "shoulder.R": (8, 2, 0),
        "elbow.L": (4, 0, 0), "elbow.R": (4, 0, 0),
        "hip.L": (8, 0, 0), "hip.R": (8, 0, 0),
        "knee.L": (-16, 0, 0), "knee.R": (-16, 0, 0),
    },
    "sit_driving": {                                 # seated, both hands forward on a wheel
        "hips": {"rot": (-6, 0, 0), "loc": (0, 0, -0.37)},
        "spine": (-4, 0, 0), "head": (6, 0, 0),
        "hip.L": (88, 4, 0), "hip.R": (88, 4, 0),
        "knee.L": (-82, 0, 0), "knee.R": (-82, 0, 0),
        "shoulder.L": (62, -6, 0), "shoulder.R": (62, -6, 0),
        "elbow.L": (24, 0, 0), "elbow.R": (24, 0, 0),
    },
}

# Which way "fwd" and "side" turn each bone, so that the pose numbers above
# mean the same thing on both sides of the body.
_UPRIGHT = {"root", "hips", "spine", "neck", "head"}


def _signs(bone_name):
    if bone_name in _UPRIGHT:
        return 1, 1
    return -1, (-1 if bone_name.endswith(".L") else 1)


def _apply(bone_name, rot=(0, 0, 0), loc=(0, 0, 0), frame=None):
    """Set one bone from (fwd, side, twist) + offset, and keyframe it if `frame` is given."""
    pose_bone = ARM.pose.bones[bone_name]
    # Pose values are written against the character's own axes. A pose bone
    # stores rotation in its private rest axes, so convert: local = R^-1 D R.
    rest = ARM.data.bones[bone_name].matrix_local.to_quaternion()
    fwd_sign, side_sign = _signs(bone_name)
    turn = Euler((math.radians(rot[0] * fwd_sign), math.radians(rot[1] * side_sign),
                  math.radians(rot[2])), "XYZ").to_quaternion()
    quat = rest.conjugated() @ turn @ rest
    # q and -q are the same rotation; pick the one nearer the previous key
    # so the interpolation never takes the long way round.
    previous = _last_quat.get(bone_name)
    if previous is not None and previous.dot(quat) < 0:
        quat.negate()
    _last_quat[bone_name] = quat.copy()

    pose_bone.rotation_quaternion = quat
    pose_bone.location = rest.conjugated() @ Vector(loc)
    if frame is not None:
        _insert_key(pose_bone, "rotation_quaternion", frame)
        _insert_key(pose_bone, "location", frame)


_curve_kind = "BEZIER"      # how the next keys interpolate; changed with `with _interpolation(...)`


class _interpolation:
    """`with _interpolation("LINEAR"):` - keys inserted inside use that curve type
    ("BEZIER" eases, "LINEAR" moves at constant speed, "CONSTANT" jumps)."""

    def __init__(self, kind):
        self.kind = kind

    def __enter__(self):
        global _curve_kind
        self.saved, _curve_kind = _curve_kind, self.kind

    def __exit__(self, *exc):
        global _curve_kind
        _curve_kind = self.saved


def _fcurves(id_block):
    """The animation curves of an object, across Blender versions."""
    data = id_block.animation_data
    action = data.action if data else None
    if action is None:
        return []
    if hasattr(action, "fcurves"):                    # Blender 4.x
        return action.fcurves
    slot = data.action_slot                           # Blender 5: curves live in layered "channelbags"
    for layer in action.layers:
        for strip in layer.strips:
            bag = strip.channelbag(slot)
            if bag:
                return bag.fcurves
    return []


def _insert_key(target, prop, frame, index=-1):
    """Insert a keyframe and give it the current curve type.

    Blender ignores the "default interpolation" preference for keys inserted
    from a script (they always come out Bezier), so the type is set on the
    new key itself.
    """
    target.keyframe_insert(prop, frame=frame, index=index)
    path = target.path_from_id(prop)
    for curve in _fcurves(target.id_data):
        if curve.data_path != path or (index >= 0 and curve.array_index != index):
            continue
        for point in curve.keyframe_points:
            if abs(point.co[0] - frame) < 0.5:
                point.interpolation = _curve_kind
                point.handle_left_type = point.handle_right_type = "AUTO_CLAMPED"   # Bezier: ease, no overshoot
        curve.update()


def _apply_pose(pose, frame):
    for bone_name in BONES:
        if bone_name == "root":
            continue
        value = pose.get(bone_name, (0, 0, 0))
        if isinstance(value, dict):
            _apply(bone_name, value.get("rot", (0, 0, 0)), value.get("loc", (0, 0, 0)), frame)
        else:
            _apply(bone_name, value, (0, 0, 0), frame)


def set_pose(name, frame):
    """Key the whole body into POSES[name] at `frame`.

    Keys use Bezier curves with auto-clamped handles, so the character
    eases out of the previous pose and into this one without overshoot.
    To hold a pose, key it twice (at the start and end of the hold).
    """
    with _interpolation("BEZIER"):
        _apply_pose(POSES[name], frame)


def set_face(eyes=None, mouth=None, frame=None):
    """Swap the face. eyes: open / wide / half_closed / squint;
    mouth: neutral / open / small_o / smile / flat. None leaves that part alone.

    Each expression is its own quad with its own material; swapping shows
    one and hides the rest. With `frame`, the swap is keyframed and happens
    on exactly that frame (stepped, no blending).
    """
    for part, choice in (("eyes", eyes), ("mouth", mouth)):
        if choice is None:
            continue
        if choice not in FACE[part]:
            raise ValueError(f"unknown {part} {choice!r}; choose from {list(FACE[part])}")
        with _interpolation("CONSTANT"):
            for style, obj in FACE[part].items():
                obj.hide_render = obj.hide_viewport = style != choice
                if frame is not None:
                    _insert_key(obj, "hide_render", frame)
                    _insert_key(obj, "hide_viewport", frame)


def set_root(frame, position, heading=0.0, interpolation="BEZIER"):
    """Place the whole character. position = (x, y) on the ground;
    heading in degrees: 0 faces the camera (-Y), 90 faces +X, -90 faces -X."""
    with _interpolation(interpolation):
        _apply("root", (0, 0, heading), (position[0], position[1], 0), frame)


def walk_pose(i):
    """Pose number i (0-7) of the 8-pose walk loop.

    0 and 4 are the passing poses (legs together, one knee lifted);
    2 and 6 are the contact poses (legs at full stride).
    """
    phase = 2 * math.pi * (i % 8) / 8
    swing, lift = math.sin(phase), math.cos(phase)
    return {
        "hips": {"rot": (0, 0, 5 * swing), "loc": (0, 0, -0.035 * abs(swing))},     # dips at full stride
        "spine": (4, 0, -8 * swing),                                                # counter-twist
        "head": (0, 0, 3 * swing),
        "hip.L": (28 * swing, 0, 0), "hip.R": (-28 * swing, 0, 0),
        "knee.L": (-(6 + 42 * max(0.0, lift)), 0, 0),                               # knee bends while its leg swings forward
        "knee.R": (-(6 + 42 * max(0.0, -lift)), 0, 0),
        "shoulder.L": (-24 * swing, 4, 0), "shoulder.R": (24 * swing, 4, 0),        # arms swing opposite the legs
        "elbow.L": (14 + 14 * max(0.0, -swing), 0, 0),
        "elbow.R": (14 + 14 * max(0.0, swing), 0, 0),
    }


STRIDE_PER_LOOP = 4 * LEG_LENGTH * math.sin(math.radians(28))     # ground covered by one full loop


def walk(start_frame, start, heading, loops=1.0, frames_per_pose=3):
    """Walk in a straight line, looping the 8-pose cycle.

    start            (x, y) where the walk begins
    heading          direction of travel in degrees (see set_root)
    loops            how many times round the cycle; may be fractional in
                     eighths (1.5 ends on the opposite passing pose)
    frames_per_pose  spacing of the 8 poses. 3 gives a 24-frame loop, one
                     second at 24 fps, which is a natural pace. 1 plays the
                     loop in literally 8 frames, which is a sprint.

    Travel speed is matched to the stride so the feet don't slide.
    Returns (end_frame, (x, y) end position).
    """
    steps = round(loops * 8)
    with _interpolation("BEZIER"):
        for i in range(steps + 1):
            _apply_pose(walk_pose(i), start_frame + i * frames_per_pose)
    distance = STRIDE_PER_LOOP * steps / 8
    a = math.radians(heading)
    end = (start[0] + math.sin(a) * distance, start[1] - math.cos(a) * distance)
    end_frame = start_frame + steps * frames_per_pose
    set_root(start_frame, start, heading, "LINEAR")           # constant speed between the two keys
    set_root(end_frame, end, heading, "LINEAR")
    return end_frame, end


def look_at(target, frame=None, tilt=0.0, max_turn=75.0, max_nod=40.0):
    """Turn the head (and a little of the neck) to face a point in world space.

    target  (x, y, z), e.g. the camera's location
    frame   keyframe the result there. The body pose at that frame should
            already be keyed, because the aim depends on where the chest is.
    tilt    extra sideways head tilt in degrees, applied on top

    The turn is limited to +-max_turn and the nod to +-max_nod so the head
    can't spin round like an owl's.
    """
    scene = bpy.context.scene
    if frame is not None:
        scene.frame_set(frame)                      # evaluate the body at that frame
    bpy.context.view_layer.update()
    chest = ARM.pose.bones["spine"]
    # Rotation that carries the character's rest axes to where the chest has taken them.
    carried = (ARM.matrix_world.to_quaternion() @ chest.matrix.to_quaternion()
               @ ARM.data.bones["spine"].matrix_local.to_quaternion().conjugated())
    pivot = ARM.matrix_world @ ARM.pose.bones["head"].head
    d = carried.conjugated() @ (Vector(target) - pivot)        # direction to target, in chest axes
    turn = math.degrees(math.atan2(d.x, -d.y))                 # + = to the character's left
    nod = -math.degrees(math.atan2(d.z, math.hypot(d.x, d.y)))  # + = looking down
    turn = max(-max_turn, min(max_turn, turn))
    nod = max(-max_nod, min(max_nod, nod))
    with _interpolation("BEZIER"):
        _apply("neck", (nod * 0.35, 0, turn * 0.35), frame=frame)
        _apply("head", (nod * 0.65, tilt, turn * 0.65), frame=frame)


# ---------------------------------------------------------------------------
# 6. scene
# ---------------------------------------------------------------------------
CAMERA_POSITION = (0.0, -4.7, 1.02)


def build_scene(engine, samples):
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, FPS * CLIP_SECONDS
    scene.render.resolution_x, scene.render.resolution_y = RES_X, RES_Y
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"       # keep the flat cartoon colours as authored

    # Eevee is "BLENDER_EEVEE_NEXT" in 4.2-4.x and "BLENDER_EEVEE" again from 5.0.
    available = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    wanted = {"eevee": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"], "workbench": ["BLENDER_WORKBENCH"],
              "cycles": ["CYCLES"]}[engine]
    scene.render.engine = next(e for e in wanted if e in available)
    if engine == "eevee":
        scene.eevee.taa_render_samples = samples
    elif engine == "cycles":
        scene.cycles.samples = samples
    else:
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "TEXTURE"      # show the face textures
        scene.display.shading.show_shadows = True

    camera_data = bpy.data.cameras.new("Camera")
    camera_data.lens = 50
    camera = bpy.data.objects.new("Camera", camera_data)
    camera.location = CAMERA_POSITION
    camera.rotation_euler = (math.radians(90), 0, 0)      # looking along +Y, at the character's front
    scene.collection.objects.link(camera)
    scene.camera = camera

    sun_data = bpy.data.lights.new("Sun", "SUN")
    sun_data.energy = 2.4
    sun_data.angle = math.radians(8)                      # slightly soft shadow edges
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (math.radians(52), 0, math.radians(-32))
    scene.collection.objects.link(sun)

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    background = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    background.inputs["Color"].default_value = srgb(COLOURS["sky"])
    background.inputs["Strength"].default_value = 0.8
    scene.world = world

    box("ground", (40, 40, 0.1), (0, 0, -0.05), material("ground_mat", COLOURS["ground"], 0.95))
    return scene


# ---------------------------------------------------------------------------
# 7. test clip + render
# ---------------------------------------------------------------------------
def animate_test_clip():
    """5 seconds: walks in from the left, stops, goes wide-eyed, shrugs."""
    set_face("open", "neutral", frame=1)

    # 1.5 loops of the walk, heading right, timed to arrive at the centre.
    distance = STRIDE_PER_LOOP * 1.5
    arrive, spot = walk(start_frame=1, start=(-distance, 0.0), heading=90, loops=1.5)   # arrives frame 37

    # Stop: turn most of the way towards the camera and settle; the head finishes the turn.
    settle = arrive + 12
    set_root(settle, spot, heading=22)
    set_pose("idle", settle)
    look_at(CAMERA_POSITION, settle)

    # Beat, then the realisation.
    set_pose("idle", 58)
    look_at(CAMERA_POSITION, 58)
    set_face("wide", "small_o", frame=60)

    # Shrug: up, hold, and relax.
    set_pose("idle", 68)
    look_at(CAMERA_POSITION, 68)
    set_pose("shrug", 82)
    look_at(CAMERA_POSITION, 82, tilt=9)
    set_face(mouth="flat", frame=82)
    set_pose("shrug", 104)
    look_at(CAMERA_POSITION, 104, tilt=9)
    set_pose("idle", 120)
    look_at(CAMERA_POSITION, 120)
    set_face("open", "neutral", frame=112)


def parse_args():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="blender -b -P build_character.py --")
    ap.add_argument("--engine", choices=["eevee", "workbench", "cycles"], default="eevee")
    ap.add_argument("--samples", type=int, default=16, help="render samples (default 16: preview quality)")
    ap.add_argument("--out", default=None, help="output folder (default: character_out next to this script)")
    ap.add_argument("--still", type=int, default=None, metavar="FRAME", help="render one frame as PNG instead of the clip")
    ap.add_argument("--no-render", action="store_true", help="build and save the .blend only")
    return ap.parse_args(argv)


def render_clip(scene, path):
    """Render the animation to an H.264 MP4; fall back to PNG frames if this
    Blender build can't write video."""
    settings = scene.render.image_settings
    try:
        if hasattr(settings, "media_type"):               # Blender 5.0+
            settings.media_type = "VIDEO"
        settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "HIGH"
        scene.render.filepath = path
    except (TypeError, AttributeError):
        settings.file_format = "PNG"
        scene.render.filepath = os.path.splitext(path)[0] + "_"
        print("NOTE: this Blender build cannot write MP4; rendering numbered PNG frames instead.")
    bpy.ops.render.render(animation=True)
    return scene.render.filepath


def main():
    args = parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(here, "character_out")
    os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)       # start from a completely empty file
    scene = build_scene(args.engine, args.samples)
    build_character()
    animate_test_clip()
    scene.frame_set(1)

    blend_path = os.path.join(out_dir, "character.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print("saved", blend_path)

    if args.no_render:
        return
    if args.still is not None:
        scene.frame_set(args.still)
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = os.path.join(out_dir, f"character_frame_{args.still:03d}.png")
        bpy.ops.render.render(write_still=True)
        print("rendered", scene.render.filepath)
    else:
        print("rendered", render_clip(scene, os.path.join(out_dir, "character_test.mp4")))


if __name__ == "__main__":
    main()
