"""Fresh full scrape of all tweets for the 4 Nigeria X creators using twscrape.

Uses an authenticated X account (via cookies) — no Apify dependency, no monthly
limits, full historical timeline + all engagement metrics.

Output (per creator):
  Nigeria/Scraped Tweets/<Creator>_all_tweets.xlsx
  columns: tweet_link | text | likes | replies | retweets | quotes | bookmarks | views | timestamp

Setup: cookies (auth_token + ct0) live in temp/twscrape_db (sqlite). Re-runs reuse them.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from twscrape import API, gather


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

OUT_DIR = ROOT / "Nigeria" / "Scraped Tweets"
OUT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = ROOT / "temp" / "twscrape" / "accounts.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Account cookies for twscrape (provided by user, treated as throwaway credentials)
ACCOUNT_USERNAME = os.getenv("TWSCRAPE_USERNAME", "scraper_account")
ACCOUNT_PASSWORD = os.getenv("TWSCRAPE_PASSWORD", "unused")
ACCOUNT_EMAIL    = os.getenv("TWSCRAPE_EMAIL",    "unused@example.com")
ACCOUNT_EMAIL_PW = os.getenv("TWSCRAPE_EMAIL_PW", "unused")
COOKIES = os.getenv("TWSCRAPE_COOKIES")
assert COOKIES, "TWSCRAPE_COOKIES must be set in .env (format: 'auth_token=...; ct0=...')"

CREATORS = [
    {"name": "Deyemi Okanlawon", "handle": "_deyemi"},
    {"name": "Agba John Doe",    "handle": "jon_d_doe"},
    {"name": "Shola",            "handle": "itsSh0la"},
    {"name": "Wizarab",          "handle": "Wizarab10"},
]

PER_CREATOR_LIMIT = 10000  # generous upper bound; stops earlier when timeline ends


async def setup_api():
    api = API(str(DB_PATH))
    accounts = await api.pool.accounts_info()
    if not accounts:
        await api.pool.add_account(
            ACCOUNT_USERNAME, ACCOUNT_PASSWORD, ACCOUNT_EMAIL, ACCOUNT_EMAIL_PW,
            cookies=COOKIES,
        )
        print(f"  added account: {ACCOUNT_USERNAME}", flush=True)
    else:
        print(f"  using cached account: {accounts[0]['username']}", flush=True)
    return api


async def scrape_creator(api, creator):
    print(f"\n=== {creator['name']} (@{creator['handle']}) ===", flush=True)
    user = await api.user_by_login(creator["handle"])
    if user is None:
        print(f"  ! couldn't resolve @{creator['handle']}", flush=True)
        return []
    print(f"  user_id={user.id}, profile says {user.statusesCount:,} statuses ever", flush=True)

    rows = []
    async for tw in api.user_tweets(user.id, limit=PER_CREATOR_LIMIT):
        # Skip retweets / replies to others (keep only own tweets + own replies in own thread)
        if tw.user.username.lower() != creator["handle"].lower():
            continue
        rows.append({
            "tweet_link": tw.url,
            "text":       tw.rawContent,
            "likes":      tw.likeCount,
            "replies":    tw.replyCount,
            "retweets":   tw.retweetCount,
            "quotes":     tw.quoteCount,
            "bookmarks":  tw.bookmarkedCount,
            "views":      tw.viewCount,
            "timestamp":  tw.date.isoformat() if tw.date else None,
        })
        if len(rows) % 200 == 0:
            print(f"  ... {len(rows)} so far", flush=True)
    print(f"  ✓ collected {len(rows)} tweets", flush=True)
    return rows


def save_creator(name, rows):
    df = pd.DataFrame(rows)
    if df.empty:
        print(f"  ! no rows for {name}, skip save", flush=True)
        return
    # Dedup by tweet_link (just in case)
    df = df.drop_duplicates(subset="tweet_link", keep="first")
    # Sort newest first
    df["_ts"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.sort_values("_ts", ascending=False).drop(columns="_ts").reset_index(drop=True)
    out_path = OUT_DIR / f"{name}_all_tweets.xlsx"
    df.to_excel(out_path, index=False)
    print(f"  → {out_path.relative_to(ROOT)}: {len(df)} unique tweets", flush=True)


async def main():
    print("=== twscrape full timeline scrape ===", flush=True)
    api = await setup_api()
    for creator in CREATORS:
        try:
            rows = await scrape_creator(api, creator)
            save_creator(creator["name"], rows)
        except Exception as e:
            print(f"  ✗ FAILED {creator['name']}: {e}", flush=True)
            import traceback; traceback.print_exc()
    print("\n=== ALL DONE ===", flush=True)
    for p in sorted(OUT_DIR.glob("*_all_tweets.xlsx")):
        df = pd.read_excel(p)
        print(f"  {p.name}: {len(df)} tweets", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
