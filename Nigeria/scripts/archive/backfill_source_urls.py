"""
Backfill Source URL (and Source File where applicable) into the 5 Final
content-analysis datasets that lack them. Ebuka already has them.

Twitter creators: match Verbatim Text -> raw tweet text -> tweet_link.
Banky Wellington (MENtality podcast): match Verbatim Text against each
transcript file's contents to identify the source episode, then map to URL.
"""
from pathlib import Path
import pandas as pd
import html
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "Content Analysis" / "Content - Final"
RAW   = ROOT / "Content Analysis" / "Content - Raw"

# Use the same MENtality URL mapping already locked into the Ebuka final file.
MENTALITY_URLS = {
    "Masculinity + Fatherhood.txt":         "https://www.youtube.com/watch?v=V_eHJfW87iA",
    "Masculinity + Money.txt":              "https://www.youtube.com/watch?v=f6WW9g5hqLI",
    "Masculinity + Relationships.txt":      "https://www.youtube.com/watch?v=mU5uAVhVEzA",
    "Pt 2 Masculinity + Relationships.txt": "https://www.youtube.com/watch?v=7uLzlPGsiVo",
    "Masculinity + Friendship.txt":         "https://www.youtube.com/watch?v=XbFCPgdK8QQ",
    "Masculinity + Young Boys.txt":         "https://www.youtube.com/watch?v=-YGXo00-fHw",
}

NORMALIZE_RE = re.compile(r"\s+")
def norm(s: str) -> str:
    return NORMALIZE_RE.sub(" ", html.unescape(str(s))).strip().lower()


def backfill_twitter(name: str, file_stem: str):
    final_path = FINAL / f"{file_stem}.xlsx"
    raw_path   = RAW / name / f"{name}_Twitter_Raw.xlsx"
    final_df = pd.read_excel(final_path)
    raw_df   = pd.read_excel(raw_path)

    # Supplemental source: the deleted scope_relevant_full.xlsx files (in git
    # history) carry tweets that the v2 raw file dropped. Restored to /tmp
    # before this script runs.
    extras = []
    extra_path = Path(f"/tmp/{name}_full.xlsx")
    if extra_path.exists():
        ex = pd.read_excel(extra_path)
        if "text_raw" in ex.columns and "tweetUrl" in ex.columns:
            extras.append(pd.DataFrame({"text": ex["text_raw"], "tweet_link": ex["tweetUrl"]}))

    # The Deyemi Final pulled in tweets (incl. replies) from a 6,311-tweet
    # Apify scrape that isn't checked in. Use it as a final fallback.
    apify_path = Path("/Users/sushildalavi/Downloads/dataset_advanced-x-twitter-profile-scraper_2026-04-30_06-33-28-572.xlsx")
    if name == "Deyemi Okanlawon" and apify_path.exists():
        ap = pd.read_excel(apify_path)
        extras.append(pd.DataFrame({"text": ap["fullText"], "tweet_link": ap["tweetUrl"]}))

    if extras:
        raw_df = pd.concat([raw_df[["text", "tweet_link"]]] + extras, ignore_index=True)

    raw_df["_norm"] = raw_df["text"].map(norm)
    raw_df = raw_df.drop_duplicates(subset=["_norm"])
    raw_lookup = dict(zip(raw_df["_norm"], raw_df["tweet_link"]))

    urls = []
    misses = 0
    for txt in final_df["Verbatim Text (CODE THIS)"]:
        n = norm(txt)
        url = raw_lookup.get(n)
        if not url:
            # Substring fallback: a coded snippet may be a portion of the tweet.
            hit = next((link for nt, link in zip(raw_df["_norm"], raw_df["tweet_link"])
                        if n and (n in nt or nt in n)), None)
            url = hit
        if not url:
            misses += 1
        urls.append(url or "")

    # Insert Source URL column after Content Type to match Ebuka's shape.
    if "Source URL" in final_df.columns:
        final_df["Source URL"] = urls
    else:
        insert_at = list(final_df.columns).index("Content Type") + 1
        final_df.insert(insert_at, "Source URL", urls)

    final_df.to_excel(final_path, index=False)
    print(f"[done] {final_path.name}: {len(final_df)} rows, {misses} unmatched")


def backfill_banky():
    final_path = FINAL / "Banky Wellington_Podcast.xlsx"
    transcripts_dir = RAW / "Banky Wellington" / "Transcripts"
    final_df = pd.read_excel(final_path)

    transcripts = {}
    for fp in sorted(transcripts_dir.glob("*.txt")):
        transcripts[fp.name] = norm(fp.read_text(encoding="utf-8", errors="ignore"))

    source_files = []
    source_urls  = []
    misses = 0
    for txt in final_df["Verbatim Text (CODE THIS)"]:
        n = norm(txt)
        # Use a long-enough probe to disambiguate across episodes.
        probe = n[:200] if len(n) > 200 else n
        match_file = None
        for fname, body in transcripts.items():
            if probe and probe in body:
                match_file = fname
                break
        if not match_file:
            # Fallback: try a shorter probe from the middle.
            mid = len(n) // 2
            probe2 = n[max(0, mid - 80): mid + 80]
            for fname, body in transcripts.items():
                if probe2 and probe2 in body:
                    match_file = fname
                    break
        if not match_file:
            misses += 1
        source_files.append(match_file or "")
        source_urls.append(MENTALITY_URLS.get(match_file, "") if match_file else "")

    cols = list(final_df.columns)
    insert_at = cols.index("Content Type") + 1
    if "Source File" not in final_df.columns:
        final_df.insert(insert_at, "Source File", source_files)
        insert_at += 1
    else:
        final_df["Source File"] = source_files
    if "Source URL" not in final_df.columns:
        final_df.insert(insert_at, "Source URL", source_urls)
    else:
        final_df["Source URL"] = source_urls

    final_df.to_excel(final_path, index=False)
    print(f"[done] {final_path.name}: {len(final_df)} rows, {misses} unmatched")


def main():
    backfill_twitter("Agba John Doe",     "Agba John Doe_Twitter")
    backfill_twitter("Shola",             "Shola_Twitter")
    backfill_twitter("Wizarab",           "Wizarab_Twitter")
    backfill_twitter("Deyemi Okanlawon",  "Deyemi Okanlawon_Twitter")
    backfill_banky()


if __name__ == "__main__":
    main()
