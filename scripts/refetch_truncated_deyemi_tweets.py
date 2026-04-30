"""Re-fetch full text for the Deyemi 'Stop Raping Women' replies that look
truncated at ~280 chars, using Twitter's free public oEmbed endpoint.

Strategy:
  1. Find rows in the current Audience Demo file that look truncated
     (250-280 chars, no terminal punctuation).
  2. Look up each one's source tweet URL from the original scrape.
  3. Fetch oEmbed HTML, strip tags, strip the trailing " — Author (@handle) Date"
     signature and any pic.twitter.com URL.
  4. Replace in-place ONLY when the fresh text is meaningfully longer than what
     we have. Otherwise the row was already complete (just lacked punctuation).
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "Audience Demo Comments" / "Deyemi Okanlawon" / "Stop Raping Women Response.xlsx"
SRC_PATH = ROOT / "Nigeria Audience Comments" / "Deyemi Okanlawon" / "Stop Raping Women Response.xlsx"

OEMBED = "https://publish.twitter.com/oembed"


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def find_truncated(df_out):
    rows = []
    for i, t in enumerate(df_out["text"].astype(str)):
        if 250 <= len(t) <= 280 and not t.rstrip().endswith(
            (".", "!", "?", '"', ")", "…", "”", "’", ";", ":")
        ):
            rows.append((i, t))
    return rows


def oembed_text(url, retries=3):
    """Fetch tweet via oEmbed, return cleaned tweet text or None."""
    q = urllib.parse.urlencode({"url": url, "omit_script": "true"})
    api = f"{OEMBED}?{q}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            blob = data.get("html", "")
            text = re.sub(r"<[^>]+>", " ", blob)
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            # Strip trailing " — AuthorName (@handle) <date>"
            text = re.sub(r"\s+—\s+[^—]+\(@\w+\)\s+\w+\s+\d{1,2},\s+\d{4}\s*$", "", text)
            # Strip embedded pic.twitter.com URL
            text = re.sub(r"\s*pic\.twitter\.com/\S+", "", text)
            return text.strip()
        except Exception as e:
            if attempt == retries - 1:
                print(f"    oEmbed failed for {url}: {e}")
                return None
            time.sleep(2 ** attempt)


def main():
    df_out = pd.read_excel(OUT_PATH)
    df_src = pd.read_excel(SRC_PATH)
    src_url_for_text = {norm(r["text"]): r["url"] for _, r in df_src.iterrows()}

    truncated = find_truncated(df_out)
    print(f"Found {len(truncated)} truncated-looking rows")

    updated = 0
    confirmed_complete = 0
    misses = 0
    not_found = 0
    for idx, old_text in truncated:
        nt = norm(old_text)
        url = src_url_for_text.get(nt)
        if not url:
            for sn, su in src_url_for_text.items():
                if nt and (nt in sn or sn in nt):
                    url = su
                    break
        if not url:
            print(f"  ! row {idx + 1}: no URL match in source")
            not_found += 1
            continue

        full = oembed_text(url)
        if full is None:
            misses += 1
            continue

        if len(full) > len(old_text.strip()) + 5:  # at least 5 more chars to count as "longer"
            df_out.at[idx, "text"] = full
            updated += 1
            print(f"  ✓ row {idx + 1}: {len(old_text.strip())} → {len(full)} chars")
            print(f"      old end: ...{old_text[-60:]}")
            print(f"      new end: ...{full[-60:]}")
        else:
            confirmed_complete += 1
            print(f"  · row {idx + 1}: already complete ({len(old_text.strip())}c, oEmbed={len(full)}c)")

        time.sleep(0.5)  # be polite to Twitter

    print(f"\nUpdated: {updated}")
    print(f"Confirmed already-complete: {confirmed_complete}")
    print(f"oEmbed failures: {misses}")
    print(f"No source URL: {not_found}")

    if updated:
        df_out.to_excel(OUT_PATH, index=False)
        print(f"Saved {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
