#!/usr/bin/env python3
"""Scrape and filter @Wizarab10 tweets for masculinity content analysis."""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from apify_client import ApifyClient


DEFAULT_SEARCH_ACTOR = "maximedupre/twitter-scraper"
APIDOJO_SEARCH_ACTOR = "apidojo/tweet-scraper"
INFLUENCER_NAME = "Wizarab"
COUNTRY = "Nigeria"
PLATFORM = "X"
HANDLE = "Wizarab10"

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

SEARCH_TERMS = [
    "masculinity",
    "man",
    "men",
    "male",
    "masculine",
    "woman",
    "women",
    "wife",
    "wives",
    "marry",
    "marriage",
    "dating",
    "relationship",
    "love",
    "feminism",
    "feminist",
    "single mother",
    "baby mama",
    "child support",
    "divorce",
    "body count",
    "virgin",
    "sex",
    "rape",
    "assault",
    "abuse",
    "cheating",
    "faithful",
    "loyalty",
    "provider",
    "money",
    "spend",
    "equality",
    "gender",
    "responsibility",
    "accountability",
    "modern woman",
    "submissive",
    "submit",
    "respect",
    "disrespect",
    "paternity",
    "DNA",
    "alimony",
    "marriage market",
    "women are",
    "men are",
    "false accusation",
    "gold digger",
    "gold-digger",
    "promiscuous",
    "promiscuity",
    "hypergamy",
    "patriarchy",
    "single mothers",
    "modern women",
    "false accusations",
]

APIDOJO_QUERIES = [
    f"from:{HANDLE} {term}" for term in [
        "masculinity",
        "man OR men OR male OR masculine",
        "woman OR women OR wife OR wives",
        "marry OR marriage OR wife",
        "dating OR relationship OR love",
        "feminism OR feminist",
        '"single mother" OR "baby mama"',
        '"child support"',
        "divorce",
        '"body count" OR virgin OR sex',
        "rape OR assault OR abuse",
        "cheating OR faithful OR loyalty",
        "provider OR money OR spend",
        "equality OR gender",
        "responsibility OR accountability",
        '"modern woman"',
        "submissive OR submit",
        "respect OR disrespect",
        "paternity OR DNA",
        "alimony",
        '"marriage market"',
        '"women are"',
        '"men are"',
        '"false accusation"',
        '"gold digger" OR gold-digger',
        "promiscuous OR promiscuity",
        "hypergamy",
        "patriarchy",
        '"single mothers"',
        '"modern women"',
        '"false accusations"',
    ]
]

