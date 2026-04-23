"""Scrape ~400 tweets per Nigeria creator via Apify (delicious_zebu actor),
filter for masculinity/gender scope relevance using the same 4-signal pipeline
as audience analysis, keep top ~150 per creator.

Actor: delicious_zebu/advanced-x-twitter-profile-scraper
Pricing on FREE tier: $0.0008 per tweet + ~$0.00005 actor start. 1600 tweets ~= $1.30.

Output: Scraped Tweets - Nigeria/<Creator>_scope_relevant.xlsx
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from apify_client import ApifyClient
from openai import AsyncOpenAI, OpenAI
from tqdm.asyncio import tqdm as atqdm
from tqdm.auto import tqdm


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

KEYWORDS_XLSX = ROOT / "Codebook and Keywords" / "NLC Proposed keywords.xlsx"
OUT_DIR = ROOT / "Scraped Tweets - Nigeria"
CACHE_DIR = ROOT / "temp" / "scraped_tweets_nigeria"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CREATORS = [
    {"name": "Deyemi Okanlawon",  "orientation": "Progressive", "handle": "_deyemi",   "raw_target": 1000},
    {"name": "Agba John Doe",     "orientation": "Regressive",  "handle": "jon_d_doe", "raw_target": 500},
    {"name": "Shola",             "orientation": "Regressive",  "handle": "itsSh0la",  "raw_target": 500},
    {"name": "Wizarab",           "orientation": "Regressive",  "handle": "Wizarab10", "raw_target": 500},
]
TARGET_AFTER_FILTER = 150
START_DATE = "2023-01-01"
END_DATE = "2026-04-23"
EMBED_MODEL = "text-embedding-3-large"
LLM_MODEL = "gpt-4o-mini"
LLM_BATCH_SIZE = 20
LLM_CONCURRENCY = 16

ANCHORS = [
    "views on what it means to be a man",
    "gender roles and masculinity",
    "traditional masculinity and providing for family",
    "progressive masculinity and emotional vulnerability",
    "marriage, infidelity and fidelity",
    "dating standards and expectations between men and women",
    "child support, divorce, and parenting responsibilities",
    "polygamy and female scarcity narratives",
    "rape, sexual violence and accountability",
    "male victimhood and abuse of boys",
    "feminism, misogyny and women's rights",
    "faith, partnership and trust in marriage",
    "religion and gender expectations",
    "advice to young men or young women",
    "money, status and masculinity",
    "women's bodies, sexuality, and respectability",
    "male mental health and emotional expression",
    "fatherhood and raising sons and daughters",
]

SCOPE_SYSTEM_PROMPT = """You are a qualitative research reviewer filtering Nigerian X (Twitter) posts from a single creator for a study on masculinity, gender, relationships, marriage, family, and adjacent social discourse.

Be GENEROUS. Keep a post if it touches ANY of these, even indirectly:
- Masculinity, manhood, male identity, being a man
- Gender roles, gender dynamics, gender norms, gender differences
- Dating, marriage, relationships, love, heartbreak, infidelity
- Female sexuality, female behavior, female stereotypes, women's roles
- Fatherhood, motherhood, parenting, raising children, family structure
- Child support, divorce, provider role, financial dynamics between partners
- Polygamy, marriage market dynamics, hypergamy
- Sex, sexual morality, body counts, virginity, sexual violence, rape, consent
- Feminism, misogyny, anti-feminism, women's rights
- Faith / religion as it connects to gender, marriage, or manhood
- Self-improvement, life advice, discipline, success, or status framed around men or masculinity
- Culture, respect, hierarchy, value between men and women
- Emotional expression, mental health, vulnerability among men

DROP ONLY if the post is clearly:
- Pure promo, ads, crypto / NFT / token shilling, product plugs, event RSVPs
- Sports / entertainment / movie promo with no gender commentary
- Birthday wishes, personal photo posts, travel pics
- Technical / business content unrelated to any of the themes above
- A one-word reaction or pure emoji tweet

When uncertain, KEEP the post. The filter is broad, deliberately — downstream coders will do the fine-grained sort.

