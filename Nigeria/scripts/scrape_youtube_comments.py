"""Scrape YouTube comments for Banky Wellington videos that don't yet have comments.

Uses yt-dlp's --write-comments to dump all comments+replies as JSON, then flattens
into the same xlsx schema used in `Nigeria/Audience Analysis/Audience Comments - Raw/Banky Wellington/YouTube/`:
columns = author | comment | likes | reply_count
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "Nigeria/Audience Analysis/Audience Comments - Raw" / "Banky Wellington" / "YouTube"
TMP = ROOT / "temp" / "yt_comments"
TMP.mkdir(parents=True, exist_ok=True)

# (yt_id, output_file_stem). Already-existing files are skipped.
VIDEOS = [
    # First batch (already scraped in earlier run):
    ("SoVSXTTH2dg", "Face it Like a Man"),
    ("qFHXI0jHJRM", "Faith after a Fall"),
    ("9e9zAjM9wuA", "The Prison of Pornography"),
    # Channel sweep — Road to Freedom series (siblings to Prison of Pornography)
    ("RNGVBuXuTao", "The Road to Freedom Part 1"),
    ("mwOKheQRqJo", "The Permission of Pride - Road To Freedom Part 2"),
    ("rZM63_3c4t0", "Winning but Wounded - Road to Freedom Part 3"),
    # Other candidates: explicitly relational / male-themed
    ("78lX8sZ5QpE", "14 Couple Questions with Banky and Adesua"),
    ("kMnjdrh9mSY", "Wounded Warriors"),
    ("ItAlmvbHfi4", "Under Construction - Matters of the Mind"),
    ("9bOOEuiVEeY", "Faith after a Fall Part II"),
    ("cgfjIil40tI", "Prison Break"),
]


def scrape_one(yt_id: str, stem: str) -> int:
    out_path = OUT_DIR / f"{stem}.xlsx"
    if out_path.exists():
        existing = pd.read_excel(out_path)
        print(f"  ⏭  {stem}.xlsx already exists ({len(existing)} rows) — skipping")
        return len(existing)
    workdir = TMP / yt_id
    workdir.mkdir(exist_ok=True)
    out_template = str(workdir / "%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        f"https://www.youtube.com/watch?v={yt_id}",
        "--skip-download",
        "--write-info-json",
        "--write-comments",
        "--extractor-args", "youtube:max_comments=all,all,all,all;comment_sort=top",
        "-o", out_template,
        "--no-warnings",
    ]
    print(f"  → yt-dlp {yt_id} ...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"     FAILED: {res.stderr[:400]}")
        return 0

    info_path = workdir / f"{yt_id}.info.json"
    if not info_path.exists():
        print(f"     no info json")
        return 0

    info = json.loads(info_path.read_text())
    comments = info.get("comments") or []
    rows = []
    for c in comments:
        rows.append({
            "author": c.get("author") or "",
            "comment": c.get("text") or "",
            "likes": c.get("like_count") or 0,
            "reply_count": 0,  # yt-dlp flattens replies; reply_count is per top-level
        })
    df = pd.DataFrame(rows)
    df.to_excel(out_path, index=False)
    print(f"     wrote {len(df)} rows -> {out_path.relative_to(ROOT)}")
    return len(df)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for yt_id, stem in VIDEOS:
        total += scrape_one(yt_id, stem)
    print(f"\nTotal comments scraped: {total}")
    # cleanup
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
