"""Add a 'Reference Text/Context' column with source URL to each audience comment Final file.

For each comment in:
  Nigeria/Audience Analysis/Audience Comments - Final/<creator>_<topic>.xlsx

look it up in the raw scrape and resolve the source URL:
  - X tweets/replies: per-row URL stored in raw (each reply has its own X URL)
  - YouTube comments (Banky MENtality + standalone): URL = https://www.youtube.com/watch?v=<yt_id>
    of the episode the comment was scraped from. We search all candidate episodes
    by text match.
  - Instagram comments: URL = https://www.instagram.com/p/<post_id>/

Output: same filenames, with new column 'Reference Text/Context' populated.
"""
from __future__ import annotations

import re
from pathlib import Path
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RAW   = ROOT / "Nigeria" / "Audience Analysis" / "Audience Comments - Raw"
FINAL = ROOT / "Nigeria" / "Audience Analysis" / "Audience Comments - Final"

# MENtality podcast episode → YouTube ID
MENTALITY_YT = {
    "Masculinity + Money":              "f6WW9g5hqLI",
    "Masculinity + Relationships":      "mU5uAVhVEzA",
    "Pt 2 Masculinity + Relationships": "7uLzlPGsiVo",
    "Masculinity + Friendship":         "XbFCPgdK8QQ",
    "Masculinity + Fatherhood":         "V_eHJfW87iA",
    "Masculinity + Young Boys":         "-YGXo00-fHw",
}

# Banky standalone YouTube series → YouTube ID
BANKY_YT = {
    "Face it Like a Man":                                     "SoVSXTTH2dg",
    "Faith after a Fall":                                     "qFHXI0jHJRM",
    "The Prison of Pornography":                              "9e9zAjM9wuA",
    "The Road to Freedom Part 1":                             "RNGVBuXuTao",
    "The Permission of Pride - Road To Freedom Part 2":       "mwOKheQRqJo",
    "Winning but Wounded - Road to Freedom Part 3":           "rZM63_3c4t0",
    "14 Couple Questions with Banky and Adesua":              "78lX8sZ5QpE",
    "Wounded Warriors":                                       "kMnjdrh9mSY",
    "Under Construction - Matters of the Mind":               "ItAlmvbHfi4",
    "Faith after a Fall Part II":                             "9bOOEuiVEeY",
    "Prison Break":                                           "cgfjIil40tI",
}


def normalize(s: str) -> str:
    """Normalize text for matching across files (strip whitespace, smart quotes, html entities, emoji)."""
    s = str(s)
    s = s.replace("&amp;", "&")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("…", "...")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_x_url_index(raw_path: Path) -> dict[str, str]:
    """Build {normalized_text: parent_tweet_url} for an X-tweet raw file.

    Every reply gets the PARENT post URL (row 0 = the creator's own tweet that
    the audience is responding to), not its own reply URL. This gives the
    coder the context of what the audience was reacting to.
    """
    df = pd.read_excel(raw_path)
    parent_url = str(df.iloc[0]["url"]) if len(df) and "url" in df.columns else ""
    out = {}
    for _, r in df.iterrows():
        t = normalize(r.get("text", ""))
        if t:
            out.setdefault(t, parent_url)
    return out


def build_yt_index(raw_root: Path, name_to_yt_id: dict, prefix: str = "") -> dict[str, str]:
    """Build {normalized_comment: youtube_url} across multiple episode files."""
    out = {}
    for stem, yt_id in name_to_yt_id.items():
        f = raw_root / f"{stem}.xlsx"
        if not f.exists():
            continue
        df = pd.read_excel(f)
        col = "comment" if "comment" in df.columns else "text"
        for v in df[col].dropna():
            t = normalize(v)
            if t:
                out.setdefault(t, f"https://www.youtube.com/watch?v={yt_id}")
    return out


