import re
from pathlib import Path


BAD_JSON_KEYS = {"turns", "speaker", "text"}
NORMAL_SPEAKER_RE = re.compile(r"^([^:\n]{1,120}):\s*(.*)$")
JSON_SPEAKER_RE = re.compile(r'^"speaker"\s*:\s*"(.+?)"\s*,?\s*$')
JSON_TEXT_RE = re.compile(r'^"text"\s*:\s*"(.*)$')
INLINE_GENERIC_SPEAKER_RE = re.compile(
    r'(?<!\n)(?:(?<=\s)|^)((?:Speaker \d+|Unknown|Narrator|Audience|Host|Guest)):'
)
INLINE_NAMED_SPEAKER_RE = re.compile(
    r"(?<!\n)(?:(?<=\s)|^)([A-Z][A-Za-z0-9&().'/-]*(?: [A-Z0-9][A-Za-z0-9&().'/-]*){1,5}):"
)
SINGLE_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9&().'/-]{1,40}$")
JSON_TAIL_RE = re.compile(
    r'(?:"\s*,\s*\{.*|"\s*\}\]?\}?,?|\s*,\s*\{\s*)$',
    re.IGNORECASE,
)
PAREN_CONTENT_RE = re.compile(r"\([^)]*\)")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def clean_turn_text(text: str) -> str:
    normalized = clean_text(text).replace(r"\/", "/").replace(r"\"", '"')
    previous = None
    while normalized and normalized != previous:
        previous = normalized
        normalized = JSON_TAIL_RE.sub("", normalized).strip()
        normalized = normalized.rstrip('",')
    return clean_text(normalized)


def normalize_speaker_label(label: str) -> str:
    return clean_text(label).strip('"').strip("'")


def is_valid_output_speaker(label: str) -> bool:
    normalized = normalize_speaker_label(label).lower()
    return bool(normalized) and normalized not in BAD_JSON_KEYS


def is_jsonish_transcript_text(text: str) -> bool:
    lowered = (text or "").lower()
    return '"speaker"' in lowered or '"text"' in lowered or '"turns"' in lowered


def preprocess_jsonish_text(text: str) -> str:
    normalized = text or ""
    normalized = re.sub(r'(?<!\n)("turns"\s*:\s*\[\{)', r"\n\1\n", normalized)
    normalized = re.sub(r'(?<!\n)("speaker"\s*:)', r"\n\1", normalized)
    normalized = re.sub(r'(?<!\n)("text"\s*:)', r"\n\1", normalized)
    normalized = re.sub(r'\},\s*\{', "\n}, {\n", normalized)
    normalized = normalized.replace("}]}", '\n}]}\n')
    return normalized


def flatten_embedded_json_blocks(text: str) -> str:
    normalized = text or ""
    speaker_replacements = [
        r'\s*"turns"\s*:\s*\[\{\s*"speaker"\s*:\s*"([^"]+)"\s*,\s*"text"\s*:\s*"',
        r'"\s*,\s*\{\s*"speaker"\s*:\s*"([^"]+)"\s*,\s*"text"\s*:\s*"',
        r'"\s*\},\s*\{\s*"speaker"\s*:\s*"([^"]+)"\s*,\s*"text"\s*:\s*"',
        r'"\s*\}\]\s*,\s*\{\s*"speaker"\s*:\s*"([^"]+)"\s*,\s*"text"\s*:\s*"',
    ]
    for pattern in speaker_replacements:
        normalized = re.sub(
            pattern,
            lambda match: f"\n\n{normalize_speaker_label(match.group(1))}: ",
            normalized,
        )
    normalized = re.sub(r'\s*"text"\s*:\s*"', " ", normalized)
    normalized = re.sub(r'"\s*\}\]?\}?,?', "", normalized)
    normalized = normalized.replace(r"\/", "/").replace(r"\"", '"')
    return normalized


def parse_transcript_style_lines(text: str) -> list[dict]:
    refined = []
    current = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = NORMAL_SPEAKER_RE.match(line)
        if match and is_valid_output_speaker(match.group(1)):
            if current and clean_text(current.get("text", "")):
                refined.append(
                    {
                        "speaker": normalize_speaker_label(current["speaker"]) or "Unknown",
                        "text": clean_text(current["text"]),
                    }
                )
            current = {"speaker": match.group(1), "text": match.group(2)}
            continue
        if current is not None:
            current["text"] = clean_text(current["text"] + " " + line)
    if current and clean_text(current.get("text", "")):
        refined.append(
            {
                "speaker": normalize_speaker_label(current["speaker"]) or "Unknown",
                "text": clean_text(current["text"]),
            }
        )
    return refined


