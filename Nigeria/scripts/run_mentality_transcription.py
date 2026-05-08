"""Run the full transcription pipeline for the 6 Banky MENtality episodes.

Hybrid: OpenAI Whisper API for speed + cost (~$2-3 total), pyannote local for
diarisation (free), Gemini for speaker labelling (cheap).

Pipeline per episode:
  1. Compress audio → 16kHz mono Opus 24 kbps (small enough for OpenAI's 25MB limit)
  2. Whisper API → word + segment timestamps  (parallel across all 6 episodes)
  3. Pyannote diarisation → speaker turns       (sequential, MPS-bound)
  4. Merge whisper + diarisation               (instant)
  5. Gemini speaker labelling with panel context (cheap)

Total wall time: ~60-90 min for all 6 episodes.

Output: Nigeria/Content Analysis/Content - Raw/Banky Wellington/Transcripts/<episode>.txt
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"
assert os.getenv("HF_TOKEN"), "HF_TOKEN missing"
assert os.getenv("GEMINI_API_KEY"), "GEMINI_API_KEY missing"

AUDIO_DIR    = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Banky Wellington" / "Audio Files"
CAPTIONS_DIR = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Banky Wellington" / "Captions"
TRANS_DIR    = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Banky Wellington" / "Transcripts"
TEMP_DIR     = ROOT / "temp" / "transcribe_mentality"
COMPRESSED_DIR = TEMP_DIR / "compressed"
for d in (CAPTIONS_DIR, TRANS_DIR, TEMP_DIR, COMPRESSED_DIR):
    d.mkdir(parents=True, exist_ok=True)

EPISODES = [
    {"audio": "Masculinity + Money.mp3",                  "yt_id": "f6WW9g5hqLI",
     "panel": ["Ebuka Obi-Uchendu", "Banky W (Bankole Wellington)", "Seun Kuti", "Noble Igwe"]},
    {"audio": "Masculinity + Relationships.mp3",          "yt_id": "mU5uAVhVEzA",
     "panel": ["Ebuka Obi-Uchendu", "Banky W", "Bovi Ugboma", "Do2dtun Energy gAD"]},
    {"audio": "Pt 2 Masculinity + Relationships.mp3",     "yt_id": "7uLzlPGsiVo",
     "panel": ["Ebuka Obi-Uchendu", "Banky W", "Alex Ikemefuna", "Johnny Drille"]},
    {"audio": "Masculinity + Friendship.mp3",             "yt_id": "XbFCPgdK8QQ",
     "panel": ["Ebuka Obi-Uchendu", "Banky W", "Alex Ikemefuna"]},
    {"audio": "Masculinity + Fatherhood.mp3",             "yt_id": "V_eHJfW87iA",
     "panel": ["Ebuka Obi-Uchendu", "Banky W", "Timi Dakolo", "Hermes Iyele"]},
    {"audio": "Masculinity + Young Boys.mp3",             "yt_id": "-YGXo00-fHw",
     "panel": ["Ebuka Obi-Uchendu", "Banky W", "IK Osakioduwa", "Murewa", "Sonariwo OnDeck"]},
]

DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
GEMINI_MODEL = "gemini-2.5-flash"
WHISPER_MODEL = "whisper-1"


# ---------------------------------------------------------------------------
# Step 0 — Captions (fast, useful for ground-truth verification later)
# ---------------------------------------------------------------------------
def download_captions(yt_id, audio_name):
    out_stem = Path(audio_name).stem
    target = CAPTIONS_DIR / f"{out_stem}.txt"
    if target.exists():
        return target
    cmd = [
        "yt-dlp",
        "--write-auto-sub", "--sub-lang", "en", "--sub-format", "vtt",
        "--skip-download",
        "-o", str(TEMP_DIR / f"{out_stem}.%(ext)s"),
        f"https://www.youtube.com/watch?v={yt_id}",
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    vtt = next(TEMP_DIR.glob(f"{out_stem}*.vtt"), None)
    if vtt is None:
        return None
    lines, seen = [], set()
    for line in vtt.read_text().splitlines():
        line = line.strip()
        if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean and clean not in seen:
            lines.append(clean)
            seen.add(clean)
    target.write_text("\n".join(lines))
    return target


# ---------------------------------------------------------------------------
# Step 1 — Compress audio for upload (16kHz mono Opus 24kbps, fits in 25MB)
# ---------------------------------------------------------------------------
def compress_audio(audio_path: Path) -> Path:
    out = COMPRESSED_DIR / f"{audio_path.stem}.ogg"
    if out.exists():
        return out
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libopus", "-b:a", "24k",
        str(out),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"  compressed {audio_path.name}: {size_mb:.1f} MB", flush=True)
    return out


def split_if_needed(compressed: Path, max_mb: int = 24) -> list[Path]:
    """Split into chunks if over OpenAI's 25MB limit. Each chunk = 30 min."""
    size_mb = compressed.stat().st_size / (1024 * 1024)
    if size_mb <= max_mb:
        return [compressed]
    chunk_dir = COMPRESSED_DIR / f"{compressed.stem}_chunks"
    chunk_dir.mkdir(exist_ok=True)
    if list(chunk_dir.glob("chunk_*.ogg")):
        return sorted(chunk_dir.glob("chunk_*.ogg"))
    cmd = [
        "ffmpeg", "-y", "-i", str(compressed),
        "-f", "segment", "-segment_time", "1800",  # 30 min chunks
        "-c", "copy",
        str(chunk_dir / "chunk_%03d.ogg"),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    chunks = sorted(chunk_dir.glob("chunk_*.ogg"))
    print(f"  split {compressed.name} ({size_mb:.1f} MB) → {len(chunks)} chunks", flush=True)
    return chunks


# ---------------------------------------------------------------------------
# Step 2 — Whisper API (per-chunk, runs in parallel for all episodes)
# ---------------------------------------------------------------------------
def whisper_transcribe(audio_path: Path) -> dict:
    """Returns OpenAI verbose_json for a single audio file (or chunk)."""
    client = OpenAI()
    with open(audio_path, "rb") as f:
        return client.audio.transcriptions.create(
            file=f,
            model=WHISPER_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        ).model_dump()


def transcribe_episode(audio_path: Path) -> dict:
    """Compress + chunk + transcribe + stitch. Returns whisper-shape dict."""
    cache = TEMP_DIR / f"{audio_path.stem}.whisper.json"
    if cache.exists():
        return json.loads(cache.read_text())

    print(f"  whisper-api: starting {audio_path.name}", flush=True)
    t0 = time.time()
    compressed = compress_audio(audio_path)
    chunks = split_if_needed(compressed)

    all_segments = []
    offset = 0.0
    for chunk in chunks:
        result = whisper_transcribe(chunk)
        for seg in result.get("segments", []):
            seg = dict(seg)
            seg["start"] = float(seg["start"]) + offset
            seg["end"] = float(seg["end"]) + offset
            all_segments.append(seg)
        # Bump offset by the chunk's duration (last segment end if available)
        if result.get("segments"):
            offset += float(result["segments"][-1]["end"])
        else:
            offset += float(result.get("duration", 1800.0))

    out = {"segments": all_segments, "language": "en"}
    cache.write_text(json.dumps(out, indent=1))
    print(f"  whisper-api: done {audio_path.name} in {time.time()-t0:.0f}s "
          f"({len(all_segments)} segments)", flush=True)
    return out


# ---------------------------------------------------------------------------
# Step 3 — Pyannote diarisation (sequential, MPS-bound)
# ---------------------------------------------------------------------------
_pipeline = None
def get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pyannote.audio import Pipeline
        import torch
        print("  pyannote: loading pipeline (~30s)...", flush=True)
        _pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=os.getenv("HF_TOKEN"))
        if torch.backends.mps.is_available():
            _pipeline.to(torch.device("mps"))
            print("  pyannote: using MPS", flush=True)
    return _pipeline


