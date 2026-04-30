"""
Fix speaker labels across all transcripts.

Phase 1 — Deterministic fixes (no API):
  - Corrupted labels: "Word. Speaker:" → "Speaker:"
  - Inconsistent naming: normalize variants to canonical form
  - Duplicate content blocks: detect and remove near-duplicate paragraphs

Phase 2 — Gemini-assisted relabeling:
  - Uses YouTube metadata (title, description, channel) as context
  - Asks Gemini to assign real names to generic labels (Host, Interviewee N, etc.)
  - Strict: Gemini may only reassign labels, never alter transcript text

Usage:
    python scripts/fix_speaker_labels.py                    # full run
    python scripts/fix_speaker_labels.py --phase1-only      # deterministic fixes only
    python scripts/fix_speaker_labels.py --jobs andrew_kibe  # specific job(s)
    python scripts/fix_speaker_labels.py --no-backup        # skip backup
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_all_transcriptions import build_runtime, select_jobs
from transcripts_utils import clean_text, repair_transcript_text

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS_DIR = ROOT / "Generated Transcripts"
METADATA_DIR = ROOT / "temp" / "yt_metadata"
LOG = logging.getLogger("fix_speaker_labels")

# Known speaker names per job — canonical labels
KNOWN_SPEAKERS: dict[str, dict[str, str]] = {
    "face_it_like_a_man": {},
    "faith_after_a_fall": {},
    "final_say_faith": {},
    "my_story_journey_through_hope_and_faith": {},
    "the_prison_of_pornography": {},
    "andrew_kibe_071_28_commandments_of_journeying_into_wealth_health_and_respect": {},
    "onyango_narelate_mens_mental_health_workshop_nakuru_january_2023": {},
    "onyango_men_addiction_and_violence_the_story_of_our_childhood_trauma": {
        "Happy. Jagero": "Jagero",
        "Stuff. Jagero": "Jagero",
        "Ugenya. Jagero": "Jagero",
        "Nyanza. Jagero": "Jagero",
        "Underneath. Jagero": "Jagero",
        "Yes. Jagero": "Jagero",
        "Estate. Jagero": "Jagero",
        "Oh. Jagero": "Jagero",
        "Brothers. Jagero": "Jagero",
        "Daddy. Jagero": "Jagero",
        "Nothing Jagero": "Jagero",
        "South Jagero": "Jagero",
        "Ah. Jagero": "Jagero",
        "Huruma Jagero": "Jagero",
        "Dadd Jagero": "Jagero",
    },
    "onyango_my_voice_was_beaten_out_of_me_by_my_father_toxic_masculinity": {},
    "onyango_undoing_my_fathers_damage": {},
    "onyango_your_story_i_thought_having_a_lot_of_sex_would_cure_my_depression": {},
    "philip_karanja_my_childhood_upbringing": {
        "Host": "CTA Host",
    },
    "philip_karanja_episode_1_a_girl_dad_on_a_mission": {
        "SGBV. Crowd": "Crowd",
        "Dorcas. Judy": "Judy",
    },
    "philip_karanja_episode_2_a_girl_dad_on_a_mission": {
        "Kwale. Violet": "Violet",
        "Kwale Violet": "Violet",
    },
    "philip_karanja_season_finale_a_girl_dad_on_a_mission": {},
}

# Regex pattern: lines starting with "SomeWord. ActualSpeaker:" where the first
# word is clearly leaked content (single short word followed by period + space)
_CORRUPTED_LABEL_RE = re.compile(
    r"^([A-Z][a-z]{0,15})\.\s+([A-Z][A-Za-z &()'\-,.]+):\s",
    re.MULTILINE,
)

# Metadata short-name mapping (yt_metadata filename → job key prefix)
_METADATA_MAP = {
    "face_it_like_a_man": "face_it_like_a_man",
    "faith_after_a_fall": "faith_after_a_fall",
    "final_say_faith": "final_say_faith",
    "my_story_journey_through_hope_and_faith": "my_story_journey_through_hope_and_faith",
    "the_prison_of_pornography": "the_prison_of_pornography",
    "andrew_kibe": "andrew_kibe_071",
    "narelate_workshop": "onyango_narelate",
    "men_addiction_violence": "onyango_men_addiction",
    "toxic_masculinity": "onyango_my_voice",
    "undoing_fathers_damage": "onyango_undoing",
    "sex_depression": "onyango_your_story",
    "childhood_upbringing": "philip_karanja_my_childhood",
    "girl_dad_ep1": "philip_karanja_episode_1",
    "girl_dad_ep2": "philip_karanja_episode_2",
    "girl_dad_finale": "philip_karanja_season_finale",
}


def load_yt_metadata(job_key: str) -> dict:
    """Load YouTube metadata JSON for a given job key."""
    for meta_name, prefix in _METADATA_MAP.items():
        if job_key.startswith(prefix):
            meta_path = METADATA_DIR / f"{meta_name}.json"
            if meta_path.exists():
                return json.loads(meta_path.read_text("utf-8"))
    return {}


def transcript_path_for_job(job_name: str, job: dict) -> Path | None:
    audit_path = ROOT / "transcript_audit_report.json"
    if audit_path.exists():
        report = json.loads(audit_path.read_text("utf-8"))
        for item in report:
            if item.get("job_key") == job_name:
                p = ROOT / item["transcript_path"]
                if p.exists():
                    return p

    output_dir = TRANSCRIPTS_DIR / str(job.get("output_subdir", "")).strip("/")
    if output_dir.is_dir():
        for txt in sorted(output_dir.glob("*.txt")):
            if "backups" not in str(txt):
                stem = txt.stem.lower().replace("_", " ")
                if any(part in stem for part in job_name.split("_")[:3]):
                    return txt
        # Fallback: try matching via local_audio_path stem
        audio_stem = Path(str(job.get("local_audio_path", ""))).stem
        candidate = output_dir / f"{audio_stem}.txt"
        if candidate.exists():
            return candidate
    return None


def backup_file(path: Path) -> None:
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_name = f"{path.stem}.pre_speaker_fix{path.suffix}"
    backup_path = backup_dir / backup_name
    if not backup_path.exists():
        import shutil
        shutil.copy2(path, backup_path)
        LOG.info("Backed up: %s", backup_path)


# ---------------------------------------------------------------------------
# Phase 1: Deterministic fixes
# ---------------------------------------------------------------------------


def fix_corrupted_labels(text: str, job_name: str) -> str:
    """Fix 'Word. Speaker:' patterns and apply known speaker renames."""
    renames = KNOWN_SPEAKERS.get(job_name, {})

    for old_label, new_label in renames.items():
        pattern = re.compile(r"^" + re.escape(old_label) + r":", re.MULTILINE)
        text = pattern.sub(f"{new_label}:", text)

    # Generic fix: catch "Word. Speaker:" and "Word Speaker:" patterns
    def _fix_dot_match(m: re.Match) -> str:
        leaked_word = m.group(1)
        if leaked_word.lower() in _COMMON_LEAKED_WORDS:
            rest = m.group(0)[len(m.group(1)) + 2:]  # skip "Word. "
            return rest
        return m.group(0)

    text = _CORRUPTED_LABEL_RE.sub(_fix_dot_match, text)

    # Also catch "Word Speaker:" without dot (e.g. "Nothing Jagero:")
    _no_dot_re = re.compile(
        r"^([A-Z][a-z]{1,12})\s+([A-Z][A-Za-z &()'\-,.]+):\s",
        re.MULTILINE,
    )

    def _fix_no_dot_match(m: re.Match) -> str:
        leaked_word = m.group(1)
        if leaked_word.lower() in _COMMON_LEAKED_WORDS:
            rest = m.group(0)[len(m.group(1)) + 1:]  # skip "Word "
            return rest
        return m.group(0)

    text = _no_dot_re.sub(_fix_no_dot_match, text)
    return text


_COMMON_LEAKED_WORDS = {
    "yes", "no", "oh", "ok", "okay", "yeah", "right", "so", "and", "but",
    "the", "happy", "stuff", "brothers", "daddy", "estate", "underneath",
    "ugenya", "nyanza", "kwale", "dorcas", "sgbv", "well", "true", "sure",
    "good", "bad", "man", "men", "now", "then", "here", "there", "what",
    "how", "why", "when", "where", "this", "that", "it", "all", "um",
    "uh", "like", "just", "really", "very", "too", "much",
    "nothing", "south", "ah", "huruma", "dadd", "north", "east", "west",
}


def remove_duplicate_blocks(text: str, min_block_words: int = 80) -> str:
    """Remove duplicate content at both the paragraph and sentence level.

    Pass 1: Remove turns where >60% of sentences already appeared earlier.
    Pass 2: Remove exact-duplicate paragraphs by fingerprint.
    """
    # Parse into speaker turns (lines separated by blank lines)
    _speaker_re = re.compile(r"^([A-Z][A-Za-z0-9 &()'\-,.]+):\s")
    lines = text.split("\n")
    turns: list[dict] = []
    current: dict = {"start": 0, "lines": []}

    for i, line in enumerate(lines):
        if line.strip() == "" and current["lines"]:
            turns.append({"start": current["start"], "end": i, "lines": current["lines"]})
            current = {"start": i + 1, "lines": []}
        else:
            if not current["lines"]:
                current["start"] = i
            current["lines"].append(line)
    if current["lines"]:
        turns.append({"start": current["start"], "end": len(lines), "lines": current["lines"]})

    # Sentence-level dedup: split each turn into sentences, track seen ones
    def _normalize_sentence(s: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

    def _to_sentences(text: str) -> list[str]:
        return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 20]

    seen_sentences: set[str] = set()
    remove_turn_ranges: list[tuple[int, int]] = []

    for turn in turns:
        turn_text = "\n".join(turn["lines"])
        words = re.findall(r"\w+", turn_text)

        # Skip metadata lines and short turns
        if len(words) < min_block_words:
            for sent in _to_sentences(turn_text):
                seen_sentences.add(_normalize_sentence(sent))
            continue

        sentences = _to_sentences(turn_text)
        if not sentences:
            continue

        dupe_count = sum(1 for s in sentences if _normalize_sentence(s) in seen_sentences)
        dupe_ratio = dupe_count / len(sentences) if sentences else 0

        if dupe_ratio > 0.6 and len(words) > 50:
            remove_turn_ranges.append((turn["start"], turn["end"]))
            LOG.info(
                "Removing duplicate turn at lines %d-%d (%.0f%% sentences duplicated, %d words)",
                turn["start"], turn["end"], dupe_ratio * 100, len(words),
            )
        else:
            for sent in sentences:
                seen_sentences.add(_normalize_sentence(sent))

    if not remove_turn_ranges:
        return text

    remove_lines = set()
    for start, end in remove_turn_ranges:
        for i in range(start, end):
            remove_lines.add(i)

    result_lines = [line for i, line in enumerate(lines) if i not in remove_lines]

    # Clean up excessive blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(result_lines))
    return cleaned


# ---------------------------------------------------------------------------
# Phase 2: Gemini-assisted relabeling
# ---------------------------------------------------------------------------


def init_gemini():
    """Initialize Gemini client."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        LOG.warning("No Gemini API key found; skipping Phase 2")
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        LOG.warning("Failed to initialize Gemini: %s", e)
        return None


