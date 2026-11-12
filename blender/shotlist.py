"""Shot-list format: load and validate an episode's JSON.

This file is plain Python (no Blender needed), so you can check a shot list
from an ordinary terminal:

    python shotlist.py episodes/episode1.json

The runner, shots.py, uses the same code before it renders anything.

Format
------
{
  "title": "Episode 1",
  "voice": "en-GB-RyanNeural",                 optional: any edge-tts voice
  "music": {"path": "music/bed.mp3", "volume": 0.12},   optional: ducks under the narration
  "shots": [
    {
      "name": "Clock strikes",                 optional label
      "narration": "At midnight, the street was quiet.",   optional: spoken; sets the shot's length
      "sfx": ["clock_chime", {"tag": "whoosh", "at": 1.2}], optional sound effects
      "duration": 3.5,                         seconds (a minimum, if there is narration), or "auto" = length of "audio"
      "audio": "audio/shot1.mp3",              only read when duration is "auto"
      "lighting": "midnight",                  day / dawn / midnight
      "clock": "12:00",                        optional: time on the clock tower
      "camera": {
        "move": "push_in",                     static / push_in / pull_back / orbit / follow / handheld_shake
        "target": "clock",                     a name (see TARGETS) or [x, y, z]
        "position": [1.9, -9.5, 2.3],          optional: where the camera starts
        "amount": 0.35,                        optional: push_in / pull_back distance as a share of the way to the target
        "degrees": 40,                         optional: orbit sweep
        "lens": 28                             optional: focal length in mm
      },
      "character": {                           leave out to keep him off screen
        "pose": "idle",
        "expression": "surprised",             a name (see EXPRESSIONS) or {"eyes": ..., "mouth": ...}
        "position": [4.8, 2.0],                where he stands (ignored if there is a path)
        "heading": 0,                          degrees: 0 faces -Y, 90 faces +X
        "path": {"points": [[4.8, -4], [4.8, 6]], "speed": 1.4},   he walks it, then takes the pose
        "look_at": "clock"                     optional: a target name or [x, y, z]
      },
      "props": {"show": ["bus"], "hide": ["moon"]},   stays in force for later shots
      "vehicle": {"path": [[5.1, 23.6], [1.75, 14], [1.75, -4]], "speed": 6.0},
      "text": "Somewhere, a clock struck twelve."     optional on-screen caption
    }
  ]
}

Coordinates are metres. The street runs along +Y from y = -6 (near the
camera) to y = 40 (the school). The road is x = -3.5 .. 3.5; pavements run
out to x = +-6.1, where the building fronts are.
"""

import difflib
import json
import os
import sys

MOVES = ["static", "push_in", "pull_back", "orbit", "follow", "handheld_shake"]
LIGHTING = ["day", "dawn", "midnight"]
POSES = ["idle", "talking", "point", "shrug", "panic", "sleepy", "sit_driving"]
EYES = ["open", "wide", "half_closed", "squint"]
MOUTHS = ["neutral", "open", "small_o", "smile", "flat"]

# Named expressions -> (eyes, mouth).
EXPRESSIONS = {
    "neutral": ("open", "neutral"),
    "surprised": ("wide", "small_o"),
    "shocked": ("wide", "open"),
    "worried": ("wide", "flat"),
    "happy": ("squint", "smile"),
    "pleased": ("open", "smile"),
    "talking": ("open", "open"),
    "sleepy": ("half_closed", "flat"),
    "deadpan": ("half_closed", "neutral"),
}

SFX = ["clock_chime", "bus_engine", "whoosh"]

BUILDINGS = ["bakery", "clock_tower", "house", "bus_depot", "school"]
# Things a camera or a look can aim at.
TARGETS = BUILDINGS + ["clock", "bus", "character", "street"]
# Things "props" can show or hide.
PROPS = BUILDINGS + ["bus", "streetlamps", "trees", "fences", "loaves", "moon"]

MOVING_TARGETS = ["character", "bus"]         # the only things "follow" can follow