def _ensure_wav(audio_path: Path) -> Path:
    """Convert MP3 → 16kHz mono WAV (pyannote chokes on some MP3 framings)."""
    wav = COMPRESSED_DIR / f"{audio_path.stem}.wav"
    if wav.exists():
        return wav
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(wav),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return wav


def diarize(audio_path: Path):
    cache = TEMP_DIR / f"{audio_path.stem}.diarization.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pipeline = get_pipeline()
    # Convert to WAV first — pyannote has a known bug with some MP3 framings
    # (sample-count mismatch on first chunk). WAVs have predictable framing.
    wav_path = _ensure_wav(audio_path)
    print(f"  pyannote: diarising {audio_path.name} via {wav_path.name} (~10–20 min)...", flush=True)
    t0 = time.time()
    result = pipeline(str(wav_path))
    # pyannote 4.x returns DiarizeOutput wrapper; 3.x returned Annotation directly
    annotation = getattr(result, "speaker_diarization", result)
    turns = [{"start": float(seg.start), "end": float(seg.end), "speaker": str(label)}
             for seg, _, label in annotation.itertracks(yield_label=True)]
    cache.write_text(json.dumps(turns, indent=1))
    print(f"  pyannote: done {audio_path.name} in {time.time()-t0:.0f}s "
          f"({len(turns)} turns, {len({t['speaker'] for t in turns})} speakers)", flush=True)
    return turns