def build_ig_index(ig_root: Path) -> dict[str, str]:
    """Build {normalized_comment: instagram_url} from IG post files (filename embeds shortcode)."""
    out = {}
    if not ig_root.exists():
        return out
    for f in ig_root.glob("IG Post *.xlsx"):
        # Filename like "IG Post DQ6jTPkiIXC.xlsx" or "IG Post DSh0JSiiLvz - I Love You Bro.xlsx"
        m = re.match(r"IG Post ([A-Za-z0-9_-]+)", f.stem)
        if not m:
            continue
        shortcode = m.group(1)
        url = f"https://www.instagram.com/p/{shortcode}/"
        df = pd.read_excel(f)
        col = "comment" if "comment" in df.columns else "text"
        for v in df[col].dropna():
            t = normalize(v)
            if t:
                out.setdefault(t, url)
    return out


def add_reference_column(final_path: Path, lookup: dict[str, str], default_url: str = "") -> tuple[int, int]:
    """Read a Final xlsx, add 'Reference Text/Context' column, write back. Return (matched, total)."""
    df = pd.read_excel(final_path)
    text_col = "text" if "text" in df.columns else df.columns[0]
    refs = []
    matched = 0
    for v in df[text_col]:
        t = normalize(v)
        url = lookup.get(t, default_url)
        if url and url != default_url:
            matched += 1
        refs.append(url or default_url)
    df["Reference Text/Context"] = refs
    df.to_excel(final_path, index=False)
    return matched, len(df)


# ---- Per-file work ----

JOBS = [
    {
        "final": "Agba John Doe_Never Leave Marriage Because Husband Cheated.xlsx",
        "kind":  "x",
        "raw":   RAW / "Agba John Doe" / "Never Leave Marriage Because Husband Cheated.xlsx",
        "default_url": "https://x.com/jon_d_doe/status/1556739908810817536",  # parent tweet
    },
    {
        "final": "Deyemi Okanlawon_Stop Raping Women Response.xlsx",
        "kind":  "x",
        "raw":   RAW / "Deyemi Okanlawon" / "Stop Raping Women Response.xlsx",
        "default_url": "https://x.com/_deyemi/status/2025896860288708660",
    },
    {
        "final": "Shola_7 Women Will Beg One Man to Marry.xlsx",
        "kind":  "x",
        "raw":   RAW / "Shola" / "7 Women Will Beg One Man to Marry.xlsx",
        "default_url": "https://x.com/itsSh0la/status/2030562648656335258",
    },
    {
        "final": "Banky Wellington_MENtality Podcast.xlsx",
        "kind":  "youtube_set",
        "yt_root": RAW / "Banky Wellington" / "MENtality",
        "yt_map":  MENTALITY_YT,
        # Plus also search Banky standalone YT + IG since the file might mix sources
        "extra_youtube_root": RAW / "Banky Wellington" / "YouTube",
        "extra_youtube_map":  BANKY_YT,
        "extra_ig_root":      RAW / "Banky Wellington" / "Instagram",
        "default_url": "",
    },
]


def main() -> None:
    print("=== Adding Reference Text/Context column to audience-comment Final files ===\n")
    for job in JOBS:
        final_path = FINAL / job["final"]
        if not final_path.exists():
            print(f"  ! missing final: {job['final']}")
            continue

        if job["kind"] == "x":
            lookup = build_x_url_index(job["raw"])
            matched, total = add_reference_column(final_path, lookup, job["default_url"])
            print(f"  {job['final']}:  matched={matched}/{total}  (default for unmatched = parent tweet)")
        elif job["kind"] == "youtube_set":
            lookup = build_yt_index(job["yt_root"], job["yt_map"])
            extra_yt = build_yt_index(job["extra_youtube_root"], job["extra_youtube_map"])
            extra_ig = build_ig_index(job["extra_ig_root"])
            # Merge — episode YT first (most likely), then standalone YT, then IG
            for k, v in extra_yt.items(): lookup.setdefault(k, v)
            for k, v in extra_ig.items(): lookup.setdefault(k, v)
            matched, total = add_reference_column(final_path, lookup, job["default_url"])
            print(f"  {job['final']}:  matched={matched}/{total}")

    print("\n=== Verification ===")
    for job in JOBS:
        df = pd.read_excel(FINAL / job["final"])
        n_with_url = (df["Reference Text/Context"].astype(str).str.startswith("http")).sum()
        print(f"  {job['final']}: rows={len(df)}, with URL={n_with_url}, cols={list(df.columns)}")


if __name__ == "__main__":
    main()
