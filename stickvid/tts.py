"""Narration: text -> speech with edge-tts, plus per-word timings.

synthesize() returns the MP3 path, its duration and a list of Word objects
(one per whitespace-separated word of the ORIGINAL text, punctuation kept)
with start/end times in seconds. Captions are built from those.

Results are cached on disk, keyed by text + voice + rate, so re-rendering a
video only calls the speech service for scenes whose narration changed.

estimate() is the offline stand-in: no audio, timings guessed from word
lengths. It lets you preview layout and pacing without a network.
"""

import asyncio
import difflib
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass


class TTSError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Narration:
    path: str            # MP3 file, or None when estimated
    duration: float      # seconds
    words: list          # [Word]


def _norm(token):
    """Lowercase letters and digits only, for matching words across sources."""
    return re.sub(r"[^a-z0-9]", "", token.lower())


def audio_duration(path):
    """Length of an audio file in seconds, measured by ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise TTSError(f"could not read the duration of {path}: {out.stderr.strip()}") from None


# ---------------------------------------------------------------------------
# aligning the script's words with the timings the speech service reports
# ---------------------------------------------------------------------------
def align_words(text, boundaries, duration):
    """Give every word of `text` a start/end time.

    boundaries  [(spoken_text, start, end)] as reported by the speech service

    The service's words don't always match the script one-to-one (it drops
    punctuation, may split "don't" or merge "twenty-five"). Words that
    match get the reported timing; any run in between shares the gap in
    proportion to word length. With no boundaries at all, the whole clip
    is shared out the same way.
    """
    tokens = text.split()
    times = [None] * len(tokens)
    if boundaries:
        matcher = difflib.SequenceMatcher(
            a=[_norm(t) for t in tokens], b=[_norm(b[0]) for b in boundaries], autojunk=False)
        for block in matcher.get_matching_blocks():
            for k in range(block.size):
                _, start, end = boundaries[block.b + k]
                times[block.a + k] = (start, end)

    # Fill unmatched runs between the nearest timed neighbours.
    i = 0
    while i < len(tokens):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(tokens) and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else (boundaries[0][1] if boundaries else 0.05)
        right = times[j][0] if j < len(tokens) else (boundaries[-1][2] if boundaries else duration - 0.05)
        if i == 0 and j < len(tokens):
            left = min(left, right)
        right = max(right, left)
        weights = [max(len(_norm(t)), 1) for t in tokens[i:j]]
        total, cursor = sum(weights), left
        for k, w in enumerate(weights):
            span = (right - left) * w / total
            times[i + k] = (cursor, cursor + span)
            cursor += span
        i = j
    return [Word(tok, s, e) for tok, (s, e) in zip(tokens, times)]


# ---------------------------------------------------------------------------
# edge-tts
# ---------------------------------------------------------------------------
async def _stream(text, voice, rate, mp3_path):
    import edge_tts
    from edge_tts import communicate as _communicate

    # Behind a TLS-inspecting corporate proxy, the proxy's CA is usually
    # supplied via SSL_CERT_FILE. edge-tts only trusts certifi's bundle, so
    # add that file to its trust store (this adds a CA; it never disables
    # certificate checks).
    extra_ca = os.environ.get("SSL_CERT_FILE")
    ctx = getattr(_communicate, "_SSL_CTX", None)
    if extra_ca and ctx is not None and os.path.isfile(extra_ca):
        ctx.load_verify_locations(extra_ca)

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    talker = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary", proxy=proxy)
    boundaries = []
    with open(mp3_path, "wb") as f:
        async for chunk in talker.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7            # service reports 100ns ticks
                boundaries.append((chunk["text"], start, start + chunk["duration"] / 1e7))
    return boundaries


def synthesize(text, voice, rate="+0%", cache_dir=".cache/tts"):
    """Speak `text` and return a Narration. Uses the on-disk cache when it can."""
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        raise TTSError("edge-tts is not installed. Run: pip install -r requirements.txt") from None

    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]
    mp3_path = os.path.join(cache_dir, key + ".mp3")
    meta_path = os.path.join(cache_dir, key + ".json")

    if os.path.isfile(mp3_path) and os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            boundaries = [tuple(b) for b in json.load(f)]
    else:
        tmp = mp3_path + ".part"
        try:
            boundaries = asyncio.run(_stream(text, voice, rate, tmp))
        except Exception as e:  # network, bad voice name, service refusal...
            if os.path.exists(tmp):
                os.remove(tmp)
            raise TTSError(
                f'edge-tts failed for voice "{voice}": {type(e).__name__}: {e}\n'
                f"Check your internet connection and the voice name "
                f"(list voices with: edge-tts --list-voices). "
                f"To render without narration, add --no-tts.") from None
        if os.path.getsize(tmp) == 0:
            os.remove(tmp)
            raise TTSError(f'edge-tts returned no audio for voice "{voice}". Is the voice name right?')
        os.replace(tmp, mp3_path)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(boundaries, f)

    duration = audio_duration(mp3_path)
    return Narration(mp3_path, duration, align_words(text, boundaries, duration))


def estimate(text, words_per_minute=165):
    """Narration with guessed timings and no audio (for --no-tts previews)."""
    tokens = text.split()
    per_word = 60 / words_per_minute
    # Share the time out by word length; punctuation adds a pause after the word.
    weights = [3 + len(_norm(t)) for t in tokens]
    mean = sum(weights) / len(weights)
    words, cursor = [], 0.1
    for tok, weight in zip(tokens, weights):
        spoken = per_word * weight / mean * 0.85
        words.append(Word(tok, cursor, cursor + spoken))
        pause = 0.45 if tok[-1] in ".?!…" else 0.18 if tok[-1] in ",;:" else 0.0
        cursor += per_word * weight / mean + pause
    return Narration(None, cursor + 0.1, words)
