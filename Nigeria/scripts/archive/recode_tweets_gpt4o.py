"""Re-tag all X tweets in Content - Final with gpt-4o for higher accuracy.

The earlier mini-model pass over-used "other_off_scope" — flagged ~40% of tweets
as off-scope when many were actually on-topic dating/marriage/sex content. This
script re-runs theme + context tagging with gpt-4o, then drops only the
confirmed off-scope rows.

Output: same files in Nigeria/Content Analysis/Content - Final/, overwritten with
the cleaner re-tagged data. Same schema.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from collections import Counter

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

RAW_DIR   = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw"
FINAL_DIR = ROOT / "Nigeria" / "Content Analysis" / "Content - Final"
TEMP_DIR  = ROOT / "temp" / "recode_tweets_gpt4o"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

LLM_MODEL = "gpt-4o"
BATCH_SIZE = 8       # smaller batches to stay under 30K TPM
CONCURRENCY = 3      # lower concurrency to avoid 30K TPM rate limit
RETRY_DELAY_BASE = 5 # back off harder on 429s

CREATORS = [
    {"name": "Deyemi Okanlawon", "orientation": "Progressive", "id_prefix": "DEY"},
    {"name": "Agba John Doe",    "orientation": "Regressive",  "id_prefix": "AGB"},
    {"name": "Shola",            "orientation": "Regressive",  "id_prefix": "SHO"},
    {"name": "Wizarab",          "orientation": "Regressive",  "id_prefix": "WIZ"},
]

CANONICAL_THEMES = [
    "marriage_relationships", "infidelity_cheating", "polygamy_scarcity",
    "female_submission", "men_as_prize", "marriage_market_logic",
    "dating_standards", "sexual_double_standards",
    "fatherhood_parenting", "raising_boys", "male_role_models",
    "men_money_provider", "wealth_status",
    "male_emotional_life", "vulnerability_mental_health", "male_friendship",
    "rape_sexual_violence", "false_accusations", "boy_child_male_victim",
    "gender_debate_feminism", "anti_women", "anti_feminism", "not_all_men_deflection",
    "religion_faith_framing", "biblical_marriage_framing",
    "humor_meme_pidgin", "self_promotion",
    "other_off_scope",  # used ONLY when truly off-topic; prompt enforces strict criteria
]
THEMES_FOR_PROMPT = [t for t in CANONICAL_THEMES if t != "other_off_scope"]

SYSTEM_PROMPT = """You are a research coder for the Norman Lear Center / Gates Foundation study of Nigerian masculinity influencers (regressive vs progressive). Each tweet is from one of:
- Deyemi Okanlawon (PROGRESSIVE — male accountability, anti-rape, vulnerability, male emotional life)
- Agba John Doe (REGRESSIVE — soft patriarchy, marriage advice, sexual double standards, "men will be men")
- Shola (REGRESSIVE — scarcity narratives, men-are-the-prize, female submission, anti-feminism)
- Wizarab (REGRESSIVE — anti-women cynicism, anti-feminism, denigration)

For each tweet, you MUST do TWO things:

1. THEMES: Pick 1-3 themes (semicolon-separated) from this exact list:
{themes}

CRITICAL: Be GENEROUS in attribution. The MAJORITY of tweets from these creators are on-scope for masculinity / gender / men's lives even when not explicit. Re-read each tweet carefully and ask "is this AT ALL related to gender, masculinity, men, women, marriage, dating, sex, fatherhood, money/provider pressure, religion-on-gender, mental health, female agency?". If yes → pick the closest theme(s).

ONLY use "other_off_scope" if the tweet is GENUINELY off-topic — e.g.:
  - Movie/show/song promo with no gender content
  - Generic political commentary about emigration / Nigerian economy unrelated to gender
  - Pure greetings, weather, food, sports
  - Cryptic one-liners with no interpretable content ("Yes, your suspicion is true.")
  - Replies to others without enough standalone meaning

Examples of tweets that LOOK off-scope but are actually IN-scope:
  - "Hustle for yours. Stop looking for another man to come save you" → female_submission, dating_standards
  - "She saw the first text, she's not busy. Don't double text her" → dating_standards
  - "They are not knacking enough and she is complaining" → sexual_double_standards
  - "many men shall fall again" → religion_faith_framing
  - Book promo for "Becoming A Better Man" → self_promotion (still keep — masculinity-related)

2. CONTEXT: Write ONE concise sentence (max 25 words) explaining what the tweet is about for a human coder unfamiliar with the creator. Include any references (case names, slang, shows, Pidgin idioms) the coder might miss.

