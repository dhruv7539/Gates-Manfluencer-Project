"""
Caption-based transcript improvement using deterministic text alignment.

Instead of asking an LLM to merge captions with transcripts (which causes
over-generation and under-generation), this script:

1. Uses YouTube captions as the word-accurate base text
2. Transfers speaker labels from the existing diarized transcript
   via deterministic word-level alignment
3. Uses Gemini ONLY for residual speaker-boundary polish (optional)

Usage:
    python scripts/improve_transcripts_with_captions.py
    python scripts/improve_transcripts_with_captions.py --jobs face_it_like_a_man
    python scripts/improve_transcripts_with_captions.py --country kenya
    python scripts/improve_transcripts_with_captions.py --skip-gemini
    python scripts/improve_transcripts_with_captions.py --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_all_transcriptions import build_runtime, select_jobs
from transcripts_utils import (
    clean_text,
    parse_transcript_style_lines,
    render_transcript,
    repair_transcript_text,
    split_header_and_body,
)

ROOT = Path(__file__).resolve().parents[2]
CAPTIONS_VTT_DIR = ROOT / "Downloaded Captions"
CAPTIONS_TXT_DIR = ROOT / "Captions"
LOG = logging.getLogger("improve_transcripts")
MODEL_NAME = "gemini-2.5-flash"

ALIGN_SEARCH_WINDOW = 80
MIN_ALIGNMENT_RATIO = 0.25

_TIMESTAMP_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{3})"
)
_VTT_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"\S+")


# ---------------------------------------------------------------------------
# Environment & Gemini helpers
# ---------------------------------------------------------------------------


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_gemini_safety_settings():
    from google.genai import types

    categories = [
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
    ]
    return [
        types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_NONE)
        for c in categories
    ]


def extract_gemini_text(response) -> str:
    direct = getattr(response, "text", None)
    if direct:
        return str(direct)
    pieces: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            t = getattr(part, "text", None)
            if t:
                pieces.append(str(t))
    return "\n".join(pieces).strip()


# ---------------------------------------------------------------------------
# Caption downloading
# ---------------------------------------------------------------------------


def extract_video_id(url: str) -> str | None:
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url or "")
    return match.group(1) if match else None


def download_captions(video_url: str, output_dir: Path) -> Path | None:
    video_id = extract_video_id(video_url)
    if not video_id:
        LOG.warning("Could not extract video ID from %s", video_url)
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / f"{video_id}.%(ext)s")

    for sub_args in [
        ["--write-sub", "--sub-lang", "en", "--skip-download"],
        ["--write-auto-sub", "--sub-lang", "en", "--skip-download"],
    ]:
        try:
            subprocess.run(
                ["yt-dlp", *sub_args, "--sub-format", "vtt/srt/best",
                 "-o", output_template, video_url],
                capture_output=True, text=True, check=True, timeout=60,
            )
            for ext in ("en.vtt", "en.srt", "en.ttml"):
                candidate = output_dir / f"{video_id}.{ext}"
                if candidate.exists() and candidate.stat().st_size > 100:
                    LOG.info("Downloaded captions: %s", candidate.name)
                    return candidate
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            LOG.debug("yt-dlp attempt failed: %s", exc)
            continue

    LOG.warning("No captions found for %s", video_url)
    return None


def _normalize_filename(name: str) -> str:
    """Normalize a filename for fuzzy comparison (handles curly quotes, etc.)."""
    name = name.lower().replace("_", " ")
    name = name.replace("\u2018", "'").replace("\u2019", "'")
    name = name.replace("\u201c", '"').replace("\u201d", '"')
    return name.strip()


def find_plain_text_caption(job: dict, transcript_path: Path) -> Path | None:
    """Find a matching .txt caption file in the Captions/ directory.

    Caption files mirror the Generated Transcripts directory structure,
    so we just swap the root directory.
    """
    output_subdir = str(job.get("output_subdir", "")).strip("/")
    caption_dir = ROOT / output_subdir / "Captions"

    # Best match: same filename as the transcript
    exact = caption_dir / transcript_path.name
    if exact.exists() and exact.stat().st_size > 50:
        return exact

    # Fuzzy fallback: normalize both filenames (handles curly vs straight quotes)
    t_norm = _normalize_filename(transcript_path.stem)
    if caption_dir.is_dir():
        for txt_path in sorted(caption_dir.glob("*.txt")):
            if _normalize_filename(txt_path.stem) == t_norm and txt_path.stat().st_size > 50:
                return txt_path

    return None


def parse_plain_text_as_segments(txt_path: Path) -> list[dict]:
    """Wrap plain-text caption content as a single timed segment."""
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    text = clean_text(text)
    if not text:
        return []
    return [{"start": 0.0, "end": 0.0, "text": text}]


# ---------------------------------------------------------------------------
# VTT/SRT parsing with timestamps
# ---------------------------------------------------------------------------


def _parse_vtt_timestamp(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _strip_vtt_tags(text: str) -> str:
    text = _VTT_TAG_RE.sub("", text)
    for entity, replacement in [
        ("&gt;", ">"), ("&lt;", "<"), ("&amp;", "&"),
        ("&#39;", "'"), ("&quot;", '"'),
    ]:
        text = text.replace(entity, replacement)
    return text


def parse_vtt_timed_segments(vtt_path: Path) -> list[dict]:
    """Parse VTT/SRT into [{start, end, text}] with deduplication."""
    raw = vtt_path.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"^WEBVTT.*?\n\n", "", raw, flags=re.DOTALL)
    raw = re.sub(r"NOTE.*?\n\n", "", raw, flags=re.DOTALL)

    segments: list[dict] = []
    current_start: float | None = None
    current_end: float | None = None
    current_lines: list[str] = []

    for line in raw.splitlines():
        stripped = line.strip()
        ts_match = _TIMESTAMP_RE.search(stripped)
        if ts_match:
            if current_start is not None and current_lines:
                text = clean_text(_strip_vtt_tags(" ".join(current_lines)))
                if text:
                    segments.append({"start": current_start, "end": current_end, "text": text})
            current_start = _parse_vtt_timestamp(ts_match.group(1))
            current_end = _parse_vtt_timestamp(ts_match.group(2))
            current_lines = []
            continue
        if not stripped or re.match(r"^\d+$", stripped):
            continue
        if re.match(r"^(align|position|line):", stripped):
            continue
        current_lines.append(stripped)

    if current_start is not None and current_lines:
        text = clean_text(_strip_vtt_tags(" ".join(current_lines)))
        if text:
            segments.append({"start": current_start, "end": current_end, "text": text})

    return _deduplicate_rolling_segments(segments)


def _deduplicate_rolling_segments(segments: list[dict]) -> list[dict]:
    """Remove rolling-caption duplicates while preserving unique text."""
    if not segments:
        return []

    deduped: list[dict] = [segments[0]]
    for seg in segments[1:]:
        prev = deduped[-1]

        if seg["text"] == prev["text"]:
            prev["end"] = max(prev["end"], seg["end"])
            continue

        prev_words = prev["text"].split()
        curr_words = seg["text"].split()
        overlap = 0
        max_check = min(len(prev_words), len(curr_words))
        for size in range(max_check, 0, -1):
            if prev_words[-size:] == curr_words[:size]:
                overlap = size
                break

        if overlap > 0 and overlap < len(curr_words):
            suffix = " ".join(curr_words[overlap:])
            suffix = clean_text(suffix)
            if suffix:
                deduped.append({"start": seg["start"], "end": seg["end"], "text": suffix})
        elif overlap == 0:
            deduped.append(seg)

    return deduped


# ---------------------------------------------------------------------------
# Word-level alignment engine
# ---------------------------------------------------------------------------


def _normalize_word(word: str) -> str:
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _flatten_turns_to_words(turns: list[dict]) -> list[tuple[str, str]]:
    """Flatten [{speaker, text}] into [(word, speaker), ...]"""
    words: list[tuple[str, str]] = []
    for turn in turns:
        speaker = turn.get("speaker") or "Unknown"
        for word in _tokenize(turn.get("text", "")):
            words.append((word, speaker))
    return words


def align_captions_to_speakers(
    caption_segments: list[dict],
    transcript_turns: list[dict],
) -> tuple[list[dict], float]:
    """Align caption text with transcript speaker labels.

    Uses position-proportional matching: both texts represent the same
    temporal audio, so caption word i/N maps to ~i/N*M in the transcript.
    This avoids the catastrophic misalignment of pure sequential matching.

    Returns (aligned_turns, match_ratio) where aligned_turns use caption
    words (accurate) with speaker labels transferred from the transcript.
    """
    caption_words: list[str] = []
    for seg in caption_segments:
        for word in _tokenize(seg["text"]):
            caption_words.append(word)

    transcript_word_speakers = _flatten_turns_to_words(transcript_turns)

    c_len = len(caption_words)
    t_len = len(transcript_word_speakers)

    if not caption_words:
        return [], 0.0

    if not transcript_word_speakers:
        return [{"speaker": "Unknown", "text": " ".join(caption_words)}], 0.0

    half_window = ALIGN_SEARCH_WINDOW
    matched_count = 0
    speaker_per_caption_word: list[str] = []

    for i, c_word in enumerate(caption_words):
        c_norm = _normalize_word(c_word)
        prop_j = min(int(i / c_len * t_len), t_len - 1)

        if not c_norm:
            speaker_per_caption_word.append(transcript_word_speakers[prop_j][1])
            continue

        search_start = max(0, prop_j - half_window)
        search_end = min(t_len, prop_j + half_window)

        best_j: int | None = None
        best_dist = float("inf")

        for j in range(search_start, search_end):
            if _normalize_word(transcript_word_speakers[j][0]) == c_norm:
                dist = abs(j - prop_j)
                if dist < best_dist:
                    best_dist = dist
                    best_j = j

        if best_j is not None:
            speaker_per_caption_word.append(transcript_word_speakers[best_j][1])
            matched_count += 1
        else:
            speaker_per_caption_word.append(transcript_word_speakers[prop_j][1])

    match_ratio = matched_count / c_len if c_len else 0.0

    # Smooth noisy speaker labels with a local majority vote
    smoothed = _smooth_speaker_labels(speaker_per_caption_word)

    turns: list[dict] = []
    current_speaker: str | None = None
    current_words: list[str] = []

    for word, speaker in zip(caption_words, smoothed):
        if speaker != current_speaker:
            if current_words and current_speaker:
                turns.append({
                    "speaker": current_speaker,
                    "text": clean_text(" ".join(current_words)),
                })
            current_speaker = speaker
            current_words = [word]
        else:
            current_words.append(word)

    if current_words and current_speaker:
        turns.append({
            "speaker": current_speaker,
            "text": clean_text(" ".join(current_words)),
        })

    turns = [t for t in turns if clean_text(t.get("text", ""))]
    return turns, match_ratio


def _smooth_speaker_labels(labels: list[str], window: int = 15) -> list[str]:
    """Apply local majority-vote smoothing to reduce noisy speaker flips."""
    if len(labels) <= window:
        return labels
    from collections import Counter
    smoothed = list(labels)
    half = window // 2
    for i in range(len(labels)):
        lo = max(0, i - half)
        hi = min(len(labels), i + half + 1)
        counts = Counter(labels[lo:hi])
        smoothed[i] = counts.most_common(1)[0][0]
    return smoothed


# ---------------------------------------------------------------------------
# Post-alignment cleanup
# ---------------------------------------------------------------------------


def _merge_short_turns(turns: list[dict], min_words: int = 3) -> list[dict]:
    """Merge very short fragments and consecutive same-speaker turns."""
    if len(turns) < 2:
        return turns

    merged: list[dict] = [turns[0]]
    for turn in turns[1:]:
        prev = merged[-1]
        word_count = len(_tokenize(turn["text"]))

        if word_count <= min_words and turn["speaker"] != prev["speaker"]:
            if len(merged) >= 2 and merged[-2]["speaker"] == turn["speaker"]:
                prev["text"] = clean_text(prev["text"] + " " + turn["text"])
                continue

        merged.append(turn)

    final: list[dict] = [merged[0]] if merged else []
    for turn in merged[1:]:
        if turn["speaker"] == final[-1]["speaker"]:
            final[-1]["text"] = clean_text(final[-1]["text"] + " " + turn["text"])
        else:
            final.append(turn)

    return [t for t in final if clean_text(t.get("text", ""))]


# ---------------------------------------------------------------------------
# Optional Gemini refinement (speaker labels ONLY — no word changes)
# ---------------------------------------------------------------------------


def _build_boundary_refinement_prompt(
    turns: list[dict],
    speakers: list[str],
    content_format: str,
    title: str,
) -> str:
    numbered = "\n".join(
        f"{i}. {t['speaker']}: {t['text']}"
        for i, t in enumerate(turns, 1)
    )
    return dedent(f"""\
