"""A modular blocky town for Blender: buildings, props, a street and lighting.

Run (no Blender window needed):

    blender -b -P buildings.py

Options go after a lone "--":

    blender -b -P buildings.py -- --preset dawn          # one shot only
    blender -b -P buildings.py -- --scale 50 --samples 8 # faster, smaller
    blender -b -P buildings.py -- --engine cycles        # if Eevee can't start
    blender -b -P buildings.py -- --no-render            # only save the .blend

Writes to ./town_out/ next to this script:

    town.blend                    the whole street, lit for midnight
    establishing_midnight.png     the street at midnight, clock at 12:00
    establishing_dawn.png         the same shot at dawn, clock at 5:40

Needs Blender 4.2 LTS or newer. Uses only modules that ship inside Blender.

Layout of this file
    1. settings, colours, materials
    2. MeshBuilder: many boxes -> one low-poly mesh
    3. make_building() and the window / door / roof parts
    4. specific buildings: bakery, school, bus depot, clock tower
    5. props: bus, loaf, streetlamp, fence, tree, road, pavement
    6. street_layout()
    7. lighting presets: day, dawn, midnight
    8. test render

Conventions
    One unit is about one metre (the character from build_character.py is 1.8
    tall). A building's own origin is the middle of its FRONT wall at ground
    level; its front faces -Y and it extends back along +Y. "left" and
    "right" are as you face the front.

Signs, the bus's destination board and the school flag are blank panels.
There is deliberately no text anywhere, and the clock faces have tick marks
instead of numerals.

Keeping it cheap
    Every building is a handful of mesh objects, not hundreds: all window
    frames share one mesh, all glass another. Bevels use a single segment.
    The whole street is around 20,000 triangles.
"""

import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

# ---------------------------------------------------------------------------
# 1. settings, colours, materials
# ---------------------------------------------------------------------------
FLOOR_HEIGHT = 2.8
WINDOW_GLOW = "#FFD98A"             # colour of lit windows
LAMP_GLOW = "#FFC670"

PALETTE = {
    "roof_tile": "#B5543C",
    "roof_flat": "#5B6270",
    "trim": "#F3EEE2",              # window frames, door frames
    "plinth": "#6F6A68",
    "door": "#5A4638",
    "sign": "#F4EBD2",              # blank sign panels
    "sign_back": "#3C4254",
    "glass": "#33435C",
    "metal": "#8E949E",
    "dark_metal": "#3A3E48",
    "road": "#3B3E46",
    "marking": "#E8E6DC",
    "pavement": "#B4B2AC",
    "kerb": "#8C8A86",
    "grass": "#6F9B5F",
    "trunk": "#6B4A35",
    "leaf": "#4F8A4B",
    "leaf_light": "#6BA65C",
    "wood": "#9A6B45",
    "bread": "#C98A45",
    "bread_cut": "#E9C788",
    "clock_face": "#F2EDE0",
    "clock_hand": "#22242C",
    "awning_a": "#D9534F",
    "awning_b": "#F6F1E7",
    "bus": "#2F8F83",
    "bus_roof": "#E9E6DA",
    "tyre": "#1C1D22",
    "hub": "#B9BEC8",
    "flag": "#E9E4D6",
    "moon": "#E6ECFF",
}

_materials = {}