def extract_speaker_labels(text: str) -> list[str]:
    """Extract unique speaker labels from transcript text."""
    labels = set()
    for m in re.finditer(r"^([A-Z][A-Za-z0-9 &()'\-,.]+):\s", text, re.MULTILINE):
        label = m.group(1).strip()
        if label not in ("Stats", "Speaker"):
            labels.add(label)
    return sorted(labels)


def has_generic_labels(labels: list[str]) -> bool:
    """Check if any labels are generic/unresolved."""
    generic_patterns = [
        r"^Host$", r"^CTA Host$", r"^Interviewee \d+$", r"^Participant \d+$",
        r"^Member \d+$", r"^Leader \d+$", r"^Speaker \d*$",
        r"^Unknown", r"^Voice \d+$", r"^Guest$",
        r"^Survivor", r"^Community Member",
        r"^Young Woman$", r"^Young Man$",
    ]
    for label in labels:
        for pat in generic_patterns:
            if re.match(pat, label):
                return True
    return False


def relabel_with_gemini(
    client,
    transcript_text: str,
    job: dict,
    yt_metadata: dict,
    current_labels: list[str],
) -> dict[str, str]:
    """Ask Gemini to suggest better speaker labels.

    Returns a dict of {old_label: new_label} for labels that should change.
    """
    title = yt_metadata.get("title", "Unknown")
    channel = yt_metadata.get("channel", "Unknown")
    description = (yt_metadata.get("description") or "")[:1500]

    primary = job.get("primary_speaker_name", "")
    host = job.get("host_name", "")
    guest = job.get("guest_name", "")
    content_format = job.get("content_format", "")

    known = []
    for s in job.get("known_speakers") or []:
        if isinstance(s, str):
            known.append(s)
        elif isinstance(s, dict):
            known.append(s.get("name", ""))

    # Get first ~2000 chars of transcript for context
    transcript_excerpt = transcript_text[:3000]

    prompt = textwrap.dedent(f"""\
    You are analyzing a transcript to improve speaker label accuracy.

    VIDEO METADATA:
    - Title: {title}
    - Channel: {channel}
    - Format: {content_format}
    - Description: {description}

    KNOWN SPEAKERS FROM CONFIG:
    - Primary speaker: {primary}
    - Host: {host}
    - Guest: {guest}
    - Other known: {', '.join(known) if known else 'none'}

    CURRENT SPEAKER LABELS IN TRANSCRIPT:
    {', '.join(current_labels)}

    TRANSCRIPT EXCERPT (first ~3000 chars):
    ---
    {transcript_excerpt}
    ---

    TASK:
    For each current speaker label, decide if it should be renamed to a more
    specific/accurate name. Rules:
    1. Only rename if you are CONFIDENT about the identity
    2. Named speakers (Banky W, Philip Karanja, etc.) should stay as-is
    3. "Audience" is fine for crowd/congregation responses
    4. "Narrator" is fine for documentary narration
    5. "News Reader" is fine for news clip voiceovers
    6. For generic labels like "Host", "Interviewee N", "Participant N":
       - Use the video metadata to identify them if possible
       - If you can't identify them, keep the generic label
    7. "CTA Host" should be renamed to the actual host name if identifiable
    8. Do NOT invent names — only use names from metadata/transcript/config

    Respond with ONLY a JSON object mapping old labels to new labels.
    Only include labels that should CHANGE. Example:
    {{"Host": "Richard Njau", "Interviewee 1": "Survivor (Female)"}}

    If no labels need changing, respond with: {{}}
    """)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        resp_text = response.text.strip()
        # Extract JSON from response
        json_match = re.search(r"\{[^{}]*\}", resp_text, re.DOTALL)
        if json_match:
            renames = json.loads(json_match.group())
            # Validate: only accept string->string mappings
            validated = {}
            for old, new in renames.items():
                if isinstance(old, str) and isinstance(new, str) and old in current_labels:
                    validated[old] = new
            return validated
    except Exception as e:
        LOG.warning("Gemini relabeling failed: %s", e)

    return {}