class ShotListError(ValueError):
    """Raised with every problem found, each prefixed by where it is."""

    def __init__(self, errors, source="shot list"):
        self.errors = list(errors)
        n = len(self.errors)
        super().__init__("\n".join([f"{source}: {n} problem{'s' if n != 1 else ''} found"]
                                   + [f"  - {e}" for e in self.errors]))


def _kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true/false"
    if isinstance(v, (int, float)):
        return "a number"
    if isinstance(v, str):
        return "text"
    return "a list" if isinstance(v, list) else "an object"


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _hint(word, options):
    close = difflib.get_close_matches(str(word), options, n=1, cutoff=0.6)
    return f' Did you mean "{close[0]}"?' if close else ""


class _Check:
    def __init__(self):
        self.errors = []

    def err(self, path, msg):
        self.errors.append(f"{path}: {msg}")

    def keys(self, path, obj, allowed):
        for k in obj:
            if k not in allowed:
                self.err(f"{path}.{k}", f"unknown field.{_hint(k, allowed)} Allowed: {', '.join(sorted(allowed))}.")

    def choice(self, path, v, options):
        if not isinstance(v, str) or v not in options:
            shown = f'"{v}"' if isinstance(v, str) else _kind(v)
            self.err(path, f"{shown} is not valid.{_hint(v, options)} Choose one of: {', '.join(options)}.")
            return None
        return v

    def number(self, path, v, lo=None, hi=None):
        if not _num(v):
            self.err(path, f"must be a number, got {_kind(v)}.")
            return None
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            self.err(path, f"is {v}; it must be between {lo} and {hi}.")
            return None
        return v

    def point(self, path, v, size):
        """[x, y] or [x, y, z]."""
        names = "[x, y]" if size == 2 else "[x, y, z]"
        if not isinstance(v, list) or len(v) != size or not all(_num(c) for c in v):
            self.err(path, f"must be {names} with {size} numbers.")
            return None
        if any(abs(c) > 500 for c in v):
            self.err(path, f"{v} is more than 500 m from the street; check the numbers.")
            return None
        return tuple(float(c) for c in v)

    def target(self, path, v):
        """A named target or a 3D point."""
        if isinstance(v, str):
            return self.choice(path, v, TARGETS)
        if isinstance(v, list):
            return self.point(path, v, 3)
        self.err(path, f"must be a name ({', '.join(TARGETS)}) or [x, y, z]; got {_kind(v)}.")
        return None

    def path_points(self, path, v):
        if not isinstance(v, list) or len(v) < 2:
            self.err(path, "must be a list of at least two [x, y] points.")
            return None
        pts = [self.point(f"{path}[{i}]", p, 2) for i, p in enumerate(v)]
        if None in pts:
            return None
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            if a == b:
                self.err(f"{path}[{i + 1}]", "is the same as the point before it.")
                return None
        return pts


_SHOT = {"name", "duration", "audio", "narration", "sfx", "lighting", "clock", "camera", "character",
         "props", "vehicle", "text"}
_CAMERA = {"move", "target", "position", "amount", "degrees", "lens"}
_CHARACTER = {"pose", "expression", "position", "heading", "path", "look_at"}