# ---------------------------------------------------------------------------
# Step 4 — Merge
# ---------------------------------------------------------------------------
def merge(whisper_result, turns):
    def speaker_at(t):
        for turn in turns:
            if turn["start"] <= t <= turn["end"]:
                return turn["speaker"]
        return min(turns, key=lambda x: min(abs(x["start"] - t), abs(x["end"] - t)))["speaker"]

    out, current_spk, current_text = [], None, []
    for seg in whisper_result.get("segments", []):
        spk = speaker_at(seg["start"])
        text = seg.get("text", "").strip()
        if not text:
            continue
        if spk != current_spk:
            if current_spk is not None:
                out.append(f"{current_spk}: {' '.join(current_text).strip()}")
            current_spk, current_text = spk, [text]
        else:
            current_text.append(text)
    if current_spk is not None:
        out.append(f"{current_spk}: {' '.join(current_text).strip()}")
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Step 5 — Gemini speaker labelling
# ---------------------------------------------------------------------------
LABEL_PROMPT = """You are a transcript editor. The transcript below uses generic labels (SPEAKER_00, SPEAKER_01, etc.) from automated diarisation. The actual speakers in this episode are listed below.

Your job: replace each generic label with the correct real name. Use voice/style/content cues — who tends to host, who introduces guests, who is being addressed by name, etc. Be consistent: the same SPEAKER_NN must always map to the same real name across the entire transcript.

If you can't determine a label with high confidence, leave it as-is. Output ONLY the corrected transcript, nothing else.

Episode panel: {panel}

Transcript:
---
{transcript}
---"""


def gemini_label(raw, panel):
    from google import genai
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = LABEL_PROMPT.format(panel=", ".join(panel), transcript=raw[:120000])
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return resp.text.strip()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def process_episode(ep, whisper_data):
    audio = AUDIO_DIR / ep["audio"]
    final = TRANS_DIR / f"{audio.stem}.txt"
    if final.exists():
        return final
    print(f"\n=== finalising {audio.stem} ===", flush=True)
    turns = diarize(audio)
    raw = merge(whisper_data, turns)
    raw_path = TEMP_DIR / f"{audio.stem}.raw_labelled.txt"
    raw_path.write_text(raw)
    print(f"  merge: {raw.count(chr(10)+chr(10))+1} speaker turns", flush=True)
    print(f"  gemini: relabelling speakers using panel: {', '.join(ep['panel'])}", flush=True)
    labelled = gemini_label(raw, ep["panel"])
    final.write_text(labelled)
    print(f"  ✓ {final.relative_to(ROOT)}", flush=True)
    return final


def main():
    print(f"=== Pipeline: OpenAI Whisper API + pyannote (MPS) + Gemini ===", flush=True)
    print(f"  episodes: {len(EPISODES)}", flush=True)
    print(f"  audio:    {AUDIO_DIR.relative_to(ROOT)}", flush=True)
    print(f"  output:   {TRANS_DIR.relative_to(ROOT)}", flush=True)
    t0 = time.time()

    # Step 0 — captions in parallel (fast network calls)
    print("\n--- Step 0: captions (parallel) ---", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda ep: download_captions(ep["yt_id"], ep["audio"]), EPISODES))
    print(f"  captions ready ({time.time()-t0:.0f}s elapsed)", flush=True)

    # Step 1+2 — compress + whisper API in parallel for all 6
    print("\n--- Step 1+2: compress + whisper API (parallel, all 6 at once) ---", flush=True)
    whisper_results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        future_to_ep = {ex.submit(transcribe_episode, AUDIO_DIR / ep["audio"]): ep for ep in EPISODES}
        for fut in concurrent.futures.as_completed(future_to_ep):
            ep = future_to_ep[fut]
            try:
                whisper_results[ep["audio"]] = fut.result()
            except Exception as e:
                print(f"  ✗ whisper failed for {ep['audio']}: {e}", flush=True)
    print(f"  all whisper done ({time.time()-t0:.0f}s elapsed)", flush=True)

    # Step 3-5 — pyannote (sequential MPS) + merge + gemini per episode
    print("\n--- Step 3+4+5: diarisation + merge + gemini (sequential) ---", flush=True)
    for ep in EPISODES:
        if ep["audio"] not in whisper_results:
            print(f"  skip {ep['audio']}: no whisper output", flush=True)
            continue
        try:
            process_episode(ep, whisper_results[ep["audio"]])
        except Exception as e:
            print(f"  ✗ failed for {ep['audio']}: {e}", flush=True)
            import traceback; traceback.print_exc()

    elapsed_min = (time.time() - t0) / 60
    print(f"\n========== ALL DONE ({elapsed_min:.0f} min total) ==========", flush=True)
    for p in sorted(TRANS_DIR.glob("*.txt")):
        words = sum(len(line.split(":", 1)[1].split()) for line in p.read_text().split("\n") if ":" in line)
        print(f"  {p.name}: {words:,} words", flush=True)


if __name__ == "__main__":
    main()
