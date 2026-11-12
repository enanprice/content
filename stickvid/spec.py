"""Video spec: load a JSON file describing a video and validate it.

A spec looks like this (only "scenes" and each scene's "narration" are required):

    {
      "title": "My video",
      "voice": "en-GB-RyanNeural",
      "rate": "+0%",
      "transition": "slide_left",
      "whoosh": true,
      "music": {"path": "music/track.mp3", "volume": 0.08},
      "captions": {"max_words": 3, "uppercase": true},
      "scenes": [
        {
          "narration": "What the voice says.",
          "pose": "talking",
          "expression": "happy",
          "prop": "clock",                       # or {"type": "battery", "level": 0.9}
          "keyword": "On-screen note",
          "setting": "bedroom",                  # room drawn behind the scene
          "time": "night",
          "move": "approach",                    # walk up from the back of the room
          "camera": "zoom_in",
          "background": "#E2E4F7"
        }
      ]
    }

validate() never stops at the first problem: it collects every error, each
prefixed with the exact location (e.g. `scenes[2].pose`), and raises one
SpecError listing them all.
"""

import difflib
import json
import os
import re

from .figure import EXPRESSIONS, POSES
from .rooms import SETTINGS, TIMES

DEFAULT_VOICE = "en-GB-RyanNeural"
UK_VOICES = ["en-GB-RyanNeural", "en-GB-SoniaNeural", "en-GB-LibbyNeural",
             "en-GB-ThomasNeural", "en-GB-MaisieNeural"]

TRANSITIONS = ["slide_left", "slide_right", "slide_up", "slide_down", "cut"]
CAMERAS = ["none", "zoom_in", "shake"]
MOVES = ["stay", "approach", "pace"]
EVIDENCE = ["strong", "moderate", "mixed"]
ARROW_DIRECTIONS = ["up", "down", "left", "right"]

MAX_NARRATION_CHARS = 400
MAX_KEYWORD_CHARS = 24

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_VOICE = re.compile(r"^[a-z]{2,3}-[A-Z]{2}-\w+Neural$")
_RATE = re.compile(r"^[+-]\d{1,3}%$")


class SpecError(ValueError):
    """Raised with every problem found in a spec."""

    def __init__(self, errors, source="spec"):
        self.errors = list(errors)
        n = len(self.errors)
        lines = [f"{source}: {n} problem{'s' if n != 1 else ''} found"]
        lines += [f"  - {e}" for e in self.errors]
        super().__init__("\n".join(lines))