You are reviewing speaker labels in an existing transcript.
The WORDS are correct and must NOT be changed.
Your ONLY job is to fix speaker labels where they are obviously wrong.

Rules:
- Do NOT change, add, or remove any words. Only fix speaker labels.
- Output the corrected transcript in "Speaker: text" format with blank
  lines between turns.
- Merge consecutive turns by the same speaker into one turn.
- Use only these speaker names: {json.dumps(speakers, ensure_ascii=False)}
- For clearly uncertain speakers, keep the existing label.
- Content format: {content_format}
- Title: {title}

Transcript to review:
{numbered}

Output the corrected transcript below (speaker labels only, do not change words):
""")


def _refine_speaker_boundaries(
    client,
    turns: list[dict],
    *,
    speakers: list[str],
    content_format: str,
    title: str,
) -> list[dict]:
    """Optional Gemini pass to fix speaker labels. Words are NOT changed."""
    from google.genai import types

    prompt = _build_boundary_refinement_prompt(turns, speakers, content_format, title)
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=65536,
                response_mime_type="text/plain",
                safety_settings=build_gemini_safety_settings(),
            ),
        )
        text = extract_gemini_text(response)
        if not text.strip():
            LOG.warning("Gemini boundary refinement returned empty response")
            return turns

        refined = parse_transcript_style_lines(text)
        if not refined or len(refined) < len(turns) * 0.5:
            LOG.warning(
                "Gemini refinement produced too few turns (%d vs %d original), keeping alignment result",
                len(refined), len(turns),
            )
            return turns

        orig_words = [_normalize_word(w) for w in _tokenize(" ".join(clean_text(t["text"]) for t in turns)) if _normalize_word(w)]
        ref_words = [_normalize_word(w) for w in _tokenize(" ".join(clean_text(t["text"]) for t in refined)) if _normalize_word(w)]

        if len(ref_words) < len(orig_words) * 0.9 or len(ref_words) > len(orig_words) * 1.1:
            LOG.warning(
                "Gemini changed word count significantly (%d -> %d), rejecting refinement",
                len(orig_words), len(ref_words),
            )
            return turns

        return refined
    except Exception as exc:
        LOG.warning("Gemini boundary refinement failed: %s", exc)
        return turns


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------


def current_output_path(job_name: str, job: dict) -> Path:
    audit_path = ROOT / "transcript_audit_report.json"
    if audit_path.exists():
        report = json.loads(audit_path.read_text(encoding="utf-8"))
        for item in report:
            if item.get("job_key") == job_name:
                return ROOT / item["transcript_path"]
    output_dir = ROOT / str(job.get("output_subdir", "")).strip("/") / "Generated Transcripts"
    stem = Path(str(job["local_audio_path"])).stem
    return output_dir / f"{stem}.txt"


def known_speaker_names(job: dict) -> list[str]:
    names: list[str] = []
    for key in ("primary_speaker_name", "host_name", "guest_name"):
        val = clean_text(str(job.get(key) or ""))
        if val:
            names.append(val)
    for item in job.get("known_speakers") or []:
        if isinstance(item, str) and clean_text(item):
            names.append(clean_text(item))
        elif isinstance(item, dict) and clean_text(str(item.get("name") or "")):
            names.append(clean_text(str(item["name"])))
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name.casefold() not in seen:
            seen.add(name.casefold())
            ordered.append(name)
    return ordered


# ---------------------------------------------------------------------------
# Core improvement function
# ---------------------------------------------------------------------------


def improve_transcript(
    client,
    *,
    job_name: str,
    job: dict,
    caption_segments: list[dict],
    existing_transcript_path: Path,
    use_gemini_refinement: bool = True,
) -> str:
    """Improve transcript: caption text as base, speakers from alignment."""
    existing_full = existing_transcript_path.read_text(encoding="utf-8")
    header_lines, body = split_header_and_body(existing_full)
    title = header_lines[0] if header_lines else existing_transcript_path.stem
    speakers = known_speaker_names(job)
    content_format = clean_text(str(job.get("content_format") or "default")).lower()

    existing_turns = parse_transcript_style_lines(body)
    if not existing_turns:
        LOG.warning("Could not parse existing transcript turns for %s", job_name)
        primary = speakers[0] if speakers else "Unknown"
        existing_turns = [{"speaker": primary, "text": clean_text(body)}]

    LOG.info(
        "Aligning %d caption segments with %d transcript turns for %s",
        len(caption_segments), len(existing_turns), job_name,
    )

    aligned_turns, match_ratio = align_captions_to_speakers(
        caption_segments, existing_turns,
    )
    LOG.info("Alignment match ratio for %s: %.1f%%", job_name, match_ratio * 100)

    if match_ratio < MIN_ALIGNMENT_RATIO:
        LOG.warning(
            "Low alignment ratio (%.1f%%) for %s — speaker labels may be unreliable",
            match_ratio * 100, job_name,
        )

    aligned_turns = _merge_short_turns(aligned_turns, min_words=3)

    if use_gemini_refinement and client is not None and speakers:
        LOG.info("Running Gemini speaker-boundary refinement for %s", job_name)
        chunk_size = 100
        if len(aligned_turns) > chunk_size + 20:
            refined_chunks: list[dict] = []
            for i in range(0, len(aligned_turns), chunk_size):
                chunk = aligned_turns[i:i + chunk_size]
                refined_chunk = _refine_speaker_boundaries(
                    client, chunk,
                    speakers=speakers,
                    content_format=content_format,
                    title=title,
                )
                refined_chunks.extend(refined_chunk)
            aligned_turns = refined_chunks
        else:
            aligned_turns = _refine_speaker_boundaries(
                client, aligned_turns,
                speakers=speakers,
                content_format=content_format,
                title=title,
            )
        aligned_turns = _merge_short_turns(aligned_turns, min_words=3)

    return render_transcript(header_lines, aligned_turns)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def configure_logging(log_path: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Improve transcripts using caption-aligned speaker transfer."
    )
    parser.add_argument("--country", choices=["all", "nigeria", "kenya"], default="all")
    parser.add_argument("--jobs", nargs="*", default=None)
    parser.add_argument("--captions-only", action="store_true",
                        help="Only download captions, don't run improvement.")
    parser.add_argument("--skip-download", action="store_true",
                        help="Use previously downloaded captions.")
    parser.add_argument("--skip-gemini", action="store_true",
                        help="Skip optional Gemini speaker-boundary refinement.")
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if a backup already exists from a previous run.")
    parser.add_argument("--log-file", default=str(ROOT / "transcript_improvement.log"))
    parser.add_argument("--backup", action="store_true", default=True,
                        help="Back up original transcripts before overwriting.")
    parser.add_argument("--no-backup", dest="backup", action="store_false")
    return parser.parse_args()


def backup_transcript(path: Path) -> Path:
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / f"{path.stem}.pre_caption_improvement{path.suffix}"
    if not backup_path.exists():
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        LOG.info("Backed up: %s", backup_path)
    return backup_path


def process_job(
    client,
    job_name: str,
    job: dict,
    *,
    skip_download: bool = False,
    captions_only: bool = False,
    do_backup: bool = True,
    use_gemini: bool = True,
    force: bool = False,
) -> bool:
    youtube_url = job.get("youtube_url", "")
    video_id = extract_video_id(youtube_url)
    if not video_id:
        LOG.warning("No YouTube URL for job %s, skipping", job_name)
        return False

    transcript_path = current_output_path(job_name, job)
    if not transcript_path.exists():
        LOG.warning("No existing transcript at %s, skipping", transcript_path)
        return False

    if not force and do_backup:
        backup_dir = transcript_path.parent / "backups"
        backup_candidate = backup_dir / f"{transcript_path.stem}.pre_caption_improvement{transcript_path.suffix}"
        if backup_candidate.exists():
            LOG.info("Already improved (backup exists): %s, use --force to re-run", job_name)
            return False

    caption_path = None
    caption_segments = None

    # Try VTT/SRT captions first (timestamped)
    if not skip_download:
        caption_path = download_captions(youtube_url, CAPTIONS_VTT_DIR)
    else:
        for ext in ("en.vtt", "en.srt", "en.ttml"):
            candidate = CAPTIONS_VTT_DIR / f"{video_id}.{ext}"
            if candidate.exists():
                caption_path = candidate
                break

    if caption_path:
        caption_segments = parse_vtt_timed_segments(caption_path)

    # Fall back to plain-text captions in Captions/ directory
    if not caption_segments:
        txt_path = find_plain_text_caption(job, transcript_path)
        if txt_path:
            LOG.info("Using plain-text caption file: %s", txt_path)
            caption_segments = parse_plain_text_as_segments(txt_path)

    if not caption_segments:
        LOG.warning("No captions available for %s (%s), skipping", job_name, video_id)
        return False

    total_text = " ".join(seg["text"] for seg in caption_segments)
    if len(total_text.strip()) < 50:
        LOG.warning("Caption text too short for %s (%d chars), skipping", job_name, len(total_text))
        return False

    LOG.info(
        "Captions loaded for %s: %d segments, %d chars",
        job_name, len(caption_segments), len(total_text),
    )

    if captions_only:
        return True

    if do_backup:
        backup_transcript(transcript_path)

    improved = improve_transcript(
        client,
        job_name=job_name,
        job=job,
        caption_segments=caption_segments,
        existing_transcript_path=transcript_path,
        use_gemini_refinement=use_gemini,
    )

    repaired = repair_transcript_text(improved)
    transcript_path.write_text(repaired, encoding="utf-8")
    LOG.info("Wrote improved transcript: %s", transcript_path)
    return True


def main() -> int:
    args = parse_args()
    configure_logging(Path(args.log_file) if args.log_file else None)
    load_env_file(ROOT / ".env")

    runtime = build_runtime()
    job_names = select_jobs(runtime, args.country, args.jobs)
    jobs = runtime["VIDEO_JOBS"]
    LOG.info("Selected %s jobs for caption-based improvement.", len(job_names))

    client = None
    if not args.captions_only and not args.skip_gemini:
        api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
        if not api_key:
            LOG.warning("No Gemini API key found — skipping speaker-boundary refinement.")
        else:
            from google import genai
            client = genai.Client(api_key=api_key)

    successes = 0
    failures: list[tuple[str, str]] = []

    for job_name in job_names:
        started = time.perf_counter()
        try:
            ok = process_job(
                client,
                job_name,
                jobs[job_name],
                skip_download=args.skip_download,
                captions_only=args.captions_only,
                do_backup=args.backup,
                use_gemini=not args.skip_gemini and client is not None,
                force=args.force,
            )
            elapsed = time.perf_counter() - started
            if ok:
                successes += 1
                LOG.info("Improved %s in %.1f seconds", job_name, elapsed)
            else:
                LOG.warning("Skipped %s", job_name)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            LOG.error("Failed %s after %.1f seconds: %s", job_name, elapsed, exc)
            failures.append((job_name, str(exc)))

    LOG.info(
        "Done. Improved: %s, Failed: %s, Total: %s",
        successes, len(failures), len(job_names),
    )
    if failures:
        for name, err in failures:
            LOG.error("FAILED %s: %s", name, err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
