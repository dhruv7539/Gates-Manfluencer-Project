"""Scrape Falz's tweets via the official X API v2 (Tweepy).

Uses app-only auth via Bearer Token — no user-account ban risk, no scraping
of HTML, fully sanctioned by X.

X API v2 endpoint: GET /2/users/:id/tweets
  - Free tier: very limited (~1,500 reads/month total)
  - Basic tier ($100/mo): ~10K reads/month, recommended
  - Pro tier ($5K/mo): ~1M reads/month
  - Hard limit per call: 100 tweets, max 3,200 historical tweets per user

The script:
  1. Resolves @falzthebahdguy → user_id via /2/users/by/username
  2. Paginates through /2/users/:id/tweets (up to MAX_TWEETS)
  3. Saves to Nigeria/Scraped Tweets/Falz_all_tweets.xlsx

Auto-handles rate limits via Tweepy's wait_on_rate_limit=True.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import tweepy
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

OUT_DIR = ROOT / "Nigeria" / "Scraped Tweets"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "Falz_all_tweets.xlsx"

BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
assert BEARER_TOKEN, "X_BEARER_TOKEN missing in .env"

HANDLE = "falzthebahdguy"
MAX_TWEETS = 3200          # X API hard limit for historical timeline
PER_PAGE   = 100           # X API max per page

TWEET_FIELDS = [
    "created_at", "public_metrics", "lang", "in_reply_to_user_id",
    "referenced_tweets", "entities", "conversation_id",
]


def main() -> None:
    print("=== Falz scrape via X API v2 ===", flush=True)
    print(f"  target: @{HANDLE}", flush=True)
    print(f"  cap:    {MAX_TWEETS} tweets", flush=True)
    print(f"  output: {OUT_PATH}", flush=True)

    client = tweepy.Client(bearer_token=BEARER_TOKEN, wait_on_rate_limit=True)

    # 1. Resolve handle
    print(f"\n  resolving @{HANDLE}...", flush=True)
    try:
        u = client.get_user(username=HANDLE, user_fields=["public_metrics", "verified", "description"])
    except tweepy.errors.Unauthorized as e:
        print(f"  ! 401 Unauthorized — bearer token rejected. Check the X app has at least Read permissions.", flush=True)
        print(f"    err: {e}", flush=True)
        sys.exit(1)
    except tweepy.errors.Forbidden as e:
        print(f"  ! 403 Forbidden — your X tier does not allow this endpoint. You likely need Basic tier ($100/mo).", flush=True)
        print(f"    err: {e}", flush=True)
        sys.exit(1)
    if not u.data:
        print(f"  ! could not resolve @{HANDLE}", flush=True)
        sys.exit(1)
    user_id = u.data.id
    metrics = getattr(u.data, "public_metrics", {})
    print(f"  user_id={user_id}", flush=True)
    print(f"  followers={metrics.get('followers_count', '?'):,} tweets_total={metrics.get('tweet_count', '?'):,}", flush=True)

    # 2. Paginate timeline
    print(f"\n  fetching timeline (paginating, {PER_PAGE} per call)...", flush=True)
    rows: list[dict] = []
    pagination_token = None
    page = 0
    t0 = time.time()
    while len(rows) < MAX_TWEETS:
        page += 1
        try:
            resp = client.get_users_tweets(
                id=user_id,
                max_results=PER_PAGE,
                pagination_token=pagination_token,
                tweet_fields=TWEET_FIELDS,
                exclude=None,  # include retweets+replies; we'll filter in-script
            )
        except tweepy.errors.TooManyRequests as e:
            print(f"  ! 429 rate-limited despite wait_on_rate_limit. Waiting 60s.", flush=True)
            time.sleep(60)
            continue
        except tweepy.errors.Forbidden as e:
            print(f"  ! 403 Forbidden — your X API tier does not include this endpoint.", flush=True)
            print(f"    err: {e}", flush=True)
            break
        except Exception as e:
            print(f"  ! page {page} error: {type(e).__name__}: {str(e)[:200]}", flush=True)
            break

        if not resp.data:
            print(f"  page {page}: empty — end of timeline", flush=True)
            break

        for tw in resp.data:
            pm = tw.public_metrics or {}
            rows.append({
                "tweet_link": f"https://x.com/{HANDLE}/status/{tw.id}",
                "text":       tw.text,
                "likes":      pm.get("like_count"),
                "replies":    pm.get("reply_count"),
                "retweets":   pm.get("retweet_count"),
                "quotes":     pm.get("quote_count"),
                "bookmarks":  pm.get("bookmark_count"),
                "views":      pm.get("impression_count"),
                "timestamp":  tw.created_at.isoformat() if tw.created_at else None,
                "lang":       tw.lang,
                "in_reply_to_user_id": tw.in_reply_to_user_id,
                "is_reply":   tw.in_reply_to_user_id is not None,
                "is_retweet": any(r.type == "retweeted" for r in (tw.referenced_tweets or [])),
            })

        print(f"  page {page}: +{len(resp.data)}  (running total: {len(rows)})", flush=True)

        meta = resp.meta or {}
        pagination_token = meta.get("next_token")
        if not pagination_token:
            print(f"  no next_token — end of available timeline", flush=True)
            break
        if len(rows) >= MAX_TWEETS:
            break

    elapsed = time.time() - t0
    print(f"\n  collected {len(rows)} tweets in {elapsed:.0f}s", flush=True)

    if not rows:
        print("  nothing to save", flush=True)
        sys.exit(2)

    df = pd.DataFrame(rows).drop_duplicates(subset="tweet_link")
    df["_ts"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.sort_values("_ts", ascending=False).drop(columns="_ts").reset_index(drop=True)
    df.to_excel(OUT_PATH, index=False)
    print(f"  → {OUT_PATH.relative_to(ROOT)}: {len(df)} unique tweets", flush=True)

    # Distribution summary
    print(f"\n  composition:", flush=True)
    print(f"    own non-reply tweets: {(~df['is_reply'] & ~df['is_retweet']).sum()}", flush=True)
    print(f"    replies:              {df['is_reply'].sum()}", flush=True)
    print(f"    retweets:             {df['is_retweet'].sum()}", flush=True)


if __name__ == "__main__":
    main()
