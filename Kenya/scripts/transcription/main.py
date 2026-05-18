#!/usr/bin/env python3
"""
YouTube Transcription Pipeline with Speaker Diarization
========================================================

Usage:
    python main.py --url "https://www.youtube.com/watch?v=XXXX"

Uses NVIDIA NeMo Parakeet (ASR) + Sortformer (diarization) to produce
a clean, speaker-attributed transcript from any YouTube video.
"""

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path

from config import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TEMP_DIR,
    DEFAULT_MANIFEST_DIR,
    DEFAULT_PARAKEET_MODEL,
    DEFAULT_SORTFORMER_MODEL,
    WORD_SPEAKER_TOLERANCE,
    TURN_MAX_GAP,
)
from utils import setup_logging, ensure_dir, safe_filename

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Transcribe a YouTube video with speaker diarization.",
    )
    p.add_argument("--url", required=True, help="YouTube video URL")
    p.add_argument("--output_dir", default=str(DEFAULT_OUTPUT_DIR),
                   help="Directory for final outputs (default: ./output)")
    p.add_argument("--temp_dir", default=str(DEFAULT_TEMP_DIR),
                   help="Directory for intermediate files (default: ./temp)")
    p.add_argument("--parakeet_model", default=DEFAULT_PARAKEET_MODEL,
                   help=f"Parakeet model name (default: {DEFAULT_PARAKEET_MODEL})")
    p.add_argument("--sortformer_model", default=DEFAULT_SORTFORMER_MODEL,
                   help=f"Sortformer model name (default: {DEFAULT_SORTFORMER_MODEL})")
    p.add_argument("--num_speakers", type=int, default=None,
                   help="Hint for number of speakers (optional)")
    p.add_argument("--keep_temp", action="store_true",
                   help="Keep temporary files after pipeline completes")
    p.add_argument("--tolerance", type=float, default=WORD_SPEAKER_TOLERANCE,
                   help=f"Word↔segment snap tolerance in seconds (default: {WORD_SPEAKER_TOLERANCE})")
    p.add_argument("--max_gap", type=float, default=TURN_MAX_GAP,
                   help=f"Max silence gap within a speaker turn (default: {TURN_MAX_GAP})")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging()
    t0 = time.time()

    output_dir = ensure_dir(Path(args.output_dir))
    temp_dir = ensure_dir(Path(args.temp_dir))
    manifest_dir = ensure_dir(DEFAULT_MANIFEST_DIR)

    # ------------------------------------------------------------------
    # Step 1 — Download audio + metadata
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 1: Downloading YouTube audio")
    logger.info("=" * 60)

    from downloader import download_youtube_audio

    metadata = download_youtube_audio(args.url, str(temp_dir))
    raw_audio = metadata["audio_path"]
    slug = safe_filename(metadata.get("title", "video"))

    # ------------------------------------------------------------------
    # Step 2 — Convert to 16 kHz mono WAV
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 2: Converting to 16 kHz mono WAV")
    logger.info("=" * 60)

    from audio_utils import convert_to_wav_16k_mono, get_audio_duration

    wav_path = str(temp_dir / f"{slug}.wav")
    convert_to_wav_16k_mono(raw_audio, wav_path)

    duration = get_audio_duration(wav_path)
    metadata["wav_path"] = wav_path
    metadata["duration"] = duration

    # ------------------------------------------------------------------
    # Step 3 — Create diarization manifest
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 3: Creating diarization manifest")
    logger.info("=" * 60)

    from diarize import create_manifest

    manifest_path = str(manifest_dir / f"{slug}_manifest.json")
    create_manifest(wav_path, manifest_path, duration, args.num_speakers)

    # ------------------------------------------------------------------
    # Step 4 — Run Sortformer diarization
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 4: Running Sortformer speaker diarization")
    logger.info("=" * 60)

    from diarize import run_sortformer_diarization

    diar_out = str(temp_dir / "diarization")
    speaker_segments = run_sortformer_diarization(
        wav_path, manifest_path, diar_out,
        num_speakers=args.num_speakers,
        model_name=args.sortformer_model,
    )
    logger.info("Diarization: %d segments, %d speakers",
                len(speaker_segments),
                len({s["speaker"] for s in speaker_segments}))

    # ------------------------------------------------------------------
    # Step 5 — Run Parakeet ASR
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 5: Running Parakeet ASR transcription")
    logger.info("=" * 60)

    from transcribe import transcribe_with_parakeet

    asr_result = transcribe_with_parakeet(wav_path, model_name=args.parakeet_model)
    words = asr_result["words"]
    logger.info("ASR: %d words transcribed", len(words))

    if not words:
        logger.warning(
            "Parakeet returned no word-level timestamps. "
            "The transcript will be plain text without speaker attribution."
        )

    # ------------------------------------------------------------------
    # Step 6 — Merge ASR words with speaker segments
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 6: Merging ASR + diarization")
    logger.info("=" * 60)

    from merge import assign_speakers_to_words, collapse_words_into_turns, relabel_speakers

    if words:
        words_with_speakers = assign_speakers_to_words(
            words, speaker_segments, tolerance=args.tolerance,
        )
        turns = collapse_words_into_turns(words_with_speakers, max_gap=args.max_gap)
    else:
        # Fallback: single turn with full text, no speaker attribution
        turns = [{
            "speaker": "Speaker 1",
            "start": 0.0,
            "end": duration,
            "text": asr_result["full_text"],
        }]

    # ------------------------------------------------------------------
    # Step 7 — Re-label speakers
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 7: Relabelling speakers")
    logger.info("=" * 60)

    metadata["parakeet_model"] = args.parakeet_model
    metadata["sortformer_model"] = args.sortformer_model

    turns = relabel_speakers(turns, metadata)
    speaker_names = sorted({t["speaker"] for t in turns})
    logger.info("Final speakers: %s", ", ".join(speaker_names))

    # ------------------------------------------------------------------
    # Step 8 — Write outputs
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 8: Writing outputs")
    logger.info("=" * 60)

    from writers import write_transcript_txt, write_transcript_json, write_segments_csv

    txt_path = write_transcript_txt(turns, metadata, str(output_dir / f"{slug}.txt"))
    json_path = write_transcript_json(turns, metadata, str(output_dir / f"{slug}.json"))
    csv_path = write_segments_csv(turns, str(output_dir / f"{slug}_segments.csv"))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    if not args.keep_temp:
        logger.info("Cleaning up temporary files in %s …", temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE in %.1f s", elapsed)
    logger.info("=" * 60)

    print("\n✓ Pipeline complete!")
    print(f"  Transcript : {txt_path}")
    print(f"  JSON       : {json_path}")
    print(f"  CSV        : {csv_path}")
    print(f"  Duration   : {elapsed:.1f} s")


if __name__ == "__main__":
    main()
