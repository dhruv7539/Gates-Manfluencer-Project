"""
Speaker diarization using NVIDIA NeMo Sortformer.

Sortformer is an end-to-end neural diarizer that predicts speaker activity
directly.  This module:

  1. Creates the NeMo-style manifest JSON required as input.
  2. Runs diarization via the NeMo Python API.
  3. Parses the RTTM output into a clean list of speaker segments.
"""

import json
import logging
from pathlib import Path

from config import DEFAULT_SORTFORMER_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Manifest creation
# ---------------------------------------------------------------------------

def create_manifest(
    audio_path: str,
    manifest_path: str,
    duration: float,
    num_speakers: int | None = None,
) -> str:
    """
    Write a single-entry NeMo manifest JSONL file.

    NeMo diarization expects each line to be a JSON object with at least:
        {"audio_filepath": "...", "offset": 0, "duration": ..., "label": "infer",
         "text": "-", "num_speakers": N}
    """
    entry: dict = {
        "audio_filepath": str(Path(audio_path).resolve()),
        "offset": 0,
        "duration": duration,
        "label": "infer",
        "text": "-",
    }
    if num_speakers is not None and num_speakers > 0:
        entry["num_speakers"] = num_speakers

    manifest = Path(manifest_path)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    logger.info("Manifest written: %s", manifest)
    return str(manifest)


# ---------------------------------------------------------------------------
# Run Sortformer diarization
# ---------------------------------------------------------------------------

def run_sortformer_diarization(
    audio_path: str,
    manifest_path: str,
    output_dir: str,
    num_speakers: int | None = None,
    model_name: str = DEFAULT_SORTFORMER_MODEL,
) -> list[dict]:
    """
    Run Sortformer diarization on *audio_path* and return speaker segments.

    The function loads the pretrained Sortformer model via NeMo, points it at
    the manifest, runs inference, then parses the resulting RTTM file.

    Returns
    -------
    list[dict]  — each dict has keys: speaker, start, end
    """
    try:
        from nemo.collections.asr.models import SortformerEncDecDiarModel
    except ImportError:
        raise ImportError(
            "NVIDIA NeMo is not installed or the Sortformer model class is unavailable.\n"
            "Install NeMo with:  pip install nemo_toolkit[asr]\n"
            "See README.md for details."
        )

    from omegaconf import OmegaConf

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    logger.info("Loading Sortformer model: %s …", model_name)
    model = SortformerEncDecDiarModel.from_pretrained(model_name=model_name)

    # Build / override the diarization config the model uses at inference time.
    # Sortformer expects a test_ds section pointing at the manifest.
    cfg_overrides = {
        "test_ds": {
            "manifest_filepath": str(Path(manifest_path).resolve()),
            "batch_size": 1,
            "sample_rate": 16000,
        },
        "diarizer": {
            "out_dir": str(out.resolve()),
        },
    }
    if num_speakers is not None and num_speakers > 0:
        cfg_overrides["diarizer"]["oracle_num_speakers"] = num_speakers

    model.cfg = OmegaConf.merge(model.cfg, OmegaConf.create(cfg_overrides))

    logger.info("Running Sortformer diarization …")
    model.eval()
    model.test_batch()

    # Sortformer writes RTTM files into the output directory.
    rttm_files = sorted(out.rglob("*.rttm"))
    if not rttm_files:
        # Fallback: some NeMo versions write into a pred_rttms sub-dir.
        rttm_files = sorted(out.rglob("pred_rttms/*.rttm"))
    if not rttm_files:
        raise FileNotFoundError(
            f"Sortformer completed but no RTTM files found under {out}. "
            "Check NeMo logs for errors."
        )

    rttm_path = rttm_files[0]
    logger.info("Parsing RTTM: %s", rttm_path)
    segments = parse_rttm(str(rttm_path))
    logger.info("Diarization produced %d segments across %d speakers.",
                len(segments), len({s["speaker"] for s in segments}))
    return segments


# ---------------------------------------------------------------------------
# RTTM parsing
# ---------------------------------------------------------------------------

def parse_rttm(rttm_path: str) -> list[dict]:
    """
    Parse a standard RTTM file into a sorted list of speaker segments.

    RTTM line format (space-separated):
        SPEAKER <file> 1 <start> <dur> <NA> <NA> <speaker_id> <NA> <NA>

    Returns
    -------
    list[dict] with keys: speaker (str), start (float), end (float)
        Speaker labels are normalised to "Speaker 1", "Speaker 2", …
    """
    path = Path(rttm_path)
    if not path.exists():
        raise FileNotFoundError(f"RTTM file not found: {path}")

    raw_segments: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 8 or parts[0] != "SPEAKER":
            continue
        start = float(parts[3])
        dur = float(parts[4])
        raw_label = parts[7]
        raw_segments.append({
            "raw_speaker": raw_label,
            "start": round(start, 3),
            "end": round(start + dur, 3),
        })

    raw_segments.sort(key=lambda s: s["start"])

    # Map raw IDs → human-friendly "Speaker N" labels (1-indexed, ordered by
    # first appearance).
    label_map: dict[str, str] = {}
    counter = 0
    for seg in raw_segments:
        raw = seg["raw_speaker"]
        if raw not in label_map:
            counter += 1
            label_map[raw] = f"Speaker {counter}"

    segments = [
        {"speaker": label_map[s["raw_speaker"]], "start": s["start"], "end": s["end"]}
        for s in raw_segments
    ]
    return segments
