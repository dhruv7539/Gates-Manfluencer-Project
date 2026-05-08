"""Safely scrape Falz's X timeline using twscrape with conservative anti-ban settings.

Anti-ban safeguards:
  - Single account, single sequential pass (no concurrency)
  - Hard cap at 3000 tweets (more than enough for content analysis,
    well under twscrape's typical "I am a bot" thresholds)
  - Built-in twscrape pacing (it handles rate-limit headers automatically)
  - Stop early if 10 consecutive errors
  - Print progress every 100 tweets so you can Ctrl+C if anything looks off

Output:
  Nigeria/Scraped Tweets/Falz_all_tweets.xlsx
  Columns: tweet_link | text | likes | replies | retweets | quotes |
           bookmarks | views | timestamp
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from twscrape import API


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

OUT_DIR = ROOT / "Nigeria" / "Scraped Tweets"
OUT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = ROOT / "temp" / "twscrape" / "accounts.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

USERNAME = os.getenv("TWSCRAPE_USERNAME", "falz_research_session")
PASSWORD = os.getenv("TWSCRAPE_PASSWORD", "unused")
EMAIL    = os.getenv("TWSCRAPE_EMAIL",    "unused@example.com")
EMAIL_PW = os.getenv("TWSCRAPE_EMAIL_PW", "unused")
COOKIES  = os.getenv("TWSCRAPE_COOKIES")
assert COOKIES, "TWSCRAPE_COOKIES missing in .env"

HANDLE = "falzthebahdguy"
HARD_LIMIT = 3000        # twscrape handles its own pacing; this is the upper bound
PROGRESS_EVERY = 100     # print a heartbeat
MAX_CONSECUTIVE_ERRORS = 10


async def setup_api() -> API:
    api = API(str(DB_PATH))
    accounts = await api.pool.accounts_info()
    if not accounts:
        await api.pool.add_account(
            USERNAME, PASSWORD, EMAIL, EMAIL_PW, cookies=COOKIES,
        )
        print(f"  added account: {USERNAME}", flush=True)
    else:
        # Account already in pool — try update cookies if needed
        print(f"  reusing cached account: {accounts[0]['username']}", flush=True)
    return api


async def main() -> None:
    print("=== Falz scrape (twscrape, conservative pacing) ===", flush=True)
    print(f"  target: @{HANDLE}", flush=True)
    print(f"  cap:    {HARD_LIMIT} tweets", flush=True)
    print(f"  output: {OUT_DIR / 'Falz_all_tweets.xlsx'}", flush=True)

    api = await setup_api()

    print(f"\n  resolving @{HANDLE}...", flush=True)
    user = await api.user_by_login(HANDLE)
    if user is None:
        print(f"  ! could not resolve @{HANDLE} — handle may be wrong, account suspended, or auth issue.", flush=True)
        sys.exit(1)
    print(f"  user_id={user.id}, statusesCount={user.statusesCount:,}", flush=True)

    rows: list[dict] = []
    consecutive_errors = 0
    try:
        async for tw in api.user_tweets(user.id, limit=HARD_LIMIT):
            try:
                # Skip retweets / quoted tweets that aren't his own writing
                if tw.user.username.lower() != HANDLE.lower():
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
                consecutive_errors = 0
                if len(rows) % PROGRESS_EVERY == 0:
                    print(f"    ... collected {len(rows):>4} tweets", flush=True)
            except Exception as e:
                consecutive_errors += 1
                print(f"    ! tweet parse error #{consecutive_errors}: {str(e)[:120]}", flush=True)
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"  STOPPING — {MAX_CONSECUTIVE_ERRORS} consecutive errors looks like account flag/throttle.", flush=True)
                    break
    except KeyboardInterrupt:
        print(f"\n  interrupted — saving {len(rows)} tweets so far", flush=True)
    except Exception as e:
        print(f"\n  ! fatal stream error: {str(e)[:200]}", flush=True)

    print(f"\n  collected {len(rows)} tweets total", flush=True)

    if not rows:
        print("  nothing to save.", flush=True)
        sys.exit(2)

    df = pd.DataFrame(rows).drop_duplicates(subset="tweet_link")
    df["_ts"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.sort_values("_ts", ascending=False).drop(columns="_ts").reset_index(drop=True)
    out_path = OUT_DIR / "Falz_all_tweets.xlsx"
    df.to_excel(out_path, index=False)
    print(f"  → {out_path.relative_to(ROOT)}: {len(df)} unique tweets", flush=True)
    print(f"\n  ⚠️  REMEMBER: rotate your X auth cookies after this completes.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