def _detect_missing_host(job: dict, current_labels: list[str]) -> str | None:
    """Check if the job config defines a host/guest who's missing from the transcript."""
    host = clean_text(str(job.get("host_name") or ""))
    if host and host not in current_labels:
        for label in current_labels:
            if host.lower() in label.lower():
                return None
        return host
    return None


def resegment_with_gemini(
    client,
    transcript_text: str,
    job: dict,
    yt_metadata: dict,
    missing_speaker: str,
) -> str | None:
    """Ask Gemini to resegment transcript to include a missing speaker.

    Returns the full resegmented transcript text, or None if it failed.
    """
    title = yt_metadata.get("title", "Unknown")
    channel = yt_metadata.get("channel", "Unknown")
    description = (yt_metadata.get("description") or "")[:1500]
    primary = job.get("primary_speaker_name", "")
    content_format = job.get("content_format", "")

    # Split into header and body
    lines = transcript_text.split("\n")
    header_lines = []
    body_start = 0
    for i, line in enumerate(lines):
        if re.match(r"^[A-Z][A-Za-z0-9 &()'\-,.]+:\s", line) and i > 2:
            body_start = i
            break
        header_lines.append(line)

    body_text = "\n".join(lines[body_start:])

    prompt = textwrap.dedent(f"""\
    This transcript is from a video titled "{title}" on the channel "{channel}".
    Format: {content_format}. Description: {description}

    The transcript currently attributes everything to "{primary}", but the video
    is actually a conversation between "{primary}" and "{missing_speaker}" (the host/interviewer).

    Please resegment the following transcript to properly attribute dialogue.
    Where "{missing_speaker}" is asking questions or making comments, label those
    parts with "{missing_speaker}:".

    CRITICAL RULES:
    1. Do NOT change any words in the transcript
    2. Do NOT add or remove any content
    3. ONLY split the existing text and add speaker labels
    4. Use the format "Speaker Name: text" for each turn
    5. Separate turns with a blank line
    6. Look for question patterns, interviewer prompts, topic transitions
    7. If you cannot confidently identify the host's parts, return the text unchanged

    TRANSCRIPT TO RESEGMENT:
    ---
    {body_text[:15000]}
    ---

    Return ONLY the resegmented transcript text (speaker turns separated by blank lines).
    """)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        new_body = response.text.strip()

        # Validate: new text should have the missing speaker
        if missing_speaker + ":" not in new_body:
            LOG.warning("  Gemini didn't add the missing speaker; keeping original")
            return None

        # Validate: word count shouldn't change dramatically
        old_words = len(re.findall(r"\w+", body_text))
        new_words = len(re.findall(r"\w+", new_body))
        if abs(new_words - old_words) / max(old_words, 1) > 0.15:
            LOG.warning(
                "  Gemini changed word count too much (%d → %d); keeping original",
                old_words, new_words,
            )
            return None

        header = "\n".join(header_lines)
        return header + "\n" + new_body + "\n"

    except Exception as e:
        LOG.warning("  Gemini resegmentation failed: %s", e)
        return None


