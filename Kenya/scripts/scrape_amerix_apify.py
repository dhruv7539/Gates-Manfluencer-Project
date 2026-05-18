#!/usr/bin/env python3
"""Scrape and filter @amerix tweets for masculinity content analysis.

The Apify API token is read from APIFY_TOKEN. It is intentionally not stored
in this script or in any output file.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from apify_client import ApifyClient


APIDOJO_SEARCH_ACTOR = "apidojo/tweet-scraper"
DEFAULT_SEARCH_ACTOR = "maximedupre/twitter-scraper"
FALLBACK_FREE_SEARCH_ACTOR = "maximedupre/twitter-scraper"
DEFAULT_PROFILE_ACTOR = "apidojo/twitter-profile-scraper"
INFLUENCER_NAME = "Eric Amunga / Amerix"
COUNTRY = "Kenya"
PLATFORM = "X"

RAW_COLUMNS = [
    "tweet_id",
    "tweet_url",
    "created_at",
    "full_text",
    "author_username",
    "is_reply",
    "is_retweet",
    "is_quote",
    "is_thread",
    "conversation_id",
    "reply_count",
    "retweet_count",
    "quote_count",
    "like_count",
    "view_count",
    "hashtags",
    "mentioned_users",
    "media_urls",
    "language",
    "source_query",
    "source_actor",
]

FINAL_COLUMNS = [
    "influencer_name",
    "country",
    "platform",
    "tweet_id",
    "tweet_url",
    "created_at",
    "full_text",
    "engagement_score",
    "views",
    "likes",
    "replies",
    "reposts",
    "quotes",
    "relevance_score_1_to_5",
    "relevance_reason",
    "primary_topic",
    "secondary_topics",
    "masculinity_orientation",
    "gender_norm_type",
    "rhetorical_mode",
    "key_themes",
    "keep_for_content_analysis",
    "notes",
]

SEARCH_QUERIES = [
    "from:amerix masculinity",
    "from:amerix #MasculinitySaturday",
    "from:amerix man OR men OR male OR masculine",
    "from:amerix woman OR women OR wife OR wives",
    "from:amerix modern woman",
    "from:amerix marry OR marriage OR wife",
    "from:amerix love OR relationship OR dating",
    "from:amerix submit OR submission OR obey",
    "from:amerix provider OR provide OR provision",
    "from:amerix body count OR virgin OR sex",
    "from:amerix feminism OR feminist",
    "from:amerix discipline OR self discipline",
    "from:amerix frame OR masculine frame",
    "from:amerix leadership OR lead",
    "from:amerix independence OR independent woman",
    "from:amerix family OR children OR father",
    "from:amerix respect OR disrespect",
]

COMBINED_SEARCH_QUERY = (
    'from:amerix (masculinity OR #MasculinitySaturday OR man OR men OR male OR '
    'masculine OR woman OR women OR wife OR wives OR "modern woman" OR marry OR '
    'marriage OR love OR relationship OR dating OR submit OR submission OR obey OR '
    'provider OR provide OR provision OR "body count" OR virgin OR sex OR '
    'feminism OR feminist OR discipline OR "self discipline" OR frame OR '
    '"masculine frame" OR leadership OR lead OR independence OR "independent woman" '
    'OR family OR children OR father OR respect OR disrespect) -filter:retweets'
)

TOPIC_KEYWORDS = {
    "dating/marriage": [
        "wife",
        "wives",
        "marry",
        "marriage",
        "dating",
        "relationship",
        "love",
        "girlfriend",
        "husband",
    ],
    "women/feminism": [
        "woman",
        "women",
        "feminism",
        "feminist",
        "modern woman",
        "independent woman",
        "female",
        "girl",
    ],
    "male discipline/self-improvement": [
        "discipline",
        "self discipline",
        "self-improvement",
        "improve",
        "man up",
        "habits",
        "frame",
        "masculine frame",
        "purpose",
    ],
    "provision/status/money": [
        "provider",
        "provide",
        "provision",
        "money",
        "status",
        "wealth",
        "success",
        "career",
        "work",
        "rich",
    ],
    "sexuality/body count": [
        "body count",
        "virgin",
        "virginity",
        "sex",
        "sexual",
        "promiscuous",
        "chaste",
        "fidelity",
        "cheat",
    ],
    "family/fatherhood": [
        "family",
        "children",
        "child",
        "father",
        "fatherhood",
        "mother",
        "parent",
        "son",
        "daughter",
    ],
    "health/fitness": [
        "fitness",
        "gym",
        "health",
        "body",
        "workout",
        "train",
        "training",
        "muscle",
        "diet",
    ],
    "religion/morality": [
        "god",
        "church",
        "bible",
        "sin",
        "morality",
        "moral",
        "prayer",
        "religion",
    ],
    "social/political commentary": [
        "society",
        "culture",
        "politics",
        "government",
        "kenya",
        "africa",
        "generation",
    ],
    "emotional control/vulnerability": [
        "emotion",
        "emotional",
        "cry",
        "vulnerable",
        "weak",
        "stoic",
        "pain",
        "fear",
    ],
}

GENDER_TERMS = [
    "man",
    "men",
    "male",
    "masculine",
    "masculinity",
    "woman",
    "women",
    "wife",
    "wives",
    "female",
    "father",
    "mother",
    "husband",
]

HIGH_RELEVANCE_TERMS = [
    "masculinity",
    "#masculinitysaturday",
    "masculine frame",
    "modern woman",
    "independent woman",
    "body count",
    "submit",
    "submission",
    "obey",
    "feminism",
    "feminist",
    "provider",
    "provision",
]

NORMATIVE_TERMS = [
    "should",
    "must",
    "need to",
    "needs to",
    "have to",
    "never",
    "avoid",
    "do not",
    "don't",
    "stop",
    "become",
    "lead",
    "respect",
    "disrespect",
    "submit",
    "obey",
]

THEME_RULES = [
    ("men need to dominate/lead", ["lead", "leader", "leadership", "dominate", "authority", "head of"]),
    ("men need to provide/succeed", ["provider", "provide", "provision", "money", "wealth", "success", "status"]),
    ("men are disadvantaged/victims", ["men are suffering", "men suffer", "against men", "men are victims", "divorce courts"]),
    ("men need to improve themselves", ["discipline", "improve", "self-improvement", "habits", "purpose", "build"]),
    ("men need to be self-reliant", ["self-reliant", "self reliant", "independent man", "depend on yourself", "alone"]),
    ("men should not show emotion", ["do not cry", "don't cry", "emotion", "emotional", "vulnerable", "weak"]),
    ("women should submit/obey", ["submit", "submission", "obey", "submissive"]),
    ("women/feminism are framed as a problem", ["feminism", "feminist", "toxic woman", "bad women"]),
    ("modern women are framed negatively", ["modern woman", "modern women", "independent woman"]),
    ("sexual double standards", ["body count", "virgin", "virginity", "promiscuous", "sex"]),
    ("female respectability", ["respectable woman", "modesty", "decent woman", "wife material", "chaste"]),
    ("masculine discipline", ["masculine", "masculinity", "discipline", "frame"]),
]


@dataclass
class RunReport:
    api_errors: list[str] = field(default_factory=list)
    missing_fields: Counter = field(default_factory=Counter)
    run_inputs: list[dict[str, Any]] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape @amerix tweets with Apify, export raw data, and filter about 100 masculinity/gender-norm content-analysis items."
    )
    parser.add_argument("--output-dir", default="outputs", help="Directory for CSV, XLSX, and summary outputs.")
    parser.add_argument("--target-raw", type=int, default=450, help="Raw tweet target before local filtering.")
    parser.add_argument("--target-filtered", type=int, default=100, help="Final retained content-analysis target.")
    parser.add_argument("--mode", choices=["search", "profile", "auto"], default="search", help="Apify collection mode.")
    parser.add_argument(
        "--query-mode",
        choices=["combined", "listed"],
        default="combined",
        help="Use one combined advanced-search query or the provided query list.",
    )
    parser.add_argument("--search-actor", default=DEFAULT_SEARCH_ACTOR, help="Apify actor for search scraping.")
    parser.add_argument("--profile-actor", default=DEFAULT_PROFILE_ACTOR, help="Apify actor for profile fallback scraping.")
    parser.add_argument("--sort", choices=["Latest", "Top", "Latest + Top"], default="Top", help="Search sort mode.")
    parser.add_argument("--start-date", default="", help="Optional start date for actors that support date windows, e.g. 2025-01-01.")
    parser.add_argument("--end-date", default="", help="Optional end date for actors that support date windows, e.g. 2026-03-27.")
    parser.add_argument("--min-raw-before-fallback", type=int, default=300, help="Fallback threshold in auto mode.")
    parser.add_argument("--wait-secs", type=int, default=180, help="Seconds to wait for each Apify run.")
    parser.add_argument(
        "--max-total-charge-usd",
        type=str,
        default="0.30",
        help="Cost guardrail passed to Apify per actor run. Use empty string to disable.",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Skip Apify and filter an existing outputs/raw_amerix_tweets.csv file.",
    )
    return parser.parse_args()


def require_token() -> str:
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise RuntimeError(
            "APIFY_TOKEN is not set. Export it in your shell before scraping, e.g. export APIFY_TOKEN='...'."
        )
    return token


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_search_inputs(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.search_actor == FALLBACK_FREE_SEARCH_ACTOR:
        run_input = {
            "fromUsers": ["amerix"],
            "shouldIncludeOriginalPosts": True,
            "shouldIncludeReposts": False,
            "shouldIncludeQuotePosts": True,
            "shouldIncludeReplies": False,
            "shouldUseTopSearch": False,
            "language": "en",
            "maxNbItemsToScrape": args.target_raw,
        }
        if args.start_date:
            run_input["startDate"] = args.start_date
        if args.end_date:
            run_input["endDate"] = args.end_date
        return [
            {
                "actor_id": args.search_actor,
                "run_input": run_input,
            }
        ]

    if args.query_mode == "combined":
        return [
            {
                "actor_id": args.search_actor,
                "run_input": {
                    "searchTerms": [COMBINED_SEARCH_QUERY],
                    "sort": args.sort,
                    "maxItems": args.target_raw,
                    "includeSearchTerms": True,
                },
            }
        ]

    batches = chunked([f"{query} -filter:retweets" for query in SEARCH_QUERIES], 5)
    per_batch = max(50, math.ceil(args.target_raw / max(len(batches), 1)))
    return [
        {
            "actor_id": args.search_actor,
            "run_input": {
                "searchTerms": batch,
                "sort": args.sort,
                "maxItems": per_batch,
                "includeSearchTerms": True,
            },
        }
        for batch in batches
    ]


def build_profile_input(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "actor_id": args.profile_actor,
        "run_input": {
            "twitterHandles": ["amerix"],
            "includeNativeRetweets": False,
            "getReplies": False,
            "getAboutData": False,
            "maxItems": args.target_raw,
        },
    }


def run_apify_collection(args: argparse.Namespace, report: RunReport) -> list[dict[str, Any]]:
    token = require_token()
    client = ApifyClient(token)
    items: list[dict[str, Any]] = []

    planned_runs: list[dict[str, Any]] = []
    if args.mode in {"search", "auto"}:
        planned_runs.extend(build_search_inputs(args))
    if args.mode == "profile":
        planned_runs.append(build_profile_input(args))

    for planned in planned_runs:
        actor_id = planned["actor_id"]
        run_input = planned["run_input"]
        report.run_inputs.append({"actor_id": actor_id, "run_input": sanitized_run_input(run_input)})
        try:
            call_kwargs: dict[str, Any] = {
                "run_input": run_input,
                "wait_secs": args.wait_secs,
            }
            if args.max_total_charge_usd.strip():
                call_kwargs["max_total_charge_usd"] = Decimal(args.max_total_charge_usd)

            print(f"Running Apify actor {actor_id} ...", file=sys.stderr)
            run = client.actor(actor_id).call(**call_kwargs)
            if not run:
                report.api_errors.append(f"{actor_id}: Apify returned no run metadata.")
                continue
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                report.api_errors.append(f"{actor_id}: run has no defaultDatasetId.")
                continue
            for item in client.dataset(dataset_id).iterate_items():
                if isinstance(item, dict):
                    item["_source_actor"] = actor_id
                    items.append(item)
        except Exception as exc:  # noqa: BLE001 - keep the research run alive and summarize clearly.
            report.api_errors.append(f"{actor_id}: {type(exc).__name__}: {exc}")

    if args.mode == "auto" and len(items) < args.min_raw_before_fallback:
        fallback = build_profile_input(args)
        report.run_inputs.append(
            {"actor_id": fallback["actor_id"], "run_input": sanitized_run_input(fallback["run_input"])}
        )
        try:
            print(
                f"Search returned {len(items)} items; running profile fallback {fallback['actor_id']} ...",
                file=sys.stderr,
            )
            call_kwargs = {"run_input": fallback["run_input"], "wait_secs": args.wait_secs}
            if args.max_total_charge_usd.strip():
                call_kwargs["max_total_charge_usd"] = Decimal(args.max_total_charge_usd)
            run = client.actor(fallback["actor_id"]).call(**call_kwargs)
            dataset_id = run.get("defaultDatasetId") if run else None
            if dataset_id:
                for item in client.dataset(dataset_id).iterate_items():
                    if isinstance(item, dict):
                        item["_source_actor"] = fallback["actor_id"]
                        items.append(item)
            else:
                report.api_errors.append(f"{fallback['actor_id']}: run has no defaultDatasetId.")
        except Exception as exc:  # noqa: BLE001
            report.api_errors.append(f"{fallback['actor_id']}: {type(exc).__name__}: {exc}")

    return items


def sanitized_run_input(run_input: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in run_input.items() if "token" not in key.lower()}


def get_nested(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def first_present(item: dict[str, Any], paths: list[str]) -> Any:
    for path in paths:
        value = get_nested(item, path)
        if value not in (None, "", [], {}):
            return value
    return None


def as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    multiplier = 1
    if text.lower().endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.lower().endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (list, dict)):
        return bool(value)
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def stringify_list(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for entry in value:
            if isinstance(entry, dict):
                parts.append(
                    str(
                        entry.get("url")
                        or entry.get("expanded_url")
                        or entry.get("media_url_https")
                        or entry.get("mediaUrl")
                        or entry.get("screen_name")
                        or entry.get("username")
                        or entry.get("text")
                        or entry.get("tag")
                        or entry
                    )
                )
            else:
                parts.append(str(entry))
        return "; ".join(dict.fromkeys([part for part in parts if part]))
    if isinstance(value, dict):
        return "; ".join(f"{k}={v}" for k, v in value.items())
    return str(value)


def extract_hashtags(item: dict[str, Any]) -> str:
    candidates = [
        first_present(item, ["hashtags"]),
        first_present(item, ["entities.hashtags"]),
        first_present(item, ["legacy.entities.hashtags"]),
    ]
    tags: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            for entry in candidate:
                if isinstance(entry, dict):
                    tag = entry.get("text") or entry.get("tag")
                    if tag:
                        tags.append(f"#{str(tag).lstrip('#')}")
                elif entry:
                    tags.append(f"#{str(entry).lstrip('#')}")
        elif isinstance(candidate, str):
            tags.extend(re.findall(r"#\w+", candidate))
    return "; ".join(dict.fromkeys(tags))


def extract_mentioned_users(item: dict[str, Any]) -> str:
    candidates = [
        first_present(item, ["mentionedUsers"]),
        first_present(item, ["mentions"]),
        first_present(item, ["entities.user_mentions"]),
        first_present(item, ["legacy.entities.user_mentions"]),
    ]
    users: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            for entry in candidate:
                if isinstance(entry, dict):
                    username = entry.get("username") or entry.get("screen_name") or entry.get("name")
                    if username:
                        users.append(f"@{str(username).lstrip('@')}")
                elif entry:
                    users.append(f"@{str(entry).lstrip('@')}")
        elif isinstance(candidate, str):
            users.extend(re.findall(r"@\w+", candidate))
    return "; ".join(dict.fromkeys(users))


def extract_media_urls(item: dict[str, Any]) -> str:
    candidates = [
        first_present(item, ["mediaUrls"]),
        first_present(item, ["media_urls"]),
        first_present(item, ["media"]),
        first_present(item, ["imageUrls"]),
        first_present(item, ["videoUrls"]),
        first_present(item, ["entities.media"]),
        first_present(item, ["extendedEntities.media"]),
        first_present(item, ["legacy.entities.media"]),
    ]
    urls: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            for entry in candidate:
                if isinstance(entry, dict):
                    url = (
                        entry.get("url")
                        or entry.get("expanded_url")
                        or entry.get("media_url_https")
                        or entry.get("mediaUrl")
                    )
                    if url:
                        urls.append(str(url))
                elif entry:
                    urls.append(str(entry))
        elif isinstance(candidate, str):
            urls.extend(re.findall(r"https?://\S+", candidate))
    return "; ".join(dict.fromkeys(urls))


def normalize_apify_item(item: dict[str, Any], report: RunReport) -> dict[str, Any]:
    tweet_id = first_present(item, ["tweet_id", "id", "id_str", "tweetId", "postId", "rest_id"])
    text = first_present(item, ["full_text", "text", "tweetText", "postText", "content", "legacy.full_text"])
    author_username = first_present(
        item,
        [
            "author_username",
            "author.userName",
            "author.username",
            "author.screen_name",
            "authorHandle",
            "user.username",
            "user.screen_name",
            "username",
        ],
    )
    if author_username:
        author_username = str(author_username).lstrip("@")

    url = first_present(item, ["tweet_url", "url", "postUrl", "twitterUrl", "permalink"])
    if not url and tweet_id and author_username:
        url = f"https://x.com/{author_username}/status/{tweet_id}"

    conversation_id = first_present(item, ["conversation_id", "conversationId", "conversation_id_str"])
    is_reply = as_bool(
        first_present(item, ["is_reply", "isReply", "replyingTo", "inReplyToStatusId", "replyToPostId", "replyToHandle"])
    )
    is_retweet = as_bool(first_present(item, ["is_retweet", "isRetweet", "retweeted"])) or str(text or "").startswith("RT @")
    is_quote = as_bool(first_present(item, ["is_quote", "isQuote", "quotedStatus", "quoted_tweet", "quotedPostId"]))
    is_thread = as_bool(first_present(item, ["is_thread", "isThread", "thread"])) or bool(
        conversation_id and tweet_id and str(conversation_id) == str(tweet_id)
    )

    row = {
        "tweet_id": str(tweet_id or ""),
        "tweet_url": str(url or ""),
        "created_at": first_present(item, ["created_at", "createdAt", "postDateTime", "date", "timestamp", "legacy.created_at"]) or "",
        "full_text": str(text or ""),
        "author_username": author_username or "",
        "is_reply": is_reply,
        "is_retweet": is_retweet,
        "is_quote": is_quote,
        "is_thread": is_thread,
        "conversation_id": str(conversation_id or ""),
        "reply_count": as_int(first_present(item, ["reply_count", "replyCount", "nbReplies", "replies", "reply_counts"])),
        "retweet_count": as_int(first_present(item, ["retweet_count", "retweetCount", "nbReposts", "retweets", "repostCount"])),
        "quote_count": as_int(first_present(item, ["quote_count", "quoteCount", "quotes"])),
        "like_count": as_int(first_present(item, ["like_count", "likeCount", "nbLikes", "favorite_count", "favorites", "likes"])),
        "view_count": as_int(first_present(item, ["view_count", "viewCount", "nbViews", "views", "impressionCount"])),
        "hashtags": extract_hashtags(item),
        "mentioned_users": extract_mentioned_users(item),
        "media_urls": extract_media_urls(item),
        "language": first_present(item, ["language", "lang", "tweetLanguage"]) or "",
        "source_query": stringify_list(first_present(item, ["searchTerm", "searchTerms", "query"])),
        "source_actor": item.get("_source_actor", ""),
    }

    for column in RAW_COLUMNS:
        if row.get(column) in (None, "", 0, False) and column not in {"is_reply", "is_retweet", "is_quote", "is_thread"}:
            report.missing_fields[column] += 1
    return row


def normalize_text_for_duplicate(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text.lower())
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_or_scrape_raw(args: argparse.Namespace, output_dir: Path, report: RunReport) -> pd.DataFrame:
    raw_csv = output_dir / "raw_amerix_tweets.csv"
    if args.local_only:
        if not raw_csv.exists():
            raise FileNotFoundError(f"{raw_csv} does not exist; remove --local-only to scrape with Apify.")
        return pd.read_csv(raw_csv).fillna("")

    raw_items = run_apify_collection(args, report)
    rows = [normalize_apify_item(item, report) for item in raw_items]
    raw_df = pd.DataFrame(rows, columns=RAW_COLUMNS)
    return raw_df


def dedupe_for_filtering(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return raw_df
    deduped = raw_df.copy()
    deduped["_dedupe_text"] = deduped["full_text"].map(normalize_text_for_duplicate)
    non_empty_text = deduped["_dedupe_text"].astype(str).str.len() > 0
    with_text = deduped[non_empty_text].drop_duplicates(subset=["_dedupe_text"], keep="first")
    without_text = deduped[~non_empty_text]
    deduped = pd.concat([with_text, without_text], ignore_index=True)
    if "tweet_id" in deduped.columns:
        deduped = deduped.drop_duplicates(subset=["tweet_id"], keep="first")
    return deduped.drop(columns=["_dedupe_text"])


def text_contains(text: str, terms: list[str]) -> list[str]:
    found = []
    lowered = text.lower()
    for term in terms:
        pattern = r"\b" + re.escape(term.lower()).replace(r"\ ", r"\s+") + r"\b"
        if term.startswith("#"):
            if term.lower() in lowered:
                found.append(term)
        elif re.search(pattern, lowered):
            found.append(term)
    return found


def classify_topic(text: str) -> tuple[str, list[str]]:
    counts = {
        topic: len(text_contains(text, keywords))
        for topic, keywords in TOPIC_KEYWORDS.items()
    }
    ordered = [topic for topic, count in sorted(counts.items(), key=lambda item: item[1], reverse=True) if count > 0]
    if not ordered:
        return "other", []
    return ordered[0], ordered[1:4]


def classify_themes(text: str) -> list[str]:
    themes = [label for label, terms in THEME_RULES if text_contains(text, terms)]
    return themes or ["mixed/unclear"]


def classify_rhetorical_mode(text: str) -> str:
    lowered = text.lower()
    if text_contains(lowered, ["avoid", "beware", "warning", "never", "do not", "don't", "stop"]):
        return "warning"
    if text_contains(lowered, ["must", "should", "need to", "needs to", "rule", "principle"]):
        return "rule-setting"
    if text_contains(lowered, ["fool", "simp", "stupid", "weak man", "clown"]):
        return "ridicule"
    if text_contains(lowered, ["discipline", "build", "improve", "become", "success", "purpose"]):
        return "motivational"
    if re.search(r"^\s*(men|man|women|woman|wife|wives)\b", lowered):
        return "personal claim"
    if "?" in text and len(text.split()) > 8:
        return "commentary"
    return "advice" if re.search(r"\b(do|make|choose|learn|stop|avoid|build|get|be)\b", lowered) else "commentary"


def classify_orientation(text: str, themes: list[str], score: int) -> str:
    lowered = text.lower()
    regressive_signals = [
        "women should submit/obey",
        "women/feminism are framed as a problem",
        "modern women are framed negatively",
        "sexual double standards",
        "men need to dominate/lead",
    ]
    progressive_terms = ["equal rights", "respect women", "women deserve", "gender equality", "protect women"]
    if any(theme in themes for theme in regressive_signals):
        return "regressive"
    if text_contains(lowered, progressive_terms):
        return "progressive"
    if score >= 4 and text_contains(lowered, ["provider", "leadership", "wife", "marriage", "female respectability"]):
        return "regressive"
    if score >= 3:
        return "mixed"
    return "unclear"


def classify_gender_norm_type(text: str, score: int) -> str:
    if score < 3:
        return "none"
    direct = text_contains(text, GENDER_TERMS + HIGH_RELEVANCE_TERMS)
    return "explicit" if direct else "implicit"


def relevance_score_and_reason(row: pd.Series) -> tuple[int, str, str]:
    text = str(row.get("full_text", ""))
    lowered = text.lower()
    words = re.findall(r"\w+", lowered)
    if not text.strip():
        return 1, "Exclude: empty text.", "empty text"
    if row.get("is_retweet"):
        return 1, "Exclude: retweet without original Amerix text.", "retweet"
    if len(words) < 5:
        return 1, "Exclude: too short or unclear to code meaningfully.", "too short"

    gender_hits = text_contains(lowered, GENDER_TERMS)
    high_hits = text_contains(lowered, HIGH_RELEVANCE_TERMS)
    normative_hits = text_contains(lowered, NORMATIVE_TERMS)
    topic, secondary = classify_topic(lowered)
    topic_hit_count = sum(1 for keywords in TOPIC_KEYWORDS.values() if text_contains(lowered, keywords))

    points = 0
    points += min(len(gender_hits), 3)
    points += min(len(high_hits) * 2, 4)
    points += min(len(normative_hits), 2)
    points += min(topic_hit_count, 3)
    if topic in {"dating/marriage", "women/feminism", "sexuality/body count"}:
        points += 2
    if topic in {"male discipline/self-improvement", "provision/status/money", "family/fatherhood"} and gender_hits:
        points += 1
    if row.get("is_reply"):
        points -= 1
    if re.search(r"\b(men|man|male|masculine)\b.*\b(should|must|need|lead|provide|discipline|frame)\b", lowered):
        points += 3
    if re.search(r"\b(women|woman|wife|wives)\b.*\b(submit|obey|respect|marry|body count|femin)", lowered):
        points += 3

    if points >= 8:
        score = 5
    elif points >= 5:
        score = 4
    elif points >= 3:
        score = 3
    elif points >= 1:
        score = 2
    else:
        score = 1

    if score >= 4:
        reason = "Central gender/masculinity content"
        if high_hits:
            reason += f"; matched high-signal term(s): {', '.join(high_hits[:4])}"
        elif gender_hits:
            reason += f"; matched gender term(s): {', '.join(gender_hits[:4])}"
        return score, reason + ".", ""
    if score == 3:
        return score, f"Implicit or usable masculinity/gender-norm relevance via {topic}.", ""
    if topic in {"health/fitness", "social/political commentary"}:
        return score, f"Exclude: {topic} is not clearly tied to masculinity/gender norms.", f"generic {topic}"
    if secondary or topic != "other":
        return score, "Exclude: weak relevance to project scope.", "weak relevance"
    return score, "Exclude: no clear masculinity or gender-norm angle.", "no gender angle"


def code_content_analysis(raw_df: pd.DataFrame, target_filtered: int) -> tuple[pd.DataFrame, Counter]:
    exclusion_reasons: Counter = Counter()
    coded_rows: list[dict[str, Any]] = []

    for _, row in raw_df.iterrows():
        score, reason, exclusion_reason = relevance_score_and_reason(row)
        text = str(row.get("full_text", ""))
        primary_topic, secondary_topics = classify_topic(text)
        themes = classify_themes(text)
        orientation = classify_orientation(text, themes, score)
        gender_norm_type = classify_gender_norm_type(text, score)
        rhetorical_mode = classify_rhetorical_mode(text)
        engagement_score = (
            as_int(row.get("like_count"))
            + as_int(row.get("reply_count"))
            + as_int(row.get("retweet_count"))
            + as_int(row.get("quote_count"))
        )

        keep = score >= 3
        if row.get("is_reply") and score < 4:
            keep = False
            exclusion_reason = exclusion_reason or "reply not standalone enough"
            reason = "Exclude: reply has insufficient standalone gender/masculinity content."
        if row.get("is_retweet"):
            keep = False
            exclusion_reason = exclusion_reason or "retweet"
        if not keep:
            exclusion_reasons[exclusion_reason or "weak relevance"] += 1

        coded_rows.append(
            {
                "influencer_name": INFLUENCER_NAME,
                "country": COUNTRY,
                "platform": PLATFORM,
                "tweet_id": row.get("tweet_id", ""),
                "tweet_url": row.get("tweet_url", ""),
                "created_at": row.get("created_at", ""),
                "full_text": text,
                "engagement_score": engagement_score,
                "views": as_int(row.get("view_count")),
                "likes": as_int(row.get("like_count")),
                "replies": as_int(row.get("reply_count")),
                "reposts": as_int(row.get("retweet_count")),
                "quotes": as_int(row.get("quote_count")),
                "relevance_score_1_to_5": score,
                "relevance_reason": reason,
                "primary_topic": primary_topic,
                "secondary_topics": "; ".join(secondary_topics),
                "masculinity_orientation": orientation,
                "gender_norm_type": gender_norm_type,
                "rhetorical_mode": rhetorical_mode,
                "key_themes": "; ".join(themes),
                "keep_for_content_analysis": keep,
                "notes": "reply retained for standalone content" if row.get("is_reply") and keep else "",
            }
        )

    coded_df = pd.DataFrame(coded_rows, columns=FINAL_COLUMNS)
    candidates = coded_df[coded_df["keep_for_content_analysis"]].copy()
    candidates["_score_rank"] = candidates["relevance_score_1_to_5"].astype(int)
    candidates = candidates.sort_values(
        by=["_score_rank", "engagement_score", "created_at"],
        ascending=[False, False, False],
        na_position="last",
    )
    retained = candidates.head(target_filtered).drop(columns=["_score_rank"])
    return retained, exclusion_reasons


def save_outputs(raw_df: pd.DataFrame, filtered_df: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_csv = output_dir / "raw_amerix_tweets.csv"
    raw_xlsx = output_dir / "raw_amerix_tweets.xlsx"
    filtered_csv = output_dir / "filtered_amerix_content_analysis_100.csv"
    filtered_xlsx = output_dir / "filtered_amerix_content_analysis_100.xlsx"

    raw_df.to_csv(raw_csv, index=False)
    raw_df.to_excel(raw_xlsx, index=False)
    filtered_df.to_csv(filtered_csv, index=False)
    filtered_df.to_excel(filtered_xlsx, index=False)


def write_summary(
    raw_df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    exclusion_reasons: Counter,
    report: RunReport,
    output_dir: Path,
) -> None:
    summary_path = output_dir / "amerix_filtering_summary.txt"
    lines: list[str] = []
    lines.append("Amerix / Eric Amunga X scraping and filtering summary")
    lines.append("=" * 58)
    lines.append(f"Number of raw tweets collected: {len(raw_df)}")
    lines.append(f"Number retained: {len(filtered_df)}")
    lines.append(f"Number excluded: {max(len(raw_df) - len(filtered_df), 0)}")
    lines.append("")
    lines.append("Apify actor runs:")
    if report.run_inputs:
        for index, run in enumerate(report.run_inputs, 1):
            lines.append(f"{index}. {run['actor_id']}: {run['run_input']}")
    else:
        lines.append("No Apify runs recorded (local-only mode or scrape failed before launch).")

    lines.append("")
    lines.append("Main exclusion reasons:")
    if exclusion_reasons:
        for reason, count in exclusion_reasons.most_common():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- None recorded.")

    lines.append("")
    lines.append("Count by primary_topic:")
    append_counts(lines, filtered_df.get("primary_topic"))

    lines.append("")
    lines.append("Count by masculinity_orientation:")
    append_counts(lines, filtered_df.get("masculinity_orientation"))

    lines.append("")
    lines.append("Count by relevance score:")
    append_counts(lines, filtered_df.get("relevance_score_1_to_5"))

    lines.append("")
    lines.append("Top 10 retained tweets by engagement_score:")
    if filtered_df.empty:
        lines.append("- None retained.")
    else:
        top = filtered_df.sort_values("engagement_score", ascending=False).head(10)
        for _, row in top.iterrows():
            text = re.sub(r"\s+", " ", str(row.get("full_text", ""))).strip()
            if len(text) > 180:
                text = text[:177] + "..."
            lines.append(
                f"- {row.get('engagement_score', 0)} | score {row.get('relevance_score_1_to_5', '')} | "
                f"{row.get('tweet_url', '')} | {text}"
            )

    lines.append("")
    lines.append("Apify/API errors:")
    if report.api_errors:
        for error in report.api_errors:
            lines.append(f"- {error}")
    else:
        lines.append("- None recorded.")

    lines.append("")
    lines.append("Missing fields observed during normalization:")
    if report.missing_fields:
        for field_name, count in report.missing_fields.most_common():
            lines.append(f"- {field_name}: missing/empty in {count} normalized item(s)")
    else:
        lines.append("- None recorded.")

    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_counts(lines: list[str], series: pd.Series | None) -> None:
    if series is None or len(series) == 0:
        lines.append("- None")
        return
    counts = Counter(series.dropna().astype(str))
    for label, count in counts.most_common():
        lines.append(f"- {label}: {count}")


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = RunReport()

    try:
        raw_df = load_or_scrape_raw(args, output_dir, report)
        if raw_df.empty:
            report.api_errors.append("No raw items were collected or loaded.")
            filtered_df = pd.DataFrame(columns=FINAL_COLUMNS)
            exclusion_reasons: Counter = Counter()
        else:
            filtered_df, exclusion_reasons = code_content_analysis(dedupe_for_filtering(raw_df), args.target_filtered)

        save_outputs(raw_df, filtered_df, output_dir)
        write_summary(raw_df, filtered_df, exclusion_reasons, report, output_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote outputs to {output_dir.resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
