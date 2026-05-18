"""
Download audio from YouTube using yt-dlp and return metadata.
"""

import logging
import subprocess
import json
from pathlib import Path

from utils import safe_filename, ensure_dir

logger = logging.getLogger(__name__)


def download_youtube_audio(url: str, out_dir: str) -> dict:
    """
    Download best audio from a YouTube URL.

    Returns
    -------
    dict with keys:
        audio_path   – path to the downloaded audio file
        title        – video title
        uploader     – uploader / channel name
        channel      – channel name (may duplicate uploader)
        view_count   – int or None
        like_count   – int or None
        comment_count– int or None
        webpage_url  – canonical URL
    """
    out_dir = ensure_dir(Path(out_dir))

    # ------------------------------------------------------------------
    # Step 1: fetch metadata (JSON) without downloading yet
    # ------------------------------------------------------------------
    logger.info("Fetching video metadata …")
    meta_cmd = [
        "yt-dlp",
        "--no-download",
        "--dump-json",
        "--no-warnings",
        url,
    ]
    try:
        result = subprocess.run(
            meta_cmd, capture_output=True, text=True, check=True, timeout=120,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "yt-dlp is not installed or not on PATH. "
            "Install it with: pip install yt-dlp"
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"yt-dlp metadata fetch failed:\n{exc.stderr}") from exc

    info = json.loads(result.stdout)
    title = info.get("title", "untitled")
    safe_title = safe_filename(title)

    metadata = {
        "title": title,
        "uploader": info.get("uploader"),
        "channel": info.get("channel"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "webpage_url": info.get("webpage_url", url),
    }

    # ------------------------------------------------------------------
    # Step 2: download best audio
    # ------------------------------------------------------------------
    output_template = str(out_dir / f"{safe_title}.%(ext)s")
    dl_cmd = [
        "yt-dlp",
        "-x",                        # extract audio
        "--audio-format", "best",    # keep best quality
        "-o", output_template,
        "--no-warnings",
        "--no-playlist",
        url,
    ]
    logger.info("Downloading audio for: %s", title)
    try:
        subprocess.run(dl_cmd, capture_output=True, text=True, check=True, timeout=600)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"yt-dlp download failed:\n{exc.stderr}") from exc

    # Find the downloaded file (yt-dlp may choose different extensions)
    candidates = sorted(out_dir.glob(f"{safe_title}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(
            f"Download succeeded but no audio file found matching '{safe_title}.*' in {out_dir}"
        )

    audio_path = candidates[0]
    logger.info("Downloaded audio: %s (%.1f MB)", audio_path.name, audio_path.stat().st_size / 1e6)

    metadata["audio_path"] = str(audio_path)
    return metadata
