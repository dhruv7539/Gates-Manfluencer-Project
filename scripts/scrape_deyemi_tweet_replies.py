"""Scrape Twitter replies for Deyemi Okanlawon's top scope-relevant tweets via Apify.

Uses scraper_one/x-post-replies-scraper. Picks top N tweets by replyCount from the
existing `Nigeria/Scraped Tweets/Deyemi Okanlawon_scope_relevant_full.xlsx` and
batches their URLs into one Apify run. Output mirrors the existing audience-comments
schema so the downstream scope filter just picks it up:

  Nigeria/Audience Comments - Raw/Deyemi Okanlawon/<tweet_id>__<short_summary>.xlsx
  columns = author | text | likes | replies | retweets | timestamp | url
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd
from apify_client import ApifyClient
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
APIFY_KEY = os.getenv("APIFY_API_KEY")
assert APIFY_KEY, "APIFY_API_KEY missing"

SRC = ROOT / "Nigeria/Scraped Tweets" / "Deyemi Okanlawon_scope_relevant_full.xlsx"
OUT_DIR = ROOT / "Nigeria/Audience Comments - Raw" / "Deyemi Okanlawon"
CACHE_DIR = ROOT / "temp" / "deyemi_replies"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ACTOR = "scraper_one/x-post-replies-scraper"
TOP_N_TWEETS = 35
RESULTS_LIMIT = 1000   # apify cap per run; total expected ~700


def safe(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", " ", str(s))
    return re.sub(r"\s+", " ", s).strip()[:60]


def main():
    if not SRC.exists():
        sys.exit(f"Missing source: {SRC}")
    src_df = pd.read_excel(SRC)
    top = src_df.sort_values("replyCount", ascending=False).head(TOP_N_TWEETS).reset_index(drop=True)
    urls = top["tweetUrl"].dropna().tolist()
    expected_replies = int(top["replyCount"].sum())
    print(f"Picking top {len(urls)} tweets, expected ~{expected_replies} replies")

    cache_path = CACHE_DIR / "raw_replies.parquet"
    if cache_path.exists():
        items_df = pd.read_parquet(cache_path)
        print(f"  cache hit: {len(items_df)} rows")
    else:
        client = ApifyClient(APIFY_KEY)
        all_items = []
        BATCH = 5  # actor caps postUrls at 5 per run
        for i in range(0, len(urls), BATCH):
            chunk = urls[i:i + BATCH]
            run_input = {
                "postUrls": chunk,
                "resultsLimit": RESULTS_LIMIT,
                "includeOriginalPost": False,
            }
            print(f"  → batch {i//BATCH + 1}/{(len(urls)+BATCH-1)//BATCH}: {len(chunk)} URLs ...")
            try:
                run = client.actor(ACTOR).call(run_input=run_input, timeout_secs=1800)
                items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
                all_items.extend(items)
                print(f"     +{len(items)} items (cum {len(all_items)})")
            except Exception as e:
                print(f"     batch FAILED: {e}")
        items_df = pd.DataFrame(all_items)
        items_df.to_parquet(cache_path, index=False)
        print(f"  got {len(items_df)} total reply items")

    print(f"\nColumns returned: {list(items_df.columns)}")
    print(items_df.head(2).to_string()[:1200])

    # Group by parent tweet to write one xlsx per source tweet
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Find which column identifies the parent tweet URL (often 'inReplyToUrl' / 'parentUrl' / 'conversationId')
    parent_cols = [c for c in items_df.columns if any(s in c.lower() for s in ["parent", "conversation", "inreplyto"])]
    print(f"Possible parent-id columns: {parent_cols}")

    # Map URL -> short label from src
    label_map = {row["tweetUrl"]: f"reply_to_{row['tweetUrl'].split('/')[-1]}__{safe(row.get('llm_reason', ''))}"
                 for _, row in top.iterrows()}

    # Try to attribute each reply to a parent URL. Fallback: use tweet_id from url path.
    def parent_url_of(row):
        for col in parent_cols:
            v = row.get(col)
            if isinstance(v, str) and "x.com" in v or (isinstance(v, str) and "twitter.com" in v):
                return v
        # fallback: scan all string fields for an x.com/<handle>/status/<id> matching a top URL
        return None

    # Just dump everything to a single combined file for now; we'll sort downstream
    out_combined = OUT_DIR / "_tweet_replies_combined.xlsx"
    cleaned = pd.DataFrame()
    text_col = None
    for c in ["text", "fullText", "content", "replyText"]:
        if c in items_df.columns:
            text_col = c
            break
    if text_col is None:
        sys.exit(f"No text column found in scraper output. Got: {list(items_df.columns)}")
    author_col = "author" if "author" in items_df.columns else (
        "authorHandle" if "authorHandle" in items_df.columns else None)
    cleaned["author"] = items_df[author_col].astype(str) if author_col else ""
    cleaned["text"]   = items_df[text_col].astype(str)
    for c, src_c in [("likes", "likeCount"), ("replies", "replyCount"),
                     ("retweets", "retweetCount"), ("timestamp", "createdAt"),
                     ("url", "url")]:
        if src_c in items_df.columns:
            cleaned[c] = items_df[src_c]
    cleaned.to_excel(out_combined, index=False)
    print(f"\n  wrote {len(cleaned)} rows -> {out_combined.relative_to(ROOT)}")

    # Also produce a "tweet_replies_pooled" xlsx that the downstream scope script will pick up.
    pooled = OUT_DIR / "Tweet Replies Pooled.xlsx"
    cleaned[["author", "text"]].to_excel(pooled, index=False)
    print(f"  wrote scope-ready file -> {pooled.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