Return JSON only:
{{"results": [{{"id": <int>, "themes": "theme1; theme2", "context": "..."}}]}}"""


def build_user_prompt(creator_name, batch):
    lines = [f"Creator: {creator_name}", "", "Tweets:"]
    for i, text in batch:
        lines.append(f"[{i}] {str(text).replace(chr(10), ' ')[:600]}")
    return "\n".join(lines)


async def code_batch(client, sem, creator_name, idx_to_text):
    items = list(idx_to_text.items())
    async with sem:
        for attempt in range(8):  # up to 8 retries (was 4)
            try:
                resp = await client.chat.completions.create(
                    model=LLM_MODEL, temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT.format(themes=", ".join(CANONICAL_THEMES))},
                        {"role": "user", "content": build_user_prompt(creator_name, items)},
                    ],
                )
                data = json.loads(resp.choices[0].message.content)
                out = {}
                for r in data.get("results", []):
                    rid = r.get("id")
                    if rid in idx_to_text:
                        out[rid] = (str(r.get("themes", "")), str(r.get("context", "")))
                return out
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "rate_limit" in err_str.lower():
                    delay = RETRY_DELAY_BASE * (2 ** attempt)  # 5, 10, 20, 40, 80, 160, 320, 640s
                    if attempt < 7:
                        await asyncio.sleep(min(delay, 90))
                        continue
                if attempt == 7:
                    print(f"  ! batch failed after retries: {err_str[:200]}", flush=True)
                    return {}
                await asyncio.sleep(2 ** attempt)


async def recode_creator(creator):
    # Read FROM Raw (untruncated, original 498 tweets) — the previous run
    # accidentally truncated Final and lost rate-limited rows.
    raw_path = RAW_DIR / creator["name"] / f"{creator['name']}_Twitter_Raw.xlsx"
    cache_path = TEMP_DIR / f"{creator['name'].replace(' ','_')}_v2.cache.json"
    df_raw = pd.read_excel(raw_path)
    print(f"\n=== {creator['name']} ({len(df_raw)} tweets, from Raw) ===", flush=True)

    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    text_col = "text"  # Raw schema uses lowercase
    pending = {i: row[text_col] for i, row in df_raw.iterrows() if str(i) not in cache}
    print(f"  cached: {len(cache)}, pending: {len(pending)}", flush=True)
    df = df_raw.rename(columns={"text": "Verbatim Text (CODE THIS)"})

    if pending:
        client = AsyncOpenAI()
        sem = asyncio.Semaphore(CONCURRENCY)
        coros = []
        items = list(pending.items())
        for start in range(0, len(items), BATCH_SIZE):
            chunk = dict(items[start:start + BATCH_SIZE])
            coros.append(code_batch(client, sem, creator["name"], chunk))
        results = await atqdm.gather(*coros, desc=f"{creator['name']}")
        for batch_out in results:
            for rid, (themes, ctx) in batch_out.items():
                cache[str(rid)] = {"themes": themes, "context": ctx}
        cache_path.write_text(json.dumps(cache, indent=1))

    # Apply re-tagged themes + context to df
    new_themes = []
    new_ctx = []
    for i, _ in df.iterrows():
        meta = cache.get(str(i), {"themes": "other_off_scope", "context": ""})
        new_themes.append(meta["themes"])
        new_ctx.append(meta["context"])
    df["Theme(s)"] = new_themes
    df["Context (NOT CODED - comprehension only)"] = new_ctx

    # Count off-scope BEFORE drop
    is_off = df["Theme(s)"].astype(str).str.strip().str.lower().isin(["other_off_scope", "off_scope"])
    print(f"  gpt-4o flagged off_scope: {int(is_off.sum())}/{len(df)}", flush=True)

    # Drop off-scope
    kept = df[~is_off].reset_index(drop=True)
    # Add the standard coding-unit columns (Raw schema lacks them)
    kept = kept.copy()
    kept["Segment ID"] = [f"{creator['id_prefix']}_{i+1:03d}" for i in range(len(kept))]
    kept["Influencer"] = creator["name"]
    kept["Platform"] = "X"
    kept["Content Type"] = "Tweet"
    # Order columns to match the canonical coding-unit schema
    schema = ["Segment ID", "Influencer", "Platform", "Content Type",
              "Theme(s)", "Context (NOT CODED - comprehension only)",
              "Verbatim Text (CODE THIS)"]
    kept = kept[schema]

    out_path = FINAL_DIR / f"{creator['name']}_Twitter.xlsx"
    kept.to_excel(out_path, index=False)
    print(f"  → {out_path.relative_to(ROOT)}: {len(kept)} kept (dropped {int(is_off.sum())})", flush=True)
    return out_path, len(kept), int(is_off.sum())


async def main():
    print(f"=== Re-tag X tweets with {LLM_MODEL} ===", flush=True)
    summary = []
    for c in CREATORS:
        try:
            path, kept, dropped = await recode_creator(c)
            summary.append({"creator": c["name"], "kept": kept, "dropped": dropped})
        except Exception as e:
            print(f"  ✗ failed for {c['name']}: {e}", flush=True)
            import traceback; traceback.print_exc()

    print("\n=== SUMMARY ===")
    print(f"{'Creator':<25} {'Kept':>6} {'Dropped':>9}")
    print("-" * 45)
    total_k = total_d = 0
    for s in summary:
        print(f"{s['creator']:<25} {s['kept']:>6} {s['dropped']:>9}")
        total_k += s["kept"]; total_d += s["dropped"]
    print(f"{'TOTAL':<25} {total_k:>6} {total_d:>9}")


if __name__ == "__main__":
    asyncio.run(main())