def apply_renames(text: str, renames: dict[str, str]) -> str:
    """Apply speaker label renames to transcript text."""
    for old_label, new_label in renames.items():
        if old_label == new_label:
            continue
        pattern = re.compile(r"^" + re.escape(old_label) + r":", re.MULTILINE)
        text = pattern.sub(f"{new_label}:", text)
        LOG.info("  Renamed: '%s' → '%s'", old_label, new_label)
    return text


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def process_job(
    job_name: str,
    job: dict,
    *,
    client=None,
    do_backup: bool = True,
    phase1_only: bool = False,
) -> bool:
    path = transcript_path_for_job(job_name, job)
    if not path:
        LOG.warning("No transcript found for %s", job_name)
        return False

    LOG.info("Processing: %s (%s)", job_name, path.name)
    original_text = path.read_text("utf-8", errors="replace")

    # Phase 1: deterministic fixes
    text = fix_corrupted_labels(original_text, job_name)
    text = remove_duplicate_blocks(text)

    # Phase 2: Gemini relabeling and speaker resegmentation
    if not phase1_only and client:
        labels = extract_speaker_labels(text)

        # Check for missing speakers (host defined in config but absent in transcript)
        missing_host = _detect_missing_host(job, labels)
        if missing_host:
            LOG.info("  Missing speaker detected: '%s' — asking Gemini to resegment", missing_host)
            yt_meta = load_yt_metadata(job_name)
            resegmented = resegment_with_gemini(client, text, job, yt_meta, missing_host)
            if resegmented:
                text = resegmented
                labels = extract_speaker_labels(text)

        if has_generic_labels(labels):
            LOG.info("  Generic labels found: %s — consulting Gemini", labels)
            yt_meta = load_yt_metadata(job_name)
            renames = relabel_with_gemini(client, text, job, yt_meta, labels)
            if renames:
                text = apply_renames(text, renames)
            else:
                LOG.info("  Gemini suggested no changes")
        else:
            LOG.info("  All labels look specific — skipping Gemini")

    if text == original_text:
        LOG.info("  No changes needed")
        return False

    if do_backup:
        backup_file(path)

    text = repair_transcript_text(text)
    path.write_text(text, "utf-8")
    LOG.info("  Updated: %s", path)
    return True


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'\"")
        if val:
            os.environ.setdefault(key, val)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fix speaker labels in transcripts")
    p.add_argument("--jobs", nargs="+", help="Specific job keys to process")
    p.add_argument("--country", default="all", choices=["all", "kenya", "nigeria"])
    p.add_argument("--phase1-only", action="store_true", help="Only run deterministic fixes")
    p.add_argument("--no-backup", action="store_true", help="Skip backup creation")
    p.add_argument("--log-file", help="Write logs to file")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            *([] if not args.log_file else [logging.FileHandler(args.log_file)]),
        ],
    )

    load_env(ROOT / ".env")
    runtime = build_runtime()
    job_names = select_jobs(runtime, args.country, args.jobs)
    jobs = runtime["VIDEO_JOBS"]

    LOG.info("Selected %d jobs", len(job_names))

    client = None
    if not args.phase1_only:
        client = init_gemini()
        if not client:
            LOG.warning("Gemini not available; running Phase 1 only")

    updated = 0
    for jn in job_names:
        job = jobs[jn]
        if process_job(jn, job, client=client, do_backup=not args.no_backup, phase1_only=args.phase1_only):
            updated += 1

    LOG.info("Done. Updated %d / %d transcripts.", updated, len(job_names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