TOPIC_KEYWORDS = {
    "dating/marriage": [
        "dating",
        "relationship",
        "love",
        "marry",
        "marriage",
        "wife",
        "wives",
        "husband",
        "girlfriend",
        "boyfriend",
    ],
    "women/feminism": [
        "woman",
        "women",
        "female",
        "feminism",
        "feminist",
        "modern woman",
        "modern women",
        "patriarchy",
    ],
    "male grievance/victimhood": [
        "men are",
        "man is",
        "against men",
        "false accusation",
        "false accusations",
        "disrespect",
        "unfair",
        "victim",
        "exploited",
    ],
    "provision/status/money": [
        "provider",
        "provide",
        "money",
        "spend",
        "pay",
        "bills",
        "breadwinner",
        "gold digger",
        "gold-digger",
        "transactional",
    ],
    "sexuality/body count": [
        "body count",
        "virgin",
        "virginity",
        "sex",
        "sexual",
        "promiscuous",
        "promiscuity",
        "cheating",
        "faithful",
        "loyalty",
        "hypergamy",
    ],
    "child support/divorce": [
        "child support",
        "divorce",
        "custody",
        "alimony",
        "baby mama",
        "single mother",
        "single mothers",
        "deadbeat",
    ],
    "family/parenting": [
        "family",
        "parent",
        "parenting",
        "father",
        "mother",
        "child",
        "children",
        "son",
        "daughter",
        "baby",
    ],
    "rape/assault/abuse": [
        "rape",
        "raped",
        "rapist",
        "assault",
        "abuse",
        "abused",
        "violence",
        "harassment",
        "consent",
    ],
    "paternity/DNA": [
        "paternity",
        "dna",
        "dna test",
        "paternity fraud",
        "fathered",
        "not your child",
    ],
    "gender equality": [
        "gender",
        "equality",
        "equal",
        "equal rights",
        "gender roles",
        "patriarchy",
    ],
    "social/political commentary": [
        "government",
        "politics",
        "law",
        "court",
        "police",
        "nigeria",
        "society",
        "culture",
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
    "gender",
    "father",
    "dad",
    "daddy",
    "mother",
    "mum",
    "mom",
    "husband",
    "boy",
    "girl",
    "babe",
]

HIGH_RELEVANCE_TERMS = [
    "feminism",
    "feminist",
    "single mother",
    "single mothers",
    "baby mama",
    "child support",
    "divorce",
    "body count",
    "false accusation",
    "false accusations",
    "gold digger",
    "gold-digger",
    "promiscuous",
    "promiscuity",
    "hypergamy",
    "patriarchy",
    "paternity",
    "dna",
    "alimony",
    "marriage market",
    "modern woman",
    "modern women",
    "submissive",
    "submit",
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
    "respect",
    "disrespect",
    "accountability",
    "responsibility",
    "protect yourself",
]

THEME_RULES = [
    ("men are disadvantaged/victims", ["men are", "against men", "false accusation", "false accusations", "unfair to men", "men suffer"]),
    ("women/feminism are framed as a problem", ["feminism", "feminist", "patriarchy", "toxic women"]),
    ("women are framed as exploitative", ["gold digger", "gold-digger", "exploit", "use men", "use a man", "transactional"]),
    ("modern women are framed negatively", ["modern woman", "modern women"]),
    ("child support/divorce framed as unfair to men", ["child support", "divorce", "alimony", "custody"]),
    ("paternity/DNA anxiety", ["paternity", "dna", "paternity fraud", "not your child"]),
    ("false accusation anxiety", ["false accusation", "false accusations", "falsely accused"]),
    ("sexual double standards", ["body count", "virgin", "promiscuous", "promiscuity", "cheating", "sexual past"]),
    ("female sexuality framed as threat", ["body count", "promiscuous", "hypergamy", "cheating", "sex"]),
    ("single mothers framed negatively", ["single mother", "single mothers", "baby mama"]),
    ("men need to protect themselves", ["protect yourself", "avoid", "never", "dna test", "sign prenup"]),
    ("men need to provide/succeed", ["provider", "provide", "money", "bills", "spend", "breadwinner"]),
    ("women should be accountable", ["accountability", "hold women accountable", "women should"]),
    ("gender equality framed negatively", ["gender equality", "equality", "equal rights"]),
]


@dataclass
class RunReport:
    api_errors: list[str] = field(default_factory=list)
    missing_fields: Counter = field(default_factory=Counter)
    run_inputs: list[dict[str, Any]] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape @Wizarab10 tweets and filter content-analysis items.")
    parser.add_argument("--output-dir", default="outputs", help="Directory for output files.")
    parser.add_argument("--target-raw", type=int, default=1000, help="Raw tweet target before dedupe/filtering.")
    parser.add_argument("--target-filtered", type=int, default=100, help="Final retained item target.")
    parser.add_argument("--search-actor", default=DEFAULT_SEARCH_ACTOR, help="Apify X/Twitter scraper actor ID.")
    parser.add_argument("--start-date", default="", help="Optional start date, e.g. 2025-01-01.")
    parser.add_argument("--end-date", default="", help="Optional end date, e.g. 2026-03-27.")
    parser.add_argument("--wait-secs", type=int, default=180, help="Seconds to wait for each Apify actor run.")
    parser.add_argument("--max-total-charge-usd", default="0.30", help="Apify cost guardrail per actor run.")
    parser.add_argument("--local-only", action="store_true", help="Filter existing raw_wizarab_tweets.csv only.")
    return parser.parse_args()


def require_token() -> str:
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise RuntimeError("APIFY_TOKEN is not set. Export it before running the Apify scrape.")
    return token


def build_actor_input(args: argparse.Namespace) -> dict[str, Any]:
    if args.search_actor == APIDOJO_SEARCH_ACTOR:
        return {
            "searchTerms": [f"{query} -filter:retweets" for query in APIDOJO_QUERIES],
            "sort": "Top",
            "maxItems": args.target_raw,
            "includeSearchTerms": True,
        }

    run_input: dict[str, Any] = {
        "fromUsers": [HANDLE],
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
    return run_input


def run_apify(args: argparse.Namespace, report: RunReport) -> list[dict[str, Any]]:
    client = ApifyClient(require_token())
    run_input = build_actor_input(args)
    report.run_inputs.append({"actor_id": args.search_actor, "run_input": sanitized_run_input(run_input)})
    kwargs: dict[str, Any] = {"run_input": run_input, "wait_secs": args.wait_secs}
    if args.max_total_charge_usd.strip():
        kwargs["max_total_charge_usd"] = Decimal(args.max_total_charge_usd)
    print(f"Running Apify actor {args.search_actor} for @{HANDLE} ...", file=sys.stderr)
    try:
        run = client.actor(args.search_actor).call(**kwargs)
        dataset_id = run.get("defaultDatasetId") if run else None
        if not dataset_id:
            report.api_errors.append(f"{args.search_actor}: no defaultDatasetId returned.")
            return []
        rows = []
        for item in client.dataset(dataset_id).iterate_items():
            if isinstance(item, dict):
                item["_source_actor"] = args.search_actor
                rows.append(item)
        return rows
    except Exception as exc:  # noqa: BLE001
        report.api_errors.append(f"{args.search_actor}: {type(exc).__name__}: {exc}")
        return []


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
    if value in (None, ""):
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
        parts = []
        for entry in value:
            if isinstance(entry, dict):
                parts.append(str(entry.get("url") or entry.get("screen_name") or entry.get("username") or entry.get("text") or entry.get("tag") or entry))
            else:
                parts.append(str(entry))
        return "; ".join(dict.fromkeys([part for part in parts if part]))
    if isinstance(value, dict):
        return "; ".join(f"{k}={v}" for k, v in value.items())
    return str(value)


def extract_hashtags(item: dict[str, Any]) -> str:
    candidates = [first_present(item, ["hashtags"]), first_present(item, ["entities.hashtags"]), first_present(item, ["legacy.entities.hashtags"])]
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


def extract_mentions(item: dict[str, Any]) -> str:
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


def extract_media(item: dict[str, Any]) -> str:
    candidates = [
        first_present(item, ["mediaUrls"]),
        first_present(item, ["media_urls"]),
        first_present(item, ["imageUrls"]),
        first_present(item, ["videoUrls"]),
        first_present(item, ["media"]),
        first_present(item, ["entities.media"]),
        first_present(item, ["extendedEntities.media"]),
    ]
    urls: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            for entry in candidate:
                if isinstance(entry, dict):
                    url = entry.get("url") or entry.get("expanded_url") or entry.get("media_url_https") or entry.get("mediaUrl")
                    if url:
                        urls.append(str(url))
                elif entry:
                    urls.append(str(entry))
        elif isinstance(candidate, str):
            urls.extend(re.findall(r"https?://\S+", candidate))
    return "; ".join(dict.fromkeys(urls))


def normalize_item(item: dict[str, Any], report: RunReport) -> dict[str, Any]:
    tweet_id = first_present(item, ["tweet_id", "id", "id_str", "tweetId", "postId", "rest_id"])
    text = first_present(item, ["full_text", "text", "tweetText", "postText", "content", "legacy.full_text"])
    author = first_present(item, ["author_username", "author.userName", "author.username", "authorHandle", "user.username", "username"])
    author = str(author or "").lstrip("@")
    url = first_present(item, ["tweet_url", "url", "postUrl", "twitterUrl", "permalink"])
    if not url and tweet_id and author:
        url = f"https://x.com/{author}/status/{tweet_id}"
    conversation_id = first_present(item, ["conversation_id", "conversationId", "conversation_id_str"])

    row = {
        "tweet_id": str(tweet_id or ""),
        "tweet_url": str(url or ""),
        "created_at": first_present(item, ["created_at", "createdAt", "postDateTime", "date", "timestamp", "legacy.created_at"]) or "",
        "full_text": str(text or ""),
        "author_username": author,
        "is_reply": as_bool(first_present(item, ["is_reply", "isReply", "replyingTo", "inReplyToStatusId", "replyToPostId", "replyToHandle"])),
        "is_retweet": as_bool(first_present(item, ["is_retweet", "isRetweet", "retweeted"])) or str(text or "").startswith("RT @"),
        "is_quote": as_bool(first_present(item, ["is_quote", "isQuote", "quotedStatus", "quoted_tweet", "quotedPostId"])),
        "is_thread": as_bool(first_present(item, ["is_thread", "isThread", "thread"])) or bool(conversation_id and tweet_id and str(conversation_id) == str(tweet_id)),
        "conversation_id": str(conversation_id or ""),
        "reply_count": as_int(first_present(item, ["reply_count", "replyCount", "nbReplies", "replies"])),
        "retweet_count": as_int(first_present(item, ["retweet_count", "retweetCount", "nbReposts", "retweets", "repostCount"])),
        "quote_count": as_int(first_present(item, ["quote_count", "quoteCount", "quotes"])),
        "like_count": as_int(first_present(item, ["like_count", "likeCount", "nbLikes", "favorite_count", "likes"])),
        "view_count": as_int(first_present(item, ["view_count", "viewCount", "nbViews", "views", "impressionCount"])),
        "hashtags": extract_hashtags(item),
        "mentioned_users": extract_mentions(item),
        "media_urls": extract_media(item),
        "language": first_present(item, ["language", "lang", "tweetLanguage"]) or "",
        "source_query": stringify_list(first_present(item, ["searchTerm", "searchTerms", "query"])),
        "source_actor": item.get("_source_actor", ""),
    }
    for column in RAW_COLUMNS:
        if row.get(column) in (None, "", 0, False) and column not in {"is_reply", "is_retweet", "is_quote", "is_thread"}:
            report.missing_fields[column] += 1
    return row


def normalize_text_for_duplicate(text: str) -> str:
    text = re.sub(r"https?://\S+", "", str(text).lower())
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def dedupe(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return raw_df
    df = raw_df.copy()
    df["_dedupe_text"] = df["full_text"].map(normalize_text_for_duplicate)
    if "tweet_id" in df.columns:
        non_empty_id = df["tweet_id"].astype(str).str.len() > 0
        with_id = df[non_empty_id].drop_duplicates(subset=["tweet_id"], keep="first")
        without_id = df[~non_empty_id]
        df = pd.concat([with_id, without_id], ignore_index=True)
    non_empty_text = df["_dedupe_text"].astype(str).str.len() > 0
    with_text = df[non_empty_text].drop_duplicates(subset=["_dedupe_text"], keep="first")
    without_text = df[~non_empty_text]
    return pd.concat([with_text, without_text], ignore_index=True).drop(columns=["_dedupe_text"])


def text_contains(text: str, terms: list[str]) -> list[str]:
    found = []
    lowered = text.lower()
    for term in terms:
        pattern = r"\b" + re.escape(term.lower()).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, lowered):
            found.append(term)
    return found


def classify_topic(text: str) -> tuple[str, list[str]]:
    counts = {topic: len(text_contains(text, terms)) for topic, terms in TOPIC_KEYWORDS.items()}
    ordered = [topic for topic, count in sorted(counts.items(), key=lambda item: item[1], reverse=True) if count > 0]
    if not ordered:
        return "other", []
    return ordered[0], ordered[1:4]


def classify_themes(text: str) -> list[str]:
    themes = [label for label, terms in THEME_RULES if text_contains(text, terms)]
    return themes or ["mixed/unclear"]


def classify_rhetorical_mode(text: str, themes: list[str]) -> str:
    lowered = text.lower()
    if "men are disadvantaged/victims" in themes or "false accusation anxiety" in themes:
        return "grievance claim"
    if text_contains(lowered, ["avoid", "beware", "warning", "never", "do not", "don't", "protect yourself"]):
        return "warning"
    if text_contains(lowered, ["should", "must", "need to", "needs to", "rule", "principle"]):
        return "rule-setting"
    if text_contains(lowered, ["fool", "simp", "stupid", "clown", "delusional"]):
        return "ridicule"
    if re.search(r"^\s*(men|man|women|woman|wife|wives)\b", lowered):
        return "personal claim"
    if re.search(r"\b(do|make|choose|learn|stop|avoid|protect|get|be)\b", lowered):
        return "advice"
    return "commentary" if len(text.split()) > 8 else "other"


def classify_orientation(text: str, themes: list[str], score: int) -> str:
    regressive_themes = {
        "men are disadvantaged/victims",
        "women/feminism are framed as a problem",
        "women are framed as exploitative",
        "modern women are framed negatively",
        "child support/divorce framed as unfair to men",
        "paternity/DNA anxiety",
        "false accusation anxiety",
        "sexual double standards",
        "female sexuality framed as threat",
        "single mothers framed negatively",
        "gender equality framed negatively",
    }
    progressive_terms = ["gender equality is good", "equal rights", "respect women", "protect women", "believe victims"]
    if any(theme in regressive_themes for theme in themes):
        return "regressive"
    if text_contains(text, progressive_terms):
        return "progressive"
    if score >= 3:
        return "mixed"
    return "unclear"


def classify_gender_norm_type(text: str, score: int) -> str:
    if score < 3:
        return "none"
    return "explicit" if text_contains(text, GENDER_TERMS + HIGH_RELEVANCE_TERMS) else "implicit"


def relevance_score_and_reason(row: pd.Series) -> tuple[int, str, str]:
    text = str(row.get("full_text", ""))
    lowered = text.lower()
    words = re.findall(r"\w+", lowered)
    if not text.strip():
        return 1, "Exclude: empty text.", "empty text"
    if row.get("is_retweet"):
        return 1, "Exclude: retweet without original Wizarab text.", "retweet"
    if len(words) < 5:
        return 1, "Exclude: too short or unclear to code meaningfully.", "too short"

    gender_hits = text_contains(lowered, GENDER_TERMS)
    high_hits = text_contains(lowered, HIGH_RELEVANCE_TERMS)
    normative_hits = text_contains(lowered, NORMATIVE_TERMS)
    primary_topic, _ = classify_topic(lowered)
    topic_hits = sum(1 for terms in TOPIC_KEYWORDS.values() if text_contains(lowered, terms))
    gender_pronoun_signal = bool(re.search(r"\b(she|her|hers|he|him|his)\b", lowered)) and primary_topic in {
        "dating/marriage",
        "sexuality/body count",
        "rape/assault/abuse",
        "family/parenting",
    }
    scope_signal = bool(gender_hits or high_hits or gender_pronoun_signal)

    if re.search(r"\b(happy birthday|congratulations|congrats|good morning|good night)\b", lowered):
        return 1, "Exclude: greeting or personal note without analyzable gender content.", "greeting/personal note"
    if re.search(r"\b(arsenal|bayern|psg|atletico|chelsea|manchester|liverpool)\b", lowered) and text_contains(lowered, ["rape", "raped"]):
        return 1, "Exclude: sports metaphor using assault language without analyzable gender content.", "sports metaphor"
    if "market men and women" in lowered and not high_hits:
        return 1, "Exclude: generic reference to men and women without a gender-norm claim.", "generic social/political commentary"
    if primary_topic == "social/political commentary" and not high_hits:
        return 1, "Exclude: social/political commentary without a specific gender-grievance or gender-norm claim.", "generic social/political commentary"
    if primary_topic == "family/parenting" and not high_hits and not text_contains(
        lowered,
        ["child support", "paternity", "dna", "divorce", "single mother", "baby mama", "wife", "husband", "marriage"],
    ):
        return 1, "Exclude: generic family/parenting mention without a gender-norm claim.", "generic family/parenting"
    if primary_topic == "provision/status/money" and not high_hits and not text_contains(
        lowered,
        ["man", "men", "woman", "women", "wife", "husband", "girlfriend", "boyfriend", "partner", "relationship", "gender"],
    ):
        return 1, "Exclude: generic money/status post without clear gender content.", "generic provision/status/money"
    if not scope_signal and primary_topic in {"provision/status/money", "family/parenting", "social/political commentary", "other"}:
        return 1, "Exclude: generic topic without a clear gender/masculinity angle.", f"generic {primary_topic}"
    if not scope_signal and primary_topic == "dating/marriage" and not text_contains(lowered, ["marriage", "wife", "husband", "dating", "boyfriend", "girlfriend"]):
        return 1, "Exclude: ambiguous relationship/motivation post without clear gender content.", "weak relevance"

    points = min(len(gender_hits), 3)
    points += min(len(high_hits) * 2, 6)
    points += min(len(normative_hits), 2)
    points += min(topic_hits, 4)
    if primary_topic in {"women/feminism", "sexuality/body count", "child support/divorce", "rape/assault/abuse", "paternity/DNA", "gender equality"}:
        points += 2
    if primary_topic in {"dating/marriage", "male grievance/victimhood", "provision/status/money", "family/parenting"} and gender_hits:
        points += 1
    if row.get("is_reply"):
        points -= 1
    if re.search(r"\b(men|man|male)\b.*\b(false|accused|victim|disadvantaged|responsibility|protect|provide|pay)\b", lowered):
        points += 3
    if re.search(r"\b(women|woman|wife|wives|feminist)\b.*\b(exploit|accountab|money|support|divorce|body count|promiscu|submit|respect)\b", lowered):
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
        matched = high_hits[:4] or gender_hits[:4]
        detail = f"; matched {', '.join(matched)}" if matched else ""
        return score, f"Central gender/masculinity or gender-grievance content{detail}.", ""
    if score == 3:
        return score, f"Implicit but usable gender/masculinity relevance via {primary_topic}.", ""
    if primary_topic == "social/political commentary":
        return score, "Exclude: generic social/political commentary without clear gender angle.", "generic social/political commentary"
    if primary_topic != "other":
        return score, "Exclude: weak relevance to project scope.", "weak relevance"
    return score, "Exclude: no clear masculinity or gender-norm angle.", "no gender angle"


def code_rows(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, Counter]:
    exclusion_reasons: Counter = Counter()
    rows: list[dict[str, Any]] = []
    for _, row in raw_df.iterrows():
        score, reason, exclusion_reason = relevance_score_and_reason(row)
        text = str(row.get("full_text", ""))
        primary_topic, secondary_topics = classify_topic(text)
        themes = classify_themes(text)
        rhetorical_mode = classify_rhetorical_mode(text, themes)
        engagement = as_int(row.get("like_count")) + as_int(row.get("reply_count")) + as_int(row.get("retweet_count")) + as_int(row.get("quote_count"))
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
        rows.append(
            {
                "influencer_name": INFLUENCER_NAME,
                "country": COUNTRY,
                "platform": PLATFORM,
                "tweet_id": row.get("tweet_id", ""),
                "tweet_url": row.get("tweet_url", ""),
                "created_at": row.get("created_at", ""),
                "full_text": text,
                "engagement_score": engagement,
                "views": as_int(row.get("view_count")),
                "likes": as_int(row.get("like_count")),
                "replies": as_int(row.get("reply_count")),
                "reposts": as_int(row.get("retweet_count")),
                "quotes": as_int(row.get("quote_count")),
                "relevance_score_1_to_5": score,
                "relevance_reason": reason,
                "primary_topic": primary_topic,
                "secondary_topics": "; ".join(secondary_topics),
                "masculinity_orientation": classify_orientation(text, themes, score),
                "gender_norm_type": classify_gender_norm_type(text, score),
                "rhetorical_mode": rhetorical_mode,
                "key_themes": "; ".join(themes),
                "keep_for_content_analysis": keep,
                "notes": "reply retained for standalone content" if row.get("is_reply") and keep else "",
            }
        )
    return pd.DataFrame(rows, columns=FINAL_COLUMNS), exclusion_reasons


def select_diverse(coded_df: pd.DataFrame, target: int) -> pd.DataFrame:
    candidates = coded_df[coded_df["keep_for_content_analysis"]].copy()
    candidates = candidates.sort_values(["relevance_score_1_to_5", "engagement_score"], ascending=[False, False])
    selected_parts: list[pd.DataFrame] = []
    selected_ids: set[str] = set()

    score5 = candidates[candidates["relevance_score_1_to_5"] == 5]
    if len(score5) >= target:
        return round_robin_topics(score5, target)
    selected_parts.append(score5)
    selected_ids.update(score5["tweet_id"].astype(str))

    for score in [4, 3]:
        remaining_slots = target - sum(len(part) for part in selected_parts)
        if remaining_slots <= 0:
            break
        pool = candidates[(candidates["relevance_score_1_to_5"] == score) & ~candidates["tweet_id"].astype(str).isin(selected_ids)]
        selected = round_robin_topics(pool, remaining_slots)
        selected_parts.append(selected)
        selected_ids.update(selected["tweet_id"].astype(str))

    if not selected_parts:
        return candidates.head(0)
    final = pd.concat(selected_parts, ignore_index=True)
    return final.sort_values(["relevance_score_1_to_5", "engagement_score"], ascending=[False, False]).head(target)


def round_robin_topics(df: pd.DataFrame, target: int) -> pd.DataFrame:
    if df.empty or target <= 0:
        return df.head(0)
    groups = {
        topic: group.sort_values(["relevance_score_1_to_5", "engagement_score"], ascending=[False, False]).to_dict("records")
        for topic, group in df.groupby("primary_topic", dropna=False)
    }
    topic_order = sorted(groups, key=lambda topic: len(groups[topic]), reverse=True)
    selected: list[dict[str, Any]] = []
    while len(selected) < target and any(groups.values()):
        for topic in topic_order:
            if groups[topic] and len(selected) < target:
                selected.append(groups[topic].pop(0))
    return pd.DataFrame(selected, columns=df.columns)


def save_outputs(raw_df: pd.DataFrame, filtered_df: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_df.to_csv(output_dir / "raw_wizarab_tweets.csv", index=False)
    raw_df.to_excel(output_dir / "raw_wizarab_tweets.xlsx", index=False)
    filtered_df.to_csv(output_dir / "filtered_wizarab_content_analysis_100.csv", index=False)
    filtered_df.to_excel(output_dir / "filtered_wizarab_content_analysis_100.xlsx", index=False)


def topic_diversity_note(filtered_df: pd.DataFrame) -> str:
    if filtered_df.empty:
        return "No retained tweets, so topic diversity could not be assessed."
    counts = filtered_df["primary_topic"].value_counts()
    top_topic = counts.index[0]
    top_share = counts.iloc[0] / len(filtered_df)
    represented = len(counts)
    if top_share > 0.45:
        return f"Final set is somewhat dominated by {top_topic} ({counts.iloc[0]}/{len(filtered_df)}), with {represented} topics represented."
    return f"Final set has usable topic diversity: {represented} topics represented; largest topic is {top_topic} ({counts.iloc[0]}/{len(filtered_df)})."


def write_summary(raw_df: pd.DataFrame, filtered_df: pd.DataFrame, exclusions: Counter, report: RunReport, output_dir: Path) -> None:
    lines = [
        "Wizarab X scraping and filtering summary",
        "=" * 46,
        f"Number of raw tweets collected: {len(raw_df)}",
        f"Number retained: {len(filtered_df)}",
        f"Number excluded: {max(len(raw_df) - len(filtered_df), 0)}",
        "",
        "Apify actor runs:",
    ]
    if report.run_inputs:
        for index, run in enumerate(report.run_inputs, 1):
            lines.append(f"{index}. {run['actor_id']}: {run['run_input']}")
    else:
        lines.append("No Apify runs recorded (local-only mode or scrape did not start).")

    lines.extend(["", "Main exclusion reasons:"])
    if exclusions:
        lines.extend(f"- {reason}: {count}" for reason, count in exclusions.most_common())
    else:
        lines.append("- None recorded.")

    for title, column in [
        ("Count by primary_topic:", "primary_topic"),
        ("Count by masculinity_orientation:", "masculinity_orientation"),
        ("Count by relevance score:", "relevance_score_1_to_5"),
    ]:
        lines.extend(["", title])
        if filtered_df.empty:
            lines.append("- None")
        else:
            lines.extend(f"- {label}: {count}" for label, count in Counter(filtered_df[column].dropna().astype(str)).most_common())

    lines.extend(["", "Top 10 retained tweets by engagement_score:"])
    if filtered_df.empty:
        lines.append("- None retained.")
    else:
        top = filtered_df.sort_values("engagement_score", ascending=False).head(10)
        for _, row in top.iterrows():
            text = re.sub(r"\s+", " ", str(row.get("full_text", ""))).strip()
            if len(text) > 180:
                text = text[:177] + "..."
            lines.append(f"- {row.get('engagement_score', 0)} | score {row.get('relevance_score_1_to_5', '')} | {row.get('tweet_url', '')} | {text}")

    lines.extend(["", "Topic diversity note:", f"- {topic_diversity_note(filtered_df)}"])
    lines.extend(["", "Apify/API errors:"])
    lines.extend([f"- {error}" for error in report.api_errors] or ["- None recorded."])
    lines.extend(["", "Missing fields observed during normalization:"])
    if report.missing_fields:
        lines.extend(f"- {field_name}: missing/empty in {count} normalized item(s)" for field_name, count in report.missing_fields.most_common())
    else:
        lines.append("- None recorded.")
    (output_dir / "wizarab_filtering_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_or_scrape(args: argparse.Namespace, output_dir: Path, report: RunReport) -> pd.DataFrame:
    raw_path = output_dir / "raw_wizarab_tweets.csv"
    if args.local_only:
        if not raw_path.exists():
            raise FileNotFoundError(f"{raw_path} does not exist.")
        return pd.read_csv(raw_path).fillna("")
    items = run_apify(args, report)
    rows = [normalize_item(item, report) for item in items]
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = RunReport()
    try:
        raw_df = dedupe(load_or_scrape(args, output_dir, report))
        if raw_df.empty:
            report.api_errors.append("No raw tweets were collected or loaded.")
            filtered_df = pd.DataFrame(columns=FINAL_COLUMNS)
            exclusions: Counter = Counter()
        else:
            coded_df, exclusions = code_rows(raw_df)
            filtered_df = select_diverse(coded_df, args.target_filtered)
        save_outputs(raw_df, filtered_df, output_dir)
        write_summary(raw_df, filtered_df, exclusions, report, output_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote Wizarab outputs to {output_dir.resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