# ---------------------------------------------------------------------------
# small checkers: each returns the cleaned value, or records an error and
# returns the fallback
# ---------------------------------------------------------------------------
def _kind(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "a list"
    return "an object"


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _suggest(word, options):
    close = difflib.get_close_matches(str(word), options, n=1, cutoff=0.6)
    return f' Did you mean "{close[0]}"?' if close else ""


class _Checker:
    def __init__(self):
        self.errors = []

    def err(self, path, message):
        self.errors.append(f"{path}: {message}")

    def unknown_keys(self, path, obj, allowed):
        for key in obj:
            if key not in allowed:
                where = f"{path}.{key}" if path else key
                self.err(where, f"unknown field.{_suggest(key, allowed)} "
                                f"Allowed fields: {', '.join(sorted(allowed))}.")

    def text(self, path, value, max_len=None, allow_empty=False):
        if not isinstance(value, str):
            self.err(path, f"must be text in quotes, got {_kind(value)}.")
            return None
        value = value.strip()
        if not value and not allow_empty:
            self.err(path, "must not be empty.")
            return None
        if max_len and len(value) > max_len:
            self.err(path, f"is {len(value)} characters long; the limit is {max_len}.")
            return None
        return value

    def choice(self, path, value, options):
        if not isinstance(value, str) or value not in options:
            shown = f'"{value}"' if isinstance(value, str) else _kind(value)
            self.err(path, f"{shown} is not valid.{_suggest(value, options)} "
                           f"Choose one of: {', '.join(options)}.")
            return None
        return value

    def number(self, path, value, lo=None, hi=None):
        if not _is_number(value):
            self.err(path, f"must be a number, got {_kind(value)}.")
            return None
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            self.err(path, f"is {value}; it must be between {lo} and {hi}.")
            return None
        return value

    def boolean(self, path, value):
        if not isinstance(value, bool):
            self.err(path, f"must be true or false, got {_kind(value)}.")
            return None
        return value

    def color(self, path, value):
        if not isinstance(value, str) or not _HEX.match(value):
            self.err(path, 'must be a hex colour like "#E2E4F7".')
            return None
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------------------------
# props: which options each prop type accepts
# ---------------------------------------------------------------------------
def _opt_number(lo, hi):
    return lambda ck, path, v: ck.number(path, v, lo, hi)


def _opt_bool(ck, path, v):
    return ck.boolean(path, v)


def _opt_short_text(ck, path, v):
    return ck.text(path, v, max_len=6)


def _opt_items(ck, path, v):
    if not isinstance(v, list) or not 1 <= len(v) <= 5:
        ck.err(path, "must be a list of 1 to 5 short texts.")
        return None
    items = [ck.text(f"{path}[{i}]", item, max_len=12) for i, item in enumerate(v)]
    return None if None in items else items


def _opt_values(ck, path, v):
    if not isinstance(v, list) or not 2 <= len(v) <= 5:
        ck.err(path, "must be a list of 2 to 5 numbers between 0 and 1.")
        return None
    values = [ck.number(f"{path}[{i}]", item, 0, 1) for i, item in enumerate(v)]
    return None if None in values else values


def _opt_labels(ck, path, v):
    if not isinstance(v, list) or not 2 <= len(v) <= 5:
        ck.err(path, "must be a list of 2 to 5 short texts.")
        return None
    labels = [ck.text(f"{path}[{i}]", item, max_len=8) for i, item in enumerate(v)]
    return None if None in labels else labels


PROP_OPTIONS = {
    "phone": {},
    "book": {"open": _opt_bool},
    "clock": {"time": _opt_number(0, 24), "spin": _opt_number(-2, 2)},
    "brain": {},
    "battery": {"level": _opt_number(0, 1), "from": _opt_number(0, 1)},
    "thought_bubble": {"text": _opt_short_text},
    "checklist": {"items": _opt_items, "checked": _opt_number(0, 5)},
    "bar_chart": {"values": _opt_values, "labels": _opt_labels},
    "arrow": {"direction": lambda ck, path, v: ck.choice(path, v, ARROW_DIRECTIONS),
              "color": lambda ck, path, v: ck.color(path, v)},
    "tomato": {},
}


def _check_prop(ck, path, value):
    """Accepts null, "clock", or {"type": "clock", ...options}. Returns a dict or None."""
    if value is None:
        return None
    if isinstance(value, str):
        value = {"type": value}
    if not isinstance(value, dict):
        ck.err(path, f'must be a prop name like "clock", an object like '
                     f'{{"type": "clock"}}, or null; got {_kind(value)}.')
        return None
    if "type" not in value:
        ck.err(path, f'is missing "type". Choose one of: {", ".join(PROP_OPTIONS)}.')
        return None
    kind = ck.choice(f"{path}.type" if len(value) > 1 else path, value["type"], list(PROP_OPTIONS))
    if kind is None:
        return None
    options = PROP_OPTIONS[kind]
    out = {"type": kind}
    for key, v in value.items():
        if key == "type":
            continue
        if key not in options:
            allowed = ", ".join(options) if options else "none"
            ck.err(f"{path}.{key}", f'is not an option of the "{kind}" prop.'
                                    f"{_suggest(key, list(options))} Options: {allowed}.")
            continue
        out[key] = options[key](ck, f"{path}.{key}", v)
    if kind == "bar_chart" and out.get("labels") and out.get("values") \
            and len(out["labels"]) != len(out["values"]):
        ck.err(f"{path}.labels", f"has {len(out['labels'])} entries but values has "
                                 f"{len(out['values'])}; they must match.")
    return out


# ---------------------------------------------------------------------------
# the validator
# ---------------------------------------------------------------------------
_TOP_FIELDS = {"title", "description", "hashtags", "voice", "rate", "transition", "whoosh", "music",
               "captions", "source", "scenes"}
_SCENE_FIELDS = {"narration", "pose", "expression", "prop", "keyword", "camera", "background",
                 "setting", "time", "move"}
_SOURCE_FIELDS = {"citation", "finding", "evidence", "caveat", "link"}
_MUSIC_FIELDS = {"path", "volume"}
_CAPTION_FIELDS = {"enabled", "max_words", "uppercase", "highlight"}


def validate(data, base_dir=".", source="spec"):
    """Check a parsed spec and return a normalised copy with defaults filled in.

    base_dir  folder that a relative music path is resolved against
    Raises SpecError listing every problem.
    """
    ck = _Checker()
    if not isinstance(data, dict):
        raise SpecError([f"the top level must be an object {{...}}, got {_kind(data)}."], source)
    ck.unknown_keys("", data, _TOP_FIELDS)

    spec = {
        "title": "", "voice": DEFAULT_VOICE, "rate": "+0%", "transition": "slide_left",
        "whoosh": True, "music": None, "source": None, "scenes": [],
        "description": "", "hashtags": [],
        "captions": {"enabled": True, "max_words": 4, "uppercase": False, "highlight": (255, 221, 120)},
    }

    if "title" in data:
        spec["title"] = ck.text("title", data["title"], max_len=100, allow_empty=True) or ""

    if "voice" in data:
        voice = ck.text("voice", data["voice"])
        if voice and not _VOICE.match(voice):
            ck.err("voice", f'"{voice}" does not look like an edge-tts voice name.'
                            f"{_suggest(voice, UK_VOICES)} UK English voices: {', '.join(UK_VOICES)}.")
        elif voice:
            spec["voice"] = voice

    if "rate" in data:
        rate = ck.text("rate", data["rate"])
        if rate and not _RATE.match(rate):
            ck.err("rate", f'"{rate}" is not valid. Use a signed percentage such as "+10%" or "-5%".')
        elif rate:
            spec["rate"] = rate

    if "transition" in data:
        spec["transition"] = ck.choice("transition", data["transition"], TRANSITIONS) or "cut"

    if "whoosh" in data:
        spec["whoosh"] = bool(ck.boolean("whoosh", data["whoosh"]))

    music = data.get("music")
    if music is not None:
        if isinstance(music, str):
            music = {"path": music}
        if not isinstance(music, dict):
            ck.err("music", f'must be a file path, an object like {{"path": "...", "volume": 0.08}}, '
                            f"or null; got {_kind(music)}.")
        else:
            ck.unknown_keys("music", music, _MUSIC_FIELDS)
            volume = ck.number("music.volume", music["volume"], 0, 1) if "volume" in music else 0.08
            if "path" not in music:
                ck.err("music.path", "is required when music is set.")
            else:
                path = ck.text("music.path", music["path"])
                if path:
                    full = path if os.path.isabs(path) else os.path.join(base_dir, path)
                    if not os.path.isfile(full):
                        ck.err("music.path", f'file not found: "{full}". Paths are relative to the '
                                             f"JSON file. Remove \"music\" to render without it.")
                    else:
                        spec["music"] = {"path": full, "volume": volume if volume is not None else 0.08}

    captions = data.get("captions")
    if captions is not None:
        if not isinstance(captions, dict):
            ck.err("captions", f"must be an object, got {_kind(captions)}.")
        else:
            ck.unknown_keys("captions", captions, _CAPTION_FIELDS)
            out = spec["captions"]
            if "enabled" in captions:
                out["enabled"] = bool(ck.boolean("captions.enabled", captions["enabled"]))
            if "uppercase" in captions:
                out["uppercase"] = bool(ck.boolean("captions.uppercase", captions["uppercase"]))
            if "max_words" in captions:
                n = ck.number("captions.max_words", captions["max_words"], 1, 5)
                if n is not None and int(n) != n:
                    ck.err("captions.max_words", "must be a whole number.")
                elif n is not None:
                    out["max_words"] = int(n)
            if "highlight" in captions:
                out["highlight"] = ck.color("captions.highlight", captions["highlight"]) or out["highlight"]

    # --- upload text: optional; make.py writes sensible defaults without them ---
    if "description" in data:
        spec["description"] = ck.text("description", data["description"], max_len=1000, allow_empty=True) or ""
    if "hashtags" in data:
        tags = data["hashtags"]
        if not isinstance(tags, list) or not 1 <= len(tags) <= 3:
            ck.err("hashtags", "must be a list of 1 to 3 hashtags.")
        else:
            for i, tag in enumerate(tags):
                tag = ck.text(f"hashtags[{i}]", tag, max_len=40)
                if tag and not re.match(r"^#?[A-Za-z0-9_]+$", tag):
                    ck.err(f"hashtags[{i}]", f'"{tag}" is not valid. Use letters, digits and underscores only, e.g. "#StudyTips".')
                elif tag:
                    spec["hashtags"].append("#" + tag.lstrip("#"))

    # --- source: where the video's claims come from. Not shown on screen;
    # it travels with the script so the claims can be checked. ---
    cited = data.get("source")
    if cited is not None:
        if not isinstance(cited, dict):
            ck.err("source", f"must be an object, got {_kind(cited)}.")
        else:
            ck.unknown_keys("source", cited, _SOURCE_FIELDS)
            out = {"citation": "", "finding": "", "evidence": None, "caveat": "", "link": ""}
            if "citation" not in cited:
                ck.err("source.citation", "is required: authors, year, title and journal.")
            for key in ("citation", "finding", "caveat", "link"):
                if key in cited:
                    out[key] = ck.text(f"source.{key}", cited[key], max_len=700) or ""
            if "evidence" in cited:
                out["evidence"] = ck.choice("source.evidence", cited["evidence"], EVIDENCE)
            spec["source"] = out

    # --- scenes ---
    scenes = data.get("scenes")
    if scenes is None:
        ck.err("scenes", "is required: a list with at least one scene.")
    elif not isinstance(scenes, list):
        ck.err("scenes", f"must be a list [...], got {_kind(scenes)}.")
    elif not scenes:
        ck.err("scenes", "must contain at least one scene.")
    else:
        for i, scene in enumerate(scenes):
            path = f"scenes[{i}]"
            if not isinstance(scene, dict):
                ck.err(path, f"must be an object {{...}}, got {_kind(scene)}.")
                continue
            ck.unknown_keys(path, scene, _SCENE_FIELDS)
            out = {"narration": "", "pose": "talking", "expression": "neutral", "prop": None,
                   "keyword": None, "camera": "none", "background": None,
                   "setting": "plain", "time": "day", "move": "stay"}
            if "narration" not in scene:
                ck.err(f"{path}.narration", "is required: the text the voice will read.")
            else:
                narration = ck.text(f"{path}.narration", scene["narration"], max_len=MAX_NARRATION_CHARS)
                if narration and not re.search(r"[A-Za-z0-9]", narration):
                    ck.err(f"{path}.narration", "has no speakable words.")
                elif narration:
                    out["narration"] = narration
            if "pose" in scene:
                out["pose"] = ck.choice(f"{path}.pose", scene["pose"], list(POSES)) or "idle"
            if "expression" in scene:
                out["expression"] = ck.choice(f"{path}.expression", scene["expression"],
                                              list(EXPRESSIONS)) or "neutral"
            if "prop" in scene:
                out["prop"] = _check_prop(ck, f"{path}.prop", scene["prop"])
            if scene.get("keyword") is not None:
                out["keyword"] = ck.text(f"{path}.keyword", scene["keyword"], max_len=MAX_KEYWORD_CHARS)
            if "camera" in scene:
                out["camera"] = ck.choice(f"{path}.camera", scene["camera"], CAMERAS) or "none"
            if "setting" in scene:
                out["setting"] = ck.choice(f"{path}.setting", scene["setting"], SETTINGS) or "plain"
            if "time" in scene:
                out["time"] = ck.choice(f"{path}.time", scene["time"], TIMES) or "day"
            if "move" in scene:
                out["move"] = ck.choice(f"{path}.move", scene["move"], MOVES) or "stay"
            if scene.get("background") is not None:
                out["background"] = ck.color(f"{path}.background", scene["background"])
            spec["scenes"].append(out)

    if ck.errors:
        raise SpecError(ck.errors, source)
    return spec


def load(path):
    """Read and validate a spec file. Raises SpecError with readable messages."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise SpecError([f'file not found: "{path}".'], path) from None
    except json.JSONDecodeError as e:
        raise SpecError([f"not valid JSON at line {e.lineno}, column {e.colno}: {e.msg}. "
                         f"Common causes: a missing or trailing comma, or single quotes "
                         f"instead of double quotes."], path) from None
    return validate(data, base_dir=os.path.dirname(os.path.abspath(path)), source=path)
