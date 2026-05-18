"""
Audio format conversion utilities using ffmpeg.
"""

import logging
import subprocess
import json
from pathlib import Path

from config import SAMPLE_RATE, CHANNELS

logger = logging.getLogger(__name__)


def _check_ffmpeg() -> None:
    """Raise RuntimeError if ffmpeg is not available."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, check=True, timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg is not installed or not on PATH.\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg\n"
            "  Windows: download from https://ffmpeg.org/download.html"
        )


def convert_to_wav_16k_mono(input_path: str, output_path: str) -> str:
    """
    Convert any audio file to 16 kHz mono PCM-16 WAV.

    Returns the output path on success.
    """
    _check_ffmpeg()

    inp = Path(input_path)
    out = Path(output_path)
    if not inp.exists():
        raise FileNotFoundError(f"Input audio not found: {inp}")

    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(inp),
        "-ac", str(CHANNELS),
        "-ar", str(SAMPLE_RATE),
        "-sample_fmt", "s16",      # PCM 16-bit
        "-f", "wav",
        str(out),
    ]

    logger.info("Converting %s → 16 kHz mono WAV …", inp.name)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed:\n{result.stderr}")

    if not out.exists() or out.stat().st_size < 1000:
        raise RuntimeError(f"Converted WAV is missing or suspiciously small: {out}")

    logger.info("WAV written: %s (%.1f MB)", out.name, out.stat().st_size / 1e6)
    return str(out)


def get_audio_duration(path: str) -> float:
    """
    Return the duration of an audio file in seconds using ffprobe.
    """
    _check_ffmpeg()

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}:\n{result.stderr}")

    info = json.loads(result.stdout)
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"Could not parse duration from ffprobe output for {path}") from exc

    logger.info("Audio duration: %.2f s", duration)
    return duration