def _strip_json_text_tail(fragment: str) -> tuple[str, bool]:
    text = fragment.rstrip()
    for suffix in ('"}]},', '"}]}', '"}]', '"}, {', '"},', '"}', '"'):
        if text.endswith(suffix):
            return text[: -len(suffix)], True
    return text, False


def extract_jsonish_turns(text: str) -> list[dict]:
    text = preprocess_jsonish_text(text)
    turns = []
    current_normal = None
    json_speaker = None
    json_text_parts = []
    collecting_json_text = False
    last_speaker = None

    def flush_normal() -> None:
        nonlocal current_normal, last_speaker
        if current_normal and clean_text(current_normal.get("text", "")):
            speaker = normalize_speaker_label(current_normal["speaker"]) or "Unknown"
            turns.append(
                {
                    "speaker": speaker,
                    "text": clean_text(current_normal["text"]),
                }
            )
            last_speaker = speaker
        current_normal = None

    def flush_json() -> None:
        nonlocal json_speaker, json_text_parts, collecting_json_text, last_speaker
        speaker = normalize_speaker_label(json_speaker or "")
        text_value = clean_text(" ".join(part for part in json_text_parts if part))
        text_value = text_value.replace(r"\/", "/").replace(r"\"", '"')
        if is_valid_output_speaker(speaker) and text_value:
            turns.append({"speaker": speaker, "text": text_value})
            last_speaker = speaker
        json_speaker = None
        json_text_parts = []
        collecting_json_text = False

    for raw_line in (text or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            flush_normal()
            continue

        if collecting_json_text:
            fragment, done = _strip_json_text_tail(stripped)
            if fragment:
                json_text_parts.append(fragment)
            if done:
                flush_json()
            continue

        speaker_match = JSON_SPEAKER_RE.match(stripped)
        if speaker_match:
            flush_normal()
            if json_speaker and json_text_parts:
                flush_json()
            json_speaker = speaker_match.group(1)
            continue

        text_match = JSON_TEXT_RE.match(stripped)
        if text_match and (json_speaker or last_speaker):
            if not json_speaker:
                json_speaker = last_speaker
            fragment, done = _strip_json_text_tail(text_match.group(1))
            json_text_parts = [fragment] if fragment else []
            if done:
                flush_json()
            else:
                collecting_json_text = True
            continue

        if stripped in {'"turns": [{', "{", "}", "}, {", "}]}", "}]}"}:
            flush_normal()
            continue

        normal_match = NORMAL_SPEAKER_RE.match(stripped)
        if normal_match and is_valid_output_speaker(normal_match.group(1)):
            flush_normal()
            current_normal = {
                "speaker": normal_match.group(1),
                "text": normal_match.group(2),
            }
            continue

        if current_normal is not None:
            current_normal["text"] = clean_text(current_normal["text"] + " " + stripped)

    flush_normal()
    if json_speaker and json_text_parts:
        flush_json()
    return turns


def sanitize_output_turns(turns: list[dict]) -> list[dict]:
    if not turns:
        return []

    invalid_labels = {
        normalize_speaker_label(turn.get("speaker", "")).lower()
        for turn in turns
        if normalize_speaker_label(turn.get("speaker", "")).lower() in BAD_JSON_KEYS
    }
    jsonish_text = any(is_jsonish_transcript_text(turn.get("text", "")) for turn in turns)
    if invalid_labels or jsonish_text:
        serialized = "\n".join(
            f'{turn.get("speaker", "Unknown")}: {turn.get("text", "")}'
            for turn in turns
        )
        repaired = extract_jsonish_turns(serialized)
        if repaired:
            return repaired

    cleaned = []
    for turn in turns:
        speaker = normalize_speaker_label(turn.get("speaker") or "Unknown") or "Unknown"
        text_value = clean_turn_text(turn.get("text", ""))
        if not text_value:
            continue
        if not is_valid_output_speaker(speaker):
            continue
        cleaned.append({"speaker": speaker, "text": text_value})

    if cleaned:
        serialized = "\n\n".join(f"{turn['speaker']}: {turn['text']}" for turn in cleaned)
        split_serialized = split_inline_speaker_markers(
            serialized, [turn["speaker"] for turn in cleaned]
        )
        reparsed = parse_transcript_style_lines(split_serialized)
        if reparsed:
            cleaned = reparsed
    return repair_split_speaker_names(cleaned)


def split_header_and_body(text: str) -> tuple[list[str], str]:
    lines = text.splitlines()
    header = []
    body_start = 0
    for index, line in enumerate(lines):
        if not line.strip():
            body_start = index + 1
            break
        header.append(line)
    else:
        body_start = len(lines)
    return header, "\n".join(lines[body_start:])


def render_transcript(header_lines: list[str], turns: list[dict]) -> str:
    lines = list(header_lines)
    lines.append("")
    for turn in turns:
        speaker = normalize_speaker_label(turn.get("speaker") or "Unknown") or "Unknown"
        text_value = clean_text(turn.get("text", ""))
        if not text_value:
            continue
        lines.append(f"{speaker}: {text_value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def collect_observed_speakers(text: str, header_lines: list[str]) -> list[str]:
    speakers = []
    for header_line in header_lines:
        if header_line.startswith("Speaker: "):
            speakers.append(normalize_speaker_label(header_line.split(":", 1)[1]))
    for raw_line in (text or "").splitlines():
        match = NORMAL_SPEAKER_RE.match(raw_line.strip())
        if match and is_valid_output_speaker(match.group(1)):
            speakers.append(normalize_speaker_label(match.group(1)))
    seen = set()
    ordered = []
    for speaker in speakers:
        if not speaker or speaker in seen:
            continue
        seen.add(speaker)
        ordered.append(speaker)
    return ordered


def collect_inline_candidate_speakers(text: str) -> list[str]:
    candidates = []
    for pattern in (INLINE_GENERIC_SPEAKER_RE, INLINE_NAMED_SPEAKER_RE):
        for match in pattern.finditer(text or ""):
            label = normalize_speaker_label(match.group(1))
            if is_valid_output_speaker(label):
                candidates.append(label)
    seen = set()
    ordered = []
    for speaker in candidates:
        if speaker in seen:
            continue
        seen.add(speaker)
        ordered.append(speaker)
    return ordered


def split_inline_speaker_markers(text: str, speakers: list[str]) -> str:
    normalized = text or ""
    combined_speakers = []
    for speaker in list(speakers) + collect_inline_candidate_speakers(normalized):
        if speaker not in combined_speakers:
            combined_speakers.append(speaker)
    for speaker in sorted(combined_speakers, key=len, reverse=True):
        pattern = rf'(?<!^)(?<!\n)\s+({re.escape(speaker)}):\s+'
        normalized = re.sub(pattern, r"\n\n\1: ", normalized)
    return normalized


def repair_split_speaker_names(turns: list[dict]) -> list[dict]:
    repaired = []
    for turn in turns:
        repaired.append(
            {
                "speaker": normalize_speaker_label(turn.get("speaker") or "Unknown") or "Unknown",
                "text": clean_text(turn.get("text", "")),
            }
        )

    for index in range(1, len(repaired)):
        previous = repaired[index - 1]
        current = repaired[index]
        speaker = current.get("speaker", "")
        if speaker in {"Unknown", "Narrator", "Audience", "Host", "Guest"}:
            continue
        if not SINGLE_NAME_RE.match(speaker):
            continue
        match = re.search(r"(?:(?<=\s)|^)([A-Z][A-Za-z0-9&().'/-]{1,40})$", previous.get("text", ""))
        if not match:
            continue
        first_name = match.group(1)
        combined_speaker = f"{first_name} {speaker}"
        previous["text"] = clean_text(previous["text"][: match.start(1)])
        current["speaker"] = combined_speaker

    return [turn for turn in repaired if clean_text(turn.get("text", ""))]


def restore_surname_speakers(turns: list[dict], header_lines: list[str]) -> list[dict]:
    full_names = []
    full_names.extend(collect_observed_speakers("", header_lines))
    for turn in turns:
        speaker = normalize_speaker_label(turn.get("speaker") or "")
        if " " in speaker:
            full_names.append(speaker)

    surname_map = {}
    for full_name in full_names:
        parts = [part for part in clean_text(full_name).split(" ") if part]
        if len(parts) < 2:
            continue
        surname = parts[-1]
        surname_map.setdefault(surname, set()).add(full_name)

    restored = []
    for turn in turns:
        speaker = normalize_speaker_label(turn.get("speaker") or "Unknown") or "Unknown"
        matches = surname_map.get(speaker, set())
        if len(matches) == 1:
            speaker = next(iter(matches))
        restored.append({"speaker": speaker, "text": clean_turn_text(turn.get("text", ""))})
    return restored


def primary_speaker_from_header(header_lines: list[str]) -> str:
    for header_line in header_lines:
        if header_line.startswith("Speaker: "):
            return normalize_speaker_label(header_line.split(":", 1)[1])
    return ""


def restore_initial_speakers(turns: list[dict], header_lines: list[str]) -> list[dict]:
    primary_speaker = primary_speaker_from_header(header_lines)
    if not primary_speaker:
        return turns

    primary_compact = PAREN_CONTENT_RE.sub(" ", primary_speaker)
    tokens = [token for token in clean_text(primary_compact).split(" ") if token]
    initials = {token[0].upper() for token in tokens if token}
    if not initials:
        return turns

    restored = []
    for turn in turns:
        speaker = normalize_speaker_label(turn.get("speaker") or "Unknown") or "Unknown"
        if len(speaker) == 1 and speaker.upper() in initials:
            speaker = primary_speaker
        restored.append({"speaker": speaker, "text": clean_turn_text(turn.get("text", ""))})
    return restored


def strip_trailing_name_echoes(turns: list[dict], header_lines: list[str]) -> list[dict]:
    primary_speaker = primary_speaker_from_header(header_lines)
    if not primary_speaker:
        return turns

    primary_compact = PAREN_CONTENT_RE.sub(" ", primary_speaker)
    name_tokens = [token for token in clean_text(primary_compact).split(" ") if len(token) > 1]
    if not name_tokens:
        return turns

    counts = {token: 0 for token in name_tokens}
    primary_turns = 0
    for turn in turns:
        speaker = normalize_speaker_label(turn.get("speaker") or "")
        if speaker != primary_speaker:
            continue
        primary_turns += 1
        text_value = clean_turn_text(turn.get("text", ""))
        for token in name_tokens:
            if re.search(rf"(?:\s|^){re.escape(token)}[.?!,;:]*$", text_value, re.IGNORECASE):
                counts[token] += 1

    echo_tokens = {
        token
        for token, count in counts.items()
        if count >= max(3, int(primary_turns * 0.4))
    }
    if not echo_tokens:
        return turns

    repaired = []
    for turn in turns:
        speaker = normalize_speaker_label(turn.get("speaker") or "Unknown") or "Unknown"
        text_value = clean_turn_text(turn.get("text", ""))
        if speaker == primary_speaker:
            for token in echo_tokens:
                text_value = re.sub(
                    rf"(?:\s|^){re.escape(token)}[.?!,;:]*$",
                    "",
                    text_value,
                    flags=re.IGNORECASE,
                ).strip()
        repaired.append({"speaker": speaker, "text": clean_turn_text(text_value)})
    return repaired


def repair_transcript_text(text: str) -> str:
    header_lines, body = split_header_and_body(text)
    body = flatten_embedded_json_blocks(preprocess_jsonish_text(body))
    body = split_inline_speaker_markers(body, collect_observed_speakers(body, header_lines))
    turns = parse_transcript_style_lines(body)
    if not turns:
        turns = extract_jsonish_turns(body)
    turns = sanitize_output_turns(turns)
    turns = repair_split_speaker_names(turns)
    turns = restore_surname_speakers(turns, header_lines)
    turns = restore_initial_speakers(turns, header_lines)
    turns = strip_trailing_name_echoes(turns, header_lines)
    return render_transcript(header_lines, turns)


def repair_transcript_file(path: str | Path) -> bool:
    transcript_path = Path(path)
    original = transcript_path.read_text(encoding="utf-8")
    repaired = repair_transcript_text(original)
    if repaired == original:
        return False
    transcript_path.write_text(repaired, encoding="utf-8")
    return True