Return JSON: {"results": [{"id": <int>, "keep": true/false, "reason": "<=10 words"}]}. Output nothing else."""


def normalize_text(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    return re.sub(r"\s+", " ", s).strip()


def strip_urls_mentions(s):
    s = re.sub(r"https?://\S+|www\.\S+", "", s)
    s = re.sub(r"@\w+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def scrape_creator(client: ApifyClient, creator: dict) -> pd.DataFrame:
    cache_path = CACHE_DIR / f"raw_{creator['handle']}.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        print(f"  [{creator['name']}] loaded {len(df)} from cache")
        return df
    url = f"https://x.com/{creator['handle']}"
    target = creator.get("raw_target", 400)
    run_input = {
        "accountUrls": [url],
        "maxCollections": target,
        "language": "any",
        "splitMode": "month",
        "startDate": START_DATE,
        "endDate": END_DATE,
    }
    print(f"  [{creator['name']}] scraping up to {target} tweets from {url}...")
    run = client.actor("delicious_zebu/advanced-x-twitter-profile-scraper").call(
        run_input=run_input, timeout_secs=1800
    )
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    df = pd.DataFrame(items)
    # filter to only the creator's own tweets (actor sometimes returns adjacent content)
    if "authorHandle" in df.columns:
        df = df[df["authorHandle"].astype(str).str.lower() == creator["handle"].lower()].copy()
    df.to_parquet(cache_path, index=False)
    print(f"  [{creator['name']}] got {len(df)} own-authored tweets")
    return df


def filter_quality(df, creator_handle):
    if "fullText" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["text_raw"] = df["fullText"].apply(normalize_text)
    # Drop retweets (start with RT @...) and reply-only that address others (keep original content)
    df["stripped"] = df["text_raw"].apply(strip_urls_mentions)
    df["n_words"] = df["stripped"].str.split().str.len()
    # Original posts tend to not start with @ (replies do). But creator's own tweets are kept regardless.
    # Require at least 5 words of actual text after stripping URLs and @mentions.
    df = df[df["n_words"] >= 5].copy()
    # Drop exact duplicates on text
    df = df.drop_duplicates(subset="stripped").reset_index(drop=True)
    return df


def load_keywords():
    kw_df = pd.read_excel(KEYWORDS_XLSX, sheet_name="Nigeria")
    kw_df = kw_df.dropna(subset=["Keyword"])
    kw_df["Keyword"] = kw_df["Keyword"].astype(str).str.strip()
    kw_df = kw_df[kw_df["Keyword"].str.len() >= 2]
    rel_col = "Relevance to manosphere conversations"
    hi = set(kw_df.loc[kw_df[rel_col].astype(str).str.contains("Highly", na=False), "Keyword"].str.lower())
    mod = set(kw_df.loc[kw_df[rel_col].astype(str).str.contains("Moderately", na=False), "Keyword"].str.lower())
    all_kws = sorted(hi | mod, key=len, reverse=True)
    if not all_kws:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in all_kws) + r")\b", flags=re.IGNORECASE)


def annotate_keywords(df, kw_regex):
    df = df.copy()
    df["has_keyword"] = df["text_raw"].str.lower().apply(lambda s: bool(kw_regex.search(s)) if kw_regex else False)
    df["n_keyword_hits"] = df["text_raw"].str.lower().apply(
        lambda s: len(kw_regex.findall(s)) if kw_regex else 0
    )
    return df


def compute_embeddings(client_sync: OpenAI, texts):
    out = []
    BATCH = 256
    for start in range(0, len(texts), BATCH):
        batch = texts[start:start + BATCH]
        r = client_sync.embeddings.create(model=EMBED_MODEL, input=batch)
        out.append(np.array([d.embedding for d in r.data]))
    return np.vstack(out) if out else np.empty((0, 3072))


def score_similarity(emb, anchor_emb):
    e = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    a = anchor_emb / np.linalg.norm(anchor_emb, axis=1, keepdims=True)
    sim = e @ a.T
    return sim.max(axis=1), sim.argmax(axis=1)


async def llm_classify(texts, async_client):
    sem = asyncio.Semaphore(LLM_CONCURRENCY)
    async def batch(local_to_global, batch_items):
        async with sem:
            for attempt in range(3):
                try:
                    user = "\n".join([f"[{i}] {t[:400]}" for i, t in batch_items])
                    resp = await async_client.chat.completions.create(
                        model=LLM_MODEL, temperature=0,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": SCOPE_SYSTEM_PROMPT},
                            {"role": "user", "content": user},
                        ],
                    )
                    data = json.loads(resp.choices[0].message.content)
                    out = []
                    for r in data.get("results", []):
                        lid = r.get("id")
                        if lid in local_to_global:
                            out.append((local_to_global[lid], bool(r.get("keep")), r.get("reason", "")))
                    return out
                except Exception:
                    await asyncio.sleep(2 ** attempt)
            return [(local_to_global[i], None, "error") for i, _ in batch_items]

    tasks = []
    for start in range(0, len(texts), LLM_BATCH_SIZE):
        chunk = list(enumerate(texts[start:start + LLM_BATCH_SIZE], start=start))
        local_to_global = {gi: gi for gi, _ in chunk}
        tasks.append(asyncio.create_task(batch(local_to_global, chunk)))

    all_rows = []
    for fut in atqdm.as_completed(tasks, total=len(tasks), desc="LLM filter"):
        all_rows.extend(await fut)
    return {gi: (keep, reason) for gi, keep, reason in all_rows}


def main():
    apify_key = os.getenv("APIFY_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    assert apify_key and openai_key, "Missing API keys in .env"

    apify = ApifyClient(apify_key)
    openai_sync = OpenAI()
    anchor_emb = compute_embeddings(openai_sync, ANCHORS)

    kw_regex = load_keywords()

    summary_rows = []
    for creator in CREATORS:
        print(f"\n=== {creator['name']} ({creator['orientation']}) ===")
        raw = scrape_creator(apify, creator)
        if raw.empty:
            print(f"  !! no raw data, skipping")
            continue

        # Basic quality filter
        df = filter_quality(raw, creator["handle"])
        print(f"  after quality filter: {len(df)}")
        if df.empty:
            continue

        # Keyword annotation (signal, not gate)
        df = annotate_keywords(df, kw_regex)

        # Embeddings + similarity
        emb = compute_embeddings(openai_sync, df["text_raw"].tolist())
        sim_max, sim_idx = score_similarity(emb, anchor_emb)
        df["sim_max"] = sim_max
        df["sim_top_anchor"] = [ANCHORS[i] for i in sim_idx]

        # LLM scope filter
        async_client = AsyncOpenAI()
        verdicts = asyncio.run(llm_classify(df["text_raw"].tolist(), async_client))
        df = df.reset_index(drop=True)
        df["llm_keep"] = [bool(verdicts.get(i, (False,))[0]) for i in range(len(df))]
        df["llm_reason"] = [verdicts.get(i, (None, ""))[1] for i in range(len(df))]

        # Composite score (40% LLM, 35% similarity, 25% keyword)
        sim_scaled = (df["sim_max"] - df["sim_max"].min()) / (df["sim_max"].max() - df["sim_max"].min() + 1e-9)
        df["score"] = 0.25 * df["has_keyword"].astype(float) + 0.35 * sim_scaled + 0.40 * df["llm_keep"].astype(float)

        # Select LLM-relevant only, top-TARGET by score, no padding
        eligible = df[df["llm_keep"]].copy()
        eligible = eligible.sort_values("score", ascending=False).head(TARGET_AFTER_FILTER)
        eligible = eligible.reset_index(drop=True)
        eligible["rank"] = range(1, len(eligible) + 1)

        # Export (text-only file + full metadata file)
        out_text = eligible[["text_raw"]].rename(columns={"text_raw": "text"})
        out_text.to_excel(OUT_DIR / f"{creator['name']}_scope_relevant.xlsx", index=False)
        full_cols = ["rank", "text_raw", "n_words", "has_keyword", "sim_max", "sim_top_anchor",
                      "llm_keep", "llm_reason", "score", "createdAt", "likeCount",
                      "replyCount", "repostCount", "tweetUrl"]
        full_cols = [c for c in full_cols if c in eligible.columns]
        eligible[full_cols].to_excel(OUT_DIR / f"{creator['name']}_scope_relevant_full.xlsx", index=False)

        print(f"  raw={len(raw)}  quality={len(df)}  llm_keep={int(df['llm_keep'].sum())}  final={len(eligible)}")
        summary_rows.append({
            "creator": creator["name"],
            "orientation": creator["orientation"],
            "raw_scraped": len(raw),
            "quality_passed": len(df),
            "llm_scope_relevant": int(df["llm_keep"].sum()),
            "final_selected": len(eligible),
        })

    pd.DataFrame(summary_rows).to_excel(OUT_DIR / "_summary.xlsx", index=False)
    print("\n=== SUMMARY ===")
    print(pd.DataFrame(summary_rows).to_string(index=False))


if __name__ == "__main__":
    main()
