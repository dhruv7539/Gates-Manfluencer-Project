"""
Merge ASR word-level output with speaker diarization segments and
produce clean, labelled speaker turns.

This is the most important module in the pipeline — it bridges the
word-level ASR transcript with the speaker-level diarization to create
a coherent, speaker-attributed transcript.
"""

import logging
import re
from collections import Counter

from config import (
    WORD_SPEAKER_TOLERANCE,
    TURN_MAX_GAP,
    AUDIENCE_MAX_WORDS,
    AUDIENCE_KEYWORDS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Assign a speaker label to every ASR word
# ---------------------------------------------------------------------------

def assign_speakers_to_words(
    words: list[dict],
    speaker_segments: list[dict],
    tolerance: float = WORD_SPEAKER_TOLERANCE,
) -> list[dict]:
    """
    For each word dict (with start/end), find the diarization segment that
    covers the word's **midpoint**.  If no segment contains the midpoint,
    the nearest segment within *tolerance* seconds is used.  Otherwise the
    word is labelled "Unknown".

    Returns a new list of word dicts with an added "speaker" key.
    """
    if not speaker_segments:
        logger.warning("No diarization segments — all words will be 'Unknown'.")
        return [{**w, "speaker": "Unknown"} for w in words]

    result: list[dict] = []
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        speaker = _find_speaker_at(mid, speaker_segments, tolerance)
        result.append({**w, "speaker": speaker})
    return result


def _find_speaker_at(
    t: float,
    segments: list[dict],
    tolerance: float,
) -> str:
    """Return the speaker label active at time *t*, or the nearest within *tolerance*."""
    best_label = "Unknown"
    best_dist = float("inf")

    for seg in segments:
        if seg["start"] <= t <= seg["end"]:
            return seg["speaker"]
        # distance to nearest edge of this segment
        dist = min(abs(t - seg["start"]), abs(t - seg["end"]))
        if dist < best_dist:
            best_dist = dist
            best_label = seg["speaker"]

    return best_label if best_dist <= tolerance else "Unknown"


# ---------------------------------------------------------------------------
# 2. Collapse word sequence into natural speaker turns
# ---------------------------------------------------------------------------

def collapse_words_into_turns(
    words_with_speakers: list[dict],
    max_gap: float = TURN_MAX_GAP,
) -> list[dict]:
    """
    Group consecutive words that share the same speaker into turns.

    A new turn is started when:
      • the speaker changes, OR
      • the silence gap between two consecutive words exceeds *max_gap*.

    Returns a list of turn dicts:
        {"speaker": str, "start": float, "end": float, "text": str}
    """
    if not words_with_speakers:
        return []

    turns: list[dict] = []
    cur_speaker = words_with_speakers[0]["speaker"]
    cur_words: list[str] = [words_with_speakers[0]["word"]]
    cur_start = words_with_speakers[0]["start"]
    cur_end = words_with_speakers[0]["end"]

    for w in words_with_speakers[1:]:
        gap = w["start"] - cur_end
        if w["speaker"] != cur_speaker or gap > max_gap:
            turns.append(_make_turn(cur_speaker, cur_start, cur_end, cur_words))
            cur_speaker = w["speaker"]
            cur_words = []
            cur_start = w["start"]

        cur_words.append(w["word"])
        cur_end = w["end"]

    # flush last turn
    turns.append(_make_turn(cur_speaker, cur_start, cur_end, cur_words))
    return turns


def _make_turn(speaker: str, start: float, end: float, word_list: list[str]) -> dict:
    text = " ".join(word_list)
    text = _clean_text(text)
    return {
        "speaker": speaker,
        "start": round(start, 3),
        "end": round(end, 3),
        "text": text,
    }


def _clean_text(text: str) -> str:
    """Light cleanup: collapse spaces, fix spacing around punctuation."""
    text = re.sub(r"\s+", " ", text).strip()
    # Remove space before sentence-ending punctuation
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    # Remove space after opening quote
    text = re.sub(r'(["\u201c])\s+', r"\1", text)
    # Remove space before closing quote
    text = re.sub(r'\s+(["\u201d])', r"\1", text)
    return text


# ---------------------------------------------------------------------------
# 3. Re-label speakers using metadata heuristics
# ---------------------------------------------------------------------------

def relabel_speakers(turns: list[dict], metadata: dict) -> list[dict]:
    """
    Optionally rename speakers using video metadata and simple heuristics.

    Rules applied (in order):
      1. If metadata suggests a primary speaker name, rename the speaker
         with the most total speech time to that name.
      2. Very short crowd-like utterances may be relabelled "Audience".
    """
    if not turns:
        return turns

    primary_name = _infer_primary_speaker(metadata)
    turns = _rename_dominant_speaker(turns, primary_name)
    turns = _label_audience_turns(turns)
    return turns


def _infer_primary_speaker(metadata: dict) -> str | None:
    """
    Try to extract a speaker name from video metadata.
    Returns a cleaned name string, or None.
    """
    candidates: list[str] = []

    title = metadata.get("title", "")
    uploader = metadata.get("uploader", "")
    channel = metadata.get("channel", "")

    # Heuristic: if the title contains a dash, the part after it might be
    # the speaker name  (e.g. '"My Story" - Banky Wellington')
    if " - " in title:
        after_dash = title.rsplit(" - ", 1)[-1].strip()
        # Only consider if it looks like a name (2-4 words, title-cased)
        if 1 <= len(after_dash.split()) <= 5:
            candidates.append(after_dash)

    if uploader:
        candidates.append(uploader)
    if channel and channel != uploader:
        candidates.append(channel)

    # Pick the shortest plausible name
    for name in candidates:
        cleaned = name.strip()
        if cleaned and len(cleaned) < 60:
            logger.info("Inferred primary speaker: %s", cleaned)
            return cleaned

    return None


def _rename_dominant_speaker(turns: list[dict], name: str | None) -> list[dict]:
    """Rename the speaker with the most total speech time to *name*."""
    if not name:
        return turns

    speech_time: Counter[str] = Counter()
    for t in turns:
        speech_time[t["speaker"]] += t["end"] - t["start"]

    if not speech_time:
        return turns

    dominant = speech_time.most_common(1)[0][0]
    logger.info("Renaming dominant speaker '%s' → '%s'", dominant, name)
    return [
        {**t, "speaker": name if t["speaker"] == dominant else t["speaker"]}
        for t in turns
    ]


def _label_audience_turns(turns: list[dict]) -> list[dict]:
    """
    Relabel very short, crowd-like turns as "Audience".

    A turn is considered crowd-like if:
      • it has ≤ AUDIENCE_MAX_WORDS words, AND
      • all words (lowered, stripped of punctuation) appear in AUDIENCE_KEYWORDS
    """
    result: list[dict] = []
    for t in turns:
        words = t["text"].split()
        if len(words) <= AUDIENCE_MAX_WORDS:
            stripped = re.sub(r"[^\w\s]", "", t["text"]).lower().strip()
            if stripped and stripped in AUDIENCE_KEYWORDS:
                result.append({**t, "speaker": "Audience"})
                continue
        result.append(t)
    return result
