"""
Configuration constants for the YouTube transcription pipeline.

Edit model names, paths, and tuning parameters here.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_TEMP_DIR = PROJECT_ROOT / "temp"
DEFAULT_MANIFEST_DIR = PROJECT_ROOT / "manifests"

# ---------------------------------------------------------------------------
# Audio settings
# ---------------------------------------------------------------------------
SAMPLE_RATE = 16000
CHANNELS = 1  # mono

# ---------------------------------------------------------------------------
# ASR — Parakeet
# ---------------------------------------------------------------------------
DEFAULT_PARAKEET_MODEL = "nvidia/parakeet-tdt-0.6b-v2"

# ---------------------------------------------------------------------------
# Diarization — Sortformer
# ---------------------------------------------------------------------------
DEFAULT_SORTFORMER_MODEL = "nvidia/diar_sortformer_4spk-v1"

# ---------------------------------------------------------------------------
# Merge tuning
# ---------------------------------------------------------------------------
WORD_SPEAKER_TOLERANCE = 0.5   # seconds: max distance to snap a word to a segment
TURN_MAX_GAP = 0.9             # seconds: gap before starting a new speaker turn

# ---------------------------------------------------------------------------
# Speaker naming
# ---------------------------------------------------------------------------
AUDIENCE_MAX_WORDS = 6         # turns with ≤ this many words may be labelled "Audience"
AUDIENCE_KEYWORDS = {
    "amen", "hallelujah", "proceed", "yes", "wow", "come on",
    "glory", "praise god", "praise the lord", "thank you jesus",
}