def validate(data, base_dir=".", source="shot list"):
    """Check a parsed shot list; return a normalised copy with defaults filled in.

    Raises ShotListError listing every problem.
    """
    ck = _Check()
    if not isinstance(data, dict):
        raise ShotListError([f"the top level must be an object {{...}}, got {_kind(data)}."], source)
    ck.keys("(top level)", data, {"title", "voice", "rate", "music", "shots"})
    out = {"title": data.get("title") if isinstance(data.get("title"), str) else "",
           "voice": "en-GB-RyanNeural", "rate": "+0%", "music": None, "shots": []}
    if "voice" in data:
        voice = data["voice"]
        if isinstance(voice, str) and voice.count("-") >= 2 and voice.endswith("Neural"):
            out["voice"] = voice
        else:
            ck.err("voice", 'must be an edge-tts voice name such as "en-GB-RyanNeural" or "en-GB-SoniaNeural".')
    if "rate" in data:
        rate = data["rate"]
        if isinstance(rate, str) and len(rate) >= 3 and rate[0] in "+-" and rate[-1] == "%" and rate[1:-1].isdigit():
            out["rate"] = rate
        else:
            ck.err("rate", 'must be a signed percentage such as "+10%" or "-5%".')
    music = data.get("music")
    if music is not None:
        if isinstance(music, str):
            music = {"path": music}
        if not isinstance(music, dict) or not isinstance(music.get("path"), str):
            ck.err("music", 'must be a file path or {"path": "...", "volume": 0.12}.')
        else:
            ck.keys("music", music, {"path", "volume"})
            full = music["path"] if os.path.isabs(music["path"]) else os.path.join(base_dir, music["path"])
            volume = ck.number("music.volume", music.get("volume", 0.12), 0, 1)
            if not os.path.isfile(full):
                ck.err("music.path", f'file not found: "{full}". Paths are relative to the JSON file.')
            elif volume is not None:
                out["music"] = {"path": full, "volume": volume}

    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ShotListError(ck.errors + ['shots: is required: a list with at least one shot.'], source)

    for i, shot in enumerate(shots):
        p = f"shots[{i}]"
        if not isinstance(shot, dict):
            ck.err(p, f"must be an object {{...}}, got {_kind(shot)}.")
            continue
        ck.keys(p, shot, _SHOT)
        s = {"name": shot.get("name") if isinstance(shot.get("name"), str) else f"shot {i + 1}",
             "duration": None, "audio": None, "narration": None, "sfx": [], "lighting": "day", "clock": None,
             "camera": {"move": "static", "target": "street", "position": None, "amount": 0.35,
                        "degrees": 40.0, "lens": 28.0},
             "character": None, "show": [], "hide": [], "vehicle": None, "text": None}

        # narration: spoken by the voice; sets the shot's length
        if shot.get("narration") is not None:
            text = shot["narration"]
            if not isinstance(text, str) or not any(ch.isalnum() for ch in text):
                ck.err(f"{p}.narration", "must be text with at least one speakable word, or left out.")
            elif len(text) > 400:
                ck.err(f"{p}.narration", f"is {len(text)} characters; the limit is 400. Split the shot.")
            else:
                s["narration"] = text.strip()

        # sound effects: "tag" or {"tag": ..., "at": seconds into the shot, "volume": 0..1}
        sfx = shot.get("sfx", [])
        if not isinstance(sfx, list):
            ck.err(f"{p}.sfx", f"must be a list, got {_kind(sfx)}.")
        else:
            for j, item in enumerate(sfx):
                q = f"{p}.sfx[{j}]"
                if isinstance(item, str):
                    item = {"tag": item}
                if not isinstance(item, dict) or "tag" not in item:
                    ck.err(q, f'must be a tag ({", ".join(SFX)}) or {{"tag": ..., "at": seconds}}.')
                    continue
                ck.keys(q, item, {"tag", "at", "volume"})
                tag = ck.choice(f"{q}.tag" if len(item) > 1 else q, item["tag"], SFX)
                at = ck.number(f"{q}.at", item.get("at", 0.0), 0, 120)
                volume = ck.number(f"{q}.volume", item["volume"], 0, 1) if "volume" in item else None
                if tag and at is not None:
                    s["sfx"].append({"tag": tag, "at": float(at), "volume": volume})

        # duration
        if "duration" not in shot:
            if s["narration"] is None:
                ck.err(f"{p}.duration", 'is required unless the shot has "narration": seconds, '
                                        'or "auto" to use the length of "audio".')
        elif shot["duration"] == "auto":
            audio = shot.get("audio")
            if not isinstance(audio, str) or not audio.strip():
                ck.err(f"{p}.audio", 'is required when duration is "auto": the path to a sound file.')
            else:
                full = audio if os.path.isabs(audio) else os.path.join(base_dir, audio)
                if not os.path.isfile(full):
                    ck.err(f"{p}.audio", f'file not found: "{full}". Paths are relative to the JSON file.')
                else:
                    s["duration"], s["audio"] = "auto", full
        else:
            s["duration"] = ck.number(f"{p}.duration", shot["duration"], 0.2, 120)
            if shot["duration"] != "auto" and isinstance(shot["duration"], str):
                ck.errors[-1] = f'{p}.duration: "{shot["duration"]}" is not valid. Use a number of seconds, or "auto".'

        if "lighting" in shot:
            s["lighting"] = ck.choice(f"{p}.lighting", shot["lighting"], LIGHTING) or "day"

        if shot.get("clock") is not None:
            clock = shot["clock"]
            parts = clock.split(":") if isinstance(clock, str) else []
            if len(parts) == 2 and all(x.isdigit() for x in parts) and int(parts[0]) < 24 and int(parts[1]) < 60:
                s["clock"] = (int(parts[0]), int(parts[1]))
            else:
                ck.err(f"{p}.clock", 'must be a time like "12:00" or "5:40".')

        # camera
        cam = shot.get("camera")
        if cam is not None:
            if not isinstance(cam, dict):
                ck.err(f"{p}.camera", f"must be an object, got {_kind(cam)}.")
            else:
                ck.keys(f"{p}.camera", cam, _CAMERA)
                c = s["camera"]
                if "move" in cam:
                    c["move"] = ck.choice(f"{p}.camera.move", cam["move"], MOVES) or "static"
                if "target" in cam:
                    c["target"] = ck.target(f"{p}.camera.target", cam["target"]) or "street"
                if cam.get("position") is not None:
                    c["position"] = ck.point(f"{p}.camera.position", cam["position"], 3)
                if "amount" in cam:
                    c["amount"] = ck.number(f"{p}.camera.amount", cam["amount"], 0.02, 0.9) or 0.35
                if "degrees" in cam:
                    c["degrees"] = ck.number(f"{p}.camera.degrees", cam["degrees"], -360, 360) or 40.0
                if "lens" in cam:
                    c["lens"] = ck.number(f"{p}.camera.lens", cam["lens"], 10, 200) or 28.0
                if c["move"] == "follow" and c["target"] not in MOVING_TARGETS:
                    ck.err(f"{p}.camera.target", 'a "follow" camera needs something that moves: '
                                                 f'use {" or ".join(chr(34) + t + chr(34) for t in MOVING_TARGETS)}.')

        # character
        ch = shot.get("character")
        if ch is not None:
            if not isinstance(ch, dict):
                ck.err(f"{p}.character", f"must be an object, got {_kind(ch)}.")
            else:
                ck.keys(f"{p}.character", ch, _CHARACTER)
                c = {"pose": "idle", "eyes": "open", "mouth": "neutral", "position": (4.8, 0.0),
                     "heading": 0.0, "path": None, "speed": 1.4, "look_at": None}
                if "pose" in ch:
                    c["pose"] = ck.choice(f"{p}.character.pose", ch["pose"], POSES) or "idle"
                expr = ch.get("expression")
                if isinstance(expr, str):
                    name = ck.choice(f"{p}.character.expression", expr, list(EXPRESSIONS))
                    if name:
                        c["eyes"], c["mouth"] = EXPRESSIONS[name]
                elif isinstance(expr, dict):
                    ck.keys(f"{p}.character.expression", expr, {"eyes", "mouth"})
                    if "eyes" in expr:
                        c["eyes"] = ck.choice(f"{p}.character.expression.eyes", expr["eyes"], EYES) or "open"
                    if "mouth" in expr:
                        c["mouth"] = ck.choice(f"{p}.character.expression.mouth", expr["mouth"], MOUTHS) or "neutral"
                elif expr is not None:
                    ck.err(f"{p}.character.expression", f"must be a name ({', '.join(EXPRESSIONS)}) or "
                                                        f'{{"eyes": ..., "mouth": ...}}; got {_kind(expr)}.')
                if ch.get("position") is not None:
                    c["position"] = ck.point(f"{p}.character.position", ch["position"], 2) or c["position"]
                if "heading" in ch:
                    c["heading"] = ck.number(f"{p}.character.heading", ch["heading"], -360, 360) or 0.0
                if ch.get("look_at") is not None:
                    c["look_at"] = ck.target(f"{p}.character.look_at", ch["look_at"])
                    if c["look_at"] == "character":
                        ck.err(f"{p}.character.look_at", "he cannot look at himself; pick another target.")
                walk = ch.get("path")
                if walk is not None:
                    if not isinstance(walk, dict):
                        ck.err(f"{p}.character.path", 'must be an object like {"points": [[x, y], ...], "speed": 1.4}.')
                    else:
                        ck.keys(f"{p}.character.path", walk, {"points", "speed"})
                        c["path"] = ck.path_points(f"{p}.character.path.points", walk.get("points"))
                        if "speed" in walk:
                            c["speed"] = ck.number(f"{p}.character.path.speed", walk["speed"], 0.2, 6) or 1.4
                    if c["pose"] == "sit_driving":
                        ck.err(f"{p}.character.pose", '"sit_driving" cannot be combined with a walking path.')
                s["character"] = c
        if s["camera"]["target"] == "character" and s["character"] is None:
            ck.err(f"{p}.camera.target", 'is "character" but this shot has no "character" block.')

        # props
        props = shot.get("props")
        if props is not None:
            if not isinstance(props, dict):
                ck.err(f"{p}.props", 'must be an object like {"show": [...], "hide": [...]}.')
            else:
                ck.keys(f"{p}.props", props, {"show", "hide"})
                for key in ("show", "hide"):
                    names = props.get(key, [])
                    if not isinstance(names, list):
                        ck.err(f"{p}.props.{key}", f"must be a list of names, got {_kind(names)}.")
                        continue
                    s[key] = [n for j, n in enumerate(names)
                              if ck.choice(f"{p}.props.{key}[{j}]", n, PROPS)]
                both = set(s["show"]) & set(s["hide"])
                if both:
                    ck.err(f"{p}.props", f"{', '.join(sorted(both))} cannot be in both show and hide.")

        # vehicle
        veh = shot.get("vehicle")
        if veh is not None:
            if not isinstance(veh, dict):
                ck.err(f"{p}.vehicle", 'must be an object like {"path": [[x, y], ...], "speed": 6}.')
            else:
                ck.keys(f"{p}.vehicle", veh, {"path", "speed"})
                pts = ck.path_points(f"{p}.vehicle.path", veh.get("path"))
                speed = ck.number(f"{p}.vehicle.speed", veh.get("speed", 6.0), 0.1, 40)
                if pts and speed:
                    s["vehicle"] = {"path": pts, "speed": speed}
            if "bus" in s["hide"]:
                ck.err(f"{p}.vehicle", "the bus has a path in this shot but is also hidden by props.hide.")
        if s["camera"]["target"] == "bus" and s["camera"]["move"] == "follow" and s["vehicle"] is None:
            ck.err(f"{p}.camera", 'follows the bus, but this shot has no "vehicle" path, so it would not move.')

        if shot.get("text") is not None:
            text = shot["text"]
            if not isinstance(text, str) or not text.strip():
                ck.err(f"{p}.text", "must be non-empty text, or left out.")
            elif len(text) > 90:
                ck.err(f"{p}.text", f"is {len(text)} characters; keep on-screen text under 90.")
            else:
                s["text"] = text.strip()

        out["shots"].append(s)

    if ck.errors:
        raise ShotListError(ck.errors, source)
    return out


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ShotListError([f'file not found: "{path}".'], path) from None
    except json.JSONDecodeError as e:
        raise ShotListError([f"not valid JSON at line {e.lineno}, column {e.colno}: {e.msg}. Common causes: "
                             f"a missing or trailing comma, or single quotes instead of double quotes."], path) from None
    return validate(data, os.path.dirname(os.path.abspath(path)), path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python shotlist.py episode.json [more.json ...]")
    bad = 0
    for arg in sys.argv[1:]:
        try:
            shots = load(arg)["shots"]
            fixed = sum(s["duration"] for s in shots if isinstance(s["duration"], (int, float)))
            auto = sum(1 for s in shots if not isinstance(s["duration"], (int, float)))
            print(f"{arg}: OK ({len(shots)} shots, {fixed:.1f}s" + (f" + {auto} timed from narration or audio" if auto else "") + ")")
        except ShotListError as e:
            print(e, file=sys.stderr)
            bad += 1
    sys.exit(1 if bad else 0)
