"""Consolidate per-post Topic Relevant Comments into a single `Topic Relevant Comments/{Kenya,Nigeria}/`
folder with files named `<Creator>_<Post>.xlsx` and all @<handle> mentions stripped from the text column.

Deletes the old `Topic Relevant Comments - Kenya/` and `Topic Relevant Comments - Nigeria/` folders on success.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NEW_DIR = ROOT / "Topic Relevant Comments"
OLD_DIRS = {
    "Nigeria": ROOT / "Topic Relevant Comments - Nigeria",
    "Kenya": ROOT / "Topic Relevant Comments - Kenya",
}

MENTION_PATTERN = re.compile(r"@\w+")


def strip_mentions(t: str) -> str:
    if not isinstance(t, str):
        return ""
    cleaned = MENTION_PATTERN.sub("", t)
    # collapse whitespace introduced by removals
    return re.sub(r"\s+", " ", cleaned).strip()


def safe(s: str) -> str:
    return re.sub(r"[^\w\- ]+", "", s).strip()


def consolidate():
    NEW_DIR.mkdir(parents=True, exist_ok=True)
    for country, old_dir in OLD_DIRS.items():
        country_dir = NEW_DIR / country
        country_dir.mkdir(parents=True, exist_ok=True)
        if not old_dir.exists():
            print(f"  skip: {old_dir} does not exist")
            continue
        summary_rows = []
        for xlsx in sorted(old_dir.rglob("*.xlsx")):
            if xlsx.name.startswith("_") or xlsx.name.startswith("~$"):
                continue
            creator = xlsx.parent.name
            post_stem = xlsx.stem
            df = pd.read_excel(xlsx)
            if "text" not in df.columns:
                print(f"  ! {xlsx}: no 'text' column, skipping")
                continue
            original_n = len(df)
            # Strip all @<handle> mentions from every cell in the text column.
            df["text"] = df["text"].apply(strip_mentions)
            # Drop any rows that became empty after mention stripping.
            df = df[df["text"].str.len() > 0].reset_index(drop=True)
            out_name = f"{safe(creator)}_{safe(post_stem)}.xlsx"
            out_path = country_dir / out_name
            df.to_excel(out_path, index=False)
            summary_rows.append({
                "country": country,
                "creator": creator,
                "post": post_stem,
                "rows_in": original_n,
                "rows_out": len(df),
                "path": str(out_path.relative_to(ROOT)),
            })
            print(f"  [{country}] {out_name:<85}  {original_n} -> {len(df)} rows")
        # Per-country summary.
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_excel(country_dir / "_summary.xlsx", index=False)

    # Global summary at the top level.
    all_summary = []
    for country, old_dir in OLD_DIRS.items():
        country_dir = NEW_DIR / country
        for f in sorted(country_dir.glob("*.xlsx")):
            if f.name.startswith("_"):
                continue
            df = pd.read_excel(f)
            all_summary.append({"country": country, "file": f.name, "rows": len(df)})
    pd.DataFrame(all_summary).to_excel(NEW_DIR / "_summary.xlsx", index=False)
    print(f"\nWrote {NEW_DIR}")


def delete_old():
    for p in OLD_DIRS.values():
        if p.exists():
            shutil.rmtree(p)
            print(f"  removed {p}")


if __name__ == "__main__":
    consolidate()
    print("\nDeleting old folders...")
    delete_old()
    print("Done.")
