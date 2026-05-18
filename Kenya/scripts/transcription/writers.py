"""
Output writers: plain-text transcript, JSON, and CSV.
"""

import csv
import json
import logging
from pathlib import Path

from utils import format_number

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plain-text transcript
# ---------------------------------------------------------------------------

def write_transcript_txt(
    turns: list[dict],
    metadata: dict,
    output_path: str,
) -> str:
    """
    Write a clean, human-readable transcript to *output_path*.

    Format:
        "VIDEO TITLE"
        Stats: Views: 123,456; Likes: 7,890; Comments: 321.
        Speaker: Main Speaker Name

        Speaker 1: Hello everyone and welcome back.

        Speaker 2: Thank you for having me.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    # --- metadata header ---
    title = metadata.get("title", "")
    if title:
        lines.append(f'"{title}"')

    stats_parts: list[str] = []
    view_count = metadata.get("view_count")
    like_count = metadata.get("like_count")
    comment_count = metadata.get("comment_count")
    if view_count is not None:
        stats_parts.append(f"Views: {format_number(view_count)}")
    if like_count is not None:
        stats_parts.append(f"Likes: {format_number(like_count)}")
    if comment_count is not None:
        stats_parts.append(f"Comments: {format_number(comment_count)}")
    if stats_parts:
        lines.append("Stats: " + "; ".join(stats_parts) + ".")

    # Primary speaker line — find the most-used non-generic speaker name
    primary = _detect_primary_name(turns)
    if primary:
        lines.append(f"Speaker: {primary}")

    lines.append("")  # blank line before transcript body

    # --- transcript body ---
    for turn in turns:
        if not turn["text"].strip():
            continue
        lines.append(f'{turn["speaker"]}: {turn["text"]}')
        lines.append("")  # blank line between turns

    text = "\n".join(lines).rstrip("\n") + "\n"
    out.write_text(text, encoding="utf-8")
    logger.info("Transcript TXT saved: %s", out)
    return str(out)


def _detect_primary_name(turns: list[dict]) -> str | None:
    """
    If the dominant speaker has a real name (not 'Speaker N' / 'Unknown'),
    return it for the header.
    """
    if not turns:
        return None

    from collections import Counter
    time_by_speaker: Counter[str] = Counter()
    for t in turns:
        time_by_speaker[t["speaker"]] += t["end"] - t["start"]

    dominant, _ = time_by_speaker.most_common(1)[0]
    if dominant.startswith("Speaker ") or dominant == "Unknown" or dominant == "Audience":
        return None
    return dominant


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def write_transcript_json(
    turns: list[dict],
    metadata: dict,
    output_path: str,
) -> str:
    """
    Write structured JSON with metadata, turns, and pipeline info.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "metadata": {
            "title": metadata.get("title"),
            "uploader": metadata.get("uploader"),
            "channel": metadata.get("channel"),
            "view_count": metadata.get("view_count"),
            "like_count": metadata.get("like_count"),
            "comment_count": metadata.get("comment_count"),
            "webpage_url": metadata.get("webpage_url"),
        },
        "turns": turns,
        "pipeline": {
            "audio_path": metadata.get("wav_path"),
            "parakeet_model": metadata.get("parakeet_model"),
            "sortformer_model": metadata.get("sortformer_model"),
        },
    }

    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Transcript JSON saved: %s", out)
    return str(out)


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def write_segments_csv(
    turns: list[dict],
    output_path: str,
) -> str:
    """
    Write a CSV with columns: speaker, start, end, text.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["speaker", "start", "end", "text"])
        writer.writeheader()
        for turn in turns:
            writer.writerow({
                "speaker": turn["speaker"],
                "start": turn["start"],
                "end": turn["end"],
                "text": turn["text"],
            })

    logger.info("Segments CSV saved: %s", out)
    return str(out)