def srgb(hex_colour):
    """'#RRGGBB' -> linear RGBA, which is what Blender materials expect."""
    out = []
    for i in (1, 3, 5):
        c = int(hex_colour[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (*out, 1.0)


def _principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def mat(colour, roughness=0.85):
    """Shared plain material for a palette name or '#RRGGBB'. Cached, so the
    whole town uses a few dozen materials."""
    hex_colour = PALETTE.get(colour, colour)
    key = (hex_colour, roughness)
    if key not in _materials:
        m = bpy.data.materials.new(colour if colour in PALETTE else "colour_" + hex_colour[1:])
        m.use_nodes = True
        bsdf = _principled(m)
        bsdf.inputs["Base Color"].default_value = srgb(hex_colour)
        bsdf.inputs["Roughness"].default_value = roughness
        m.diffuse_color = srgb(hex_colour)
        _materials[key] = m
    return _materials[key]


def glow_material(name, base="glass", glow=WINDOW_GLOW, roughness=0.25):
    """A NEW material that can emit light. Not cached: each building owns its
    own, so its windows switch independently of everyone else's.
    Starts switched off (emission strength 0)."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = _principled(m)
    bsdf.inputs["Base Color"].default_value = srgb(PALETTE.get(base, base))
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Emission Color"].default_value = srgb(glow)
    bsdf.inputs["Emission Strength"].default_value = 0.0
    m.diffuse_color = srgb(PALETTE.get(base, base))
    return m


def set_glow(material, on, strength=5.0, frame=None):
    """Switch an emissive material on or off; keyframe it if `frame` is given."""
    socket = _principled(material).inputs["Emission Strength"]
    socket.default_value = strength if on else 0.0
    if frame is not None:
        socket.keyframe_insert("default_value", frame=frame)


# ---------------------------------------------------------------------------
# 2. MeshBuilder: collect many boxes into ONE mesh
# ---------------------------------------------------------------------------
class MeshBuilder:
    """Accumulates primitives, then makes a single mesh object from them.

    One object with 40 boxes renders far faster than 40 objects, and keeps
    the outliner readable. Coordinates are in the parent's local space.
    """

    def __init__(self):
        self.bm = bmesh.new()

    @property
    def empty(self):
        return len(self.bm.verts) == 0

    def _finish(self, verts, centre, rotate_z, bevel):
        if rotate_z:
            bmesh.ops.rotate(self.bm, cent=(0, 0, 0), matrix=Matrix.Rotation(rotate_z, 3, "Z"), verts=verts)
        bmesh.ops.translate(self.bm, vec=Vector(centre), verts=verts)
        if bevel:
            edges = list({e for v in verts for e in v.link_edges})
            bmesh.ops.bevel(self.bm, geom=edges, offset=bevel, segments=1, affect="EDGES")

    def box(self, size, centre, bevel=0.0, tilt_x=0.0, rotate_z=0.0):
        """Box of `size` centred on `centre`. bevel uses ONE segment (cheap).
        tilt_x leans it about its own X axis (awnings); rotate_z spins it."""
        verts = bmesh.ops.create_cube(self.bm, size=1.0)["verts"]
        bmesh.ops.scale(self.bm, vec=Vector(size), verts=verts)
        if tilt_x:
            bmesh.ops.rotate(self.bm, cent=(0, 0, 0), matrix=Matrix.Rotation(tilt_x, 3, "X"), verts=verts)
        self._finish(verts, centre, rotate_z, bevel)
        return self

    def cylinder(self, radius, length, centre, axis="X", segments=12):
        """Capped cylinder along `axis` (wheels, clock faces, poles)."""
        verts = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=segments,
                                      radius1=radius, radius2=radius, depth=length)["verts"]
        turn = {"X": Matrix.Rotation(math.pi / 2, 3, "Y"), "Y": Matrix.Rotation(math.pi / 2, 3, "X"),
                "Z": Matrix.Identity(3)}[axis]
        bmesh.ops.rotate(self.bm, cent=(0, 0, 0), matrix=turn, verts=verts)
        self._finish(verts, centre, 0.0, 0.0)
        return self

    def gable(self, width, depth, height, base_centre):
        """Triangular prism: a pitched roof whose ridge runs along X."""
        x, y, z = base_centre
        w, d = width / 2, depth / 2
        pts = [(x - w, y - d, z), (x + w, y - d, z), (x + w, y + d, z), (x - w, y + d, z),
               (x - w, y, z + height), (x + w, y, z + height)]
        v = [self.bm.verts.new(p) for p in pts]
        for face in ((0, 1, 5, 4), (2, 3, 4, 5), (1, 2, 5), (3, 0, 4), (0, 3, 2, 1)):
            self.bm.faces.new([v[i] for i in face])
        return self

    def pyramid(self, width, height, base_centre):
        x, y, z = base_centre
        w = width / 2
        v = [self.bm.verts.new(p) for p in
             [(x - w, y - w, z), (x + w, y - w, z), (x + w, y + w, z), (x - w, y + w, z), (x, y, z + height)]]
        for face in ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4), (0, 3, 2, 1)):
            self.bm.faces.new([v[i] for i in face])
        return self

    def to_object(self, name, material, parent=None, location=(0, 0, 0), rotation=(0, 0, 0)):
        """Create the mesh object (or return None if nothing was added)."""
        if self.empty:
            self.bm.free()
            return None
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:])
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        mesh.materials.append(material)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.location, obj.rotation_euler = location, rotation
        if parent:
            obj.parent = parent
        return obj


def empty(name, location=(0, 0, 0), rotation_z=0.0, parent=None):
    """An Empty: the handle you move, rotate or parent a whole assembly by."""
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = 0.5
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (0, 0, rotation_z)
    if parent:
        obj.parent = parent
    return obj


def descendants(obj):
    for child in obj.children:
        yield child
        yield from descendants(child)


# ---------------------------------------------------------------------------
# 3. make_building()
# ---------------------------------------------------------------------------
class _Wall:
    """Maps "u metres along the wall, z metres up, out metres proud of it" to
    building-local coordinates, for one of the four walls."""

    def __init__(self, side, width, depth):
        self.side = side
        self.length = width if side in ("front", "back") else depth
        self.width, self.depth = width, depth

    def point(self, u, z, out=0.0):
        w, d = self.width, self.depth
        if self.side == "front":
            return (u, -out, z)
        if self.side == "back":
            return (-u, d + out, z)
        if self.side == "left":
            return (-w / 2 - out, d / 2 - u, z)
        return (w / 2 + out, d / 2 + u, z)                      # right

    def size(self, along, thick, tall):
        """Box size for something `along` the wall, `thick` out of it, `tall` up."""
        return (along, thick, tall) if self.side in ("front", "back") else (thick, along, tall)


def _framed_panel(frames, panel, wall, u, z, w, h, bar=0.09, proud=0.09):
    """A recessed rectangle: four frame bars standing proud of the wall with a
    flat panel set back between them. Used for windows, doors and shopfronts."""
    for du, dz, bw, bh in ((0, h / 2 + bar / 2, w + 2 * bar, bar), (0, -h / 2 - bar / 2, w + 2 * bar, bar),
                           (-w / 2 - bar / 2, 0, bar, h), (w / 2 + bar / 2, 0, bar, h)):
        frames.box(wall.size(bw, proud, bh), wall.point(u + du, z + dz, proud / 2))
    panel.box(wall.size(w, 0.03, h), wall.point(u, z, 0.015))


def make_building(width, depth, floors, roof_style, wall_colour, door_side,
                  name="Building", location=(0, 0, 0), rotation=0.0,
                  floor_height=FLOOR_HEIGHT, door_offset=0.0, door_width=1.0, door_height=2.1,
                  door_colour="door", roof_colour=None, sign=True, shopfront=False,
                  front_ground_windows=True, lit_fraction=0.7, seed=0):
    """Build one building and return its root Empty.

    width, depth   footprint in metres (width runs along the street)
    floors         number of storeys
    roof_style     "flat", "gabled" or "clock_tower"
    wall_colour    palette name or "#RRGGBB"
    door_side      which wall has the door: "front", "back", "left" or "right"

    Keyword options
    location, rotation   where the front-centre goes, and a turn about Z in degrees
    door_offset          -1..1: slide the door along its wall (0 = centred)
    sign                 a BLANK panel above the door (there is no text option)
    shopfront            one large display window on the ground floor at the front
    front_ground_windows False leaves the front ground floor bare (for a garage door)
    lit_fraction         share of windows that light up at night; the rest stay dark
    seed                 changes which windows those are

    Windows on or off:   set_windows(building, on=True)
    """
    if roof_style not in ("flat", "gabled", "clock_tower"):
        raise ValueError(f'roof_style must be "flat", "gabled" or "clock_tower", not {roof_style!r}')
    if door_side not in ("front", "back", "left", "right"):
        raise ValueError(f'door_side must be "front", "back", "left" or "right", not {door_side!r}')

    rng = random.Random(seed)
    root = empty(name, location, math.radians(rotation))
    height = floors * floor_height
    walls, trim, door, roof = MeshBuilder(), MeshBuilder(), MeshBuilder(), MeshBuilder()
    glass_lit, glass_dark = MeshBuilder(), MeshBuilder()

    # --- shell ---------------------------------------------------------------
    walls.box((width, depth, height), (0, depth / 2, height / 2), bevel=0.06)
    plinth = MeshBuilder().box((width + 0.16, depth + 0.16, 0.35), (0, depth / 2, 0.175))

    # --- door ----------------------------------------------------------------
    door_wall = _Wall(door_side, width, depth)
    door_u = door_offset * (door_wall.length / 2 - door_width / 2 - 0.5)
    _framed_panel(trim, door, door_wall, door_u, door_height / 2 + 0.02, door_width, door_height)
    trim.box(door_wall.size(0.07, 0.07, 0.07), door_wall.point(door_u + door_width * 0.32, 1.0, 0.07))   # handle
    plinth.box(door_wall.size(door_width + 0.6, 0.5, 0.14), door_wall.point(door_u, 0.07, 0.25))        # step

    # --- windows -------------------------------------------------------------
    win_w, win_h = 1.0, 1.25
    for side in ("front", "left", "right", "back"):
        wall = _Wall(side, width, depth)
        columns = max(1, int((wall.length - 0.8) / 2.1))
        for floor in range(floors):
            ground_front = floor == 0 and side == "front"
            if ground_front and (shopfront or not front_ground_windows):
                continue
            z = floor * floor_height + 0.95 + win_h / 2
            for c in range(columns):
                u = (c + 0.5) / columns * wall.length - wall.length / 2
                if floor == 0 and side == door_side and abs(u - door_u) < door_width / 2 + win_w / 2 + 0.25:
                    continue                                    # the door is here
                pane = glass_lit if rng.random() < lit_fraction else glass_dark
                _framed_panel(trim, pane, wall, u, z, win_w, win_h)
                trim.box(wall.size(win_w + 0.3, 0.16, 0.06), wall.point(u, z - win_h / 2 - 0.12, 0.08))  # sill

    if shopfront:
        # One wide display window beside the door (or across the front if the door is elsewhere).
        front = _Wall("front", width, depth)
        if door_side == "front":
            left_room = (door_u - door_width / 2) - (-width / 2)
            right_room = width / 2 - (door_u + door_width / 2)
            if left_room >= right_room:
                lo, hi = -width / 2 + 0.5, door_u - door_width / 2 - 0.4
            else:
                lo, hi = door_u + door_width / 2 + 0.4, width / 2 - 0.5
        else:
            lo, hi = -width / 2 + 0.5, width / 2 - 0.5
        _framed_panel(trim, glass_lit, front, (lo + hi) / 2, 0.55 + 0.85, hi - lo, 1.7, bar=0.11)

    # --- blank sign above the door -------------------------------------------
    sign_builder = MeshBuilder()
    if sign:
        sign_w = min(max(door_width + 1.6, 2.4), door_wall.length - 0.6)
        sign_z = min(door_height + 0.55, height - 0.4)
        MeshBuilder().box(door_wall.size(sign_w + 0.14, 0.06, 0.64), door_wall.point(door_u, sign_z, 0.03)) \
            .to_object("sign_back", mat("sign_back"), root)
        sign_builder.box(door_wall.size(sign_w, 0.05, 0.5), door_wall.point(door_u, sign_z, 0.08))

    # --- roof ----------------------------------------------------------------
    if roof_style == "gabled":
        roof.gable(width + 0.5, depth + 0.5, depth * 0.36, (0, depth / 2, height))
        roof.box((0.6, 0.6, 1.3), (width * 0.28, depth * 0.68, height + depth * 0.2))          # chimney
        roof_material = mat(roof_colour or "roof_tile")
    else:
        roof.box((width + 0.3, depth + 0.3, 0.3), (0, depth / 2, height + 0.15), bevel=0.05)
        if roof_style == "flat":
            roof.box((1.2, 0.9, 0.5), (-width * 0.22, depth * 0.6, height + 0.55))             # rooftop vent
        roof_material = mat(roof_colour or "roof_flat")

    # --- turn the builders into objects ---------------------------------------
    walls.to_object("walls", mat(wall_colour), root)
    plinth.to_object("plinth", mat("plinth"), root)
    trim.to_object("trim", mat("trim"), root)
    door.to_object("door", mat(door_colour), root)
    roof.to_object("roof", roof_material, root)
    sign_builder.to_object("sign", mat("sign"), root)

    lit_material = glow_material(name + "_windows")
    glass_lit.to_object("windows_lit", lit_material, root)
    glass_dark.to_object("windows_dark", mat("glass", roughness=0.25), root)
    root["windows_material"] = lit_material.name                # how set_windows() finds it

    if roof_style == "clock_tower":
        _add_clock_tower(root, wall_colour, width, depth, height, roof_colour)
    return root


def set_windows(building, on=True, strength=5.0, frame=None):
    """Light or darken one building's windows (day versus night).

    Each building has its own window material, so this affects nothing else.
    Give `frame` to keyframe the switch, e.g. a light coming on mid-shot.
    """
    set_glow(bpy.data.materials[building["windows_material"]], on, strength, frame)


# --- clock tower ------------------------------------------------------------
def _add_clock_tower(root, wall_colour, width, depth, base_height, roof_colour):
    """A square tower rising from the middle of the roof, with a clock face
    and a pair of hands on each of its four sides."""
    side = min(width, depth) * 0.5
    shaft = 5.2
    cy = depth / 2
    top = base_height + shaft
    MeshBuilder().box((side, side, shaft), (0, cy, base_height + shaft / 2), bevel=0.06) \
        .to_object("tower", mat(wall_colour), root)
    MeshBuilder().box((side + 0.35, side + 0.35, 0.25), (0, cy, top + 0.125), bevel=0.04) \
        .pyramid(side + 0.2, side * 0.75, (0, cy, top + 0.25)) \
        .to_object("tower_roof", mat(roof_colour or "roof_tile"), root)

    radius = side * 0.36
    clock_z = top - side * 0.55
    face_material = glow_material(root.name + "_clock_face", base="clock_face", glow="#FFF2D0", roughness=0.6)
    root["clock_material"] = face_material.name
    faces, ticks = MeshBuilder(), MeshBuilder()
    for quarter in range(4):
        # Each clock is built facing -Y at the origin, then swung round the tower.
        holder = empty(f"clock_{quarter}", (0, cy, clock_z), quarter * math.pi / 2, parent=root)
        out = side / 2
        turn = quarter * math.pi / 2
        # Face disc and its 12 tick marks go into shared meshes (rotated into place).
        spot = Matrix.Rotation(turn, 3, "Z") @ Vector((0, -out - 0.03, 0)) + Vector((0, cy, clock_z))
        faces.cylinder(radius, 0.06, spot, axis="Y" if quarter % 2 == 0 else "X", segments=16)
        for hour in range(12):
            a = hour * math.pi / 6
            r = radius * 0.82
            local = Vector((math.sin(a) * r, -out - 0.07, math.cos(a) * r))
            big = hour % 3 == 0
            size = Vector((0.07, 0.03, 0.2 if big else 0.1))
            # Lay the tick along the radius by building it upright and rotating about Y.
            verts = bmesh.ops.create_cube(ticks.bm, size=1.0)["verts"]
            bmesh.ops.scale(ticks.bm, vec=size, verts=verts)
            bmesh.ops.rotate(ticks.bm, cent=(0, 0, 0), matrix=Matrix.Rotation(a, 3, "Y"), verts=verts)
            bmesh.ops.translate(ticks.bm, vec=local, verts=verts)
            bmesh.ops.rotate(ticks.bm, cent=(0, 0, 0), matrix=Matrix.Rotation(turn, 3, "Z"), verts=verts)
            bmesh.ops.translate(ticks.bm, vec=Vector((0, cy, clock_z)), verts=verts)
        # Hands: separate objects pivoting at the clock centre, so they can be animated.
        for kind, length, thick in (("hour", radius * 0.52, 0.11), ("minute", radius * 0.8, 0.075)):
            hand = MeshBuilder().box((thick, 0.04, length), (0, 0, length / 2 - 0.06)) \
                .to_object(f"{kind}_hand", mat("clock_hand"), holder, location=(0, -out - (0.1 if kind == "hour" else 0.15), 0))
            hand["hand"] = kind
    faces.to_object("clock_faces", face_material, root)
    ticks.to_object("clock_ticks", mat("clock_hand"), root)
    set_clock(root, 12, 0)


def set_clock(building, hours, minutes=0, frame=None):
    """Point the clock hands (on all four faces) at a time, e.g. set_clock(tower, 5, 40).

    With `frame`, the hands are keyframed. Hours may run past 12 or 24:
    set_clock(t, 0, 0, frame=1) then set_clock(t, 3, 0, frame=120) sweeps
    the minute hand round three full turns.
    """
    total_minutes = hours * 60 + minutes
    angles = {"minute": total_minutes / 60 * 2 * math.pi, "hour": total_minutes / 720 * 2 * math.pi}
    for obj in descendants(building):
        kind = obj.get("hand")
        if kind:
            obj.rotation_euler[1] = angles[kind]        # about Y = clockwise seen from the front
            if frame is not None:
                obj.keyframe_insert("rotation_euler", index=1, frame=frame)


# ---------------------------------------------------------------------------
# 4. specific buildings
# ---------------------------------------------------------------------------
def make_bakery(name="Bakery", location=(0, 0, 0), rotation=0.0):
    """Two-storey shop: display window, striped awning, blank sign, bread table outside."""
    width = 7.0
    b = make_building(width, 6.0, 2, "gabled", "#F0D9A8", "front", name=name, location=location,
                      rotation=rotation, door_offset=0.75, shopfront=True, door_colour="#7A4B3A", seed=11)
    # Awning: seven slanted stripes above the shopfront and door.
    stripes = [MeshBuilder(), MeshBuilder()]
    count, span = 7, width - 0.6
    for i in range(count):
        x = -span / 2 + (i + 0.5) * span / count
        stripes[i % 2].box((span / count, 1.25, 0.07), (x, -0.55, 2.62), tilt_x=math.radians(-18))
    stripes[0].to_object("awning_a", mat("awning_a"), b)
    stripes[1].to_object("awning_b", mat("awning_b"), b)
    # A table of bread outside the window.
    MeshBuilder().box((1.9, 0.75, 0.07), (-1.3, -0.9, 0.82)) \
        .box((0.08, 0.08, 0.8), (-2.15, -1.2, 0.4)).box((0.08, 0.08, 0.8), (-0.45, -1.2, 0.4)) \
        .box((0.08, 0.08, 0.8), (-2.15, -0.6, 0.4)).box((0.08, 0.08, 0.8), (-0.45, -0.6, 0.4)) \
        .to_object("bread_table", mat("wood"), b)
    for i, x in enumerate((-1.95, -1.3, -0.65)):
        make_loaf(location=(x, -0.9, 0.86), rotation=(-8, 12, 6)[i], parent=b)
    return b


def make_school(name="School", location=(0, 0, 0), rotation=0.0):
    """Wide two-storey block with double doors, steps and a flagpole (blank flag)."""
    b = make_building(17.0, 8.0, 2, "flat", "#B86A52", "front", name=name, location=location,
                      rotation=rotation, door_width=2.2, door_height=2.4, door_colour="#39506B", seed=23)
    MeshBuilder().box((4.2, 1.2, 0.16), (0, -0.7, 0.08)).box((3.6, 0.6, 0.16), (0, -0.4, 0.24)) \
        .to_object("steps", mat("pavement"), b)
    # Flagpole on the lawn in front, with a blank flag.
    px, py = 5.6, -2.6
    MeshBuilder().cylinder(0.07, 7.0, (px, py, 3.5), axis="Z", segments=8).box((0.5, 0.5, 0.2), (px, py, 0.1)) \
        .to_object("flagpole", mat("metal"), b)
    MeshBuilder().box((1.5, 0.03, 0.9), (px + 0.82, py, 6.4)).to_object("flag", mat("flag"), b)
    return b


def make_bus_depot(name="BusDepot", location=(0, 0, 0), rotation=0.0):
    """One tall storey with a wide garage door and a side door for people."""
    width, floor_height = 12.0, 4.6
    b = make_building(width, 9.0, 1, "flat", "#8E9AA8", "front", name=name, location=location,
                      rotation=rotation, floor_height=floor_height, door_offset=0.92,
                      front_ground_windows=False, sign=False, seed=31)
    front = _Wall("front", width, 9.0)
    frames, shutter, slats = MeshBuilder(), MeshBuilder(), MeshBuilder()
    gw, gh, gu = 5.4, 3.5, -1.6
    _framed_panel(frames, shutter, front, gu, gh / 2 + 0.02, gw, gh, bar=0.16, proud=0.12)
    for i in range(1, 7):                                       # roller-door ribs
        slats.box((gw, 0.04, 0.05), front.point(gu, i * gh / 7, 0.05))
    frames.to_object("garage_frame", mat("trim"), b)
    shutter.to_object("garage_door", mat("#C9CDD4"), b)
    slats.to_object("garage_slats", mat("metal"), b)
    # Blank sign across the top of the garage door.
    MeshBuilder().box((gw + 0.14, 0.06, 0.74), front.point(gu, gh + 0.62, 0.03)).to_object("sign_back", mat("sign_back"), b)
    MeshBuilder().box((gw, 0.05, 0.6), front.point(gu, gh + 0.62, 0.08)).to_object("sign", mat("sign"), b)
    return b


def make_clock_tower(name="ClockTower", location=(0, 0, 0), rotation=0.0):
    """Stone hall with a clock tower. Move the hands with set_clock()."""
    return make_building(6.5, 6.5, 2, "clock_tower", "#C9C2B4", "front", name=name, location=location,
                         rotation=rotation, door_width=1.4, door_height=2.4, roof_colour="#4F6B8A", seed=41)


# ---------------------------------------------------------------------------
# 5. props
# ---------------------------------------------------------------------------
def make_loaf(location=(0, 0, 0), rotation=0.0, parent=None, scale=1.0):
    """A loaf of bread: a rounded box with three pale score marks."""
    root = empty("Loaf", location, math.radians(rotation), parent)
    root.scale = (scale,) * 3
    MeshBuilder().box((0.5, 0.24, 0.18), (0, 0, 0.09), bevel=0.06).to_object("crust", mat("bread", 0.7), root)
    scores = MeshBuilder()
    for x in (-0.13, 0.0, 0.13):
        scores.box((0.035, 0.17, 0.02), (x, 0, 0.178), rotate_z=math.radians(24))
    scores.to_object("scores", mat("bread_cut", 0.7), root)
    return root


LAMPS = []          # (bulb material, light object) for every streetlamp, used by the lighting presets


def make_streetlamp(location=(0, 0, 0), rotation=0.0, height=4.6):
    """Pole with an arm reaching out along its local -Y, a glowing head and a real light."""
    root = empty("Streetlamp", location, math.radians(rotation))
    MeshBuilder().box((0.14, 0.14, height), (0, 0, height / 2)).box((0.3, 0.3, 0.25), (0, 0, 0.125)) \
        .box((0.1, 1.1, 0.1), (0, -0.5, height)).box((0.34, 0.5, 0.1), (0, -1.0, height - 0.02)) \
        .to_object("pole", mat("dark_metal"), root)
    bulb = glow_material("lamp_bulb", base="#F4F0E4", glow=LAMP_GLOW, roughness=0.5)
    MeshBuilder().box((0.26, 0.42, 0.06), (0, -1.0, height - 0.1)).to_object("bulb", bulb, root)
    data = bpy.data.lights.new("lamp_light", "POINT")
    data.color = srgb(LAMP_GLOW)[:3]
    data.shadow_soft_size = 0.25
    data.energy = 0.0
    light = bpy.data.objects.new("lamp_light", data)
    bpy.context.scene.collection.objects.link(light)
    light.parent = root
    light.location = (0, -1.0, height - 0.35)
    LAMPS.append((bulb, light))
    return root


def make_fence(length, location=(0, 0, 0), rotation=0.0, height=1.0):
    """Picket-style fence running along its local X."""
    root = empty("Fence", location, math.radians(rotation))
    b = MeshBuilder()
    posts = max(2, round(length / 1.2) + 1)
    for i in range(posts):
        b.box((0.12, 0.12, height), (-length / 2 + i * length / (posts - 1), 0, height / 2))
    for z in (height * 0.38, height * 0.78):
        b.box((length, 0.05, 0.1), (0, 0, z))
    b.to_object("fence", mat("#EDE7DA"), root)
    return root


def make_tree(location=(0, 0, 0), size=1.0, seed=0):
    """Box trunk with a canopy of three stacked, slightly turned cubes."""
    rng = random.Random(seed)
    root = empty("Tree", location, rng.uniform(0, math.pi / 2))
    root.scale = (size,) * 3
    MeshBuilder().box((0.4, 0.4, 2.0), (0, 0, 1.0)).to_object("trunk", mat("trunk"), root)
    MeshBuilder().box((2.3, 2.3, 1.7), (0, 0, 2.7), bevel=0.12) \
        .box((1.6, 1.6, 1.2), (0.25, -0.15, 3.85), bevel=0.1, rotate_z=0.5).to_object("canopy", mat("leaf"), root)
    MeshBuilder().box((1.2, 1.2, 0.9), (-0.55, 0.45, 3.3), bevel=0.08, rotate_z=0.3) \
        .to_object("canopy_light", mat("leaf_light"), root)
    return root


def make_road(length, width=7.0, centre=(0, 0, 0), pavement_width=2.6):
    """A straight road along Y with a dashed centre line, edge lines, and a
    raised pavement with a kerb down each side. Returns the root Empty."""
    root = empty("Road", centre)
    MeshBuilder().box((width, length, 0.1), (0, 0, -0.05)).to_object("tarmac", mat("road", 0.95), root)
    marks = MeshBuilder()
    dash, gap = 2.0, 2.0
    y = -length / 2 + 1.0
    while y + dash < length / 2:
        marks.box((0.16, dash, 0.012), (0, y + dash / 2, 0.006))
        y += dash + gap
    for x in (-width / 2 + 0.3, width / 2 - 0.3):
        marks.box((0.12, length, 0.012), (x, 0, 0.006))
    marks.to_object("lane_markings", mat("marking", 0.9), root)
    slabs, kerbs = MeshBuilder(), MeshBuilder()
    for sx in (-1, 1):
        x = sx * (width / 2 + pavement_width / 2)
        slabs.box((pavement_width, length, 0.15), (x, 0, 0.075))
        kerbs.box((0.18, length, 0.17), (sx * (width / 2 + 0.09), 0, 0.085))
    slabs.to_object("pavement", mat("pavement", 0.95), root)
    kerbs.to_object("kerb", mat("kerb", 0.95), root)
    return root


# --- bus --------------------------------------------------------------------
WHEEL_RADIUS = 0.5


def make_bus(name="Bus", location=(0, 0, 0), rotation=0.0, colour="bus"):
    """A blocky single-decker. It faces along its local +Y.

    The four wheels are separate objects so they can spin; drive_bus() moves
    it along a curve and spins them the right amount. Lights: set_bus_lights().
    """
    root = empty(name, location, math.radians(rotation))
    w, length, body_h, floor = 2.5, 7.6, 2.5, 0.55
    MeshBuilder().box((w, length, body_h), (0, 0, floor + body_h / 2), bevel=0.14).to_object("body", mat(colour, 0.6), root)
    MeshBuilder().box((w - 0.25, length - 0.5, 0.14), (0, 0, floor + body_h + 0.05), bevel=0.05) \
        .to_object("roof", mat("bus_roof"), root)
    MeshBuilder().box((w + 0.04, length - 0.3, 0.3), (0, 0, floor + 0.15)).box((w - 0.2, 0.2, 0.3), (0, length / 2, floor + 0.18)) \
        .to_object("skirt", mat("dark_metal"), root)

    glass = glow_material(name + "_windows", glow="#FFE9B8")
    panes = MeshBuilder()
    for sx in (-1, 1):
        for i in range(5):                                      # side windows
            panes.box((0.03, 1.05, 0.95), (sx * (w / 2 + 0.005), -length / 2 + 1.0 + i * 1.32, floor + 1.75))
    panes.box((w - 0.5, 0.03, 1.15), (0, length / 2 + 0.005, floor + 1.65))      # windscreen
    panes.box((w - 0.7, 0.03, 0.8), (0, -length / 2 - 0.005, floor + 1.8))       # rear window
    panes.to_object("windows", glass, root)
    root["windows_material"] = glass.name

    # Blank destination board above the windscreen.
    MeshBuilder().box((1.7, 0.04, 0.3), (0, length / 2 + 0.01, floor + body_h - 0.2)).to_object("destination_board", mat("sign"), root)

    lights = glow_material(name + "_headlights", base="#F4F0E4", glow="#FFF3D6", roughness=0.4)
    MeshBuilder().box((0.36, 0.05, 0.2), (-0.85, length / 2 + 0.01, floor + 0.55)) \
        .box((0.36, 0.05, 0.2), (0.85, length / 2 + 0.01, floor + 0.55)).to_object("headlights", lights, root)
    root["headlights_material"] = lights.name

    for i, (sx, y) in enumerate(((-1, 2.3), (1, 2.3), (-1, -2.3), (1, -2.3))):
        wheel = MeshBuilder().cylinder(WHEEL_RADIUS, 0.36, (0, 0, 0), axis="X", segments=12) \
            .to_object(f"wheel_{i}", mat("tyre", 0.9), root, location=(sx * (w / 2 - 0.12), y, WHEEL_RADIUS))
        MeshBuilder().cylinder(0.24, 0.38, (0, 0, 0), axis="X", segments=8).box((0.39, 0.1, 0.34), (0, 0, 0)) \
            .to_object("hub", mat("hub"), wheel)                 # the bar across the hub makes the spin visible
        wheel["wheel"] = True
    return root


def set_bus_lights(bus, on=True, frame=None):
    """Interior lights and headlights on or off."""
    set_glow(bpy.data.materials[bus["windows_material"]], on, 0.45, frame)
    set_glow(bpy.data.materials[bus["headlights_material"]], on, 6.0, frame)


def make_path(points, name="BusPath"):
    """A smooth curve through `points` [(x, y), ...] on the ground, for drive_bus()."""
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 16
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, (x, y) in zip(spline.bezier_points, points):
        point.co = (x, y, 0)
        point.handle_left_type = point.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def drive_bus(bus, path, start_frame, end_frame, start=0.0, end=1.0):
    """Drive the bus along a curve between two frames, wheels turning.

    start, end   how far along the path it begins and finishes (0..1), so a
                 bus can pull away, stop half way, and carry on later.
    The bus follows the curve's direction and travels at constant speed.
    To leave it parked somewhere on the path, call this with start == end.
    """
    bus.location = (0, 0, 0)                        # the constraint takes over its position
    bus.rotation_euler = (0, 0, 0)
    follow = bus.constraints.get("Follow Path") or bus.constraints.new("FOLLOW_PATH")
    follow.target = path
    follow.use_fixed_location = True                # position comes from offset_factor (0..1)
    follow.use_curve_follow = True
    follow.forward_axis, follow.up_axis = "FORWARD_Y", "UP_Z"

    length = path.data.splines[0].calc_length()
    spin = -(end - start) * length / WHEEL_RADIUS   # rolling without slipping; forward is negative about X
    for frame, factor, angle in ((start_frame, start, 0.0), (end_frame, end, spin)):
        follow.offset_factor = factor
        _key_linear(follow, "offset_factor", frame)
        for obj in descendants(bus):
            if obj.get("wheel"):
                obj.rotation_euler[0] = obj.get("spin_base", 0.0) + angle
                _key_linear(obj, "rotation_euler", frame, index=0)
    for obj in descendants(bus):                    # so a later drive carries on from this wheel angle
        if obj.get("wheel"):
            obj["spin_base"] = obj.get("spin_base", 0.0) + spin


def _fcurves(id_block):
    """The animation curves of an object, across Blender versions."""
    data = id_block.animation_data
    action = data.action if data else None
    if action is None:
        return []
    if hasattr(action, "fcurves"):                  # Blender 4.x
        return action.fcurves
    for layer in action.layers:                     # Blender 5: layered actions
        for strip in layer.strips:
            bag = strip.channelbag(data.action_slot)
            if bag:
                return bag.fcurves
    return []


def _key_linear(target, prop, frame, index=-1):
    """Insert a keyframe that interpolates in a straight line (constant speed).
    Keys inserted from a script are always Bezier, so the type is set afterwards."""
    target.keyframe_insert(prop, frame=frame, index=index)
    path = target.path_from_id(prop)
    for curve in _fcurves(target.id_data):
        if curve.data_path == path and (index < 0 or curve.array_index == index):
            for point in curve.keyframe_points:
                if abs(point.co[0] - frame) < 0.5:
                    point.interpolation = "LINEAR"


# ---------------------------------------------------------------------------
# 6. the street
# ---------------------------------------------------------------------------
ROAD_WIDTH = 7.0
PAVEMENT = 2.6
STREET_LENGTH = 46.0


def street_layout():
    """One street running away from the camera along +Y.

        left side              right side
        Bakery                 House (with fence and tree)
        Clock tower            Bus depot (bus on the road outside)
                    School across the far end

    Five buildings. Returns a dict of the named things you will want to
    animate or light: buildings by name, "bus", "bus_path", "all_buildings".
    """
    front = ROAD_WIDTH / 2 + PAVEMENT              # building fronts line up with the back of the pavement
    road = make_road(STREET_LENGTH, ROAD_WIDTH, centre=(0, STREET_LENGTH / 2 - 6, 0), pavement_width=PAVEMENT)
    MeshBuilder().box((160, 160, 0.1), (0, 30, -0.1)).to_object("grass", mat("grass", 0.95))

    # Left-hand buildings face +X (rotation 90); right-hand ones face -X (rotation -90).
    town = {
        "bakery": make_bakery(location=(-front, 5.0, 0), rotation=90),
        "clock_tower": make_clock_tower(location=(-front, 21.0, 0), rotation=90),
        "house": make_building(6.0, 6.0, 2, "gabled", "#A9C4D8", "front", name="House",
                               location=(front, 5.0, 0), rotation=-90, door_offset=-0.6, sign=False, seed=5),
        "bus_depot": make_bus_depot(location=(front, 22.0, 0), rotation=-90),
        "school": make_school(location=(0, STREET_LENGTH - 6 + 4.5, 0), rotation=0),
    }
    town["all_buildings"] = [town[k] for k in ("bakery", "clock_tower", "house", "bus_depot", "school")]
    town["road"] = road

    # Streetlamps down both pavements, arms over the road.
    kerb_x = ROAD_WIDTH / 2 + 0.5
    for y, side in ((0.5, -1), (11.5, 1), (15.0, -1), (30.0, 1), (31.5, -1)):
        make_streetlamp(location=(side * kerb_x, y, 0.15), rotation=90 if side < 0 else -90)

    # Greenery and fences.
    for i, (x, y, size) in enumerate(((-front - 2.5, 12.6, 1.05), (front + 2.5, 12.8, 1.2), (-front - 3.0, 31.0, 1.25),
                                      (front + 4.0, 33.5, 1.1), (-13.5, 36.5, 1.3), (13.5, 37.0, 1.15))):
        make_tree(location=(x, y, 0), size=size, seed=i)
    make_fence(5.0, location=(front + 0.3, 11.2, 0), rotation=90)
    make_fence(6.0, location=(-front - 0.3, 13.2, 0), rotation=90)
    make_fence(7.0, location=(-9.5, STREET_LENGTH - 6 + 1.2, 0))
    make_fence(7.0, location=(9.5, STREET_LENGTH - 6 + 1.2, 0))

    # The bus, on a path that leaves the depot, joins the near lane and drives towards the camera.
    town["bus_path"] = make_path([(front - 1.0, 23.6), (2.6, 21.0), (1.75, 14.0), (1.75, -4.0)])
    town["bus"] = make_bus()
    drive_bus(town["bus"], town["bus_path"], 1, 1, start=0.42, end=0.42)        # parked part-way along
    return town


# ---------------------------------------------------------------------------
# 7. lighting presets
# ---------------------------------------------------------------------------
# sun            (energy, colour, elevation in degrees above the horizon, compass direction it shines FROM)
# sky            (horizon colour, zenith colour, strength)
# windows        "all", "none", or a list of building keys from street_layout()
# fog            density of the volumetric haze (0 = none), and fog_colour its tint
LIGHTING = {
    "day": dict(sun=(3.6, "#FFF6E8", 52, 215), sky=("#CFE6F7", "#6FA9E6", 1.0),
                windows="none", window_strength=0.0, lamps=0.0, fog=0.0, fog_colour="#FFFFFF",
                moon=False, exposure=0.0),
    "dawn": dict(sun=(2.4, "#FFB07A", 11, 60), sky=("#F7B48C", "#56699F", 0.8),
                 windows=["bakery"], window_strength=1.6, lamps=40.0, fog=0.006, fog_colour="#FFD9C2",
                 moon=False, exposure=0.0),
    "midnight": dict(sun=(1.1, "#7C9DFF", 50, 150), sky=("#1D2C55", "#080D20", 1.0),
                     windows="all", window_strength=1.8, lamps=160.0, fog=0.008, fog_colour="#9FB4E8",
                     moon=True, exposure=0.5),
}

_rig = {}


def _lighting_rig():
    """Create the sun, sky, fog and moon once; presets only change their values."""
    if _rig:
        return _rig
    scene = bpy.context.scene
    sun_data = bpy.data.lights.new("Sun", "SUN")
    sun_data.angle = math.radians(6)
    sun = bpy.data.objects.new("Sun", sun_data)
    scene.collection.objects.link(sun)

    # Sky: a vertical gradient from horizon to zenith, plus an optional haze.
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    background = next(n for n in nodes if n.type == "BACKGROUND")
    output = next(n for n in nodes if n.type == "OUTPUT_WORLD")
    coords = nodes.new("ShaderNodeTexCoord")
    split = nodes.new("ShaderNodeSeparateXYZ")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[1].position = 0.45
    links.new(coords.outputs["Generated"], split.inputs["Vector"])      # for a world this is the view direction
    links.new(split.outputs["Z"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], background.inputs["Color"])
    scene.world = world

    # Haze: a big box of thin scattering volume over the street. (A volume on
    # the WORLD would be infinitely deep: it blacks out the sky and swallows
    # the sun, so the haze is an object with edges instead.)
    haze_material = bpy.data.materials.new("haze")
    haze_material.use_nodes = True
    haze_nodes = haze_material.node_tree.nodes
    haze_nodes.remove(_principled(haze_material))
    fog = haze_nodes.new("ShaderNodeVolumeScatter")
    haze_out = next(n for n in haze_nodes if n.type == "OUTPUT_MATERIAL")
    haze_material.node_tree.links.new(fog.outputs["Volume"], haze_out.inputs["Volume"])
    haze = MeshBuilder().box((90, 110, 26), (0, 30, 13)).to_object("Haze", haze_material)
    haze.display_type = "WIRE"                          # don't block the viewport

    moon = MeshBuilder().box((5, 5, 5), (0, 0, 0), bevel=0.6).to_object("Moon", glow_material("moon", base="moon", glow="#DDE6FF"))
    moon.location = (-34, 120, 62)
    moon.rotation_euler = (0.5, 0.4, 0.6)
    set_glow(bpy.data.materials[moon.active_material.name], True, 1.4)

    _rig.update(sun=sun, ramp=ramp, background=background, fog=fog, haze=haze, moon=moon)
    return _rig


def set_lighting(preset, town):
    """Relight the whole scene: "day", "dawn" or "midnight".

    Changes the sun (or moon) light, the sky, the haze, which buildings have
    lit windows, the streetlamps and the bus lights. Nothing is rebuilt, so
    the same shot can be rendered under each preset.
    """
    if preset not in LIGHTING:
        raise ValueError(f"unknown lighting preset {preset!r}; choose from {list(LIGHTING)}")
    p = LIGHTING[preset]
    rig = _lighting_rig()
    scene = bpy.context.scene

    energy, colour, elevation, compass = p["sun"]
    rig["sun"].data.energy = energy
    rig["sun"].data.color = srgb(colour)[:3]
    # A sun lamp shines down its own -Z. Tip it over by (90 - elevation), then
    # turn it so the light arrives from the given compass bearing (0 = from +Y).
    rig["sun"].rotation_euler = (math.radians(90 - elevation), 0, math.radians(180 - compass))

    horizon, zenith, strength = p["sky"]
    rig["ramp"].color_ramp.elements[0].color = srgb(horizon)
    rig["ramp"].color_ramp.elements[1].color = srgb(zenith)
    rig["background"].inputs["Strength"].default_value = strength

    # Haze: hidden entirely when not wanted, because volumetrics cost render time.
    rig["haze"].hide_render = rig["haze"].hide_viewport = p["fog"] <= 0
    rig["fog"].inputs["Density"].default_value = p["fog"]
    rig["fog"].inputs["Color"].default_value = srgb(p["fog_colour"])

    lit = p["windows"]
    for key in ("bakery", "clock_tower", "house", "bus_depot", "school"):
        set_windows(town[key], on=lit == "all" or (isinstance(lit, list) and key in lit), strength=p["window_strength"])
    clock = town["clock_tower"].get("clock_material")
    if clock:
        set_glow(bpy.data.materials[clock], p["lamps"] > 0, 0.9)        # the clock face is lit whenever the lamps are
    for bulb, light in LAMPS:
        set_glow(bulb, p["lamps"] > 0, 4.0)
        light.data.energy = p["lamps"]
    set_bus_lights(town["bus"], on=preset == "midnight")

    rig["moon"].hide_render = rig["moon"].hide_viewport = not p["moon"]
    scene.view_settings.exposure = p["exposure"]


# ---------------------------------------------------------------------------
# 8. test render
# ---------------------------------------------------------------------------
def setup_render(engine, samples, scale):
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 1080, 1920
    scene.render.resolution_percentage = scale
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"       # keep the flat cartoon colours as authored

    # Eevee is "BLENDER_EEVEE_NEXT" in 4.2-4.x and "BLENDER_EEVEE" again from 5.0.
    available = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    wanted = {"eevee": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"], "workbench": ["BLENDER_WORKBENCH"],
              "cycles": ["CYCLES"]}[engine]
    scene.render.engine = next(e for e in wanted if e in available)
    if engine == "eevee":
        scene.eevee.taa_render_samples = samples
        # Coarse, short-range volumetrics: enough for a soft haze, cheap to render.
        scene.eevee.volumetric_tile_size = "16"
        scene.eevee.volumetric_samples = 32
        scene.eevee.volumetric_end = 90.0
    elif engine == "cycles":
        scene.cycles.samples = samples
    return scene


def establishing_camera():
    """Low on the near pavement, looking up the street to the school, clock tower in frame."""
    scene = bpy.context.scene
    data = bpy.data.cameras.new("EstablishingCamera")
    data.lens = 24
    data.clip_end = 400
    camera = bpy.data.objects.new("EstablishingCamera", data)
    scene.collection.objects.link(camera)
    camera.location = (1.9, -9.5, 2.3)
    aim = Vector((-1.4, 21.0, 5.9)) - camera.location
    camera.rotation_euler = aim.to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    return camera


def triangle_count():
    return sum(len(p.vertices) - 2 for o in bpy.data.objects if o.type == "MESH" for p in o.data.polygons)


def parse_args():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="blender -b -P buildings.py --")
    ap.add_argument("--engine", choices=["eevee", "workbench", "cycles"], default="eevee")
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--scale", type=int, default=100, help="percent of 1080x1920 (50 = 540x960)")
    ap.add_argument("--preset", choices=list(LIGHTING), action="append",
                    help="lighting to render; repeat for several (default: midnight then dawn)")
    ap.add_argument("--out", default=None, help="output folder (default: town_out next to this script)")
    ap.add_argument("--no-render", action="store_true", help="build and save the .blend only")
    return ap.parse_args(argv)


# The clock time shown in each test shot.
SHOT_TIME = {"midnight": (12, 0), "dawn": (5, 40), "day": (10, 10)}


def main():
    args = parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(here, "town_out")
    os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = setup_render(args.engine, args.samples, args.scale)
    town = street_layout()
    establishing_camera()
    print(f"town built: {sum(1 for o in bpy.data.objects if o.type == 'MESH')} mesh objects, "
          f"{triangle_count()} triangles, {len(bpy.data.materials)} materials")

    presets = args.preset or ["midnight", "dawn"]
    set_lighting(presets[0], town)
    set_clock(town["clock_tower"], *SHOT_TIME[presets[0]])
    blend_path = os.path.join(out_dir, "town.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print("saved", blend_path)
    if args.no_render:
        return

    for preset in presets:
        set_lighting(preset, town)
        set_clock(town["clock_tower"], *SHOT_TIME[preset])
        scene.render.filepath = os.path.join(out_dir, f"establishing_{preset}.png")
        bpy.ops.render.render(write_still=True)
        print("rendered", scene.render.filepath)


if __name__ == "__main__":
    main()
